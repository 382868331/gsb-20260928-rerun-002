import asyncio
import math
import os

import httpx

from backend.app import app


async def run_workflow(client):
    r = await client.post("/api/scenes", json={})
    assert r.status_code == 200
    sid = r.json()["scene_id"]
    scene = r.json()["scene"]

    async def op(path, **kw):
        nonlocal scene
        resp = await client.post(f"/api/ops/{path}", json={"scene": scene, **kw})
        assert resp.status_code == 200, (path, resp.text)
        scene = resp.json()["scene"]

    async def worlds():
        return {
            w["id"]: w
            for w in (
                await client.post("/api/ops/world-transforms", json={"scene": scene})
            ).json()["world"]
        }

    await op("add-node", type="group", name="A")
    a = scene["root_ids"][0]
    await op(
        "transform",
        node_id=a,
        position=[1, 2, 3],
        rotation_euler=[0, 0, math.pi / 2],
        scale=[2, 2, 2],
    )
    await op("add-node", type="cube", parent_id=a, name="B")
    b = next(n["id"] for n in scene["nodes"] if n["parent_id"] == a)
    await op(
        "transform",
        node_id=b,
        position=[1, 0, 0],
        rotation_euler=[0, math.pi / 2, 0],
        scale=[0.5, 2, 1],
    )
    await op("add-node", type="sphere", parent_id=b, name="C")
    cc = next(n["id"] for n in scene["nodes"] if n["parent_id"] == b)
    await op("transform", node_id=cc, position=[0, 0, 2])

    w0 = (await worlds())[cc]
    assert [round(v, 3) for v in w0["position"]] == [1.0, 8.0, 3.0]

    # 换组并保持世界位置：C 从 B 下换到 A 下
    await op("reparent", node_id=cc, new_parent_id=a, keep_world_transform=True)
    idx = {n["id"]: n for n in scene["nodes"]}
    assert idx[cc]["parent_id"] == a
    assert cc in idx[a]["children"] and cc not in idx[b]["children"]
    w1 = (await worlds())[cc]
    assert w1["matrix"] == __import__("pytest").approx(w0["matrix"], abs=1e-9)

    # 不保持位置时世界位置改变
    before_pos = w1["position"]
    await op("reparent", node_id=cc, new_parent_id=None, keep_world_transform=False)
    w2 = (await worlds())[cc]
    assert any(abs(x - y) > 1e-6 for x, y in zip(before_pos, w2["position"]))
    await op("reparent", node_id=cc, new_parent_id=a, keep_world_transform=True)

    # 循环挂接必须被拦住
    resp = await client.post(
        "/api/ops/reparent",
        json={"scene": scene, "node_id": a, "new_parent_id": cc, "keep_world_transform": True},
    )
    assert resp.status_code == 400 and "循环" in resp.json()["detail"]

    # 复制整个组，父子关系保留
    await op("duplicate", node_id=a)
    clone_a = next(rid for rid in scene["root_ids"] if rid != a)
    idx = {n["id"]: n for n in scene["nodes"]}
    # C 此前换到了 A 下，所以 A 的直接子级是 B 与 C
    clone_children = idx[clone_a]["children"]
    assert len(clone_children) == 2
    clone_b = next(cid for cid in clone_children if idx[cid]["type"] == "cube")
    clone_c = next(cid for cid in clone_children if idx[cid]["type"] == "sphere")
    assert idx[clone_b]["parent_id"] == clone_a
    assert idx[clone_c]["parent_id"] == clone_a

    # 成组：D 放进新组，世界矩阵不变
    await op("add-node", type="cone", name="D")
    d = next(n["id"] for n in scene["nodes"] if n["name"] == "D")
    before_d = (await worlds())[d]["matrix"]
    await op("group", child_ids=[d])
    after_d = (await worlds())[d]["matrix"]
    assert after_d == __import__("pytest").approx(before_d, abs=1e-9)

    # 保存后重新载入，关系仍完整
    assert (await client.put(f"/api/scenes/{sid}", json={"scene": scene})).json()["saved"]
    loaded = (await client.get(f"/api/scenes/{sid}")).json()["scene"]
    assert loaded["root_ids"] == scene["root_ids"]
    lidx = {n["id"]: n for n in loaded["nodes"]}
    assert lidx[clone_c]["parent_id"] == clone_a
    assert lidx[clone_b]["parent_id"] == clone_a
    listed = (await client.get("/api/scenes")).json()["scenes"]
    assert any(s["scene_id"] == sid and s["node_count"] == len(scene["nodes"]) for s in listed)

    # 非法父级 -> 400
    resp = await client.post(
        "/api/ops/add-node", json={"scene": scene, "type": "cube", "parent_id": "nope"}
    )
    assert resp.status_code == 400


def test_full_workflow_sync(tmp_path):
    os.environ["SCENE_STORE_DIR"] = str(tmp_path / "scenes")
    transport = httpx.ASGITransport(app=app)

    async def main():
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            await run_workflow(client)

    asyncio.run(main())


def test_batch_upgrade_api_roundtrip(tmp_path):
    os.environ["SCENE_STORE_DIR"] = str(tmp_path / "scenes")
    transport = httpx.ASGITransport(app=app)

    async def main():
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/api/scenes", json={})
            sid = r.json()["scene_id"]

            async def op(path, **kw):
                resp = await client.post(f"/api/ops/{path}", json=kw)
                assert resp.status_code == 200, (path, resp.text)
                return resp.json()

            # 内装配件
            s = (await client.post("/api/scenes", json={})).json()["scene"]
            # 直接复用已创建场景文档：加组、件、制作为装配件
            async def with_scene(payload):
                resp = await client.post("/api/ops/add-node", json={"scene": payload, "type": "group", "name": "内总成"})
                return resp.json()["scene"]
            scene = (await client.post("/api/ops/add-node", json={"scene": s, "type": "group", "name": "内总成"})).json()["scene"]
            inner_root = scene["root_ids"][0]
            scene = (await client.post("/api/ops/add-node", json={"scene": scene, "type": "cube", "parent_id": inner_root, "name": "内件"})).json()["scene"]
            inner_part = next(n["id"] for n in scene["nodes"] if n["parent_id"] == inner_root)
            scene = (await client.post("/api/ops/transform", json={"scene": scene, "node_id": inner_part, "position": [1, 0, 0]})).json()["scene"]
            scene = (await client.post("/api/ops/assembly/create", json={"scene": scene, "node_id": inner_root, "name": "内装配件"})).json()["scene"]
            inner_def = scene["assembly_defs"][0]["id"]
            scene = (await client.post("/api/ops/add-node", json={"scene": scene, "type": "group", "name": "外总成"})).json()["scene"]
            outer_root = scene["root_ids"][0]
            scene = (await client.post("/api/ops/assembly/create", json={"scene": scene, "node_id": outer_root, "name": "外装配件"})).json()["scene"]
            outer_def = next(d["id"] for d in scene["assembly_defs"] if d["id"] != inner_def)
            outer_root_id = next(d for d in scene["assembly_defs"] if d["id"] == outer_def)["root_ids"][0]
            scene = (await client.post("/api/ops/assembly/add-slot", json={
                "scene": scene,
                "parent_definition_id": outer_def,
                "parent_template_node_id": outer_root_id,
                "assembly_id": inner_def,
            })).json()["scene"]
            scene = (await client.post("/api/ops/assembly/update-apply", json={"scene": scene, "assembly_id": outer_def})).json()["scene"]
            scene = (await client.post("/api/ops/assembly/instantiate", json={"scene": scene, "assembly_id": outer_def, "position": [5, 0, 0]})).json()["scene"]
            scene = (await client.post("/api/ops/assembly/instantiate", json={"scene": scene, "assembly_id": outer_def, "position": [8, 0, 0]})).json()["scene"]
            tops = [i for i in scene["assembly_instances"] if i["assembly_id"] == outer_def and i["transform"]["position"][0] in (5.0, 8.0)]
            id_a, id_b = [i["id"] for i in sorted(tops, key=lambda i: i["transform"]["position"][0])]
            scene = (await client.post("/api/ops/release/publish", json={"scene": scene, "name": "发布"})).json()["scene"]
            rid = scene["releases"][0]["id"]
            # 升版内件
            nid = next(i for i in scene["assembly_instances"] if i["id"] == id_a)["nested_instances"][0]["node_map"][inner_part]
            scene = (await client.post("/api/ops/assembly/template-transform", json={"scene": scene, "node_id": nid, "position": [7, 0, 0]})).json()["scene"]
            inner_v2 = next(d["version"] for d in scene["assembly_defs"] if d["id"] == inner_def)

            prev = (await client.post("/api/ops/release/batch-preview", json={
                "scene": scene, "release_id": rid, "instance_ids": [id_a],
                "instance_targets": {id_a: {inner_def: inner_v2}},
            })).json()
            assert prev["missing"] == [] and prev["items"][0]["to_version"] == 2

            scene = (await client.post("/api/ops/release/batch-confirm", json={
                "scene": scene, "release_id": rid, "instance_ids": [id_a],
                "instance_targets": {id_a: {inner_def: inner_v2}}, "batch_name": "第一批",
            })).json()["scene"]
            tops = {i["id"]: i for i in scene["assembly_instances"]}
            assert tops[id_a]["nested_instances"][0]["pinned_version"] == 2
            assert tops[id_b]["nested_instances"][0]["pinned_version"] == 1

            status = (await client.post("/api/ops/release/batch-status", json={"scene": scene, "release_id": rid})).json()
            assert {b["name"] for b in status["batches"]} == {"第一批"}
            batch_id = status["batches"][0]["batch_id"]

            # 保存并重新载入，批次决定仍在
            await client.put(f"/api/scenes/{sid}", json={"scene": scene})
            scene = (await client.get(f"/api/scenes/{sid}")).json()["scene"]
            scene = (await client.post("/api/ops/release/batch-withdraw", json={"scene": scene, "batch_id": batch_id})).json()["scene"]
            tops = {i["id"]: i for i in scene["assembly_instances"]}
            assert tops[id_a]["nested_instances"][0]["pinned_version"] == 1
            assert tops[id_b]["nested_instances"][0]["pinned_version"] == 1


def test_nested_assembly_update_workflow():
    async def main():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/api/scenes", json={})
            scene = r.json()["scene"]

            async def op(path, **kw):
                nonlocal scene
                resp = await client.post(f"/api/ops/{path}", json={"scene": scene, **kw})
                assert resp.status_code == 200, (path, resp.text)
                scene = resp.json()["scene"]
                return resp.json()

            await op("add-node", type="group", name="内总成")
            inner_root = scene["root_ids"][0]
            await op("add-node", type="cube", parent_id=inner_root, name="内件")
            inner_part = next(n["id"] for n in scene["nodes"] if n["parent_id"] == inner_root)
            await op("transform", node_id=inner_part, position=[1, 0, 0])
            await op("assembly/create", node_id=inner_root, name="内装配件")
            inner_def = scene["assembly_defs"][0]

            await op("add-node", type="group", name="外总成")
            outer_root = scene["root_ids"][0]
            await op("assembly/create", node_id=outer_root, name="外装配件")
            outer_def = next(d for d in scene["assembly_defs"] if d["id"] != inner_def["id"])

            resp = await client.post(
                "/api/ops/assembly/add-slot",
                json={
                    "scene": scene,
                    "parent_definition_id": outer_def["id"],
                    "parent_template_node_id": outer_def["root_ids"][0],
                    "assembly_id": inner_def["id"],
                },
            )
            assert resp.status_code == 200, resp.text
            scene = resp.json()["scene"]

            preview = await client.post(
                "/api/ops/assembly/update-preview",
                json={"scene": scene, "assembly_id": outer_def["id"]},
            )
            updates = preview.json()["updates"]
            assert len(updates) == 1 and updates[0]["slots_added"]

            resp = await client.post(
                "/api/ops/assembly/update-apply",
                json={"scene": scene, "assembly_id": outer_def["id"], "overrides": {}},
            )
            assert resp.status_code == 200, resp.text
            scene = resp.json()["scene"]
            assert len(scene["assembly_instances"][0]["nested_instances"]) == 1

            await op("assembly/instantiate", assembly_id=outer_def["id"], position=[5, 0, 0])
            assert all(len(t["nested_instances"]) == 1 for t in scene["assembly_instances"])

            nested_part = scene["assembly_instances"][1]["nested_instances"][0]["node_map"][inner_part]
            await op("assembly/template-transform", node_id=nested_part, position=[0, 3, 0])
            updates = (await client.post(
                "/api/ops/assembly/update-preview",
                json={"scene": scene, "assembly_id": inner_def["id"]},
            )).json()["updates"]
            assert len(updates) == 2 and all(u["path"] for u in updates)

            resp = await client.post(
                "/api/ops/assembly/add-slot",
                json={
                    "scene": scene,
                    "parent_definition_id": inner_def["id"],
                    "parent_template_node_id": inner_def["root_ids"][0],
                    "assembly_id": outer_def["id"],
                },
            )
            assert resp.status_code == 400 and "相互引用" in resp.json()["detail"]

            ok = await client.post(
                "/api/ops/assembly/template-transform",
                json={"scene": scene, "node_id": nested_part, "position": [2, 0, 0]},
            )
            assert ok.status_code == 200

    asyncio.run(main())

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

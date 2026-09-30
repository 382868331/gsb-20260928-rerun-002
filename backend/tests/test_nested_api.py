"""嵌套装配 + 选择性更新的 ASGI 端到端测试。"""

import asyncio

import httpx

from backend.app import app


async def main():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        created = (await client.post("/api/scenes", json={})).json()
        scene = created["scene"]

        async def op(path, **kw):
            nonlocal scene
            resp = await client.post(f"/api/ops/{path}", json={"scene": scene, **kw})
            assert resp.status_code == 200, (path, resp.text)
            scene = resp.json()["scene"]

        # 子装配件 B
        await op("add-node", type="group", name="B根")
        b_root = scene["root_ids"][0]
        await op("add-node", type="cube", parent_id=b_root, name="B零件")
        b_part_scene = next(n["id"] for n in scene["nodes"] if n["parent_id"] == b_root)
        await op("transform", node_id=b_part_scene, position=[1, 0, 0])
        await op("assembly/create", node_id=b_root, name="子装配件B")
        b_def = scene["assembly_defs"][0]
        b_part_template = next(n["id"] for n in b_def["nodes"] if n["name"] == "B零件")
        first_b = scene["assembly_instances"][0]

        # 总成 A 中嵌套一个 B
        await op("add-node", type="group", name="A根")
        a_root = scene["root_ids"][-1]
        before = len(scene["assembly_instances"])
        await op(
            "assembly/instantiate",
            assembly_id=b_def["id"],
            parent_id=a_root,
            position=[2, 0, 0],
        )
        nested_b_id = scene["assembly_instances"][before]["id"]
        await op("assembly/create", node_id=a_root, name="总成A")
        a_def = scene["assembly_defs"][-1]
        a_inst = next(i for i in scene["assembly_instances"] if i["assembly_id"] == a_def["id"])
        nested_b = next(i for i in scene["assembly_instances"] if i.get("parent_instance_id") == a_inst["id"])
        assert nested_b["id"] == nested_b_id

        # 修改 B 原件后：预览应列出嵌套实例
        await op(
            "assembly/template-transform",
            node_id=first_b["node_map"][b_part_template],
            position=[0, 3, 0],
        )
        preview = (await client.post("/api/ops/assembly/update-preview", json={"scene": scene})).json()
        pending_ids = {p["instance_id"] for p in preview["pending"]}
        assert nested_b["id"] in pending_ids

        # 嵌套实例跟随更新
        resp = await client.post(
            "/api/ops/assembly/update-apply",
            json={"scene": scene, "choices": {nested_b["id"]: {b_part_template: "follow"}}},
        )
        assert resp.status_code == 200
        scene = resp.json()["scene"]
        nested_b = next(i for i in scene["assembly_instances"] if i["id"] == nested_b["id"])
        part_id = nested_b["node_map"][b_part_template]
        node = next(n for n in scene["nodes"] if n["id"] == part_id)
        assert node["transform"]["position"] == [0.0, 3.0, 0.0]

        # 选中嵌套零件并保存路径
        resp = await client.post("/api/ops/selection/set", json={"scene": scene, "node_id": part_id})
        scene = resp.json()["scene"]
        resolved = (await client.post("/api/ops/selection/resolve", json={"scene": scene})).json()
        assert resolved["node_id"] == part_id


def test_nested_assembly_selective_update_flow():
    asyncio.run(main())

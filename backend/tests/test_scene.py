import math

import numpy as np
import pytest

from backend import scene_ops
from backend.models import Scene
from backend.transforms import compose, decompose, quat_from_euler_xyz


def build_nested():
    """构造层层嵌套、带旋转缩放的场景：
    A(group, 平移, 旋转90°Z, 缩放2)
      B(cube, 平移, 旋转90°Y, 缩放(0.5,2,1))
        C(sphere, 平移)
    D(cone, 旋转90°X, 平移(0,1,0))
    """
    scene = Scene()
    scene = scene_ops.add_node(scene, "group", name="A")
    a = scene.root_ids[0]
    scene = scene_ops.update_transform(
        scene, a, position=[1, 2, 3], rotation_euler=[0, 0, math.pi / 2], scale=[2, 2, 2]
    )
    scene = scene_ops.add_node(scene, "cube", parent_id=a, name="B")
    b = scene.index()[a].children[0]
    scene = scene_ops.update_transform(
        scene, b, position=[1, 0, 0], rotation_euler=[0, math.pi / 2, 0], scale=[0.5, 2, 1]
    )
    scene = scene_ops.add_node(scene, "sphere", parent_id=b, name="C", position=[0, 0, 2])
    c = scene.index()[b].children[0]
    scene = scene_ops.update_transform(scene, c, position=[0, 0, 2])
    scene = scene_ops.add_node(scene, "cone", name="D")
    d = scene.root_ids[-1]
    scene = scene_ops.update_transform(scene, d, position=[0, 1, 0], rotation_euler=[math.pi / 2, 0, 0])
    return scene, {"A": a, "B": b, "C": c, "D": d}


def test_world_transform_nested():
    scene, ids = build_nested()
    worlds = {w["id"]: w for w in scene_ops.world_summary(scene)}

    a = worlds[ids["A"]]
    assert a["position"] == pytest.approx([1, 2, 3], abs=1e-9)
    assert a["scale"] == pytest.approx([2, 2, 2], abs=1e-9)

    # B: A 旋转90°Z 且缩放2，B 局部平移 (1,0,0) -> 世界平移 (1,2,3)+2*(0,1,0)=(1,4,3)
    b = worlds[ids["B"]]
    assert b["position"] == pytest.approx([1, 4, 3], abs=1e-9)
    # B 世界姿态：A(Z90) 后局部再绕 Y90（XYZ 内旋），数值上等于 (X90, Y-90)
    assert b["quaternion"] == pytest.approx([-0.5, 0.5, 0.5, 0.5], abs=1e-9)
    assert b["rotation_euler"] == pytest.approx([math.pi / 2, -math.pi / 2, 0], abs=1e-9)
    assert b["scale"] == pytest.approx([1, 4, 2], abs=1e-9)

    # C: B 世界矩阵下局部 (0,0,2) -> 世界 (1,8,3)
    c = worlds[ids["C"]]
    assert c["position"] == pytest.approx([1, 8, 3], abs=1e-9)

    d = worlds[ids["D"]]
    assert d["position"] == pytest.approx([0, 1, 0], abs=1e-9)


def test_reparent_keeps_world_position():
    scene, ids = build_nested()
    before = {w["id"]: np.array(w["matrix"]) for w in scene_ops.world_summary(scene)}

    # 把 C 从 B 下移到 A 下，保持世界位置
    moved = scene_ops.reparent(scene, ids["C"], ids["A"], keep_world_transform=True)
    after = {w["id"]: np.array(w["matrix"]) for w in scene_ops.world_summary(moved)}
    assert np.allclose(before[ids["C"]], after[ids["C"]], atol=1e-9)

    # 父子关系确实变了
    c_node = moved.index()[ids["C"]]
    assert c_node.parent_id == ids["A"]
    assert ids["C"] in moved.index()[ids["A"]].children
    assert ids["C"] not in moved.index()[ids["B"]].children

    # 移到根层级也保持
    moved2 = scene_ops.reparent(moved, ids["C"], None, keep_world_transform=True)
    after2 = {w["id"]: np.array(w["matrix"]) for w in scene_ops.world_summary(moved2)}
    assert np.allclose(before[ids["C"]], after2[ids["C"]], atol=1e-9)


def test_reparent_without_keep_moves_world_position():
    scene, ids = build_nested()
    c_before = next(w for w in scene_ops.world_summary(scene) if w["id"] == ids["C"])
    moved = scene_ops.reparent(scene, ids["C"], ids["A"], keep_world_transform=False)
    c_after = next(w for w in scene_ops.world_summary(moved) if w["id"] == ids["C"])
    # 不保持时局部 TRS 不变，挂到不同父级后世界位置应当改变
    assert c_after["position"] != pytest.approx(c_before["position"], abs=1e-9)


def test_cyclic_reparent_blocked():
    scene, ids = build_nested()
    # A 挂到 B（自己的后代）-> 拒绝
    with pytest.raises(scene_ops.SceneError):
        scene_ops.reparent(scene, ids["A"], ids["B"])
    # B 挂到 C -> 拒绝
    with pytest.raises(scene_ops.SceneError):
        scene_ops.reparent(scene, ids["B"], ids["C"])
    # 挂自己 -> 拒绝
    with pytest.raises(scene_ops.SceneError):
        scene_ops.reparent(scene, ids["A"], ids["A"])


def test_duplicate_group_preserves_hierarchy():
    scene, ids = build_nested()
    dup = scene_ops.duplicate_subtree(scene, ids["A"])
    idx = dup.index()

    # 源子树仍在
    assert ids["A"] in idx and ids["B"] in idx and ids["C"] in idx
    a_roots = [r for r in dup.root_ids if r != ids["A"] and r != ids["D"]]
    assert len(a_roots) == 1
    clone_a = a_roots[0]
    assert idx[clone_a].type == "group"
    assert len(idx[clone_a].children) == 1
    clone_b = idx[clone_a].children[0]
    assert idx[clone_b].type == "cube"
    assert len(idx[clone_b].children) == 1
    clone_c = idx[clone_b].children[0]
    assert idx[clone_c].type == "sphere"

    # 复制组的世界结构与源一致（仅根节点 x 偏移 1）
    worlds = {w["id"]: w for w in scene_ops.world_summary(dup)}
    src_c, new_c = worlds[ids["C"]], worlds[clone_c]
    assert new_c["position"] == pytest.approx([src_c["position"][0] + 1, *src_c["position"][1:]], abs=1e-9)
    assert new_c["scale"] == pytest.approx(src_c["scale"], abs=1e-9)


def test_delete_removes_subtree():
    scene, ids = build_nested()
    removed = scene_ops.delete_subtree(scene, ids["B"])
    remaining = {n.id for n in removed.nodes}
    assert ids["B"] not in remaining and ids["C"] not in remaining
    assert ids["A"] in remaining


def test_group_with_selection_keeps_positions():
    scene, ids = build_nested()
    # 对两个顶层节点 A 和 D 成组，世界位置必须都不变
    before = {w["id"]: np.array(w["matrix"]) for w in scene_ops.world_summary(scene)}
    grouped = scene_ops.create_group_with_selection(scene, [ids["A"], ids["D"]])
    after = {w["id"]: np.array(w["matrix"]) for w in scene_ops.world_summary(grouped)}
    assert np.allclose(before[ids["A"]], after[ids["A"]], atol=1e-9)
    assert np.allclose(before[ids["D"]], after[ids["D"]], atol=1e-9)
    idx = grouped.index()
    roots = grouped.root_ids
    assert len(roots) == 1
    assert idx[roots[0]].type == "group"
    assert set(idx[roots[0]].children) == {ids["A"], ids["D"]}


def test_compose_decompose_roundtrip():
    m = compose([3, -2, 1], quat_from_euler_xyz(0.3, -0.7, 1.2), [2, 0.5, 3])
    pos, quat, scl = decompose(m)
    assert pos == pytest.approx([3, -2, 1], abs=1e-10)
    assert scl == pytest.approx([2, 0.5, 3], abs=1e-10)
    rebuilt = compose(pos, quat, scl)
    assert np.allclose(m, rebuilt, atol=1e-10)


def test_persistence_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENE_STORE_DIR", str(tmp_path))
    from backend import storage
    from backend.models import Scene as S

    scene, ids = build_nested()
    storage.save_scene("demo", scene)
    loaded = storage.load_scene("demo")
    assert {n.id for n in loaded.nodes} == {n.id for n in scene.nodes}
    assert loaded.root_ids == scene.root_ids
    assert storage.list_scenes()[0]["node_count"] == 4


def build_assembly_scene():
    scene = Scene()
    scene = scene_ops.add_node(scene, "group", name="支架")
    root_id = scene.root_ids[0]
    scene = scene_ops.add_node(scene, "cube", parent_id=root_id, name="横臂")
    part_id = scene.index()[root_id].children[0]
    scene = scene_ops.update_transform(scene, part_id, position=[1, 0, 0])
    scene = scene_ops.create_assembly(scene, root_id, name="支架装配件")
    definition = scene.assembly_defs[0]
    first = scene.assembly_instances[0]
    scene = scene_ops.instantiate_assembly(scene, definition.id, position=[3, 0, 0])
    second = scene.assembly_instances[-1]
    return scene, definition, first, second, part_id


def test_assembly_instances_update_from_source_and_keep_overrides():
    scene, definition, first, second, part_template_id = build_assembly_scene()
    second_part = second.node_map[part_template_id]
    scene = scene_ops.set_assembly_override(scene, second_part, scale=[2, 3, 4])

    first_part = first.node_map[part_template_id]
    scene = scene_ops.update_assembly_template_transform(scene, first_part, position=[0, 2, 0])

    assert definition.version == 1
    refreshed_def = scene.assembly_defs[0]
    assert refreshed_def.version == 2
    refreshed_first = next(item for item in scene.assembly_instances if item.id == first.id)
    refreshed_second = next(item for item in scene.assembly_instances if item.id == second.id)
    assert refreshed_first.assembly_version == 2
    assert refreshed_second.assembly_version == 2
    idx = scene.index()
    assert idx[refreshed_first.node_map[part_template_id]].transform.position == pytest.approx([0, 2, 0])
    assert idx[refreshed_second.node_map[part_template_id]].transform.position == pytest.approx([0, 2, 0])
    assert idx[refreshed_second.node_map[part_template_id]].transform.scale == pytest.approx([2, 3, 4])
    assert refreshed_second.transform.position == pytest.approx([3, 0, 0])


def test_detached_assembly_is_not_rebound_after_source_edit_or_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENE_STORE_DIR", str(tmp_path))
    from backend import storage

    scene, definition, first, second, part_template_id = build_assembly_scene()
    first_root = first.node_map["__root__"]
    scene = scene_ops.detach_assembly_instance(scene, first_root)
    scene = scene_ops.update_assembly_template_transform(
        scene, second.node_map[part_template_id], position=[0, 4, 0]
    )
    detached_part = first.node_map[part_template_id]
    assert scene.index()[detached_part].assembly is None
    assert scene.index()[detached_part].transform.position == pytest.approx([1, 0, 0])

    storage.save_scene("assembly", scene)
    loaded = storage.load_scene("assembly")
    loaded_idx = loaded.index()
    assert loaded_idx[detached_part].assembly is None
    assert len(loaded.assembly_instances) == 1
    assert loaded.assembly_instances[0].id == second.id


def test_delete_assembly_definition_detaches_instances():
    scene, definition, first, second, _ = build_assembly_scene()
    generated = set(first.node_map.values()) | set(second.node_map.values())
    deleted = scene_ops.delete_assembly_definition(scene, definition.id)
    assert deleted.assembly_defs == []
    assert deleted.assembly_instances == []
    assert all(node.assembly is None for node in deleted.nodes if node.id in generated)
    assert {node.id for node in deleted.nodes} >= generated


def test_assembly_template_reparent_updates_linked_instances():
    scene = Scene()
    scene = scene_ops.add_node(scene, "group", name="原件根")
    root_id = scene.root_ids[0]
    scene = scene_ops.add_node(scene, "cube", parent_id=root_id, name="横臂")
    arm_id = scene.index()[root_id].children[0]
    scene = scene_ops.add_node(scene, "sphere", parent_id=root_id, name="立柱")
    pillar_id = scene.index()[root_id].children[1]
    scene = scene_ops.update_transform(scene, arm_id, position=[1, 0, 0])
    before_matrices = {w["id"]: np.array(w["matrix"]) for w in scene_ops.world_summary(scene)}
    scene = scene_ops.create_assembly(scene, root_id, name="可换层组件")
    scene = scene_ops.instantiate_assembly(scene, scene.assembly_defs[0].id, position=[4, 0, 0])
    instance = scene.assembly_instances[-1]
    scene = scene_ops.reparent_assembly_template(
        scene, instance.node_map[arm_id], instance.node_map[pillar_id], True
    )
    refreshed = scene.assembly_instances[0]
    moved = scene.index()[refreshed.node_map[arm_id]]
    assert moved.parent_id == refreshed.node_map[pillar_id]
    after_matrices = {w["id"]: np.array(w["matrix"]) for w in scene_ops.world_summary(scene)}
    assert np.allclose(
        after_matrices[refreshed.node_map[arm_id]],
        before_matrices[arm_id],
        atol=1e-9,
    )

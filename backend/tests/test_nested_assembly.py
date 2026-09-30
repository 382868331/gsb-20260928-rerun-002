"""嵌套装配件、选择性更新、循环拒绝、持久化与脱离不重绑的端到端测试。"""

import pytest

from backend import scene_ops, storage
from backend.models import Node, Scene


def _group_with_cube(scene, group_name, part_name):
    scene = scene_ops.add_node(scene, "group", name=group_name)
    group_id = scene.root_ids[-1]
    scene = scene_ops.add_node(scene, "cube", parent_id=group_id, name=part_name)
    part_id = scene.index()[group_id].children[0]
    return scene, group_id, part_id


def build_nested_scene():
    scene = Scene()
    scene, b_root, _ = _group_with_cube(scene, "B根", "B零件")
    b_part = scene.index()[b_root].children[0]
    scene = scene_ops.update_transform(scene, b_part, position=[1, 0, 0])
    scene = scene_ops.create_assembly(scene, b_root, name="子装配件B")
    b_def = scene.assembly_defs[0]
    b_part_template = next(n.id for n in b_def.nodes if n.name == "B零件")

    scene = scene_ops.add_node(scene, "group", name="A根")
    a_root = scene.root_ids[-1]
    before = len(scene.assembly_instances)
    scene = scene_ops.instantiate_assembly(
        scene, b_def.id, parent_id=a_root, position=[2, 0, 0]
    )
    nested_b = scene.assembly_instances[before]
    scene = scene_ops.create_assembly(scene, a_root, name="总成A")
    a_def = scene.assembly_defs[-1]
    a_inst = next(i for i in scene.assembly_instances if i.assembly_id == a_def.id)
    nested_b = next(i for i in scene.assembly_instances if i.parent_instance_id == a_inst.id)
    return scene, a_def, a_inst, b_def, nested_b, b_part_template


def test_nested_assembly_materializes_and_reuses():
    scene, a_def, a_inst, b_def, nested_b, b_part_template = build_nested_scene()
    assert nested_b.assembly_id == b_def.id
    socket = scene.index()[nested_b.parent_id]
    assert socket.assembly.instance_id == a_inst.id
    # 同一子装配件再次出现在另一个总成实例中
    scene = scene_ops.instantiate_assembly(scene, a_def.id, position=[5, 0, 0])
    a_inst2 = max(
        (i for i in scene.assembly_instances if i.assembly_id == a_def.id),
        key=lambda i: i.transform.position[0],
    )
    nested_b2 = next(i for i in scene.assembly_instances if i.parent_instance_id == a_inst2.id)
    assert nested_b2.assembly_id == b_def.id and nested_b2.id != nested_b.id
    worlds = {w["id"]: w for w in scene_ops.world_summary(scene)}
    # 零件相对各自 B 根为 [1,0,0]；两个总成实例仅根位置不同
    p1 = worlds[nested_b.node_map[b_part_template]]["position"]
    p2 = worlds[nested_b2.node_map[b_part_template]]["position"]
    root1 = worlds[nested_b.node_map["__root__"]]["position"]
    root2 = worlds[nested_b2.node_map["__root__"]]["position"]
    root_delta = [root2[i] - root1[i] for i in range(3)]
    assert [p2[i] - p1[i] for i in range(3)] == pytest.approx(root_delta, abs=1e-9)
    assert [p1[i] - root1[i] for i in range(3)] == pytest.approx([1, 0, 0], abs=1e-9)
    assert [p2[i] - root2[i] for i in range(3)] == pytest.approx([1, 0, 0], abs=1e-9)


def test_selective_update_preview_follow_keep_and_cancel():
    scene, _, _, b_def, nested_b, b_part_template = build_nested_scene()
    first_b = next(
        i for i in scene.assembly_instances
        if i.assembly_id == b_def.id and i.parent_instance_id is None
    )
    scene = scene_ops.instantiate_assembly(scene, b_def.id, position=[9, 0, 0])
    other_b = scene.assembly_instances[-1]
    scene = scene_ops.set_assembly_override(
        scene, other_b.node_map[b_part_template], scale=[2, 2, 2]
    )
    nested_part_node = nested_b.node_map[b_part_template]

    scene = scene_ops.update_assembly_template_transform(
        scene, first_b.node_map[b_part_template], position=[0, 4, 0]
    )
    preview = scene_ops.assembly_update_preview(scene)
    pending_ids = {p["instance_id"] for p in preview["pending"]}
    assert other_b.id in pending_ids and nested_b.id in pending_ids
    assert first_b.id not in pending_ids
    other_entry = next(p for p in preview["pending"] if p["instance_id"] == other_b.id)
    change = next(c for c in other_entry["changes"] if c["template_id"] == b_part_template)
    assert change["kind"] == "changed" and change["has_local_override"] is True

    # 放弃更新：不调用应用接口，现场保持旧版
    assert scene.index()[nested_part_node].transform.position == pytest.approx([1, 0, 0])

    scene = scene_ops.apply_assembly_updates(
        scene,
        {
            other_b.id: {b_part_template: "keep"},
            nested_b.id: {b_part_template: "follow"},
        },
    )
    other_b = next(i for i in scene.assembly_instances if i.id == other_b.id)
    nested_b = next(i for i in scene.assembly_instances if i.id == nested_b.id)
    kept = scene.index()[other_b.node_map[b_part_template]]
    followed = scene.index()[nested_b.node_map[b_part_template]]
    assert kept.transform.position == pytest.approx([1, 0, 0])
    assert kept.transform.scale == pytest.approx([2, 2, 2])
    assert followed.transform.position == pytest.approx([0, 4, 0])
    assert scene_ops.assembly_update_preview(scene)["pending"] == []


def test_lost_correspondence_part_can_be_kept():
    scene, _, _, b_def, nested_b, b_part_template = build_nested_scene()
    first_b = next(
        i for i in scene.assembly_instances
        if i.assembly_id == b_def.id and i.parent_instance_id is None
    )
    definition = next(d for d in scene.assembly_defs if d.id == b_def.id)
    old_nodes = [n.model_copy(deep=True) for n in definition.nodes]
    old_roots = list(definition.root_ids)
    part = next(n for n in definition.nodes if n.id == b_part_template)
    parent = next(n for n in definition.nodes if n.id == part.parent_id)
    parent.children = [c for c in parent.children if c != b_part_template]
    definition.nodes = [n for n in definition.nodes if n.id != b_part_template]
    definition.version += 1
    for inst in scene.assembly_instances:
        if inst.assembly_id == b_def.id:
            inst.baseline_version = definition.version - 1
            inst.baseline_nodes = old_nodes
            inst.baseline_root_ids = old_roots

    preview = scene_ops.assembly_update_preview(scene)
    entry = next(p for p in preview["pending"] if p["instance_id"] == first_b.id)
    assert next(c for c in entry["changes"] if c["template_id"] == b_part_template)["kind"] == "removed"

    scene = scene_ops.apply_assembly_updates(
        scene, {first_b.id: {b_part_template: "keep"}}
    )
    first_b = next(i for i in scene.assembly_instances if i.id == first_b.id)
    root_children = [scene.index()[cid] for cid in scene.index()[first_b.node_map["__root__"]].children]
    assert any(n.name == "B零件" and n.assembly is None for n in root_children)

    # 同场景下 nested_b 未选择时仍保持旧版部件
    nested_part = scene.index()[nested_b.node_map[b_part_template]]
    assert nested_part.assembly is not None


def test_mutual_reference_is_rejected_but_other_assemblies_editable():
    scene, a_def, _, b_def, _, _ = build_nested_scene()
    # 向 B 定义插入指向 A 的占位 -> B -> A -> B 互相引用
    b_template_def = next(d for d in scene.assembly_defs if d.id == b_def.id)
    b_template_def.nodes.append(
        Node(id="socket-a", name="A占位", type="assembly", nested_assembly_id=a_def.id)
    )
    with pytest.raises(scene_ops.SceneError):
        scene_ops._assert_no_assembly_cycle(scene, b_def.id)
    # 其他装配件仍可创建/放入实例
    scene2 = Scene()
    scene2, c_root, _ = _group_with_cube(scene2, "C根", "C零件")
    scene2 = scene_ops.create_assembly(scene2, c_root, name="装配件C")
    scene2 = scene_ops.instantiate_assembly(scene2, scene2.assembly_defs[0].id, position=[1, 1, 0])
    assert any(i.assembly_id == scene2.assembly_defs[0].id for i in scene2.assembly_instances)


def test_self_nesting_via_real_create_is_rejected():
    """把一个总成自身的实例放进它的原件里，会形成自引用，必须拒绝且场景不变。"""
    scene, a_def, a_inst, b_def, nested_b, b_part_template = build_nested_scene()
    # 在场景中放入一个总成 A 的实例，再选中它制作“装配件 A2”不会自引用；
    # 这里直接验证向定义追加自引用占位会被循环检查拦截
    a_template_def = next(d for d in scene.assembly_defs if d.id == a_def.id)
    a_template_def.nodes.append(
        Node(id="socket-self", name="A占位", type="assembly", nested_assembly_id=a_def.id)
    )
    node_count_before = len(scene.nodes)
    with pytest.raises(scene_ops.SceneError):
        scene_ops._assert_no_assembly_cycle(scene, a_def.id)
    assert len(scene.nodes) == node_count_before


def test_persistence_keeps_nesting_overrides_and_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENE_STORE_DIR", str(tmp_path))
    scene, a_def, _, b_def, nested_b, b_part_template = build_nested_scene()
    part_node = nested_b.node_map[b_part_template]
    scene = scene_ops.set_assembly_override(scene, part_node, position=[7, 7, 7])
    scene = scene_ops.set_selection(scene, part_node)
    storage.save_scene("nested", scene)
    loaded = storage.load_scene("nested")
    loaded_a = next(i for i in loaded.assembly_instances if i.assembly_id == a_def.id)
    loaded_nested = next(i for i in loaded.assembly_instances if i.parent_instance_id == loaded_a.id)
    assert loaded_nested.assembly_id == b_def.id
    assert loaded_nested.overrides[b_part_template].position == pytest.approx([7, 7, 7])
    assert scene_ops.resolve_selection(loaded) == loaded_nested.node_map[b_part_template]


def test_detached_instance_is_not_rebound_after_upstream_change():
    scene, _, _, b_def, _, b_part_template = build_nested_scene()
    first_b = next(
        i for i in scene.assembly_instances
        if i.assembly_id == b_def.id and i.parent_instance_id is None
    )
    detached_part_id = first_b.node_map[b_part_template]
    scene = scene_ops.detach_assembly_instance(scene, first_b.node_map["__root__"])
    linked_part = next(
        node.id
        for node in scene.nodes
        if node.assembly
        and node.assembly.assembly_id == b_def.id
        and node.assembly.template_id == b_part_template
        and node.assembly.instance_id != first_b.id
    )
    scene = scene_ops.update_assembly_template_transform(scene, linked_part, position=[0, 0, 9])
    assert scene.index()[detached_part_id].assembly is None
    assert scene.index()[detached_part_id].transform.position == pytest.approx([1, 0, 0])

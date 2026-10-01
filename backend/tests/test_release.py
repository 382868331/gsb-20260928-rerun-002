import pytest

from backend import scene_ops
from backend.models import Scene


def build_release_scene():
    """内装配件 S（根+内件+副件）嵌进外装配件 A，再放一个顶层实例。"""
    scene = Scene()
    scene = scene_ops.add_node(scene, "group", name="内总成")
    inner_root = scene.root_ids[0]
    scene = scene_ops.add_node(scene, "cube", parent_id=inner_root, name="内件")
    inner_part = scene.index()[inner_root].children[0]
    scene = scene_ops.add_node(scene, "sphere", parent_id=inner_root, name="副件")
    spare_part = scene.index()[inner_root].children[1]
    scene = scene_ops.create_assembly(scene, inner_root, name="内装配件")
    inner_def = scene.assembly_defs[0]

    scene = scene_ops.add_node(scene, "group", name="外总成")
    outer_root = scene.root_ids[0]
    scene = scene_ops.create_assembly(scene, outer_root, name="外装配件")
    outer_def = next(d for d in scene.assembly_defs if d.id != inner_def.id)
    scene = scene_ops.add_nested_slot(
        scene, outer_def.id, outer_def.root_ids[0], inner_def.id, position=[0, 2, 0]
    )
    outer_def = next(d for d in scene.assembly_defs if d.id == outer_def.id)
    scene = scene_ops.apply_assembly_update(scene, outer_def.id)
    scene = scene_ops.instantiate_assembly(scene, outer_def.id, position=[5, 0, 0])
    top = scene.assembly_instances[-1]
    return scene, inner_def, outer_def, inner_part, spare_part, top


def test_publish_locks_versions_and_overrides():
    scene, inner_def, outer_def, inner_part, spare_part, top = build_release_scene()
    nested = top.nested_instances[0]
    # 发布前做一个实例覆盖
    scene = scene_ops.set_assembly_override(
        scene, nested.node_map[inner_part], position=[0, 0, 7]
    )
    top = scene.assembly_instances[-1]
    scene = scene_ops.publish_release(scene, top.id, name="批次一")
    release = scene.releases[-1]
    assert release.pins[""].assembly_id == outer_def.id
    slot_path = next(p for p in release.pins if p)
    assert release.pins[slot_path].assembly_id == inner_def.id
    assert release.pins[slot_path].version == 1
    assert inner_part in release.overrides[slot_path]

    # 原件后来更新：改内件、删掉副件（内装配件升到 v3）
    nested = scene.assembly_instances[-1].nested_instances[0]
    scene = scene_ops.update_assembly_template_transform(
        scene, nested.node_map[inner_part], position=[9, 9, 9]
    )
    nested = scene.assembly_instances[-1].nested_instances[0]
    scene = scene_ops.remove_assembly_template_part(scene, nested.node_map[spare_part])
    current_inner = next(d for d in scene.assembly_defs if d.id == inner_def.id)
    assert current_inner.version == 3

    # 打开旧发布版：仍按当时状态，不混入新部件
    node_count = len(scene.nodes)
    scene = scene_ops.open_release(scene, release.id, position=[-5, 0, 0])
    reopened = scene.assembly_instances[-1]
    assert reopened.source_release_id == release.id
    assert reopened.pinned_version == release.pins[""].version
    reopened_nested = reopened.nested_instances[0]
    assert reopened_nested.pinned_version == 1
    # 覆盖恢复
    assert inner_part in reopened_nested.overrides
    assert reopened_nested.overrides[inner_part].position == [0, 0, 7]
    # 被删的副件重新出现，且没有新部件混入
    reopened_def = scene_ops._definition_at(scene, inner_def.id, 1)
    assert len(reopened_def.nodes) == 3
    outer_def_now = scene_ops._definition_at(scene, outer_def.id, release.pins[""].version)
    assert len(scene.nodes) == node_count + len(outer_def_now.nodes) + len(reopened_def.nodes)


def test_derive_upgrades_only_one_level():
    scene, inner_def, outer_def, inner_part, spare_part, top = build_release_scene()
    scene = scene_ops.publish_release(scene, top.id, name="批次一")
    base = scene.releases[-1]
    slot_path = next(p for p in base.pins if p)

    nested = scene.assembly_instances[-1].nested_instances[0]
    scene = scene_ops.update_assembly_template_transform(
        scene, nested.node_map[inner_part], position=[9, 9, 9]
    )
    # 只升级内装配件，外层保留旧版
    scene = scene_ops.derive_release(scene, base.id, {slot_path: 2}, name="批次二")
    derived = scene.releases[-1]
    assert derived.source_release_id == base.id
    assert derived.upgrades == {slot_path: [1, 2]}
    assert derived.pins[""] == base.pins[""]
    assert derived.pins[slot_path].version == 2

    scene = scene_ops.open_release(scene, derived.id, position=[-5, 0, 0])
    reopened = scene.assembly_instances[-1]
    assert reopened.pinned_version == base.pins[""].version
    assert reopened.nested_instances[0].pinned_version == 2


def test_derive_preview_separates_upstream_override_and_deletion():
    scene, inner_def, outer_def, inner_part, spare_part, top = build_release_scene()
    nested = top.nested_instances[0]
    scene = scene_ops.set_assembly_override(
        scene, nested.node_map[inner_part], scale=[2, 2, 2]
    )
    top = scene.assembly_instances[-1]
    scene = scene_ops.publish_release(scene, top.id)
    base = scene.releases[-1]
    slot_path = next(p for p in base.pins if p)

    nested = scene.assembly_instances[-1].nested_instances[0]
    scene = scene_ops.update_assembly_template_transform(
        scene, nested.node_map[inner_part], position=[9, 9, 9]
    )
    nested = scene.assembly_instances[-1].nested_instances[0]
    scene = scene_ops.remove_assembly_template_part(scene, nested.node_map[spare_part])

    preview = scene_ops.derive_release_preview(scene, base.id, {slot_path: 3})
    assert len(preview) == 1
    item = preview[0]
    assert item["from_version"] == 1 and item["to_version"] == 3
    # 上游升级造成的变化
    assert [c["template_id"] for c in item["upstream_changed"]] == [inner_part]
    # 部件删除单独列出
    assert [c["template_id"] for c in item["parts_removed"]] == [spare_part]
    # 实例覆盖受影响（内件既有覆盖又被上游改动）
    assert item["override_impacts"] == [
        {"template_id": inner_part, "path": item["override_impacts"][0]["path"], "part_removed": False}
    ]


def test_two_releases_with_different_pins_open_together():
    scene, inner_def, outer_def, inner_part, spare_part, top = build_release_scene()
    scene = scene_ops.publish_release(scene, top.id, name="批次一")
    base = scene.releases[-1]
    slot_path = next(p for p in base.pins if p)
    nested = scene.assembly_instances[-1].nested_instances[0]
    scene = scene_ops.update_assembly_template_transform(
        scene, nested.node_map[inner_part], position=[9, 9, 9]
    )
    scene = scene_ops.derive_release(scene, base.id, {slot_path: 2}, name="批次二")
    derived = scene.releases[-1]

    scene = scene_ops.open_release(scene, base.id, position=[-5, 0, 0])
    scene = scene_ops.open_release(scene, derived.id, position=[-10, 0, 0])
    first, second = scene.assembly_instances[-2], scene.assembly_instances[-1]
    assert first.nested_instances[0].pinned_version == 1
    assert second.nested_instances[0].pinned_version == 2
    # 两个总成都还在场景里，可同时查看
    assert first.id != second.id
    assert scene.index()[first.node_map["__root__"]].transform.position == [-5, 0, 0]
    assert scene.index()[second.node_map["__root__"]].transform.position == [-10, 0, 0]


def test_unavailable_version_lists_affected_and_keeps_scene():
    scene, inner_def, outer_def, inner_part, spare_part, top = build_release_scene()
    scene = scene_ops.publish_release(scene, top.id, name="批次一")
    release = scene.releases[-1]
    # 原件被删除 -> 旧版本不可用
    scene = scene_ops.delete_assembly_definition(scene, inner_def.id)
    node_count = len(scene.nodes)
    with pytest.raises(scene_ops.SceneError) as err:
        scene_ops.open_release(scene, release.id)
    message = str(err.value)
    assert "不可用" in message and "内装配件" in message and "v1" in message
    # 现场不变
    assert len(scene.nodes) == node_count
    assert len(scene.assembly_instances) == 2


def test_release_sequence_keeps_provenance_and_selection():
    scene, inner_def, outer_def, inner_part, spare_part, top = build_release_scene()
    scene = scene_ops.publish_release(scene, top.id, name="批次一")
    base = scene.releases[-1]
    slot_path = next(p for p in base.pins if p)
    nested = scene.assembly_instances[-1].nested_instances[0]
    scene = scene_ops.update_assembly_template_transform(
        scene, nested.node_map[inner_part], position=[9, 9, 9]
    )
    scene = scene_ops.derive_release(scene, base.id, {slot_path: 2}, name="批次二")
    derived = scene.releases[-1]
    # 放弃升级 = 删除派生记录，可撤销的场景文档语义由前端快照保证
    scene = scene_ops.derive_release(scene, base.id, {slot_path: 2}, name="批次二-重试")
    retried = scene.releases[-1]
    scene = scene_ops.delete_release(scene, derived.id)
    assert all(r.id != derived.id for r in scene.releases)
    scene = scene_ops.open_release(scene, retried.id)
    reopened = scene.assembly_instances[-1]
    # 部件身份可追溯：实例 -> 发布版 -> 源发布版
    assert reopened.source_release_id == retried.id
    assert retried.source_release_id == base.id
    # 选中引用在重开后仍能定位到同一部件
    part_node = reopened.nested_instances[0].node_map[inner_part]
    ref = scene_ops.make_selection_ref(scene, part_node)
    assert scene_ops.resolve_selection(scene, ref) == part_node
    assert ref.top_instance_id == reopened.id

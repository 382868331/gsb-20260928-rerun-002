import pytest

from backend import scene_ops
from backend.models import Scene, SelectionRef


def build_nested_assemblies():
    """内装配件（含一个内件）嵌进外装配件，再放两个顶层实例。"""
    scene = Scene()
    scene = scene_ops.add_node(scene, "group", name="内总成")
    inner_root = scene.root_ids[0]
    scene = scene_ops.add_node(scene, "cube", parent_id=inner_root, name="内件")
    inner_part = scene.index()[inner_root].children[0]
    scene = scene_ops.update_transform(scene, inner_part, position=[1, 0, 0])
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
    return scene, inner_def, outer_def, inner_part


def _bump_inner(scene, inner_def, inner_part, position):
    nested = next(
        inst.nested_instances[0]
        for inst in scene.assembly_instances
        if inst.nested_instances
    )
    node_id = nested.node_map[inner_part]
    scene = scene_ops.update_assembly_template_transform(scene, node_id, position=position)
    return scene, next(d for d in scene.assembly_defs if d.id == inner_def.id)


def test_publish_locks_versions_and_overrides():
    scene, inner_def, outer_def, inner_part = build_nested_assemblies()
    # 实例覆盖：第一个总成的内件缩放
    nested_node = scene.assembly_instances[0].nested_instances[0].node_map[inner_part]
    scene = scene_ops.set_assembly_override(scene, nested_node, scale=[2, 2, 2])

    scene = scene_ops.publish_release(scene, name="批次A")
    assert len(scene.releases) == 1
    release = scene.releases[0]
    assert release.name == "批次A"
    # 锁定了两层各自的具体版本与实例覆盖
    versions = {(d.id, d.version) for d in release.definitions}
    assert (inner_def.id, 1) in versions
    assert (outer_def.id, outer_def.version) in versions
    top_state = next(s for s in release.instances if s.instance_id == scene.assembly_instances[0].id)
    assert top_state.nested[0].overrides[inner_part].scale == [2, 2, 2]

    # 原件后来更新：内件移动并升版，实例跟随到最新
    scene, inner_def = _bump_inner(scene, inner_def, inner_part, [9, 9, 9])
    assert inner_def.version == 2
    scene = scene_ops.apply_assembly_update(scene, inner_def.id)
    assert scene.assembly_instances[0].nested_instances[0].pinned_version == 2

    # 重开发布版：仍按当时状态打开，不混入新部件
    reopened = scene_ops.open_release(scene, release.id)
    top = next(i for i in reopened.assembly_instances if i.id == top_state.instance_id)
    assert top.nested_instances[0].pinned_version == 1
    assert top.nested_instances[0].overrides[inner_part].scale == [2, 2, 2]
    part_node = reopened.index()[top.nested_instances[0].node_map[inner_part]]
    assert part_node.transform.position == [1.0, 0.0, 0.0]
    assert part_node.transform.scale == [2.0, 2.0, 2.0]
    # 实例 id 保持不变，选中引用仍可追溯
    ref = SelectionRef(
        top_instance_id=top.id,
        path=[top.nested_instances[0].slot_key],
        template_id=inner_part,
    )
    assert scene_ops.resolve_selection(reopened, ref) == part_node.id


def test_derive_upgrades_only_one_subassembly():
    scene, inner_def, outer_def, inner_part = build_nested_assemblies()
    scene = scene_ops.publish_release(scene, name="批次A")
    release = scene.releases[0]

    # 内装配件升到 v2（外装配件不动）
    scene, inner_def = _bump_inner(scene, inner_def, inner_part, [7, 0, 0])

    derived = scene_ops.derive_release(scene, release.id, upgrades={inner_def.id: 2})
    # 旧总成保持旧版，派生总成同时存在 -> 两个版本可同时查看
    assert len(derived.assembly_instances) == 4
    new_top = next(
        i for i in derived.assembly_instances if i.derived_from == release.id
    )
    old_top = next(i for i in derived.assembly_instances if i.id == new_top.source_instance_id)
    assert old_top.nested_instances[0].pinned_version == 1
    assert new_top.nested_instances[0].pinned_version == 2
    # 其余层级保留发布时的旧版
    assert new_top.pinned_version == release.instances[0].pinned_version
    # 来源可追溯
    assert new_top.source_instance_id == old_top.id
    new_part = derived.index()[new_top.nested_instances[0].node_map[inner_part]]
    old_part = derived.index()[old_top.nested_instances[0].node_map[inner_part]]
    assert new_part.transform.position == [7.0, 0.0, 0.0]
    assert old_part.transform.position == [1.0, 0.0, 0.0]


def test_derive_preview_distinguishes_change_kinds():
    scene, inner_def, outer_def, inner_part = build_nested_assemblies()
    # 实例覆盖，用于预览中区分“实例覆盖”影响
    nested_node = scene.assembly_instances[0].nested_instances[0].node_map[inner_part]
    scene = scene_ops.set_assembly_override(scene, nested_node, scale=[3, 3, 3])
    scene = scene_ops.publish_release(scene, name="批次A")
    release = scene.releases[0]

    # 上游升级：内件移动（v2）；再删件（v3：原件中删除内件）
    scene, inner_def = _bump_inner(scene, inner_def, inner_part, [4, 0, 0])
    live_def = next(d for d in scene.assembly_defs if d.id == inner_def.id)
    live_def.nodes = [n for n in live_def.nodes if n.id != inner_part]
    scene_ops._bump_definition(scene, live_def)
    assert live_def.version == 3

    preview = scene_ops.release_derive_preview(scene, release.id, upgrades={inner_def.id: 3})
    assert preview["missing"] == []
    # 未升级的层级列为“保留旧版”
    assert any(k["assembly_id"] == outer_def.id for k in preview["kept"])
    item = next(i for i in preview["items"] if i["assembly_id"] == inner_def.id)
    assert item["from_version"] == 1 and item["to_version"] == 3
    # 部件删除单独列出
    assert any(r["template_id"] == inner_part for r in item["removed"])
    # 实例覆盖的影响标记在被删/变化的部件上
    assert inner_part in scene.releases[0].instances[0].nested[0].overrides

    # 放弃升级：预览是只读的，现场不变
    assert scene.assembly_instances[0].nested_instances[0].pinned_version == 1


def test_missing_version_lists_instances_and_keeps_scene():
    scene, inner_def, outer_def, inner_part = build_nested_assemblies()
    scene = scene_ops.publish_release(scene, name="批次A")
    release = scene.releases[0]

    # 原件升到 v2 后，模拟旧版本不可用：发布快照与场景历史都丢掉内装配件 v1
    scene, inner_def = _bump_inner(scene, inner_def, inner_part, [6, 6, 6])
    scene.releases[0].definitions = [
        d for d in scene.releases[0].definitions if not (d.id == inner_def.id and d.version == 1)
    ]
    scene.assembly_history = [
        d for d in scene.assembly_history if not (d.id == inner_def.id and d.version == 1)
    ]
    before_nodes = len(scene.nodes)
    before_instances = len(scene.assembly_instances)
    with pytest.raises(scene_ops.SceneError) as excinfo:
        scene_ops.open_release(scene, release.id)
    message = str(excinfo.value)
    assert "外装配件" not in message  # 只列受影响的
    assert "内装配件 v1" in message
    assert "实例" in message
    # 保留现场，不用最新版本代替
    assert len(scene.nodes) == before_nodes
    assert len(scene.assembly_instances) == before_instances
    assert scene.assembly_instances[0].nested_instances[0].pinned_version == 1


def test_publish_derive_undo_chain_keeps_identity():
    """发布 -> 原件升级 -> 派生 -> 重开发布版 连续进行后，身份与来源仍可追溯。"""
    scene, inner_def, outer_def, inner_part = build_nested_assemblies()
    first_top_id = scene.assembly_instances[0].id
    scene = scene_ops.publish_release(scene, name="批次A")
    release = scene.releases[0]
    scene, inner_def = _bump_inner(scene, inner_def, inner_part, [2, 5, 0])

    # 派生新方案（只升内装配件）
    scene = scene_ops.derive_release(scene, release.id, upgrades={inner_def.id: 2})
    derived_top = next(i for i in scene.assembly_instances if i.derived_from == release.id)
    assert derived_top.source_instance_id in {first_top_id, scene.assembly_instances[1].id}

    # 再重开发布版：原实例回到 v1，派生实例不受影响
    scene = scene_ops.open_release(scene, release.id)
    reopened_old = next(i for i in scene.assembly_instances if i.id == first_top_id)
    still_derived = next(i for i in scene.assembly_instances if i.id == derived_top.id)
    assert reopened_old.nested_instances[0].pinned_version == 1
    assert still_derived.nested_instances[0].pinned_version == 2
    assert still_derived.derived_from == release.id

    # 部件身份：模板 id 稳定，选中引用沿各自实例解析
    old_part = reopened_old.nested_instances[0].node_map[inner_part]
    new_part = still_derived.nested_instances[0].node_map[inner_part]
    assert old_part != new_part
    ref_old = SelectionRef(
        top_instance_id=reopened_old.id,
        path=[reopened_old.nested_instances[0].slot_key],
        template_id=inner_part,
    )
    assert scene_ops.resolve_selection(scene, ref_old) == old_part


def test_open_release_restores_detached_slot_scene():
    """发布时已有脱离槽的实例，重开后脱离子树作为普通节点保留。"""
    scene, inner_def, outer_def, inner_part = build_nested_assemblies()
    # 第一个总成的嵌套实例脱离原件
    top = scene.assembly_instances[0]
    nested_root = top.nested_instances[0].node_map["__root__"]
    scene = scene_ops.detach_assembly_instance(scene, nested_root)
    top = scene.assembly_instances[0]
    assert top.detached_slots and not top.nested_instances

    scene = scene_ops.publish_release(scene, name="批次B")
    release = scene.releases[0]
    # 原件升级后重开：脱离的子树仍是普通节点
    scene, inner_def = _bump_inner(scene, inner_def, inner_part, [8, 8, 8])
    reopened = scene_ops.open_release(scene, release.id)
    top = next(i for i in reopened.assembly_instances if i.id == top.id)
    assert top.detached_slots
    detached_ids = {nid for d in top.detached_slots.values() for nid in d.node_ids}
    assert detached_ids
    for nid in detached_ids:
        assert reopened.index()[nid].assembly is None

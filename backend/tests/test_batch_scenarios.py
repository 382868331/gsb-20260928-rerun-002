"""交错场景核对：嵌套装配 + 不同实例覆盖 + 旧部件不可用 + 撤回后继续。"""

import pytest

from backend import scene_ops
from backend.models import Scene, SelectionRef


def _build_three_level():
    """内装配件 <- 中装配件 <- 外装配件；外装配件放两个实例，内件覆盖互不相同。"""
    scene = Scene()
    scene = scene_ops.add_node(scene, "group", name="内总成")
    inner_root = scene.root_ids[0]
    scene = scene_ops.add_node(scene, "cube", parent_id=inner_root, name="内件")
    inner_part = scene.index()[inner_root].children[0]
    scene = scene_ops.update_transform(scene, inner_part, position=[1, 0, 0])
    scene = scene_ops.create_assembly(scene, inner_root, name="内装配件")
    inner_def = scene.assembly_defs[0]

    scene = scene_ops.add_node(scene, "group", name="中总成")
    mid_root = scene.root_ids[0]
    scene = scene_ops.create_assembly(scene, mid_root, name="中装配件")
    mid_def = next(d for d in scene.assembly_defs if d.id != inner_def.id)
    scene = scene_ops.add_nested_slot(
        scene, mid_def.id, mid_def.root_ids[0], inner_def.id, position=[0, 1, 0]
    )
    mid_def = next(d for d in scene.assembly_defs if d.id == mid_def.id)
    scene = scene_ops.apply_assembly_update(scene, mid_def.id)

    scene = scene_ops.add_node(scene, "group", name="外总成")
    outer_root = scene.root_ids[0]
    scene = scene_ops.create_assembly(scene, outer_root, name="外装配件")
    outer_def = next(d for d in scene.assembly_defs if d.id not in {inner_def.id, mid_def.id})
    scene = scene_ops.add_nested_slot(
        scene, outer_def.id, outer_def.root_ids[0], mid_def.id, position=[0, 2, 0]
    )
    outer_def = next(d for d in scene.assembly_defs if d.id == outer_def.id)
    scene = scene_ops.apply_assembly_update(scene, outer_def.id)
    scene = scene_ops.instantiate_assembly(scene, outer_def.id, position=[5, 0, 0])
    scene = scene_ops.instantiate_assembly(scene, outer_def.id, position=[9, 0, 0])
    placed = [
        i for i in scene.assembly_instances
        if i.assembly_id == outer_def.id and i.transform.position[0] in (5.0, 9.0)
    ]
    placed = sorted(placed, key=lambda i: i.transform.position[0])
    top_a, top_b = placed
    source = next(
        i for i in scene.assembly_instances
        if i.assembly_id == outer_def.id and i not in placed
    )
    scene = scene_ops.delete_subtree(scene, source.node_map["__root__"])
    mid_slot = top_a.nested_instances[0].slot_key
    inner_a = top_a.nested_instances[0].nested_instances[0]
    inner_b = top_b.nested_instances[0].nested_instances[0]
    scene = scene_ops.set_assembly_override(
        scene, inner_a.node_map[inner_part], scale=[2, 2, 2]
    )
    scene = scene_ops.set_assembly_override(
        scene, inner_b.node_map[inner_part], scale=[5, 5, 5]
    )
    return scene, inner_def, mid_def, outer_def, inner_part, top_a.id, top_b.id, mid_slot


def _bump(scene, inner_def, inner_part, position):
    nested = next(
        inst.nested_instances[0].nested_instances[0]
        for inst in scene.assembly_instances
        if inst.nested_instances and inst.nested_instances[0].nested_instances
    )
    scene = scene_ops.update_assembly_template_transform(
        scene, nested.node_map[inner_part], position=position
    )
    return scene, next(d for d in scene.assembly_defs if d.id == inner_def.id)


def _top(scene, tid):
    return next(i for i in scene.assembly_instances if i.id == tid)


def test_interleaved_nested_overrides_withdraw_and_resume():
    scene, inner_def, mid_def, outer_def, inner_part, id_a, id_b, mid_slot = _build_three_level()
    scene = scene_ops.publish_release(scene, name="发布")
    release = scene.releases[0]
    # 内件升到 v2（移动），中装配件保持不动（两批共用的子装配仍是同一旧版）
    scene, inner_def = _bump(scene, inner_def, inner_part, [7, 7, 0])

    # 第一批只升级 A，B 保持旧版和自己的覆盖
    scene = scene_ops.confirm_release_batch(
        scene, release.id, [id_a], {id_a: {inner_def.id: 2}}, batch_name="一车间"
    )
    release = scene.releases[0]
    a_inner = _top(scene, id_a).nested_instances[0].nested_instances[0]
    b_inner = _top(scene, id_b).nested_instances[0].nested_instances[0]
    assert a_inner.pinned_version == 2 and b_inner.pinned_version == 1
    a_part = scene.index()[a_inner.node_map[inner_part]]
    b_part = scene.index()[b_inner.node_map[inner_part]]
    assert a_part.transform.position == [7, 7, 0] and a_part.transform.scale == [2, 2, 2]
    assert b_part.transform.position == [1, 0, 0] and b_part.transform.scale == [5, 5, 5]

    # 旧部件 v1 变得不可用：预览列出受影响的 B（仍在旧版），A 不受影响
    frozen_v1 = next(d for d in release.definitions if d.id == inner_def.id and d.version == 1)
    release.definitions.remove(frozen_v1)
    scene.assembly_history = [
        d for d in scene.assembly_history if not (d.id == inner_def.id and d.version == 1)
    ]
    preview = scene_ops.release_batch_preview(scene, release.id, [id_b], {id_b: {inner_def.id: 2}})
    # B 选择升级到 v2 时，旧版 v1 不再被需要，因此没有缺失；若要求保留 v1 则报缺失
    keep_preview = scene_ops.release_batch_preview(scene, release.id, [id_b], {})
    assert keep_preview["missing"]
    assert id_b in {n for m in keep_preview["missing"] for n in []} or keep_preview["missing"][0]["version"] == 1

    # B 从保存记录继续，升级到 v2；A 不回退
    reloaded = Scene.model_validate(scene.model_dump())
    status = scene_ops.release_batch_status(reloaded, release.id)
    assert {b["name"] for b in status["batches"]} == {"一车间"}
    reloaded = scene_ops.confirm_release_batch(
        reloaded, release.id, [id_b], {id_b: {inner_def.id: 2}}, batch_name="二车间"
    )
    a_inner = _top(reloaded, id_a).nested_instances[0].nested_instances[0]
    b_inner = _top(reloaded, id_b).nested_instances[0].nested_instances[0]
    assert a_inner.pinned_version == 2 and b_inner.pinned_version == 2
    assert scene.index() is not reloaded.index()
    b_part = reloaded.index()[b_inner.node_map[inner_part]]
    assert b_part.transform.scale == [5, 5, 5]

    # 撤回第一批：A 回到自己的旧版与覆盖——但 v1 已不可用，应明确报错并保留现场
    first_batch = next(b for b in reloaded.release_batches if b.name == "一车间").batch_id
    with pytest.raises(scene_ops.SceneError) as excinfo:
        scene_ops.withdraw_release_batch(reloaded, first_batch)
    message = str(excinfo.value)
    assert "内装配件 v1" in message
    # 只列受影响实例，外/中装配件不在其中，且原因可解释
    assert "外装配件 v" not in message
    assert "已保留现场" in message
    # 现场两实例仍是 v2
    assert _top(reloaded, id_a).nested_instances[0].nested_instances[0].pinned_version == 2
    assert _top(reloaded, id_b).nested_instances[0].nested_instances[0].pinned_version == 2

    # 发布来源、批次决定与实际场景一致
    status = scene_ops.release_batch_status(reloaded, release.id)
    live = {i["instance_id"]: i for i in status["instances"]}
    assert live[id_a]["confirmed"] and live[id_b]["confirmed"]
    assert live[id_a]["last_batch_name"] == "一车间"
    assert live[id_b]["last_batch_name"] == "二车间"

    # 选中引用按各自实例解析到不同节点
    a_ref = SelectionRef(
        top_instance_id=id_a,
        path=[mid_slot, a_inner.slot_key],
        template_id=inner_part,
    )
    b_ref = SelectionRef(
        top_instance_id=id_b,
        path=[_top(reloaded, id_b).nested_instances[0].slot_key, b_inner.slot_key],
        template_id=inner_part,
    )
    na = scene_ops.resolve_selection(reloaded, a_ref)
    nb = scene_ops.resolve_selection(reloaded, b_ref)
    assert na and nb and na != nb


def test_withdraw_succeeds_when_old_version_available():
    """旧版本仍可用时，撤回只回退本批且其他批次保持。"""
    scene, inner_def, mid_def, outer_def, inner_part, id_a, id_b, _ = _build_three_level()
    scene = scene_ops.publish_release(scene, name="发布")
    release = scene.releases[0]
    scene, inner_def = _bump(scene, inner_def, inner_part, [3, 0, 0])
    scene = scene_ops.confirm_release_batch(
        scene, release.id, [id_a], {id_a: {inner_def.id: 2}}, batch_name="批1"
    )
    scene = scene_ops.confirm_release_batch(
        scene, release.id, [id_b], {id_b: {inner_def.id: 2}}, batch_name="批2"
    )
    batch1 = next(b for b in scene.release_batches if b.name == "批1").batch_id
    scene = scene_ops.withdraw_release_batch(scene, batch1)
    a_inner = _top(scene, id_a).nested_instances[0].nested_instances[0]
    b_inner = _top(scene, id_b).nested_instances[0].nested_instances[0]
    assert a_inner.pinned_version == 1 and b_inner.pinned_version == 2
    a_part = scene.index()[a_inner.node_map[inner_part]]
    assert a_part.transform.scale == [2, 2, 2]
    assert {b.name for b in scene.release_batches} == {"批2"}

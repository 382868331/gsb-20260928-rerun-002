"""分批采用子装配升级：逐实例选择、批次确认、撤回、继续与缺失版本处理。"""

import pytest

from backend import scene_ops
from backend.models import Scene, SelectionRef


def _build_nested_two_tops():
    """内装配件（含一个内件）嵌进外装配件；外装配件放入两个顶层实例。"""
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
    scene = scene_ops.instantiate_assembly(scene, outer_def.id, position=[8, 0, 0])
    outers = [i for i in scene.assembly_instances if i.assembly_id == outer_def.id]
    placed = [i for i in outers if i.transform.position[0] in (5.0, 8.0)]
    placed = sorted(placed, key=lambda i: i.transform.position[0])
    top_a, top_b = placed
    # 制作外装配件时由原件生成的初始实例不属于本场景，用其根节点直接删除整棵实例
    source = next(i for i in outers if i not in placed)
    scene = scene_ops.delete_subtree(scene, source.node_map["__root__"])
    # 两个实例对内件给出不同覆盖
    scene = scene_ops.set_assembly_override(
        scene, top_a.nested_instances[0].node_map[inner_part], scale=[2, 2, 2]
    )
    scene = scene_ops.set_assembly_override(
        scene, top_b.nested_instances[0].node_map[inner_part], scale=[3, 3, 3]
    )
    return scene, inner_def, outer_def, inner_part, top_a.id, top_b.id


def _bump_inner_part(scene, inner_def, inner_part, position):
    nested = next(
        inst.nested_instances[0]
        for inst in scene.assembly_instances
        if inst.assembly_id != inner_def.id and inst.nested_instances
    )
    node_id = nested.node_map[inner_part]
    scene = scene_ops.update_assembly_template_transform(scene, node_id, position=position)
    return scene, next(d for d in scene.assembly_defs if d.id == inner_def.id)


def _top(scene, top_id):
    return next(i for i in scene.assembly_instances if i.id == top_id)


def test_batch_confirm_upgrades_only_selected_instances():
    scene, inner_def, outer_def, inner_part, id_a, id_b = _build_nested_two_tops()
    scene = scene_ops.publish_release(scene, name="发布一")
    release = scene.releases[0]
    scene, inner_def = _bump_inner_part(scene, inner_def, inner_part, [7, 0, 0])

    preview = scene_ops.release_batch_preview(
        scene, release.id, [id_a], {id_a: {inner_def.id: 2}}
    )
    assert preview["missing"] == []
    assert {i["instance_id"] for i in preview["not_in_batch"]} == {id_b}
    item = preview["items"][0]
    assert item["top_instance_id"] == id_a
    assert item["from_version"] == 1 and item["to_version"] == 2
    # 预览说明该实例自己的覆盖值会叠加到候选版上
    ov = next(o for o in item["overrides"] if o["template_id"] == inner_part)
    assert ov["scale"] == [2, 2, 2]
    assert "覆盖" in ov["effect"]

    scene = scene_ops.confirm_release_batch(
        scene, release.id, [id_a], {id_a: {inner_def.id: 2}}, batch_name="第一批"
    )
    top_a, top_b = _top(scene, id_a), _top(scene, id_b)
    # 已确认实例升到候选版并保留自己的覆盖；未确认实例仍是旧版、旧覆盖不被带走
    assert top_a.nested_instances[0].pinned_version == 2
    assert top_b.nested_instances[0].pinned_version == 1
    part_a = scene.index()[top_a.nested_instances[0].node_map[inner_part]]
    part_b = scene.index()[top_b.nested_instances[0].node_map[inner_part]]
    assert part_a.transform.position == [7, 0, 0] and part_a.transform.scale == [2, 2, 2]
    assert part_b.transform.position == [1, 0, 0] and part_b.transform.scale == [3, 3, 3]

    # 第二批确认 B：A 不受影响
    scene = scene_ops.confirm_release_batch(
        scene, release.id, [id_b], {id_b: {inner_def.id: 2}}, batch_name="第二批"
    )
    top_a, top_b = _top(scene, id_a), _top(scene, id_b)
    assert top_a.nested_instances[0].pinned_version == 2
    assert top_b.nested_instances[0].pinned_version == 2
    part_b = scene.index()[top_b.nested_instances[0].node_map[inner_part]]
    assert part_b.transform.scale == [3, 3, 3]


def test_withdraw_batch_restores_only_that_batch():
    scene, inner_def, outer_def, inner_part, id_a, id_b = _build_nested_two_tops()
    scene = scene_ops.publish_release(scene, name="发布一")
    release = scene.releases[0]
    scene, inner_def = _bump_inner_part(scene, inner_def, inner_part, [7, 0, 0])

    scene = scene_ops.confirm_release_batch(
        scene, release.id, [id_a], {id_a: {inner_def.id: 2}}, batch_name="第一批"
    )
    scene = scene_ops.confirm_release_batch(
        scene, release.id, [id_b], {id_b: {inner_def.id: 2}}, batch_name="第二批"
    )
    first_batch = next(b for b in scene.release_batches if b.name == "第一批").batch_id

    # 模拟保存后继续：批次记录随场景持久化，状态查询能区分已确认 / 未撤回
    reloaded = Scene.model_validate(scene.model_dump())
    status = scene_ops.release_batch_status(reloaded, release.id)
    names = {b["name"] for b in status["batches"]}
    assert names == {"第一批", "第二批"}
    assert {i["instance_id"] for i in status["instances"]} == {id_a, id_b}

    # 升级途中撤回第一批：A 回到该批自己的版本与覆盖，B 不回退
    reloaded = scene_ops.withdraw_release_batch(reloaded, first_batch)
    top_a, top_b = _top(reloaded, id_a), _top(reloaded, id_b)
    assert top_a.nested_instances[0].pinned_version == 1
    assert top_b.nested_instances[0].pinned_version == 2
    part_a = reloaded.index()[top_a.nested_instances[0].node_map[inner_part]]
    assert part_a.transform.position == [1, 0, 0]
    assert part_a.transform.scale == [2, 2, 2]
    assert "第一批" not in {
        b["name"] for b in scene_ops.release_batch_status(reloaded, release.id)["batches"]
    }
    # 撤回后可以重新分批确认 A
    reloaded = scene_ops.confirm_release_batch(
        reloaded, release.id, [id_a], {id_a: {inner_def.id: 2}}, batch_name="第一批重做"
    )
    assert _top(reloaded, id_a).nested_instances[0].pinned_version == 2
    assert _top(reloaded, id_b).nested_instances[0].pinned_version == 2


def test_preview_explains_removed_parts_and_selection_refs():
    scene, inner_def, outer_def, inner_part, id_a, id_b = _build_nested_two_tops()
    scene = scene_ops.publish_release(scene, name="发布一")
    release = scene.releases[0]
    # 内装配件升 v2（移动），再升 v3（删除内件）
    scene, inner_def = _bump_inner_part(scene, inner_def, inner_part, [4, 0, 0])
    live = next(d for d in scene.assembly_defs if d.id == inner_def.id)
    live.nodes = [n for n in live.nodes if n.id != inner_part]
    scene_ops._bump_definition(scene, live)

    preview = scene_ops.release_batch_preview(
        scene, release.id, [id_a], {id_a: {inner_def.id: 3}}
    )
    item = preview["items"][0]
    assert any(r["template_id"] == inner_part for r in item["removed"])
    # 被删部件上的实例覆盖被明确说明：保留为普通节点，不再链接原件
    ov = next(o for o in item["overrides"] if o["template_id"] == inner_part)
    assert "删除" in ov["effect"]
    # 选中引用影响被单独列出
    ref_info = next(r for r in item["selection_refs"] if r["template_id"] == inner_part)
    assert ref_info["top_instance_id"] == id_a
    assert "无法再解析" in ref_info["effect"]

    # 确认升级后：被删内件作为普通节点保留在 A 内，B 不受影响
    scene = scene_ops.confirm_release_batch(
        scene, release.id, [id_a], {id_a: {inner_def.id: 3}}, batch_name="删件批"
    )
    top_a, top_b = _top(scene, id_a), _top(scene, id_b)
    # 被删内件保留为 A 内的普通节点（整棵子树中出现无绑定节点）
    subtree = scene_ops._subtree_root_ids(scene, [top_a.node_map["__root__"]])
    assert any(scene.index()[nid].assembly is None for nid in subtree)
    assert top_b.nested_instances[0].pinned_version == 1


def test_missing_version_lists_instances_and_keeps_scene():
    scene, inner_def, outer_def, inner_part, id_a, id_b = _build_nested_two_tops()
    scene = scene_ops.publish_release(scene, name="发布一")
    release = scene.releases[0]
    scene, inner_def = _bump_inner_part(scene, inner_def, inner_part, [6, 0, 0])
    # 模拟旧版本 v1 不可用：快照与历史都清掉
    inner_pub_id = next(
        d.id for d in scene.releases[0].definitions if d.name == "内装配件" and d.version == 1
    )
    release = scene.releases[0]
    release.definitions = [
        d for d in release.definitions if d.id != inner_pub_id
    ]
    scene.assembly_history = [
        d for d in scene.assembly_history if not (d.id == inner_pub_id and d.version == 1)
    ]
    before_nodes = len(scene.nodes)
    preview = scene_ops.release_batch_preview(scene, release.id, [id_a], {})
    miss = preview["missing"][0]
    assert miss["assembly_id"] == inner_pub_id and miss["version"] == 1
    # 原因可解释，且只列受影响实例（外装配件不在其中）
    assert outer_def.id != miss["assembly_id"]
    with pytest.raises(scene_ops.SceneError) as excinfo:
        scene_ops.confirm_release_batch(scene, release.id, [id_a], {}, batch_name="坏批")
    assert "内装配件 v1" in str(excinfo.value)
    assert len(scene.nodes) == before_nodes  # 现场保留，未被空场景覆盖


def test_shared_nested_assembly_choices_do_not_cross_batches():
    """两个顶层实例共用同一子装配；分别确认时选择互不串扰，来源可追溯。"""
    scene, inner_def, outer_def, inner_part, id_a, id_b = _build_nested_two_tops()
    scene = scene_ops.publish_release(scene, name="发布一")
    release = scene.releases[0]
    scene, inner_def = _bump_inner_part(scene, inner_def, inner_part, [9, 1, 0])

    # A 选候选版 v2，B 明确保留旧版 v1，同一批里分别选择
    scene = scene_ops.confirm_release_batch(
        scene,
        release.id,
        [id_a, id_b],
        {id_a: {inner_def.id: 2}, id_b: {inner_def.id: 1}},
        batch_name="同批不同选",
    )
    assert _top(scene, id_a).nested_instances[0].pinned_version == 2
    assert _top(scene, id_b).nested_instances[0].pinned_version == 1

    # 发布来源一致：两个顶层实例 id 仍是发布快照记录的 id；选中引用按各自版本解析
    ref_a = SelectionRef(
        top_instance_id=id_a,
        path=[_top(scene, id_a).nested_instances[0].slot_key],
        template_id=inner_part,
    )
    ref_b = SelectionRef(
        top_instance_id=id_b,
        path=[_top(scene, id_b).nested_instances[0].slot_key],
        template_id=inner_part,
    )
    node_a = scene_ops.resolve_selection(scene, ref_a)
    node_b = scene_ops.resolve_selection(scene, ref_b)
    assert node_a is not None and node_b is not None and node_a != node_b
    assert scene.index()[node_a].transform.position == [9, 1, 0]
    assert scene.index()[node_b].transform.position == [1, 0, 0]

"""分批采用子装配升级：逐实例决定、批次隔离、撤回还原、缺失版本保留。"""

import pytest

from backend import scene_ops, storage
from backend.models import BatchDecision, SelectionRef
from backend.tests.test_release import _bump_inner, build_nested_assemblies


def _part_world_position(scene, nested, inner_part):
    matrices = scene_ops.world_matrices(scene)
    return list(matrices[nested.node_map[inner_part]][3, :3])


def _decide(tops, slot, want):
    """want: dict top_id -> action。"""
    return [
        BatchDecision(
            top_instance_id=top.id,
            path=[slot],
            instance_name=top.name,
            action=want.get(top.id, "keep"),
        )
        for top in tops
    ]


def _by_id(tops, top_id):
    return next(t for t in tops if t.id == top_id)


def _nested_part(scene, top, inner_part):
    nested = top.nested_instances[0]
    return nested, scene.index()[nested.node_map[inner_part]]


def _upgrade_inner_to_v3_deleted(scene, inner_def, inner_part):
    scene, inner_def = _bump_inner(scene, inner_def, inner_part, [9, 0, 0])
    live = next(d for d in scene.assembly_defs if d.id == inner_def.id)
    live.nodes = [n for n in live.nodes if n.id != inner_part]
    scene_ops._bump_definition(scene, live)
    assert live.version == 3
    return scene, live


def test_batches_isolate_instances_and_keep_overrides():
    scene, inner_def, outer_def, inner_part = build_nested_assemblies()
    top1, top2 = scene.assembly_instances
    id1, id2 = top1.id, top2.id
    slot = top1.nested_instances[0].slot_key
    n1 = top1.nested_instances[0].node_map[inner_part]
    n2 = top2.nested_instances[0].node_map[inner_part]
    scene = scene_ops.set_assembly_override(scene, n1, scale=[2, 2, 2])
    scene = scene_ops.set_assembly_override(scene, n2, position=[3, 0, 0])
    scene, inner_def = _bump_inner(scene, inner_def, inner_part, [7, 0, 0])

    preview = scene_ops.batch_upgrade_preview(scene, inner_def.id, 2)
    by_top = {item["top_instance_id"]: item for item in preview["items"]}
    assert set(by_top) == {top1.id, top2.id}
    assert by_top[top1.id]["overrides"][0]["scale"] == [2.0, 2.0, 2.0]
    assert by_top[top2.id]["overrides"][0]["position"] == [3.0, 0.0, 0.0]

    scene, batch1 = scene_ops.create_upgrade_batch(scene, inner_def.id, 2, "第一批")
    scene = scene_ops.save_batch_decisions(
        scene,
        batch1.id,
        [BatchDecision(top_instance_id=top1.id, path=[slot], instance_name="A", action="upgrade")],
    )
    # 仅保存决定时现场不变
    assert scene.assembly_instances[0].nested_instances[0].pinned_version == 1
    scene = scene_ops.confirm_upgrade_batch(scene, batch1.id)
    t1, t2 = scene.assembly_instances
    assert t1.nested_instances[0].pinned_version == 2
    assert t2.nested_instances[0].pinned_version == 1
    node1 = scene.index()[t1.nested_instances[0].node_map[inner_part]]
    assert node1.transform.position == [7.0, 0.0, 0.0]
    assert node1.transform.scale == [2.0, 2.0, 2.0]
    assert t2.nested_instances[0].overrides[inner_part].position == [3.0, 0.0, 0.0]

    # 第二批升级另一个实例：不带走第一批
    scene, batch2 = scene_ops.create_upgrade_batch(scene, inner_def.id, 2, "第二批")
    scene = scene_ops.save_batch_decisions(
        scene,
        batch2.id,
        [BatchDecision(top_instance_id=top2.id, path=[slot], instance_name="B", action="upgrade")],
    )
    scene = scene_ops.confirm_upgrade_batch(scene, batch2.id)
    t1, t2 = scene.assembly_instances
    assert t1.nested_instances[0].pinned_version == 2
    assert t2.nested_instances[0].pinned_version == 2
    assert t2.nested_instances[0].overrides[inner_part].position == [3.0, 0.0, 0.0]

    # 撤回第一批：只回退第一批实例，第二批保持 v2
    scene = scene_ops.withdraw_upgrade_batch(scene, batch1.id)
    t1, t2 = scene.assembly_instances
    assert t1.nested_instances[0].pinned_version == 1
    assert t2.nested_instances[0].pinned_version == 2
    node1 = scene.index()[t1.nested_instances[0].node_map[inner_part]]
    assert node1.transform.scale == [2.0, 2.0, 2.0]
    assert node1.transform.position == [1.0, 0.0, 0.0]


def test_deleted_part_is_kept_plain_and_selection_ref_listed():
    scene, inner_def, outer_def, inner_part = build_nested_assemblies()
    top1, top2 = scene.assembly_instances
    slot = top1.nested_instances[0].slot_key
    n1 = top1.nested_instances[0].node_map[inner_part]
    scene = scene_ops.set_assembly_override(scene, n1, scale=[2, 2, 2])
    scene = scene_ops.publish_release(scene, name="发布")
    scene, v3 = _upgrade_inner_to_v3_deleted(scene, inner_def, inner_part)

    preview = scene_ops.batch_upgrade_preview(scene, v3.id, 3)
    item = next(i for i in preview["items"] if i["top_instance_id"] == top1.id)
    assert any(change["template_id"] == inner_part for change in item["removed"])
    assert item["selection_ref_impact"]["lost_refs"]

    scene, batch = scene_ops.create_upgrade_batch(scene, v3.id, 3, "批")
    scene = scene_ops.save_batch_decisions(
        scene,
        batch.id,
        [BatchDecision(top_instance_id=top1.id, path=[slot], action="upgrade")],
    )
    scene = scene_ops.confirm_upgrade_batch(scene, batch.id)
    t1, t2 = scene.assembly_instances
    nested_root = t1.nested_instances[0].node_map["__root__"]
    orphans = [n for n in scene.nodes if n.parent_id == nested_root and n.assembly is None]
    assert len(orphans) == 1
    assert orphans[0].transform.scale == [2.0, 2.0, 2.0]
    assert t2.nested_instances[0].pinned_version == 1

    # 撤回后重新绑定回原件，覆盖仍在
    scene = scene_ops.withdraw_upgrade_batch(scene, batch.id)
    t1 = scene.assembly_instances[0]
    rebound = scene.index()[t1.nested_instances[0].node_map[inner_part]]
    assert rebound.assembly is not None
    assert rebound.transform.scale == [2.0, 2.0, 2.0]


def test_missing_original_version_keeps_instance_with_reason():
    scene, inner_def, outer_def, inner_part = build_nested_assemblies()
    top1, _ = scene.assembly_instances
    slot = top1.nested_instances[0].slot_key
    scene, v3 = _upgrade_inner_to_v3_deleted(scene, inner_def, inner_part)
    scene, batch = scene_ops.create_upgrade_batch(scene, v3.id, 3, "批")
    scene = scene_ops.save_batch_decisions(
        scene,
        batch.id,
        [BatchDecision(top_instance_id=top1.id, path=[slot], action="upgrade")],
    )
    scene = scene_ops.confirm_upgrade_batch(scene, batch.id)

    # 模拟旧版本 v1 在原件历史与发布快照中都不可用
    scene.assembly_history = [
        d for d in scene.assembly_history if not (d.id == v3.id and d.version == 1)
    ]
    for release in scene.releases:
        release.definitions = [
            d for d in release.definitions if not (d.id == v3.id and d.version == 1)
        ]
    restored = scene_ops.withdraw_upgrade_batch(scene, batch.id)
    t1 = restored.assembly_instances[0]
    assert t1.nested_instances[0].pinned_version == 3
    batch_after = restored.upgrade_batches[-1]
    assert batch_after.status == "withdrawn"
    assert any("v1" in w and "保留" in w for w in batch_after.warnings)


def test_nested_path_is_slot_key_for_selection_refs():
    scene, inner_def, outer_def, inner_part = build_nested_assemblies()
    top = scene.assembly_instances[0]
    nested = top.nested_instances[0]
    paths = [p for _, _, p in scene_ops._all_instances(scene) if p]
    assert paths and all(p == [nested.slot_key] for p in paths)
    ref = SelectionRef(
        top_instance_id=top.id,
        path=[nested.slot_key],
        template_id=inner_part,
    )
    assert scene_ops.resolve_selection(scene, ref) == nested.node_map[inner_part]


def test_three_nested_instances_two_batches_save_reload_withdraw_first():
    """三个不同位置/缩放的嵌套实例：外层不动内层升级；分两批采用，保存重开后只撤回第一批。"""
    scene, inner_def, outer_def, inner_part = build_nested_assemblies()
    top1, top2 = scene.assembly_instances
    id1, id2 = top1.id, top2.id
    # 第三个顶层实例：不同位置与整体缩放
    scene = scene_ops.instantiate_assembly(scene, outer_def.id, position=[-4, 1, 0])
    top3 = next(i for i in scene.assembly_instances if i.id not in {id1, id2})
    id3 = top3.id
    root3 = top3.node_map["__root__"]
    scene = scene_ops.update_assembly_instance_transform(
        scene, root3, position=[-4, 1, 0], scale=[1.5, 1.5, 1.5]
    )
    tops = scene.assembly_instances
    slot = tops[0].nested_instances[0].slot_key

    # 每个内层实例各自的内件覆盖（不同位置/缩放）
    overrides = {
        id1: ([2, 2, 2], None),
        id2: (None, [3, 0, 0]),
        id3: ([0.5, 0.5, 0.5], [0, 0, 4]),
    }
    for top, (scale, position) in zip(tops, [overrides[t.id] for t in tops]):
        node = top.nested_instances[0].node_map[inner_part]
        if scale:
            scene = scene_ops.set_assembly_override(scene, node, scale=scale)
        if position:
            scene = scene_ops.set_assembly_override(scene, node, position=position)

    def nested_versions():
        return [t.nested_instances[0].pinned_version for t in scene.assembly_instances]

    def top_scales():
        return [list(t.transform.scale) for t in scene.assembly_instances]

    assert nested_versions() == [1, 1, 1]

    # 发布后内层原件升级到 v2（内件移到 [7,0,0]）
    scene = scene_ops.publish_release(scene, name="发布")
    scene, inner_def = _bump_inner(scene, inner_def, inner_part, [7, 0, 0])

    # 必须能明确选中内层装配件；预览覆盖全部三个嵌套实例
    preview = scene_ops.batch_upgrade_preview(scene, inner_def.id, 2)
    assert len(preview["items"]) == 3
    top_ids = {item["top_instance_id"] for item in preview["items"]}
    assert top_ids == {t.id for t in tops}
    assert {item["from_version"] for item in preview["items"]} == {1}
    # 外层装配件本身不出现在内层预览里
    assert all(item["assembly_id"] == inner_def.id and item["path"] == [slot]
               for item in preview["items"])

    # 第一批只采用实例 1；其余两个保持 v1
    scene, batch1 = scene_ops.create_upgrade_batch(scene, inner_def.id, 2, "第一批")
    scene = scene_ops.save_batch_decisions(
        scene, batch1.id, _decide(tops, slot, {id1: "upgrade"})
    )
    scene = scene_ops.confirm_upgrade_batch(scene, batch1.id)
    assert nested_versions() == [2, 1, 1]
    assert [t.pinned_version for t in scene.assembly_instances] == [
        outer_def.version,
        outer_def.version,
        outer_def.version,
    ]
    n1, node1 = _nested_part(scene, _by_id(scene.assembly_instances, id1), inner_part)
    # 候选版模板位置 + 本实例缩放覆盖都在
    assert node1.transform.position == [7.0, 0.0, 0.0]
    assert node1.transform.scale == [2.0, 2.0, 2.0]
    # 第三个实例整体缩放仍在，内件仍是旧版位置
    n3, node3 = _nested_part(scene, _by_id(scene.assembly_instances, id3), inner_part)
    assert node3.transform.position == [0.0, 0.0, 4.0]
    assert top_scales()[2] == [1.5, 1.5, 1.5]

    # 保存重开：批次状态、实际实例版本与覆盖一致
    storage.save_scene("batch-e2e", scene)
    scene = storage.load_scene("batch-e2e")
    tops = scene.assembly_instances
    assert nested_versions() == [2, 1, 1]
    n1, node1 = _nested_part(scene, _by_id(tops, id1), inner_part)
    assert node1.transform.position == [7.0, 0.0, 0.0]
    assert node1.transform.scale == [2.0, 2.0, 2.0]
    n2, node2 = _nested_part(scene, _by_id(tops, id2), inner_part)
    assert node2.transform.position == [3.0, 0.0, 0.0]
    n3, node3 = _nested_part(scene, _by_id(tops, id3), inner_part)
    assert node3.transform.position == [0.0, 0.0, 4.0]
    assert n3.overrides[inner_part].scale == [0.5, 0.5, 0.5]
    stored_b1 = next(b for b in scene.upgrade_batches if b.name == "第一批")
    assert stored_b1.status == "confirmed"

    # 第二批采用实例 2 和 3
    scene, batch2 = scene_ops.create_upgrade_batch(scene, inner_def.id, 2, "第二批")
    scene = scene_ops.save_batch_decisions(
        scene,
        batch2.id,
        _decide(tops, slot, {id2: "upgrade", id3: "upgrade"}),
    )
    scene = scene_ops.confirm_upgrade_batch(scene, batch2.id)
    assert nested_versions() == [2, 2, 2]
    n2, node2 = _nested_part(scene, _by_id(scene.assembly_instances, id2), inner_part)
    # 分批升级保留各实例自己的覆盖（位置 [3,0,0] 仍是实例本地决定）
    assert node2.transform.position == [3.0, 0.0, 0.0]
    assert node2.transform.scale == [1.0, 1.0, 1.0]
    n3, node3 = _nested_part(scene, _by_id(scene.assembly_instances, id3), inner_part)
    assert node3.transform.position == [0.0, 0.0, 4.0]
    assert node3.transform.scale == [0.5, 0.5, 0.5]
    assert top_scales()[2] == [1.5, 1.5, 1.5]

    # 世界矩阵：缩放不同的第三个实例，内件世界位置也受其 1.5 倍整体缩放影响
    world3 = _part_world_position(scene, n3, inner_part)
    assert world3 == pytest.approx([-4.0, 4.0, 6.0])

    # 只撤回第一批：实例 1 回到 v1 与自身覆盖；第二、三批实例仍为 v2
    scene = scene_ops.withdraw_upgrade_batch(scene, stored_b1.id)
    assert nested_versions() == [1, 2, 2]
    n1, node1 = _nested_part(scene, _by_id(scene.assembly_instances, id1), inner_part)
    assert node1.transform.position == [1.0, 0.0, 0.0]
    assert node1.transform.scale == [2.0, 2.0, 2.0]
    n2, node2 = _nested_part(scene, _by_id(scene.assembly_instances, id2), inner_part)
    assert node2.transform.position == [3.0, 0.0, 0.0]
    n3, node3 = _nested_part(scene, _by_id(scene.assembly_instances, id3), inner_part)
    assert node3.transform.position == [0.0, 0.0, 4.0]
    assert _by_id(scene.assembly_instances, id3).transform.scale == [1.5, 1.5, 1.5]
    statuses = {b.name: b.status for b in scene.upgrade_batches}
    assert statuses == {"第一批": "withdrawn", "第二批": "confirmed"}

    # 再保存重开：撤回后的版本/来源仍一致
    storage.save_scene("batch-e2e", scene)
    scene = storage.load_scene("batch-e2e")
    assert nested_versions() == [1, 2, 2]
    n1, node1 = _nested_part(scene, _by_id(scene.assembly_instances, id1), inner_part)
    assert node1.transform.position == [1.0, 0.0, 0.0]
    assert node1.transform.scale == [2.0, 2.0, 2.0]
    storage.delete_scene("batch-e2e")


def test_open_batch_decision_persists_without_touching_instances():
    """仅保存决定后重开：决定可继续确认，现场始终不变。"""
    scene, inner_def, outer_def, inner_part = build_nested_assemblies()
    tops = scene.assembly_instances
    slot = tops[0].nested_instances[0].slot_key
    scene = scene_ops.publish_release(scene, name="发布")
    scene, inner_def = _bump_inner(scene, inner_def, inner_part, [7, 0, 0])
    scene, batch = scene_ops.create_upgrade_batch(scene, inner_def.id, 2, "待确认批")
    scene = scene_ops.save_batch_decisions(
        scene, batch.id, _decide(tops, slot, {tops[0].id: "upgrade"})
    )
    assert all(t.nested_instances[0].pinned_version == 1 for t in scene.assembly_instances)
    storage.save_scene("batch-open", scene)
    scene = storage.load_scene("batch-open")
    saved = next(b for b in scene.upgrade_batches if b.name == "待确认批")
    assert saved.status == "open"
    assert len(saved.decisions) == 2
    assert all(t.nested_instances[0].pinned_version == 1 for t in scene.assembly_instances)
    scene = scene_ops.confirm_upgrade_batch(scene, saved.id)
    assert scene.assembly_instances[0].nested_instances[0].pinned_version == 2
    assert scene.assembly_instances[1].nested_instances[0].pinned_version == 1
    storage.delete_scene("batch-open")

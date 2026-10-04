"""分批采用子装配升级：逐实例决定、批次隔离、撤回还原、缺失版本保留。"""

import pytest

from backend import scene_ops, storage
from backend.models import BatchDecision, SelectionRef
from backend.tests.test_release import _bump_inner, build_nested_assemblies


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


def test_three_nested_instances_two_batches_persist_and_withdraw_first(tmp_path, monkeypatch):
    scene, inner_def, outer_def, inner_part = build_nested_assemblies()
    scene = scene_ops.instantiate_assembly(scene, outer_def.id, position=[-4, 0, 0])
    top_a, top_b, top_c = scene.assembly_instances
    slot = top_a.nested_instances[0].slot_key

    scene = scene_ops.update_assembly_instance_transform(scene, top_a.node_map["__root__"], position=[5, 1, 0])
    scene = scene_ops.update_assembly_instance_transform(scene, top_b.node_map["__root__"], position=[-4, -2, 0])
    scene = scene_ops.update_assembly_instance_transform(scene, top_c.node_map["__root__"], position=[8, 3, 0])
    for top, scale in ((top_a, [2, 2, 2]), (top_b, [3, 3, 3]), (top_c, [4, 4, 4])):
        nested_node = top.nested_instances[0].node_map[inner_part]
        scene = scene_ops.set_assembly_override(scene, nested_node, scale=scale)

    scene, inner_def = _bump_inner(scene, inner_def, inner_part, [7, 0, 0])
    outer_id = outer_def.id
    inner_id = inner_def.id
    preview = scene_ops.batch_upgrade_preview(scene, inner_id, 2)
    assert [item["assembly_id"] for item in preview["items"]] == [inner_id] * 3
    assert {tuple(item["path"]) for item in preview["items"]} == {(slot,)}

    scene, batch1 = scene_ops.create_upgrade_batch(scene, inner_id, 2, "第一批")
    scene = scene_ops.save_batch_decisions(scene, batch1.id, [
        BatchDecision(top_instance_id=top_a.id, path=[slot], instance_name="A", action="upgrade"),
        BatchDecision(top_instance_id=top_b.id, path=[slot], instance_name="B", action="keep"),
        BatchDecision(top_instance_id=top_c.id, path=[slot], instance_name="C", action="upgrade"),
    ])
    scene = scene_ops.confirm_upgrade_batch(scene, batch1.id)
    assert len(batch1.rollback) == 0

    def assert_state(expected, scene_obj, *, statuses=("confirmed",)):
        tops = {top.id: top for top in scene_obj.assembly_instances}
        for top_id, version, scale, position in expected:
            top = tops[top_id]
            nested = tops[top_id].nested_instances[0]
            assert top.assembly_id == outer_id
            assert nested.assembly_id == inner_id
            assert nested.pinned_version == version
            assert nested.assembly_version == version
            node = scene_obj.index()[nested.node_map[inner_part]]
            assert node.transform.scale == scale
            root = scene_obj.index()[top.node_map["__root__"]]
            assert root.transform.position == position
        assert [batch.status for batch in scene_obj.upgrade_batches[:len(statuses)]] == list(statuses)

    assert_state([
        (top_a.id, 2, [2.0, 2.0, 2.0], [5.0, 1.0, 0.0]),
        (top_b.id, 1, [3.0, 3.0, 3.0], [-4.0, -2.0, 0.0]),
        (top_c.id, 2, [4.0, 4.0, 4.0], [8.0, 3.0, 0.0]),
    ], scene)
    stored_batch1 = next(batch for batch in scene.upgrade_batches if batch.id == batch1.id)
    assert len(stored_batch1.rollback) == 2
    assert {
        (record.assembly_id, record.top_instance_id, record.from_version, record.to_version)
        for record in stored_batch1.rollback
    } == {
        (inner_id, top_a.id, 1, 2),
        (inner_id, top_c.id, 1, 2),
    }
    refreshed_tops = {top.id: top for top in scene.assembly_instances}
    for top_id in (top_a.id, top_c.id):
        top = refreshed_tops[top_id]
        node = scene.index()[top.nested_instances[0].node_map[inner_part]]
        assert node.transform.position == [7.0, 0.0, 0.0]
    node_b = scene.index()[refreshed_tops[top_b.id].nested_instances[0].node_map[inner_part]]
    assert node_b.transform.position == [1.0, 0.0, 0.0]

    monkeypatch.setenv("SCENE_STORE_DIR", str(tmp_path))
    storage.save_scene("nested-batch", scene)
    reopened = storage.load_scene("nested-batch")
    assert_state([
        (top_a.id, 2, [2.0, 2.0, 2.0], [5.0, 1.0, 0.0]),
        (top_b.id, 1, [3.0, 3.0, 3.0], [-4.0, -2.0, 0.0]),
        (top_c.id, 2, [4.0, 4.0, 4.0], [8.0, 3.0, 0.0]),
    ], reopened)

    reopened, batch2 = scene_ops.create_upgrade_batch(reopened, inner_id, 2, "第二批")
    reopened = scene_ops.save_batch_decisions(reopened, batch2.id, [
        BatchDecision(top_instance_id=top_b.id, path=[slot], instance_name="B", action="upgrade"),
    ])
    reopened = scene_ops.confirm_upgrade_batch(reopened, batch2.id)
    assert_state([
        (top_a.id, 2, [2.0, 2.0, 2.0], [5.0, 1.0, 0.0]),
        (top_b.id, 2, [3.0, 3.0, 3.0], [-4.0, -2.0, 0.0]),
        (top_c.id, 2, [4.0, 4.0, 4.0], [8.0, 3.0, 0.0]),
    ], reopened, statuses=("confirmed", "confirmed"))
    stored_batch2 = next(batch for batch in reopened.upgrade_batches if batch.id == batch2.id)
    assert len(stored_batch2.rollback) == 1
    assert stored_batch2.rollback[0].assembly_id == inner_id
    assert (stored_batch2.rollback[0].from_version, stored_batch2.rollback[0].to_version) == (1, 2)

    storage.save_scene("nested-batch", reopened)
    after_second = storage.load_scene("nested-batch")
    withdrawn = scene_ops.withdraw_upgrade_batch(after_second, batch1.id)
    assert_state([
        (top_a.id, 1, [2.0, 2.0, 2.0], [5.0, 1.0, 0.0]),
        (top_b.id, 2, [3.0, 3.0, 3.0], [-4.0, -2.0, 0.0]),
        (top_c.id, 1, [4.0, 4.0, 4.0], [8.0, 3.0, 0.0]),
    ], withdrawn, statuses=("withdrawn", "confirmed"))
    assert withdrawn.upgrade_batches[0].status == "withdrawn"
    assert withdrawn.upgrade_batches[1].status == "confirmed"

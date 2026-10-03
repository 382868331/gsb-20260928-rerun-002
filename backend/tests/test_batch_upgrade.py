"""分批采用子装配升级：逐实例决定、批次隔离、撤回还原、缺失版本保留。"""

import pytest

from backend import scene_ops
from backend.models import BatchDecision, SelectionRef
from backend.storage import load_scene, save_scene
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


def test_three_instances_two_batches_reload_withdraw_then_adopt(monkeypatch, tmp_path):
    """三个带不同覆盖的嵌套实例分两批升级；重开后撤回第一批，再采用第三个实例。"""
    monkeypatch.setenv("SCENE_STORE_DIR", str(tmp_path))
    scene, inner_def, outer_def, inner_part = build_nested_assemblies()
    scene = scene_ops.instantiate_assembly(scene, outer_def.id, position=[9, 0, 0])
    top1, top2, top3 = scene.assembly_instances
    slot = top1.nested_instances[0].slot_key
    nodes = [
        t.nested_instances[0].node_map[inner_part] for t in (top1, top2, top3)
    ]
    scene = scene_ops.set_assembly_override(scene, nodes[0], scale=[2, 2, 2])
    scene = scene_ops.set_assembly_override(scene, nodes[1], position=[3, 0, 0])
    scene = scene_ops.set_assembly_override(
        scene, nodes[2], position=[0, 4, 0], scale=[0.5, 0.5, 0.5]
    )
    scene = scene_ops.publish_release(scene, name="总成基线")
    scene, inner_def = _bump_inner(scene, inner_def, inner_part, [7, 0, 0])

    def do_batch(scene, top, name):
        scene, batch = scene_ops.create_upgrade_batch(scene, inner_def.id, 2, name)
        scene = scene_ops.save_batch_decisions(
            scene,
            batch.id,
            [BatchDecision(
                top_instance_id=top.id, path=[slot], instance_name=top.name,
                action="upgrade",
            )],
        )
        return scene_ops.confirm_upgrade_batch(scene, batch.id), batch

    scene, batch1 = do_batch(scene, top1, "第一批")
    scene, batch2 = do_batch(scene, top2, "第二批")

    # 保存并重开：批次记录、实例版本与覆盖完整恢复
    save_scene("batch-e2e", scene)
    scene = load_scene("batch-e2e")
    tops = {t.id: t for t in scene.assembly_instances}
    assert tops[top1.id].nested_instances[0].pinned_version == 2
    assert tops[top2.id].nested_instances[0].pinned_version == 2
    assert tops[top3.id].nested_instances[0].pinned_version == 1

    # 只撤回第一批：第二、三批不受影响
    scene = scene_ops.withdraw_upgrade_batch(scene, batch1.id)
    tops = {t.id: t for t in scene.assembly_instances}
    assert tops[top1.id].nested_instances[0].pinned_version == 1
    assert tops[top2.id].nested_instances[0].pinned_version == 2
    assert tops[top3.id].nested_instances[0].pinned_version == 1

    # 继续采用第三个实例
    scene, batch3 = do_batch(scene, tops[top3.id], "第三批")

    # 与独立重算的期望一致：版本、覆盖、批次来源
    tops = {t.id: t for t in scene.assembly_instances}
    expected_version = {top1.id: 1, top2.id: 2, top3.id: 2}
    expected_position = {top1.id: [1.0, 0.0, 0.0], top2.id: [3.0, 0.0, 0.0], top3.id: [0.0, 4.0, 0.0]}
    expected_scale = {top1.id: [2.0, 2.0, 2.0], top2.id: [1.0, 1.0, 1.0], top3.id: [0.5, 0.5, 0.5]}
    for top_id, version in expected_version.items():
        nested = tops[top_id].nested_instances[0]
        assert nested.pinned_version == version
        node = scene.index()[nested.node_map[inner_part]]
        assert node.transform.position == expected_position[top_id]
        assert node.transform.scale == expected_scale[top_id]
    status = {b.name: b.status for b in scene.upgrade_batches}
    assert status == {"第一批": "withdrawn", "第二批": "confirmed", "第三批": "confirmed"}
    rolled_back = {r.top_instance_id for b in scene.upgrade_batches for r in b.rollback}
    assert rolled_back == {top1.id, top2.id, top3.id}

from backend import scene_ops, storage
from backend.models import Scene


def build_assembly():
    scene = Scene()
    scene = scene_ops.add_node(scene, "group", name="车架")
    root_id = scene.root_ids[0]
    scene = scene_ops.add_node(scene, "cube", parent_id=root_id, name="左轮")
    wheel_id = scene.index()[root_id].children[0]
    scene = scene_ops.update_transform(scene, wheel_id, position=[-1, 0, 0])
    return scene_ops.create_assembly(scene, root_id, name="小车"), root_id, wheel_id


def test_instances_share_template_but_keep_root_override():
    scene, root_id, wheel_id = build_assembly()
    assembly_id = scene.assemblies[0].id

    scene = scene_ops.instantiate_assembly(scene, assembly_id)
    idx = scene.index()
    roots = [rid for rid in scene.root_ids if rid != root_id]
    assert len(roots) == 1
    instance_root_id = roots[0]
    assert idx[instance_root_id].assembly.instance_id != idx[root_id].assembly.instance_id
    assert idx[instance_root_id].assembly.overrides == ["position"]

    instance_wheel_id = idx[instance_root_id].children[0]
    assert idx[instance_wheel_id].name == "左轮"

    scene = scene_ops.update_transform(scene, instance_wheel_id, position=[-2, 0, 0])
    scene = scene_ops.add_node(scene, "sphere", parent_id=root_id, name="车灯")
    light_id = scene.index()[root_id].children[-1]
    scene = scene_ops.update_transform(scene, wheel_id, position=[-3, 0, 0])
    scene = scene_ops.publish_assembly(scene, root_id)

    idx = scene.index()
    assert scene.assemblies[0].version == 2
    assert idx[root_id].assembly.assembly_version == 2
    assert idx[instance_root_id].assembly.assembly_version == 2
    assert len(idx[instance_root_id].children) == 2
    new_instance_wheel = next(
        node for node in idx[instance_root_id].children if idx[node].assembly.part_id == wheel_id
    )
    assert idx[new_instance_wheel].transform.position == [-2, 0, 0]
    assert any(
        idx[cid].name == "车灯" for cid in idx[instance_root_id].children
    )
    assert idx[light_id].parent_id == root_id


def test_detached_instance_is_not_rebound_by_publish_or_persistence(tmp_path, monkeypatch):
    scene, root_id, wheel_id = build_assembly()
    assembly_id = scene.assemblies[0].id
    scene = scene_ops.instantiate_assembly(scene, assembly_id)
    instance_root_id = next(rid for rid in scene.root_ids if rid != root_id)

    scene = scene_ops.detach_assembly(scene, instance_root_id)
    idx = scene.index()
    assert all(node.assembly is None for node_id in scene_ops.subtree_ids(idx, instance_root_id) for node in [idx[node_id]])

    scene = scene_ops.update_transform(scene, wheel_id, position=[-5, 0, 0])
    scene = scene_ops.publish_assembly(scene, root_id)
    idx = scene.index()
    detached_wheel_id = idx[instance_root_id].children[0]
    assert idx[detached_wheel_id].assembly is None
    assert idx[detached_wheel_id].transform.position == [-1, 0, 0]

    monkeypatch.setenv("SCENE_STORE_DIR", str(tmp_path))
    import importlib
    importlib.reload(storage)
    storage.save_scene("assembly-scene", scene)
    loaded = storage.load_scene("assembly-scene")
    loaded_idx = loaded.index()
    assert loaded_idx[instance_root_id].assembly is None
    assert loaded_idx[loaded_idx[instance_root_id].children[0]].assembly is None


def test_duplicate_linked_instance_creates_separate_instance_id():
    scene, root_id, _ = build_assembly()
    scene = scene_ops.instantiate_assembly(scene, scene.assemblies[0].id)
    second_root_id = next(rid for rid in scene.root_ids if rid != root_id)
    scene = scene_ops.duplicate_subtree(scene, second_root_id)
    roots = [rid for rid in scene.root_ids if rid != root_id and rid != second_root_id]
    assert len(roots) == 1
    idx = scene.index()
    duplicate_root_id = roots[0]
    assert idx[duplicate_root_id].assembly.instance_id != idx[second_root_id].assembly.instance_id
    assert idx[duplicate_root_id].assembly.assembly_id == idx[second_root_id].assembly.assembly_id


def test_deleting_source_instance_keeps_other_instances_and_definition():
    scene, root_id, wheel_id = build_assembly()
    assembly_id = scene.assemblies[0].id
    scene = scene_ops.instantiate_assembly(scene, assembly_id)
    second_root_id = next(rid for rid in scene.root_ids if rid != root_id)

    scene = scene_ops.delete_subtree(scene, root_id)
    idx = scene.index()
    assert root_id not in idx and wheel_id not in idx
    assert second_root_id in idx
    assert len(idx[second_root_id].children) == 1
    assert scene.assemblies[0].id == assembly_id


def test_adding_and_grouping_parts_before_publish_syncs_structure():
    scene, root_id, wheel_id = build_assembly()
    assembly_id = scene.assemblies[0].id
    scene = scene_ops.instantiate_assembly(scene, assembly_id)
    instance_root_id = next(rid for rid in scene.root_ids if rid != root_id)

    scene = scene_ops.add_node(scene, "cone", parent_id=root_id, name="轴")
    axle_id = scene.index()[root_id].children[-1]
    scene = scene_ops.create_group_with_selection(scene, [wheel_id, axle_id])
    parts_group_id = scene.index()[root_id].children[0]
    assert scene.index()[parts_group_id].assembly is not None
    assert scene.index()[axle_id].assembly is not None

    scene = scene_ops.publish_assembly(scene, root_id)
    idx = scene.index()
    instance_root = idx[instance_root_id]
    synced_group_id = next(iter(instance_root.children))
    assert idx[synced_group_id].type == "group"
    assert {idx[cid].name for cid in idx[synced_group_id].children} == {"左轮", "轴"}

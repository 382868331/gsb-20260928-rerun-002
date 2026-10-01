"""场景编辑的纯函数：全部基于传入的 scene 返回新 scene（请求级无状态）。"""

from __future__ import annotations

import time
import uuid
from typing import Dict, List, Optional

import numpy as np

from .models import (
    AssemblyBinding,
    AssemblyDefinition,
    AssemblyInstance,
    AssemblyOverride,
    Node,
    ReleaseInstanceState,
    ReleaseSnapshot,
    Scene,
    Transform,
)
from .transforms import compose, decompose, euler_xyz_from_quat, inverse, multiply, to_elements


class SceneError(ValueError):
    pass


def _require(index: Dict[str, Node], node_id: str) -> Node:
    if node_id not in index:
        raise SceneError(f"节点不存在: {node_id}")
    return index[node_id]


def is_ancestor(index: Dict[str, Node], ancestor_id: str, node_id: Optional[str]) -> bool:
    """ancestor_id 是否是 node_id 的祖先（含自身）。"""
    current = node_id
    seen = set()
    while current is not None:
        if current == ancestor_id:
            return True
        if current in seen:
            return False
        seen.add(current)
        current = index[current].parent_id if current in index else None
    return False


def subtree_ids(index: Dict[str, Node], root_id: str) -> List[str]:
    # 前序遍历：父先于子，且每个节点恰好出现一次
    result: List[str] = []
    stack = [root_id]
    while stack:
        nid = stack.pop()
        result.append(nid)
        stack.extend(reversed(index[nid].children))
    return result


def local_matrix(node: Node) -> np.ndarray:
    t = node.transform
    return compose(t.position, t.rotation, t.scale)


def world_matrices(scene: Scene) -> Dict[str, np.ndarray]:
    index = scene.index()
    matrices: Dict[str, np.ndarray] = {}

    def compute(nid: str) -> np.ndarray:
        if nid in matrices:
            return matrices[nid]
        node = _require(index, nid)
        local = local_matrix(node)
        if node.parent_id is None:
            matrices[nid] = local
        else:
            matrices[nid] = multiply(compute(node.parent_id), local)
        return matrices[nid]

    for node in scene.nodes:
        compute(node.id)
    return matrices


def world_summary(scene: Scene) -> List[dict]:
    matrices = world_matrices(scene)
    summary = []
    for node in scene.nodes:
        matrix = matrices[node.id]
        position, quaternion, scale = decompose(matrix)
        euler = euler_xyz_from_quat(quaternion)
        summary.append(
            {
                "id": node.id,
                "name": node.name,
                "type": node.type,
                "parent_id": node.parent_id,
                "position": [float(v) for v in position],
                "quaternion": [float(v) for v in quaternion],
                "rotation_euler": euler,
                "scale": [float(v) for v in scale],
                "matrix": matrix.flatten(order="C").tolist(),
                "assembly": node.assembly.model_dump() if node.assembly else None,
            }
        )
    return summary


def _new_id(existing: set) -> str:
    nid = uuid.uuid4().hex[:12]
    while nid in existing:
        nid = uuid.uuid4().hex[:12]
    existing.add(nid)
    return nid




def add_node(
    scene: Scene,
    node_type: str,
    parent_id: Optional[str] = None,
    name: Optional[str] = None,
    position=None,
) -> Scene:
    scene = scene.model_copy(deep=True)
    index = scene.index()
    if parent_id is not None:
        _require(index, parent_id)
        _require_not_assembly_node(index, parent_id)
    existing = set(index)
    labels = {
        "group": "组",
        "cube": "立方体",
        "sphere": "球体",
        "cylinder": "圆柱体",
        "cone": "圆锥体",
        "plane": "平面",
    }
    nid = _new_id(existing)
    count = sum(1 for n in scene.nodes if n.type == node_type) + 1
    node = Node(
        id=nid,
        name=name or f"{labels.get(node_type, node_type)} {count}",
        type=node_type,
        parent_id=parent_id,
        transform=Transform(position=list(position) if position else [0.0, 0.0, 0.0]),
    )
    scene.nodes.append(node)
    if parent_id is None:
        scene.root_ids.append(nid)
    else:
        index[parent_id].children.append(nid)
    return scene




def create_group_with_selection(scene: Scene, child_ids: List[str]) -> Scene:
    """新建组并把给定同级节点放进去；组取第一个子节点的世界变换（保持眼前位置）。"""
    if not child_ids:
        return add_node(scene, "group")
    scene = scene.model_copy(deep=True)
    index = scene.index()
    for cid in child_ids:
        _require(index, cid)
        _require_not_assembly_node(index, cid)
    parents = {index[cid].parent_id for cid in child_ids}
    if len(parents) != 1:
        raise SceneError("成组节点必须处于同一父级")
    parent_id = next(iter(parents))

    matrices = world_matrices(scene)
    group_world = matrices[child_ids[0]].copy()
    group_pos, group_quat, group_scale = decompose(group_world)

    existing = set(index)
    group_id = _new_id(existing)
    count = sum(1 for n in scene.nodes if n.type == "group") + 1
    group = Node(
        id=group_id,
        name=f"组 {count}",
        type="group",
        parent_id=parent_id,
        transform=Transform(
            position=[float(v) for v in group_pos],
            rotation=[float(v) for v in group_quat],
            scale=[float(v) for v in group_scale],
        ),
    )
    scene.nodes.append(group)
    if parent_id is None:
        scene.root_ids.append(group_id)
    else:
        index[parent_id].children.append(group_id)

    inv_group = inverse(group_world)
    for cid in child_ids:
        child = index[cid]
        old_parent = child.parent_id
        if old_parent is None:
            scene.root_ids.remove(cid)
        else:
            index[old_parent].children.remove(cid)
        child.parent_id = group_id
        group.children.append(cid)
        pos, quat, scl = decompose(multiply(inv_group, matrices[cid]))
        child.transform = Transform(
            position=[float(v) for v in pos],
            rotation=[float(v) for v in quat],
            scale=[float(v) for v in scl],
        )
    return scene




def update_transform(
    scene: Scene,
    node_id: str,
    position=None,
    rotation_euler=None,
    scale=None,
) -> Scene:
    from .transforms import quat_from_euler_xyz

    scene = scene.model_copy(deep=True)
    node = _require(scene.index(), node_id)
    if node.assembly:
        raise SceneError("装配件节点请使用实例覆盖或原件编辑接口")
    if position is not None:
        node.transform.position = [float(v) for v in position]
    if rotation_euler is not None:
        node.transform.rotation = [float(v) for v in quat_from_euler_xyz(*rotation_euler)]
    if scale is not None:
        node.transform.scale = [float(v) for v in scale]
    return scene


from .models import AssemblySlot, DetachedSlot, SelectionRef

ROOT_KEY = "__root__"


def _assembly_index(scene: Scene) -> Dict[str, AssemblyDefinition]:
    return {item.id: item for item in scene.assembly_defs}


def _instance_index(scene: Scene) -> Dict[str, AssemblyInstance]:
    return {item.id: item for item in scene.assembly_instances}


def _all_instances(scene: Scene):
    """返回 (instance, top_level_instance, path_slots)，path 为从外到内的 slot key。"""
    found = []

    def walk(items, top, path):
        for item in items:
            found.append((item, top, list(path)))
            if item.nested_instances:
                walk(item.nested_instances, top, path + [item.slot_key or item.id])

    for item in scene.assembly_instances:
        found.append((item, item, []))
        walk(item.nested_instances, item, [item.slot_key or item.id])
    return found


def _find_instance(scene: Scene, instance_id: str):
    for item, top, path in _all_instances(scene):
        if item.id == instance_id:
            return item, top, path
    return None


def _instance_for_node(scene: Scene, node_id: str) -> Optional[AssemblyInstance]:
    node = scene.index().get(node_id)
    if not node or not node.assembly:
        return None
    found = _find_instance(scene, node.assembly.instance_id)
    return found[0] if found else None


def _instance_path_for_node(scene: Scene, node: Node):
    found = _find_instance(scene, node.assembly.instance_id)
    if not found:
        return None
    inst, top, path = found
    return list(node.assembly.path)


def _require_not_assembly_node(index: Dict[str, Node], node_id: str) -> None:
    node = index.get(node_id)
    if node and node.assembly:
        raise SceneError("装配件实例不能作为普通层级节点直接修改；请使用覆盖、脱离或整实例操作")


def _override_transform(base: Transform, override: AssemblyOverride) -> Transform:
    return Transform(
        position=list(override.position) if override.position is not None else list(base.position),
        rotation=list(override.rotation) if override.rotation is not None else list(base.rotation),
        scale=list(override.scale) if override.scale is not None else list(base.scale),
    )


def _history_index(scene: Scene) -> Dict[str, Dict[int, AssemblyDefinition]]:
    result: Dict[str, Dict[int, AssemblyDefinition]] = {}
    for item in scene.assembly_history:
        result.setdefault(item.id, {})[item.version] = item
    for item in scene.assembly_defs:
        result.setdefault(item.id, {})[item.version] = item
    return result


def _definition_at(scene: Scene, assembly_id: str, version: Optional[int] = None) -> Optional[AssemblyDefinition]:
    versions = _history_index(scene).get(assembly_id)
    if not versions:
        return None
    if version is None:
        return versions[max(versions)]
    return versions.get(version)


def _snapshot_definition(scene: Scene, definition: AssemblyDefinition) -> None:
    """保存当前版本快照（每个版本只存一次）。"""
    versions = {item.version for item in scene.assembly_history if item.id == definition.id}
    if definition.version not in versions:
        scene.assembly_history.append(definition.model_copy(deep=True))


def _bump_definition(scene: Scene, definition: AssemblyDefinition) -> None:
    _snapshot_definition(scene, definition)
    definition.version += 1


def _slot_at(definition: AssemblyDefinition, key: str) -> Optional[AssemblySlot]:
    return next((slot for slot in definition.slots if slot.key == key), None)


def _reaches(graph, start, target) -> bool:
    stack = list(graph.get(start, ()))
    seen = set()
    while stack:
        current = stack.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(graph.get(current, ()))
    return False


def _instance_subtree_node_ids(instance: AssemblyInstance) -> List[str]:
    ids = [nid for key, nid in instance.node_map.items() if key != ROOT_KEY]
    for nested in instance.nested_instances:
        ids.extend(_instance_subtree_node_ids(nested))
    for detached in instance.detached_slots.values():
        ids.extend(detached.node_ids)
    return ids


def _all_generated_ids(instance: AssemblyInstance) -> List[str]:
    return list(instance.node_map.values()) + _instance_subtree_node_ids(instance)


def _remove_instance_nodes(scene: Scene, instance: AssemblyInstance, keep: Optional[set] = None) -> None:
    generated = set(_all_generated_ids(instance)) - set(keep or ())
    root_node_id = instance.node_map.get(ROOT_KEY, "")
    if root_node_id:
        if instance.parent_id is None:
            scene.root_ids = [rid for rid in scene.root_ids if rid != root_node_id]
        else:
            parent = scene.index().get(instance.parent_id)
            if parent:
                parent.children = [cid for cid in parent.children if cid != root_node_id]
    scene.nodes = [node for node in scene.nodes if node.id not in generated]


def _all_detached_ids(inst: AssemblyInstance) -> set:
    result = set()
    for detached in inst.detached_slots.values():
        result.update(detached.node_ids)
    for child in inst.nested_instances:
        result.update(_all_detached_ids(child))
    return result


def _state_keep_ids(state_obj) -> set:
    result = set()
    if not state_obj:
        return result
    preserved = state_obj.get("preserved") if isinstance(state_obj, dict) else None
    if isinstance(preserved, dict):
        for roots in preserved.values():
            if isinstance(roots, dict):
                for inner_roots in roots.values():
                    result.update(inner_roots)
            else:
                result.update(roots)
    for child in (state_obj.get("nested_state") or {}).values() if isinstance(state_obj, dict) else ():
        result.update(_state_keep_ids(child))
    return result


def _materialize(
    scene: Scene,
    instance: AssemblyInstance,
    definition: AssemblyDefinition,
    parent_id: Optional[str],
    existing_ids: set,
    preserved: Optional[Dict[str, List[str]]] = None,
    nested_state: Optional[Dict[str, dict]] = None,
) -> None:
    """（重新）生成实例节点。preserved 保存旧实例中要保留的子树（脱离槽/被删部件）。

    preserved: {slot_or_template_key: [顶层节点 id, ...]}，这些节点不重新生成。
    nested_state: {slot_key: {transform, overrides, pinned_version, detached_slots,
                     preserved, nested_state}} 子实例延续的状态。
    """
    preserved = preserved or {}
    nested_state = nested_state or {}
    old_map = dict(instance.node_map)

    # 摘掉旧根节点并删除由原件生成的节点；保留子树不动
    old_root = old_map.get(ROOT_KEY)
    index = scene.index()
    if old_root and old_root in index:
        if parent_id is None:
            scene.root_ids = [rid for rid in scene.root_ids if rid != old_root]
        else:
            host = index.get(parent_id)
            if host:
                host.children = [cid for cid in host.children if cid != old_root]
    keep_ids = {nid for ids in preserved.values() for nid in ids}
    keep_ids.update(_all_detached_ids(instance))
    for state_obj in nested_state.values():
        keep_ids.update(_state_keep_ids(state_obj))
    old_generated = set()
    for key, nid in old_map.items():
        old_generated.add(nid)
    for nested in instance.nested_instances:
        old_generated.update(_all_generated_ids(nested))
    old_generated -= keep_ids
    scene.nodes = [node for node in scene.nodes if node.id not in old_generated]
    pending_clear = list(keep_ids)

    instance.assembly_version = definition.version
    instance.pinned_version = definition.version
    instance.node_map = {}
    instance.nested_instances = []
    instance.detached_slots = {}
    instance.parent_id = parent_id

    template_index = {node.id: node for node in definition.nodes}
    id_map: Dict[str, str] = {}

    def fresh_id():
        return _new_id(existing_ids)

    # 先为当前层模板节点分配 id（保留覆盖/被删部件时复用旧现场节点 id）
    for template_node in definition.nodes:
        kept = preserved.get(template_node.id)
        id_map[template_node.id] = kept[0] if kept else fresh_id()

    root_template_ids = list(definition.root_ids)
    root_scene_ids: List[str] = []
    kept_scene_ids = set()
    for template_node in definition.nodes:
        scene_id = id_map[template_node.id]
        kept = preserved.get(template_node.id)
        if kept:
            scene_node = scene.index().get(scene_id)
            if scene_node is None:
                kept = None
        if kept:
            kept_scene_ids.add(scene_id)
            if template_node.parent_id in id_map:
                scene_node.parent_id = id_map[template_node.parent_id]
            elif template_node.id in root_template_ids:
                scene_node.parent_id = parent_id
            else:
                scene_node.parent_id = None
            scene_node.children = []
            scene_node.assembly = None
        else:
            scene_node = template_node.model_copy(deep=True)
            scene_node.id = scene_id
            scene_node.children = []
            if template_node.parent_id and template_node.parent_id in id_map:
                scene_node.parent_id = id_map[template_node.parent_id]
            elif template_node.id in root_template_ids:
                scene_node.parent_id = parent_id
            else:
                scene_node.parent_id = None
        if not kept:
            scene_node.assembly = AssemblyBinding(
                assembly_id=definition.id,
                instance_id=instance.id,
                template_id=template_node.id,
            )
        override = instance.overrides.get(template_node.id)
        if template_node.id in root_template_ids:
            scene_node.transform = instance.transform.model_copy(deep=True)
            root_scene_ids.append(scene_node.id)
        elif override and not kept:
            scene_node.transform = _override_transform(template_node.transform, override)
        elif not kept:
            scene_node.transform = template_node.transform.model_copy(deep=True)
        if not kept:
            scene.nodes.append(scene_node)
        instance.node_map[template_node.id] = scene_node.id
    instance.node_map[ROOT_KEY] = root_scene_ids[0]

    # 当前层父子关系
    for template_node in definition.nodes:
        child_scene = scene.index()[id_map[template_node.id]]
        for child_template_id in template_node.children:
            if child_template_id in id_map:
                child_scene.children.append(id_map[child_template_id])

    # 嵌套装配件槽
    for slot in definition.slots:
        kept_roots = preserved.get(slot.key)
        state = nested_state.get(slot.key, {})
        is_detached = kept_roots and (
            not state
            or state.get("pinned_version") is None
            or state.get("detached")
        )
        if kept_roots and is_detached:
            # 已脱离该槽：节点保留为普通节点，重新挂到（仍存在的）父部件下
            instance.detached_slots[slot.key] = DetachedSlot(node_ids=kept_roots)
            host_id = id_map.get(slot.parent_template_id)
            for root_id in kept_roots:
                kept_node = scene.index().get(root_id)
                if not kept_node:
                    continue
                kept_node.assembly = None
                if host_id:
                    kept_node.parent_id = host_id
                    scene.index()[host_id].children.append(root_id)
                else:
                    kept_node.parent_id = parent_id
                    if parent_id is None:
                        scene.root_ids.append(root_id)
                    else:
                        scene.index()[parent_id].children.append(root_id)
            for root_id in kept_roots:
                kept_node = scene.index().get(root_id)
                if kept_node is None:
                    continue
                for desc_id in _subtree_root_ids(scene, [root_id]):
                    desc = scene.index().get(desc_id)
                    if desc is not None:
                        desc.assembly = None
            continue
        pinned_version = state.get("pinned_version", slot.pinned_version)
        child_def = _definition_at(scene, slot.assembly_id, pinned_version)
        if child_def is None:
            child_def = _definition_at(scene, slot.assembly_id)
        if child_def is None:
            continue
        nested = AssemblyInstance(
            id=fresh_id(),
            name=child_def.name,
            assembly_id=child_def.id,
            assembly_version=child_def.version,
            pinned_version=child_def.version,
            parent_instance_id=instance.id,
            slot_key=slot.key,
            transform=(state.get("transform") or slot.transform).model_copy(deep=True),
            overrides={k: v.model_copy(deep=True) for k, v in state.get("overrides", {}).items()},
        )
        for detached_key, detached in (state.get("detached_slots") or {}).items():
            state.setdefault("nested_state", {})[detached_key] = {
                "preserved": {ROOT_KEY: list(detached.node_ids)}
            }
        host_id = id_map.get(slot.parent_template_id)
        _materialize(
            scene,
            nested,
            child_def,
            host_id,
            existing_ids,
            preserved=state.get("preserved"),
            nested_state=state.get("nested_state"),
        )
        for detached_key, detached in (state.get("detached_slots") or {}).items():
            nested.detached_slots[detached_key] = detached.model_copy(deep=True)
        instance.nested_instances.append(nested)

    # 被删部件但要求保留（unmapped preserved 键）挂到根下
    for key, roots in preserved.items():
        if key in id_map or any(slot.key == key for slot in definition.slots):
            continue
        for root_id in roots:
            kept_node = scene.index().get(root_id)
            if not kept_node:
                continue
            kept_node.assembly = None
            kept_node.parent_id = root_scene_ids[0]
            scene.index()[root_scene_ids[0]].children.append(root_id)

    # 挂根
    for root_id in root_scene_ids:
        if parent_id is None:
            scene.root_ids.append(root_id)
        else:
            scene.index()[parent_id].children.append(root_id)

    # 所有生成结束后，再统一解除保留子树的绑定（避免递归生成时重新挂绑定）
    for desc_id in _subtree_root_ids(scene, list(pending_clear)):
        desc = scene.index().get(desc_id)
        if desc is not None:
            desc.assembly = None


def _collect_nested_state(instance: AssemblyInstance, definition: AssemblyDefinition, scene: Scene) -> Dict[str, dict]:
    """重生成外层实例时，收集各槽子实例的局部状态与保留子树。"""
    states: Dict[str, dict] = {}
    for slot in definition.slots:
        nested = next((item for item in instance.nested_instances if item.slot_key == slot.key), None)
        kept = instance.detached_slots.get(slot.key)
        if kept:
            states[slot.key] = {"preserved": {ROOT_KEY: list(kept.node_ids)}, "detached": True}
            continue
        if nested is None:
            continue
        child_def = _definition_at(scene, nested.assembly_id, nested.pinned_version) or _definition_at(
            scene, nested.assembly_id
        )
        preserved: Dict[str, List[str]] = {}
        if child_def:
            valid_templates = {n.id for n in child_def.nodes}
            for key, nid in nested.node_map.items():
                if key != ROOT_KEY and key not in valid_templates:
                    preserved.setdefault(key, []).append(nid)
        nested_inner_state = _collect_nested_state(nested, child_def, scene) if child_def else None
        states[slot.key] = {
            "transform": nested.transform.model_copy(deep=True),
            "overrides": {k: v.model_copy(deep=True) for k, v in nested.overrides.items()},
            "pinned_version": nested.pinned_version,
            "detached_slots": {k: v.model_copy(deep=True) for k, v in nested.detached_slots.items()},
            "preserved": preserved,
            "nested_state": nested_inner_state,
        }
    return states


def _rematerialize_top_instance(scene: Scene, instance: AssemblyInstance, preserved: Optional[Dict[str, List[str]]] = None) -> None:
    definition = _definition_at(scene, instance.assembly_id, instance.pinned_version)
    if definition is None:
        definition = _assembly_index(scene).get(instance.assembly_id)
    if definition is None:
        return
    nested_state = _collect_nested_state(instance, definition, scene)
    existing = set(scene.index()) | {n.id for n in scene.nodes}
    for inst, _, _ in _all_instances(scene):
        existing.add(inst.id)
    _materialize(
        scene,
        instance,
        definition,
        instance.parent_id,
        existing,
        preserved=preserved,
        nested_state=nested_state,
    )


def create_assembly(scene: Scene, root_id: str, name: Optional[str] = None) -> Scene:
    scene = scene.model_copy(deep=True)
    index = scene.index()
    root = _require(index, root_id)
    if root.assembly:
        binding = root.assembly
        for item, top, path in _all_instances(scene):
            if item.id == binding.instance_id and binding.template_id in (
                _definition_at(scene, item.assembly_id, item.pinned_version) or _assembly_index(scene)[item.assembly_id]
            ).root_ids:
                source_top = top
                source_inst = item
                source_path = list(path)
                break
        else:
            raise SceneError("请选择装配件实例根节点，或先脱离装配件再制作新原件")
        return _create_assembly_from_instance(scene, source_top, source_inst, source_path, name)

    ids = set(subtree_ids(index, root_id))
    return _create_assembly_plain(scene, root_id, ids, name)


def _new_assembly_id(scene: Scene) -> str:
    existing = {n.id for n in scene.nodes} | {d.id for d in scene.assembly_defs} | {i.id for i, _, _ in _all_instances(scene)}
    return _new_id(existing)


def _create_assembly_plain(scene: Scene, root_id: str, subtree: set, name: Optional[str]) -> Scene:
    index = scene.index()
    root = index[root_id]
    assembly_id = _new_assembly_id(scene)
    definition = AssemblyDefinition(id=assembly_id, name=name or f"装配件 {len(scene.assembly_defs) + 1}")
    for old_id in subtree:
        source = index[old_id]
        template = source.model_copy(deep=True)
        template.parent_id = source.parent_id if source.parent_id in subtree else None
        template.children = [cid for cid in source.children if cid in subtree]
        template.assembly = None
        definition.nodes.append(template)
    definition.root_ids = [root_id]
    scene.assembly_defs.append(definition)
    _snapshot_definition(scene, definition)

    instance = AssemblyInstance(
        id=_new_assembly_id(scene),
        name=definition.name,
        assembly_id=assembly_id,
        assembly_version=1,
        pinned_version=1,
        parent_id=root.parent_id,
        transform=root.transform.model_copy(deep=True),
    )
    scene.assembly_instances.append(instance)
    if root.parent_id is None:
        scene.root_ids = [rid for rid in scene.root_ids if rid != root_id]
    else:
        index[root.parent_id].children = [cid for cid in index[root.parent_id].children if cid != root_id]
    scene.nodes = [node for node in scene.nodes if node.id not in subtree]
    existing = set(scene.index())
    for inst, _, _ in _all_instances(scene):
        existing.add(inst.id)
    _materialize(scene, instance, definition, instance.parent_id, existing)
    return scene


def _create_assembly_from_instance(scene, top: AssemblyInstance, target: AssemblyInstance, path: List[str], name: Optional[str]) -> Scene:
    """把现有（可嵌套）实例整体做成一个新装配件原件。"""
    index = scene.index()
    root_node_id = target.node_map.get(ROOT_KEY)
    root_node = index[root_node_id]
    subtree = set()
    stack = [root_node_id]
    while stack:
        cur = stack.pop()
        node = index.get(cur)
        if not node:
            continue
        subtree.add(cur)
        stack.extend(node.children)
    parent_id = target.parent_id

    assembly_id = _new_assembly_id(scene)
    definition = AssemblyDefinition(id=assembly_id, name=name or f"装配件 {len(scene.assembly_defs) + 1}")
    # 普通模板节点：该实例层中由原件生成的节点
    target_def = _definition_at(scene, target.assembly_id, target.pinned_version) or _assembly_index(scene)[target.assembly_id]
    id_remap: Dict[str, str] = {}
    existing = {n.id for n in scene.nodes}
    for template_node in target_def.nodes:
        nid = _new_id(existing)
        id_remap[template_node.id] = nid
        scene_node = index[target.node_map[template_node.id]]
        new_node = scene_node.model_copy(deep=True)
        new_node.id = nid
        new_node.parent_id = (
            id_remap[template_node.parent_id] if template_node.parent_id in id_remap else None
        )
        new_node.children = []
        new_node.assembly = None
        new_node.transform = template_node.transform.model_copy(deep=True)
        definition.nodes.append(new_node)
    definition.root_ids = [id_remap[tid] for tid in target_def.root_ids]
    for template_node in target_def.nodes:
        parent_new = definition and next(n for n in definition.nodes if n.id == id_remap[template_node.id])
        parent_new.children = [id_remap[c] for c in template_node.children]

    # 嵌套槽：子实例（含已脱离槽）
    for slot in target_def.slots:
        kept = target.detached_slots.get(slot.key)
        if kept:
            # 脱离的子树作为普通节点拷进新原件
            moved = [n for n in kept.node_ids if n in subtree]
            clone_ids = {}
            for nid in moved:
                old = index[nid]
                clone = old.model_copy(deep=True)
                clone.id = _new_id(existing)
                clone_ids[nid] = clone.id
                clone.assembly = None
                clone.children = []
                live_parent = old.parent_id
                clone.parent_id = clone_ids.get(live_parent) if live_parent in clone_ids or (live_parent and live_parent in moved) else (
                    id_remap[live_parent] if live_parent in id_remap else None
                )
                definition.nodes.append(clone)
            for nid, clone_id in clone_ids.items():
                old = index[nid]
                clone_node = next(n for n in definition.nodes if n.id == clone_id)
                clone_node.children = [clone_ids[c] for c in old.children if c in clone_ids]
            continue
        nested = next((i for i in target.nested_instances if i.slot_key == slot.key), None)
        if nested is None:
            continue
        slot_key = _new_id(existing)
        definition.slots.append(
            AssemblySlot(
                key=slot_key,
                assembly_id=nested.assembly_id,
                pinned_version=nested.pinned_version,
                parent_template_id=id_remap[slot.parent_template_id],
                transform=nested.transform.model_copy(deep=True),
            )
        )
    scene.assembly_defs.append(definition)
    _snapshot_definition(scene, definition)

    # 删除现场中这棵子树（含嵌套生成节点）
    if parent_id is None:
        scene.root_ids = [rid for rid in scene.root_ids if rid != root_node_id]
    else:
        host = index[parent_id]
        host.children = [cid for cid in host.children if cid != root_node_id]
    scene.nodes = [n for n in scene.nodes if n.id not in subtree]
    # 从实例树移除 target
    if not path:
        scene.assembly_instances = [i for i in scene.assembly_instances if i.id != target.id]
    else:
        holder = _nested_holder(scene, top, path[:-1])
        holder.nested_instances = [i for i in holder.nested_instances if i.id != target.id]

    new_instance = AssemblyInstance(
        id=_new_assembly_id(scene),
        name=definition.name,
        assembly_id=assembly_id,
        assembly_version=1,
        pinned_version=1,
        parent_id=parent_id,
        transform=target.transform.model_copy(deep=True),
    )
    scene.assembly_instances.append(new_instance)
    existing = {n.id for n in scene.nodes}
    for inst, _, _ in _all_instances(scene):
        existing.add(inst.id)
    _materialize(scene, new_instance, definition, parent_id, existing)
    return scene


def _nested_holder(top: AssemblyInstance, path: List[str]) -> AssemblyInstance:
    cur = top
    for key in path:
        cur = next(i for i in cur.nested_instances if i.slot_key == key)
    return cur


def instantiate_assembly(
    scene: Scene,
    assembly_id: str,
    parent_id: Optional[str] = None,
    position=None,
) -> Scene:
    scene = scene.model_copy(deep=True)
    if parent_id is not None:
        parent = _require(scene.index(), parent_id)
        _require_not_assembly_node(scene.index(), parent_id)
    definition = _assembly_index(scene).get(assembly_id)
    if not definition:
        raise SceneError("装配件不存在")
    existing = {n.id for n in scene.nodes}
    for inst, _, _ in _all_instances(scene):
        existing.add(inst.id)
    instance = AssemblyInstance(
        id=_new_id(existing),
        name=definition.name,
        assembly_id=assembly_id,
        assembly_version=definition.version,
        pinned_version=definition.version,
        parent_id=parent_id,
        transform=Transform(position=list(position) if position else [0.0, 0.0, 0.0]),
    )
    scene.assembly_instances.append(instance)
    _materialize(scene, instance, definition, parent_id, existing)
    return scene


def add_nested_slot(
    scene: Scene,
    parent_definition_id: str,
    parent_template_node_id: str,
    assembly_id: str,
    position=None,
) -> Scene:
    """在原件的某个部件下放入另一个装配件的引用（嵌套）。"""
    scene = scene.model_copy(deep=True)
    definition = _assembly_index(scene).get(parent_definition_id)
    if not definition:
        raise SceneError("装配件原件不存在")
    if not any(node.id == parent_template_node_id for node in definition.nodes):
        raise SceneError("父部件不存在于该原件中")
    child = _assembly_index(scene).get(assembly_id)
    if not child:
        raise SceneError("被嵌套的装配件不存在")
    if _reaches({item.id: {s.assembly_id for s in item.slots} for item in scene.assembly_defs}, assembly_id, parent_definition_id) or assembly_id == parent_definition_id:
        raise SceneError("检测到装配件相互引用，已拒绝本次修改；其他装配件仍可编辑")
    existing = {slot.key for slot in definition.slots} | {n.id for n in scene.nodes}
    key = _new_id(existing)
    definition.slots.append(
        AssemblySlot(
            key=key,
            assembly_id=assembly_id,
            pinned_version=child.version,
            parent_template_id=parent_template_node_id,
            transform=Transform(position=list(position) if position else [0.0, 0.0, 0.0]),
        )
    )
    _bump_definition(scene, definition)
    return scene


def _locate_template(scene: Scene, node: Node):
    """由实例节点找到 (instance, top, definition, template_node)。"""
    found = _find_instance(scene, node.assembly.instance_id)
    if not found:
        return None
    instance, top, path = found
    definition = _definition_at(scene, instance.assembly_id, instance.pinned_version) or _assembly_index(scene).get(
        instance.assembly_id
    )
    if not definition:
        return None
    template = next((n for n in definition.nodes if n.id == node.assembly.template_id), None)
    return instance, top, path, definition, template


def update_assembly_instance_transform(scene, node_id, position=None, rotation_euler=None, scale=None):
    from .transforms import quat_from_euler_xyz

    scene = scene.model_copy(deep=True)
    node = _require(scene.index(), node_id)
    if not node.assembly:
        return update_transform(scene, node_id, position, rotation_euler, scale)
    located = _locate_template(scene, node)
    if not located:
        raise SceneError("装配件实例不存在")
    instance, top, path, definition, template = located
    if node.assembly.template_id not in definition.root_ids:
        raise SceneError("只有装配件根节点能修改实例整体变换；内部零件请使用覆盖")
    if position is not None:
        instance.transform.position = [float(v) for v in position]
        node.transform.position = list(instance.transform.position)
    if rotation_euler is not None:
        instance.transform.rotation = [float(v) for v in quat_from_euler_xyz(*rotation_euler)]
        node.transform.rotation = list(instance.transform.rotation)
    if scale is not None:
        instance.transform.scale = [float(v) for v in scale]
        node.transform.scale = list(instance.transform.scale)
    return scene


def set_assembly_override(scene, node_id, position=None, rotation_euler=None, scale=None):
    from .transforms import quat_from_euler_xyz

    scene = scene.model_copy(deep=True)
    node = _require(scene.index(), node_id)
    if not node.assembly:
        raise SceneError("只有装配件实例零件能设置覆盖")
    located = _locate_template(scene, node)
    if not located:
        raise SceneError("装配件实例不存在")
    instance, top, path, definition, template = located
    if node.assembly.template_id in definition.root_ids:
        raise SceneError("装配件根节点变换直接保存在实例上，不需要覆盖")
    override = instance.overrides.setdefault(node.assembly.template_id, AssemblyOverride())
    if position is not None:
        override.position = [float(v) for v in position]
    if rotation_euler is not None:
        override.rotation = [float(v) for v in quat_from_euler_xyz(*rotation_euler)]
    if scale is not None:
        override.scale = [float(v) for v in scale]
    node.transform = _override_transform(template.transform, override)
    return scene


def clear_assembly_override(scene, node_id):
    scene = scene.model_copy(deep=True)
    node = _require(scene.index(), node_id)
    if not node.assembly:
        raise SceneError("只有装配件实例零件能清除覆盖")
    located = _locate_template(scene, node)
    if not located:
        raise SceneError("装配件实例不存在")
    instance, top, path, definition, template = located
    instance.overrides.pop(node.assembly.template_id, None)
    node.transform = template.transform.model_copy(deep=True)
    return scene


def update_assembly_template_transform(scene, node_id, position=None, rotation_euler=None, scale=None):
    """编辑原件：仅提升原件版本并生成快照；实例保持在旧版本，由用户预览后选择更新。"""
    from .transforms import quat_from_euler_xyz

    scene = scene.model_copy(deep=True)
    node = _require(scene.index(), node_id)
    if not node.assembly:
        raise SceneError("请在装配件实例节点上编辑原件")
    located = _locate_template(scene, node)
    if not located:
        raise SceneError("装配件原件不存在")
    instance, top, path, definition, template = located
    if node.assembly.template_id in definition.root_ids:
        raise SceneError("原件根节点变换来自实例位置；请修改内部零件")
    if position is not None:
        template.transform.position = [float(v) for v in position]
    if rotation_euler is not None:
        template.transform.rotation = [float(v) for v in quat_from_euler_xyz(*rotation_euler)]
    if scale is not None:
        template.transform.scale = [float(v) for v in scale]
    _bump_definition(scene, definition)
    return scene


def reparent_assembly_template(scene, node_id, new_parent_node_id, keep_world_transform=True):
    node = _require(scene.index(), node_id)
    target = _require(scene.index(), new_parent_node_id) if new_parent_node_id is not None else None
    if not node.assembly or (target and not target.assembly):
        raise SceneError("装配件原件换组需要选择装配件内部的新父级")
    if target and (
        node.assembly.instance_id != target.assembly.instance_id
        or node.assembly.assembly_id != target.assembly.assembly_id
    ):
        raise SceneError("不能跨装配件调整原件层级")
    located_node = _locate_template(scene, node)
    located_target = _locate_template(scene, target) if target else None
    if not located_node:
        raise SceneError("装配件原件不存在")
    _, _, _, definition, template = located_node
    template_id = node.assembly.template_id
    new_template_parent_id = located_target[4].id if located_target else None
    if template_id == new_template_parent_id:
        raise SceneError("不能把原件节点挂到自己下面")
    template_scene = Scene(nodes=definition.nodes, root_ids=definition.root_ids)
    template_index = template_scene.index()
    if is_ancestor(template_index, template_id, new_template_parent_id):
        raise SceneError("检测到循环挂接：不能把装配件零件挂到它自己的子物体下面")
    if template_id in definition.root_ids and new_template_parent_id is not None:
        raise SceneError("装配件原件根不能成为另一个零件的子级")

    scene = scene.model_copy(deep=True)
    live_def = next(d for d in scene.assembly_defs if d.id == definition.id)
    tpl = next(n for n in live_def.nodes if n.id == template_id)
    if tpl.parent_id == new_template_parent_id:
        return scene
    matrices = world_matrices(Scene(nodes=live_def.nodes, root_ids=live_def.root_ids))
    saved_world = matrices[template_id]
    new_parent_world = matrices[new_template_parent_id] if new_template_parent_id else None
    if tpl.parent_id is None:
        live_def.root_ids.remove(template_id)
    else:
        next(n for n in live_def.nodes if n.id == tpl.parent_id).children.remove(template_id)
    tpl.parent_id = new_template_parent_id
    if new_template_parent_id is None:
        live_def.root_ids.append(template_id)
    else:
        next(n for n in live_def.nodes if n.id == new_template_parent_id).children.append(template_id)
    if keep_world_transform:
        basis = inverse(new_parent_world) if new_parent_world is not None else np.identity(4)
        pos, quat, scl = decompose(multiply(basis, saved_world))
        tpl.transform = Transform(
            position=[float(v) for v in pos],
            rotation=[float(v) for v in quat],
            scale=[float(v) for v in scl],
        )
    _bump_definition(scene, live_def)
    return scene


def _template_paths(definition: AssemblyDefinition) -> Dict[str, str]:
    """模板 id -> 层级名路径，便于预览展示。"""
    index = {n.id: n for n in definition.nodes}
    paths: Dict[str, str] = {}

    def walk(nid, suffix):
        node = index.get(nid)
        name = (node.name if node else nid)
        full = f"{name}/{suffix}" if suffix else name
        paths[nid] = full
        for child in node.children if node else []:
            walk(child, full)

    for rid in definition.root_ids:
        node = index[rid]
        paths[rid] = node.name
        for child in node.children:
            walk(child, node.name)
    return paths


def _transform_equal(a: Transform, b: Transform) -> bool:
    return a.position == b.position and a.rotation == b.rotation and a.scale == b.scale


def _instance_change_info(scene, instance, old_def, new_def):
    old_index = {n.id: n for n in old_def.nodes}
    new_index = {n.id: n for n in new_def.nodes}
    new_paths = _template_paths(new_def)
    old_paths = _template_paths(old_def)
    changed, removed, added = [], [], []
    for tid, node in old_index.items():
        if tid in new_index:
            if not _transform_equal(node.transform, new_index[tid].transform) or node.parent_id != new_index[tid].parent_id:
                has_override = tid in instance.overrides
                changed.append(
                    {
                        "template_id": tid,
                        "name": new_index[tid].name,
                        "path": new_paths.get(tid, new_index[tid].name),
                        "has_local_override": has_override,
                    }
                )
        else:
            removed.append(
                {
                    "template_id": tid,
                    "name": node.name,
                    "path": old_paths.get(tid, node.name),
                    "live_node_id": instance.node_map.get(tid),
                }
            )
    for tid, node in new_index.items():
        if tid not in old_index:
            added.append({"template_id": tid, "name": node.name, "path": new_paths.get(tid, node.name)})
    old_slots = {s.key: s for s in old_def.slots}
    new_slots = {s.key: s for s in new_def.slots}
    slots_removed, slots_added = [], []
    for key, slot in old_slots.items():
        nested = next((i for i in instance.nested_instances if i.slot_key == key), None)
        if key not in new_slots:
            slots_removed.append(
                {
                    "slot_key": key,
                    "assembly_id": slot.assembly_id,
                    "name": nested.name if nested else _assembly_index(scene).get(slot.assembly_id).name
                    if _assembly_index(scene).get(slot.assembly_id)
                    else slot.assembly_id,
                    "detached": key in instance.detached_slots,
                }
            )
    for key, slot in new_slots.items():
        if key not in old_slots:
            slots_added.append({"slot_key": key, "assembly_id": slot.assembly_id})
    return {
        "changed": changed,
        "removed": removed,
        "added": added,
        "slots_removed": slots_removed,
        "slots_added": slots_added,
    }




def assembly_update_preview(scene: Scene, assembly_id: Optional[str] = None):
    """返回落后于当前原件的所有（含嵌套）实例及逐项差异。只读：放弃则现场不变。"""
    scene = scene.model_copy(deep=True)
    targets = {assembly_id} if assembly_id else {d.id for d in scene.assembly_defs}
    results = []
    for instance, top, path in _all_instances(scene):
        if instance.assembly_id not in targets:
            continue
        new_def = _assembly_index(scene).get(instance.assembly_id)
        old_def = _definition_at(scene, instance.assembly_id, instance.pinned_version)
        if not new_def or not old_def or new_def.version == instance.pinned_version:
            continue
        info = _instance_change_info(scene, instance, old_def, new_def)
        label = top.name
        if path:
            label += " / " + " / ".join(path)
        results.append(
            {
                "assembly_id": instance.assembly_id,
                "assembly_name": new_def.name,
                "instance_id": instance.id,
                "top_instance_id": top.id,
                "instance_name": label,
                "from_version": instance.pinned_version,
                "to_version": new_def.version,
                "path": path,
                **info,
            }
        )
    return results


def _subtree_root_ids(scene: Scene, roots: List[str]) -> List[str]:
    index = scene.index()
    out, stack, seen = [], list(roots), set()
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        node = index.get(nid)
        out.append(nid)
        if node:
            stack.extend(node.children)
    return out


def apply_assembly_update(
    scene: Scene,
    assembly_id: str,
    instance_ids: Optional[List[str]] = None,
    override_choices: Optional[Dict[str, str]] = None,
    drop_removed: bool = False,
):
    """把选定（可嵌套）实例更新到原件最新版本，返回新场景，供前端整笔撤销。

    override_choices: {instance_id: "follow"|"keep"} 整体选择，
    或 {"<instance_id>:<template_id>": "follow"|"keep"} 逐项选择；默认 follow。
    drop_removed=True 时，原件中消失的部件/嵌套子装配件一并删除，
    否则它们作为失去对应关系的普通节点保留在实例内。
    """
    scene = scene.model_copy(deep=True)
    override_choices = override_choices or {}
    new_def = _assembly_index(scene).get(assembly_id)
    if not new_def:
        raise SceneError("装配件原件不存在")
    wanted = set(instance_ids) if instance_ids else None

    def choice(inst_id: str, tid: str) -> str:
        return override_choices.get(f"{inst_id}:{tid}", override_choices.get(inst_id, "follow"))

    top_targets = {
        top.id
        for inst, top, _ in _all_instances(scene)
        if inst.assembly_id == assembly_id
        and inst.pinned_version != new_def.version
        and (wanted is None or inst.id in wanted)
    }

    def build_plan(inst: AssemblyInstance, selected: bool, force: bool = False, child_force: bool = False) -> Optional[dict]:
        """自底向上构造重建计划；None 表示该实例本层不变（仍可能因子槽变化重建）。"""
        current_def = _assembly_index(scene).get(inst.assembly_id)
        pinned_def = _definition_at(scene, inst.assembly_id, inst.pinned_version) or current_def
        updating = (
            selected
            and inst.assembly_id == assembly_id
            and current_def is not None
            and inst.pinned_version != current_def.version
        )
        target_def = current_def if updating else pinned_def
        child_plans = {}
        for slot in target_def.slots:
            nested = next((i for i in inst.nested_instances if i.slot_key == slot.key), None)
            detached = inst.detached_slots.get(slot.key)
            if detached:
                child_plans[slot.key] = {
                    "preserved": {ROOT_KEY: list(detached.node_ids)},
                    "detached": True,
                }
                continue
            if nested is None:
                continue
            child_selected = (
                True
                if wanted is None
                else (
                    nested.assembly_id == assembly_id
                    and nested.pinned_version != new_def.version
                    and nested.id in wanted
                )
            )
            child_plans[slot.key] = build_plan(nested, child_selected, force=child_force, child_force=child_force)
        child_plans = {k: v for k, v in child_plans.items() if v is not None}
        if not updating and not any(p and p.get("rebuilt") for p in child_plans.values()):
            if not force or not any(p is not None and (p.get("rebuilt") or any(
                q.get("rebuilt") for q in (p.get("slots") or {}).values())
            ) for p in child_plans.values()):
                return None
            return {
                "rebuilt": False,
                "identity": True,
                "instance_id": inst.id,
                "assembly_id": inst.assembly_id,
                "target_version": inst.pinned_version,
                "parent_id": inst.parent_id,
                "transform": inst.transform.model_copy(deep=True),
                "overrides": {k: v.model_copy(deep=True) for k, v in inst.overrides.items()},
                "preserved": None,
                "slots": child_plans,
            }
        preserved: Dict[str, List[str]] = {}
        if updating:
            new_template_ids = {n.id for n in target_def.nodes}
            new_slot_keys = {s.key for s in target_def.slots}
            keep_override_ids = {tid for tid in inst.overrides if choice(inst.id, tid) == "keep"}
            follow_override_ids = set(inst.overrides) - keep_override_ids
            for tid, nid in inst.node_map.items():
                if tid == ROOT_KEY:
                    continue
                if tid in keep_override_ids:
                    preserved[tid] = _subtree_root_ids(scene, [nid])
                elif tid not in new_template_ids and not drop_removed:
                    preserved[tid] = _subtree_root_ids(scene, [nid])
            for slot in pinned_def.slots:
                nested = next((i for i in inst.nested_instances if i.slot_key == slot.key), None)
                live_root = nested.node_map.get(ROOT_KEY) if nested else None
                if slot.key in new_slot_keys:
                    continue
                if live_root and not drop_removed:
                    preserved[slot.key] = _subtree_root_ids(scene, [live_root])
                elif slot.key in inst.detached_slots:
                    preserved[slot.key] = list(inst.detached_slots[slot.key].node_ids)
            for detached_key, detached in inst.detached_slots.items():
                if detached_key in new_slot_keys:
                    preserved[detached_key] = list(detached.node_ids)
            new_overrides = {
                tid: inst.overrides[tid].model_copy(deep=True)
                for tid in keep_override_ids
                if tid in {n.id for n in target_def.nodes}
            }
        else:
            follow_override_ids = set()
            new_overrides = {k: v.model_copy(deep=True) for k, v in inst.overrides.items()}
        if not updating:
            return {
                "rebuilt": False,
                "identity": True,
                "instance_id": inst.id,
                "assembly_id": inst.assembly_id,
                "target_version": inst.pinned_version,
                "parent_id": inst.parent_id,
                "transform": inst.transform.model_copy(deep=True),
                "overrides": dict(new_overrides),
                "preserved": None,
                "slots": child_plans,
            }
        return {
            "rebuilt": True,
            "instance_id": inst.id,
            "assembly_id": inst.assembly_id,
            "target_version": target_def.version,
            "parent_id": inst.parent_id,
            "transform": inst.transform.model_copy(deep=True),
            "overrides": new_overrides,
            "preserved": preserved or None,
            "slots": child_plans,
        }

    for top in list(scene.assembly_instances):
        _is_target_top = top.assembly_id == assembly_id
        if wanted is None:
            top_selected = _is_target_top
        else:
            top_selected = (
                _is_target_top and top.pinned_version != new_def.version and top.id in wanted
            )
        descendant_selected = wanted is not None and any(
            inst.id in wanted and inst.assembly_id == assembly_id
            for inst, t, _ in _all_instances(scene)
            if t.id == top.id and inst is not top
        )
        if wanted is not None and not top_selected and not descendant_selected:
            continue
        plan = build_plan(top, top_selected, force=top_selected, child_force=(wanted is None or descendant_selected))
        if plan is None:
            continue
        if not plan.get("rebuilt") and not any(p and p.get("rebuilt") for p in plan["slots"].values()):
            continue
        existing = {n.id for n in scene.nodes}
        for inst, _, _ in _all_instances(scene):
            existing.add(inst.id)
        _execute_top_plan(scene, top, plan, existing)
    return scene


def _identity_state(inst: AssemblyInstance, scene: Scene) -> dict:
    """未更新的嵌套实例：完整保留局部状态，仅随外层重生成。"""
    pinned_def = _definition_at(scene, inst.assembly_id, inst.pinned_version) or _assembly_index(scene)[inst.assembly_id]
    return {
        "transform": inst.transform.model_copy(deep=True),
        "overrides": {k: v.model_copy(deep=True) for k, v in inst.overrides.items()},
        "pinned_version": inst.pinned_version,
        "detached_slots": {k: v.model_copy(deep=True) for k, v in inst.detached_slots.items()},
        "nested_state": _collect_nested_state(inst, pinned_def, scene),
    }


def _plan_state(scene: Scene, inst: AssemblyInstance, sub_plan: dict) -> dict:
    if not sub_plan.get("rebuilt"):
        state = _identity_state(inst, scene)
        state["pinned_version"] = sub_plan["target_version"]
        if sub_plan.get("preserved"):
            state["preserved"] = sub_plan["preserved"]
        for slot_key, child_plan in (sub_plan.get("slots") or {}).items():
            child_inst = next((i for i in inst.nested_instances if i.slot_key == slot_key), None)
            if child_inst is not None and child_plan is not None:
                state["nested_state"] = state["nested_state"] or {}
                state["nested_state"][slot_key] = (
                    _plan_state(scene, child_inst, child_plan)
                )
        return state
    target_def = _definition_at(scene, sub_plan["assembly_id"], sub_plan["target_version"])
    nested_state: Dict[str, dict] = {}
    for slot in target_def.slots:
        child_plan = sub_plan["slots"].get(slot.key)
        if child_plan is None:
            continue
        if child_plan.get("preserved"):
            nested_state[slot.key] = {"preserved": child_plan["preserved"]}
            continue
        child_inst = next((i for i in inst.nested_instances if i.slot_key == slot.key), None)
        if child_inst is None:
            continue
        nested_state[slot.key] = (
            _plan_state(scene, child_inst, child_plan)
            if child_plan.get("rebuilt")
            else _plan_state(scene, child_inst, child_plan)
        )
    return {
        "transform": sub_plan["transform"],
        "overrides": sub_plan["overrides"],
        "pinned_version": sub_plan["target_version"],
        "detached_slots": {},
        "preserved": sub_plan.get("preserved") or {},
        "nested_state": nested_state,
    }


def _execute_top_plan(scene: Scene, top: AssemblyInstance, plan: dict, existing: set) -> None:
    target_def = _definition_at(scene, plan["assembly_id"], plan["target_version"])
    pinned_def = _definition_at(scene, plan["assembly_id"], top.pinned_version) or target_def
    child_state = {}
    for slot in target_def.slots if not plan.get("identity") else pinned_def.slots:
        if plan.get("identity") and slot.key not in plan["slots"]:
            continue
        child_plan = plan["slots"].get(slot.key)
        if child_plan is None:
            continue
        if child_plan.get("detached") or (
            child_plan.get("preserved") and not child_plan.get("rebuilt") and not child_plan.get("identity")
        ):
            child_state[slot.key] = {"preserved": child_plan["preserved"]}
            continue
        nested = next((i for i in top.nested_instances if i.slot_key == slot.key), None)
        if nested is None and not plan.get("identity"):
            nested = next(
                (i for i in top.nested_instances if i.assembly_id == slot.assembly_id),
                None,
            )
        if nested is None:
            continue
        child_state[slot.key] = _plan_state(scene, nested, child_plan)
    new_top = AssemblyInstance(
        id=top.id,
        name=top.name,
        assembly_id=plan["assembly_id"],
        assembly_version=plan["target_version"],
        pinned_version=plan["target_version"],
        parent_id=plan["parent_id"],
        transform=plan["transform"],
        overrides=plan["overrides"],
    )
    idx = scene.assembly_instances.index(top)
    keep = set()
    for roots in (plan.get("preserved") or {}).values():
        keep.update(roots)
    for state_obj in child_state.values():
        keep.update(_state_keep_ids(state_obj))
    keep.update(_all_detached_ids(top))
    _remove_instance_nodes(scene, top, keep)
    scene.assembly_instances[idx] = new_top
    _materialize(
        scene,
        new_top,
        target_def,
        plan["parent_id"],
        existing,
        preserved=plan.get("preserved"),
        nested_state=child_state,
    )


def reparent(
    scene: Scene, node_id: str, new_parent_id: Optional[str], keep_world_transform: bool = True
) -> Scene:
    source_node = scene.index().get(node_id)
    nested_root_info = None
    if source_node and source_node.assembly:
        found = _find_instance(scene, source_node.assembly.instance_id)
        if found:
            inst, _, _ = found
            inst_def = _definition_at(scene, inst.assembly_id, inst.pinned_version) or _assembly_index(scene)[inst.assembly_id]
            if source_node.assembly.template_id not in inst_def.root_ids:
                raise SceneError("不能单独移动装配件内部零件；请移动装配件根节点或先脱离原件")
            nested_root_info = (inst, found[1])

    scene = scene.model_copy(deep=True)
    index = scene.index()
    node = _require(index, node_id)
    if new_parent_id is not None:
        _require(index, new_parent_id)
        _require_not_assembly_node(index, new_parent_id)
    if is_ancestor(index, node_id, new_parent_id):
        raise SceneError("检测到循环挂接：不能把组挂到它自己的子物体下面")
    if node.parent_id == new_parent_id:
        return scene

    if keep_world_transform:
        matrices = world_matrices(scene)
        saved_world = matrices[node_id]
        new_parent_world = matrices[new_parent_id] if new_parent_id is not None else None
    else:
        saved_world = new_parent_world = None

    if nested_root_info is not None:
        old_inst_id, _ = nested_root_info
        found = _find_instance(scene, old_inst_id)
        inst = found[0]
        if inst.parent_instance_id is not None:
            raise SceneError("嵌套装配件随外层原件放置；请在外层原件中调整槽位或先脱离")
        old_parent_id = inst.parent_id
        root_id = inst.node_map.get(ROOT_KEY)
        if old_parent_id is None:
            scene.root_ids.remove(root_id)
        else:
            index[old_parent_id].children.remove(root_id)
        inst.parent_id = new_parent_id
        if new_parent_id is None:
            scene.root_ids.append(root_id)
        else:
            index[new_parent_id].children.append(root_id)
        if keep_world_transform:
            basis = inverse(new_parent_world) if new_parent_world is not None else np.identity(4)
            pos, quat, scl = decompose(multiply(basis, saved_world))
            inst.transform = Transform(
                position=[float(v) for v in pos],
                rotation=[float(v) for v in quat],
                scale=[float(v) for v in scl],
            )
            index[root_id].transform = inst.transform.model_copy(deep=True)
        return scene

    old_parent_id = node.parent_id
    if old_parent_id is None:
        scene.root_ids.remove(node_id)
    else:
        index[old_parent_id].children.remove(node_id)
    node.parent_id = new_parent_id
    if new_parent_id is None:
        scene.root_ids.append(node_id)
    else:
        index[new_parent_id].children.append(node_id)
    if keep_world_transform:
        basis = inverse(new_parent_world) if new_parent_world is not None else np.identity(4)
        pos, quat, scl = decompose(multiply(basis, saved_world))
        node.transform = Transform(
            position=[float(v) for v in pos],
            rotation=[float(v) for v in quat],
            scale=[float(v) for v in scl],
        )
    return scene


def duplicate_subtree(scene: Scene, node_id: str) -> Scene:
    source_node = scene.index().get(node_id)
    if source_node and source_node.assembly:
        found = _find_instance(scene, source_node.assembly.instance_id)
        if found:
            inst, top, _ = found
            inst_def = _definition_at(scene, inst.assembly_id, inst.pinned_version) or _assembly_index(scene)[inst.assembly_id]
            if source_node.assembly.template_id not in inst_def.root_ids:
                raise SceneError("不能复制装配件内部零件；请复制装配件根节点或先脱离原件")
            if inst.parent_instance_id is not None:
                raise SceneError("嵌套装配件请在外层原件中复制槽位，或先脱离外层原件")
            scene = scene.model_copy(deep=True)
            source_top = next(i for i in scene.assembly_instances if i.id == top.id)
            definition = _definition_at(scene, source_top.assembly_id, source_top.pinned_version)
            existing = {n.id for n in scene.nodes}
            for item, _, _ in _all_instances(scene):
                existing.add(item.id)
            copied = AssemblyInstance(
                id=_new_id(existing),
                name=source_top.name + " 副本",
                assembly_id=source_top.assembly_id,
                assembly_version=source_top.assembly_version,
                pinned_version=source_top.pinned_version,
                parent_id=source_top.parent_id,
                transform=source_top.transform.model_copy(deep=True),
                overrides={k: v.model_copy(deep=True) for k, v in source_top.overrides.items()},
            )
            copied.transform.position = [source_top.transform.position[0] + 1.0, source_top.transform.position[1], source_top.transform.position[2]]
            state = _collect_nested_state(source_top, definition, scene)
            scene.assembly_instances.append(copied)
            _materialize(scene, copied, definition, copied.parent_id, existing, nested_state=state)
            return scene

    scene = scene.model_copy(deep=True)
    index = scene.index()
    _require(index, node_id)
    ids = subtree_ids(index, node_id)
    id_map: Dict[str, str] = {}
    existing = set(index)
    for old_id in ids:
        id_map[old_id] = _new_id(existing)
    clones: List[Node] = []
    for old_id in ids:
        old = index[old_id]
        clone = old.model_copy(deep=True)
        clone.id = id_map[old_id]
        clone.parent_id = id_map[old.parent_id] if old.parent_id in id_map else old.parent_id
        clone.children = []
        clone.name = f"{old.name} 副本"
        clones.append(clone)
    scene.nodes.extend(clones)
    new_index = scene.index()
    for clone in clones:
        if clone.parent_id is None:
            scene.root_ids.append(clone.id)
        else:
            new_index[clone.parent_id].children.append(clone.id)
    new_root = next(c for c in clones if c.id == id_map[node_id])
    new_root.transform.position = [new_root.transform.position[0] + 1.0, new_root.transform.position[1], new_root.transform.position[2]]
    return scene


def delete_subtree(scene: Scene, node_id: str) -> Scene:
    scene = scene.model_copy(deep=True)
    index = scene.index()
    node = _require(index, node_id)
    if node.assembly:
        found = _find_instance(scene, node.assembly.instance_id)
        if found:
            inst, top, _ = found
            inst_def = _definition_at(scene, inst.assembly_id, inst.pinned_version) or _assembly_index(scene)[inst.assembly_id]
            if node.assembly.template_id not in inst_def.root_ids:
                raise SceneError("不能删除装配件内部零件；请删除整个装配件或先脱离原件")
            if inst.parent_instance_id is not None:
                raise SceneError("嵌套装配件需随外层一起删除，或先脱离外层原件")
            _remove_instance_nodes(scene, inst)
            scene.assembly_instances = [item for item in scene.assembly_instances if item.id != inst.id]
            return scene
    removed = set(subtree_ids(index, node_id))
    if node.parent_id is None:
        scene.root_ids = [rid for rid in scene.root_ids if rid != node_id]
    else:
        parent = index[node.parent_id]
        parent.children = [c for c in parent.children if c != node_id]
    scene.nodes = [n for n in scene.nodes if n.id not in removed]
    return scene


def detach_assembly_instance(scene: Scene, node_id: str) -> Scene:
    """脱离后实例节点成为普通节点（嵌套时保留为外层内的普通子树），永不重新关联。"""
    scene = scene.model_copy(deep=True)
    node = _require(scene.index(), node_id)
    if not node.assembly:
        return scene
    found = _find_instance(scene, node.assembly.instance_id)
    if not found:
        return scene
    inst, top, path = found
    inst_def = _definition_at(scene, inst.assembly_id, inst.pinned_version) or _assembly_index(scene)[inst.assembly_id]
    if node.assembly.template_id not in inst_def.root_ids:
        raise SceneError("请选择装配件根节点脱离原件")
    generated = set(_all_generated_ids(inst))
    for scene_node in scene.nodes:
        if scene_node.id in generated:
            scene_node.assembly = None
    if inst.parent_instance_id is None:
        scene.assembly_instances = [item for item in scene.assembly_instances if item.id != inst.id]
    else:
        holder = _find_instance(scene, inst.parent_instance_id)[0]
        holder.nested_instances = [item for item in holder.nested_instances if item.id != inst.id]
        roots = [inst.node_map.get(ROOT_KEY)]
        holder.detached_slots[inst.slot_key] = DetachedSlot(
            node_ids=[nid for nid in _subtree_root_ids(scene, roots) if nid in scene.index()]
        )
    return scene


def delete_assembly_definition(scene: Scene, assembly_id: str) -> Scene:
    """删除原件：顶层实例脱离；被其他原件嵌套引用的槽也转为保留的普通子树。"""
    scene = scene.model_copy(deep=True)
    definition = _assembly_index(scene).get(assembly_id)
    if not definition:
        raise SceneError("装配件原件不存在")
    linked_top_ids = {item.id for item in scene.assembly_instances if item.assembly_id == assembly_id}
    linked_node_ids = {
        n.id for n in scene.nodes if n.assembly and n.assembly.instance_id in linked_top_ids
    }
    # 嵌套实例（任意层）的节点也要脱离
    nested_generated = set()
    for top in scene.assembly_instances:
        for inst, t, p in _all_instances(scene):
            if t.id == top.id and inst.assembly_id == assembly_id and inst.parent_instance_id is not None:
                nested_generated.update(_all_generated_ids(inst))
    for scene_node in scene.nodes:
        if scene_node.id in linked_node_ids or scene_node.id in nested_generated:
            scene_node.assembly = None
    # 从实例树中摘除相关实例；嵌套槽记为脱离
    for top in scene.assembly_instances:
        if top.assembly_id == assembly_id:
            continue
        _prune_instance_tree(top, assembly_id)
    scene.assembly_instances = [item for item in scene.assembly_instances if item.assembly_id != assembly_id]
    # 其他原件移除指向该原件的槽（保留下来的节点已在实例重生成时按 detached 处理；
    # 尚未应用更新的实例仍钉在旧快照上，槽数据也保留在快照中，故只改当前原件）
    bumped = []
    for other in scene.assembly_defs:
        if other.id == assembly_id:
            continue
        if any(slot.assembly_id == assembly_id for slot in other.slots):
            other.slots = [slot for slot in other.slots if slot.assembly_id != assembly_id]
            _bump_definition(scene, other)
            bumped.append(other.id)
    scene.assembly_defs = [item for item in scene.assembly_defs if item.id != assembly_id]
    return scene


def _prune_instance_tree(inst: AssemblyInstance, assembly_id: str) -> None:
    keep = []
    for child in inst.nested_instances:
        if child.assembly_id == assembly_id:
            roots = [child.node_map.get(ROOT_KEY)]
            inst.detached_slots[child.slot_key] = DetachedSlot(node_ids=roots)
        else:
            _prune_instance_tree(child, assembly_id)
            keep.append(child)
    inst.nested_instances = keep


def resolve_selection(scene: Scene, ref: Optional[SelectionRef]) -> Optional[str]:
    if ref is None:
        return None
    if ref.node_id and ref.node_id in scene.index():
        return ref.node_id
    if ref.top_instance_id:
        top = _instance_index(scene).get(ref.top_instance_id)
        if top is not None:
            inst = top
            for key in ref.path:
                inst = next((i for i in inst.nested_instances if i.slot_key == key), None)
                if inst is None:
                    break
            if inst is not None and ref.template_id:
                return inst.node_map.get(ref.template_id)
    return None


def make_selection_ref(scene: Scene, node_id: str) -> Optional[SelectionRef]:
    node = scene.index().get(node_id)
    if not node:
        return None
    if not node.assembly:
        return SelectionRef(node_id=node_id)
    found = _find_instance(scene, node.assembly.instance_id)
    if not found:
        return SelectionRef(node_id=node_id)
    inst, top, path = found
    return SelectionRef(
        top_instance_id=top.id,
        path=path_of_instance(scene, inst),
        template_id=node.assembly.template_id,
        node_id=node_id,
    )


def path_of_instance(scene: Scene, inst: AssemblyInstance) -> List[str]:
    found = _find_instance(scene, inst.id)
    return list(found[2]) if found else []


# ---------------------------------------------------------------------------
# 发布版本：把整个总成锁定为可重开的快照，支持派生（只升级部分子装配）
# ---------------------------------------------------------------------------


def _capture_release_state(scene: Scene, inst: AssemblyInstance) -> ReleaseInstanceState:
    """冻结一棵（可嵌套）实例树：钉住版本、实例覆盖、脱离槽现场节点。"""
    index = scene.index()
    detached_nodes: Dict[str, List[Node]] = {}
    for key, detached in inst.detached_slots.items():
        ids = [nid for nid in _subtree_root_ids(scene, list(detached.node_ids)) if nid in index]
        nodes: List[Node] = []
        for nid in ids:
            node = index[nid].model_copy(deep=True)
            node.assembly = None
            nodes.append(node)
        if nodes:
            detached_nodes[key] = nodes
    return ReleaseInstanceState(
        instance_id=inst.id,
        slot_key=inst.slot_key,
        parent_id=inst.parent_id,
        assembly_id=inst.assembly_id,
        pinned_version=inst.pinned_version,
        name=inst.name,
        transform=inst.transform.model_copy(deep=True),
        overrides={k: v.model_copy(deep=True) for k, v in inst.overrides.items()},
        detached_nodes=detached_nodes,
        nested=[_capture_release_state(scene, child) for child in inst.nested_instances],
    )


def _release_required_versions(
    states: List[ReleaseInstanceState], upgrades: Optional[Dict[str, int]] = None
) -> Dict[tuple, List[str]]:
    """{(assembly_id, version): [实例名, ...]}，版本已按 upgrades 替换。"""
    upgrades = upgrades or {}
    result: Dict[tuple, List[str]] = {}

    def walk(state: ReleaseInstanceState) -> None:
        key = (state.assembly_id, upgrades.get(state.assembly_id, state.pinned_version))
        result.setdefault(key, []).append(state.name)
        for child in state.nested:
            walk(child)

    for state in states:
        walk(state)
    return result


def _assembly_name(scene: Scene, assembly_id: str) -> str:
    versions = _history_index(scene).get(assembly_id)
    if versions:
        return versions[max(versions)].name
    return assembly_id


def publish_release(scene: Scene, name: Optional[str] = None, note: Optional[str] = None) -> Scene:
    """把当前所有顶层装配件实例锁定为一个发布版本（单步操作，可撤销）。

    冻结内容：各层子装配钉住的具体版本、实例覆盖、脱离槽现场；
    同时把用到的原件版本整体拷入发布快照，原件之后的更新不会混入。
    """
    scene = scene.model_copy(deep=True)
    if not scene.assembly_instances:
        raise SceneError("场景中没有装配件实例，没有可发布的总成")
    states = [_capture_release_state(scene, inst) for inst in scene.assembly_instances]
    required = _release_required_versions(states)
    definitions: List[AssemblyDefinition] = []
    missing: List[str] = []
    for (assembly_id, version), names in sorted(required.items()):
        definition = _definition_at(scene, assembly_id, version)
        if definition is None:
            missing.append(f"实例 {'、'.join(names)} 需要 {_assembly_name(scene, assembly_id)} v{version}")
        else:
            definitions.append(definition.model_copy(deep=True))
    if missing:
        raise SceneError("以下装配件版本已不可用，无法发布：" + "；".join(missing))
    existing = {r.id for r in scene.releases} | {n.id for n in scene.nodes}
    release = ReleaseSnapshot(
        id=_new_id(existing),
        name=name or f"发布 {len(scene.releases) + 1}",
        note=note,
        created_at=time.time(),
        definitions=definitions,
        instances=states,
    )
    scene.releases.append(release)
    return scene


def _require_release(scene: Scene, release_id: str) -> ReleaseSnapshot:
    release = next((r for r in scene.releases if r.id == release_id), None)
    if release is None:
        raise SceneError("发布版本不存在")
    return release


def _release_def_map(release: ReleaseSnapshot) -> Dict[tuple, AssemblyDefinition]:
    return {(d.id, d.version): d for d in release.definitions}


def _ensure_release_versions(scene: Scene, release: ReleaseSnapshot, upgrades: Dict[str, int]) -> None:
    """校验发布所需的每个版本都可用；把快照内冻结的原件注入历史。

    任何版本缺失都直接报错并列出受影响实例，绝不用最新版本代替。
    """
    required = _release_required_versions(release.instances, upgrades)
    frozen = _release_def_map(release)
    missing: List[str] = []
    for (assembly_id, version), names in sorted(required.items()):
        if (assembly_id, version) in frozen:
            continue
        if _definition_at(scene, assembly_id, version) is not None:
            continue
        missing.append(f"实例 {'、'.join(names)} 需要 {_assembly_name(scene, assembly_id)} v{version}")
    if missing:
        raise SceneError("装配件版本不可用，已保留现场、未用最新版本代替：" + "；".join(missing))
    for key, definition in frozen.items():
        if _definition_at(scene, key[0], key[1]) is None:
            scene.assembly_history.append(definition.model_copy(deep=True))


def _state_dict_for(child: ReleaseInstanceState, upgrades: Dict[str, int]) -> dict:
    return {
        "transform": child.transform.model_copy(deep=True),
        "overrides": {k: v.model_copy(deep=True) for k, v in child.overrides.items()},
        "pinned_version": upgrades.get(child.assembly_id, child.pinned_version),
        "nested_state": {c.slot_key: _state_dict_for(c, upgrades) for c in child.nested},
    }


def _attach_release_detached(
    scene: Scene,
    inst: AssemblyInstance,
    state: ReleaseInstanceState,
    definition: AssemblyDefinition,
    existing: set,
) -> None:
    """把发布时冻结的脱离槽子树作为普通节点挂回（重新生成 id，不重新关联原件）。"""
    for slot_key, nodes in state.detached_nodes.items():
        id_map: Dict[str, str] = {}
        for node in nodes:
            id_map[node.id] = _new_id(existing)
        clones: List[Node] = []
        for node in nodes:
            clone = node.model_copy(deep=True)
            clone.id = id_map[node.id]
            clone.assembly = None
            clone.children = [id_map[c] for c in node.children if c in id_map]
            clone.parent_id = id_map[node.parent_id] if node.parent_id in id_map else None
            clones.append(clone)
        roots = [c for c in clones if c.parent_id is None]
        slot = _slot_at(definition, slot_key)
        host_id = inst.node_map.get(slot.parent_template_id) if slot else None
        if not host_id or host_id not in scene.index():
            host_id = inst.node_map.get(ROOT_KEY)
        for root in roots:
            root.parent_id = host_id
        scene.nodes.extend(clones)
        if host_id and host_id in scene.index():
            scene.index()[host_id].children.extend(root.id for root in roots)
        inst.detached_slots[slot_key] = DetachedSlot(node_ids=[root.id for root in roots])
    for child_state in state.nested:
        live = next((i for i in inst.nested_instances if i.slot_key == child_state.slot_key), None)
        if live is None:
            continue
        child_def = _definition_at(scene, live.assembly_id, live.pinned_version)
        if child_def is not None:
            _attach_release_detached(scene, live, child_state, child_def, existing)


def _spawn_from_state(
    scene: Scene,
    state: ReleaseInstanceState,
    upgrades: Dict[str, int],
    reuse_id: Optional[str],
    parent_id: Optional[str],
    derived_from: Optional[str] = None,
    source_instance_id: Optional[str] = None,
    offset_x: float = 0.0,
) -> AssemblyInstance:
    version = upgrades.get(state.assembly_id, state.pinned_version)
    definition = _definition_at(scene, state.assembly_id, version)
    if definition is None:
        raise SceneError(f"装配件版本不可用：{state.assembly_id} v{version}")
    existing = {n.id for n in scene.nodes}
    for item, _, _ in _all_instances(scene):
        existing.add(item.id)
    instance_id = reuse_id if reuse_id and reuse_id not in existing else _new_id(existing)
    existing.add(instance_id)
    transform = state.transform.model_copy(deep=True)
    if offset_x:
        transform.position = [transform.position[0] + offset_x, transform.position[1], transform.position[2]]
    instance = AssemblyInstance(
        id=instance_id,
        name=state.name,
        assembly_id=state.assembly_id,
        assembly_version=version,
        pinned_version=version,
        parent_id=parent_id,
        transform=transform,
        overrides={k: v.model_copy(deep=True) for k, v in state.overrides.items()},
        derived_from=derived_from,
        source_instance_id=source_instance_id,
    )
    scene.assembly_instances.append(instance)
    nested_state = {child.slot_key: _state_dict_for(child, upgrades) for child in state.nested}
    _materialize(scene, instance, definition, parent_id, existing, nested_state=nested_state)
    _attach_release_detached(scene, instance, state, definition, existing)
    return instance


def open_release(scene: Scene, release_id: str) -> Scene:
    """按发布时的状态重开总成：原件后来的更新不会混入。

    只替换发布快照中记录过的实例（保持实例 id 不变，选中引用仍可追溯），
    场景里的其他内容不动；任一锁定版本不可用则整体放弃并保留现场。
    """
    scene = scene.model_copy(deep=True)
    release = _require_release(scene, release_id)
    _ensure_release_versions(scene, release, {})
    recorded = {state.instance_id for state in release.instances}
    for top in list(scene.assembly_instances):
        if top.id in recorded:
            _remove_instance_nodes(scene, top)
    scene.assembly_instances = [item for item in scene.assembly_instances if item.id not in recorded]
    for state in release.instances:
        parent_id = state.parent_id if state.parent_id in scene.index() else None
        _spawn_from_state(scene, state, {}, reuse_id=state.instance_id, parent_id=parent_id)
    return scene


def derive_release(scene: Scene, release_id: str, upgrades: Optional[Dict[str, int]] = None) -> Scene:
    """从旧发布版派生新方案：只升级指定子装配，其余层级保留发布时的旧版。

    派生出的实例使用新 id 并与原总成同时存在（可同时查看不同版本），
    通过 derived_from / source_instance_id 记录来源。
    """
    upgrades = upgrades or {}
    scene = scene.model_copy(deep=True)
    release = _require_release(scene, release_id)
    _ensure_release_versions(scene, release, upgrades)
    for state in release.instances:
        derived = _spawn_from_state(
            scene,
            state,
            upgrades,
            reuse_id=None,
            parent_id=None,
            derived_from=release.id,
            source_instance_id=state.instance_id,
            offset_x=2.0,
        )
        derived.name = f"{state.name} 派生"
        root_id = derived.node_map.get(ROOT_KEY)
        if root_id and root_id in scene.index():
            scene.index()[root_id].name = derived.name
    return scene


def _pseudo_instance(state: ReleaseInstanceState) -> AssemblyInstance:
    return AssemblyInstance(
        id=state.instance_id,
        name=state.name,
        assembly_id=state.assembly_id,
        assembly_version=state.pinned_version,
        pinned_version=state.pinned_version,
        slot_key=state.slot_key,
        transform=state.transform.model_copy(deep=True),
        overrides={k: v.model_copy(deep=True) for k, v in state.overrides.items()},
        nested_instances=[_pseudo_instance(child) for child in state.nested],
        detached_slots={key: DetachedSlot(node_ids=[]) for key in state.detached_nodes},
    )


def release_derive_preview(scene: Scene, release_id: str, upgrades: Optional[Dict[str, int]] = None):
    """预览派生：区分上游升级、实例覆盖与部件删除造成的影响。只读，不改现场。"""
    upgrades = upgrades or {}
    release = _require_release(scene, release_id)
    frozen = _release_def_map(release)

    def def_at(assembly_id: str, version: int) -> Optional[AssemblyDefinition]:
        return frozen.get((assembly_id, version)) or _definition_at(scene, assembly_id, version)

    items: List[dict] = []
    missing: List[dict] = []
    kept: Dict[str, dict] = {}

    def walk(state: ReleaseInstanceState, label: str) -> None:
        target = upgrades.get(state.assembly_id, state.pinned_version)
        old_def = def_at(state.assembly_id, state.pinned_version)
        new_def = def_at(state.assembly_id, target)
        if old_def is None or new_def is None:
            missing.append(
                {
                    "instance_id": state.instance_id,
                    "instance_name": label,
                    "assembly_id": state.assembly_id,
                    "assembly_name": _assembly_name(scene, state.assembly_id),
                    "version": target if new_def is None else state.pinned_version,
                }
            )
            return
        if target != state.pinned_version:
            info = _instance_change_info(scene, _pseudo_instance(state), old_def, new_def)
            items.append(
                {
                    "instance_id": state.instance_id,
                    "instance_name": label,
                    "assembly_id": state.assembly_id,
                    "assembly_name": new_def.name,
                    "from_version": state.pinned_version,
                    "to_version": target,
                    **info,
                }
            )
        else:
            kept[state.assembly_id] = {
                "assembly_id": state.assembly_id,
                "assembly_name": old_def.name,
                "version": state.pinned_version,
            }
        for child in state.nested:
            walk(child, f"{label} / {child.slot_key or child.instance_id}")

    for state in release.instances:
        walk(state, state.name)
    return {"items": items, "kept": list(kept.values()), "missing": missing}

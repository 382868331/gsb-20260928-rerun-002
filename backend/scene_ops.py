"""场景编辑的纯函数：全部基于传入的 scene 返回新 scene（请求级无状态）。"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional

import numpy as np

from .models import AssemblyBinding, AssemblyDefinition, AssemblyInstance, AssemblyOverride, Node, Scene, Transform
from .transforms import compose, decompose, euler_xyz_from_quat, inverse, multiply, to_elements


class SceneError(ValueError):
    pass

# 复制实例树时暂存「父实例 id / 占位模板 -> 已复制的子实例」，供递归物化找回
_PENDING_CHILDREN: Dict[str, Dict[str, AssemblyInstance]] = {}


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


def _assembly_index(scene: Scene):
    return {item.id: item for item in scene.assembly_defs}


def _instance_index(scene: Scene):
    return {item.id: item for item in scene.assembly_instances}


def _definition_for_instance(scene: Scene, instance: AssemblyInstance) -> Optional[AssemblyDefinition]:
    if instance.detached:
        return None
    return _assembly_index(scene).get(instance.assembly_id)


def _instance_child_instances(scene: Scene, instance: AssemblyInstance) -> List[AssemblyInstance]:
    return [item for item in scene.assembly_instances if item.parent_instance_id == instance.id]


def _has_cycle(definitions: Dict[str, AssemblyDefinition], assembly_id: str) -> bool:
    """定义间引用是否存在（含自引用的）循环。"""
    visiting: set = set()
    visited: set = set()

    def dfs(aid: str) -> bool:
        if aid in visiting:
            return True
        if aid in visited:
            return False
        visiting.add(aid)
        definition = definitions.get(aid)
        if definition:
            for node in definition.nodes:
                child_id = node.nested_assembly_id
                if child_id and dfs(child_id):
                    return True
        visiting.discard(aid)
        visited.add(aid)
        return False

    return dfs(assembly_id)


def _assert_no_assembly_cycle(scene: Scene, changed_assembly_id: Optional[str] = None) -> None:
    definitions = _assembly_index(scene)
    targets = [changed_assembly_id] if changed_assembly_id else list(definitions)
    for aid in targets:
        if _has_cycle(definitions, aid):
            raise SceneError("检测到相互引用的装配关系：本次修改已拒绝，其他装配件仍可编辑")


def _instance_root_template_ids(scene: Scene, instance: AssemblyInstance) -> set:
    if instance.detached:
        return set(instance.detached_root_ids)
    definition = _assembly_index(scene).get(instance.assembly_id)
    if not definition:
        return set()
    if instance.baseline_version < definition.version and instance.baseline_nodes:
        return set(instance.baseline_root_ids)
    return set(definition.root_ids)


def _assert_is_instance_root(scene: Scene, instance: AssemblyInstance, node_id: str) -> None:
    root_ids = _instance_root_template_ids(scene, instance)
    if node_id not in {instance.node_map.get(tid) for tid in root_ids}:
        raise SceneError("不能单独移动装配件内部零件；请移动装配件根节点或先脱离原件")


def _instance_for_node(scene: Scene, node_id: str) -> Optional[AssemblyInstance]:
    node = scene.index().get(node_id)
    if not node or not node.assembly:
        return None
    return _instance_index(scene).get(node.assembly.instance_id)


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


def _remove_instance_nodes(scene: Scene, instance: AssemblyInstance) -> None:
    _remove_instance_subtree(scene, instance)


def _generated_node_ids(instance: AssemblyInstance) -> set:
    return {node_id for node_id in instance.node_map.values() if not node_id.startswith("__")}


def _detach_node_from_parent(scene: Scene, node_id: str, parent_id: Optional[str]) -> None:
    if parent_id is None:
        scene.root_ids = [rid for rid in scene.root_ids if rid != node_id]
    else:
        parent = scene.index().get(parent_id)
        if parent:
            parent.children = [cid for cid in parent.children if cid != node_id]


def _remove_instance_subtree(scene: Scene, instance: AssemblyInstance) -> None:
    """删除实例的全部场景节点（含嵌套子实例），并从实例表移除。"""
    for child in list(_instance_child_instances(scene, instance)):
        _clear_instance_nodes(scene, child)
    generated = _generated_node_ids(instance)
    root_node_id = instance.node_map.get("__root__", "")
    if root_node_id:
        _detach_node_from_parent(scene, root_node_id, instance.parent_id)
    scene.nodes = [node for node in scene.nodes if node.id not in generated]
    scene.assembly_instances = [item for item in scene.assembly_instances if item.id != instance.id]


def _clear_instance_nodes(scene: Scene, instance: AssemblyInstance) -> None:
    """只清空实例（含嵌套子实例）的场景节点，保留实例记录及其覆盖/基线。"""
    for child in list(_instance_child_instances(scene, instance)):
        _clear_instance_nodes(scene, child)
    generated = _generated_node_ids(instance)
    root_node_id = instance.node_map.get("__root__", "")
    if root_node_id:
        _detach_node_from_parent(scene, root_node_id, instance.parent_id)
    scene.nodes = [node for node in scene.nodes if node.id not in generated]
    instance.node_map = {}


def _detach_instance_subtree(scene: Scene, instance: AssemblyInstance) -> None:
    """实例脱离原件：烘焙定义快照；嵌套子实例一并脱离。"""
    if not instance.detached:
        definition = _assembly_index(scene).get(instance.assembly_id)
        if definition:
            instance.detached = True
            instance.detached_nodes = [node.model_copy(deep=True) for node in definition.nodes]
            instance.detached_root_ids = list(definition.root_ids)
    for child in list(_instance_child_instances(scene, instance)):
        _detach_instance_subtree(scene, child)
    for node in scene.nodes:
        if node.assembly and node.assembly.instance_id == instance.id:
            node.assembly = None


def _materialize_instance(scene: Scene, instance: AssemblyInstance) -> None:
    """按实例选择的版本重新生成场景节点（递归物化嵌套子装配件）。"""
    existing_record = _instance_index(scene).get(instance.id)
    if existing_record and existing_record.node_map:
        _clear_instance_nodes(scene, instance)

    definitions = _assembly_index(scene)
    if instance.detached:
        template_nodes = instance.detached_nodes
        template_root_ids = list(instance.detached_root_ids)
        definition_id = instance.assembly_id
        definition_version = instance.assembly_version
    else:
        definition = definitions[instance.assembly_id]
        definition_id = definition.id
        if instance.baseline_version < definition.version and instance.baseline_nodes:
            template_nodes = instance.baseline_nodes
            template_root_ids = list(instance.baseline_root_ids)
            definition_version = instance.baseline_version
        else:
            template_nodes = definition.nodes
            template_root_ids = list(definition.root_ids)
            definition_version = definition.version

    instance.assembly_version = definition_version
    instance.node_map = {}
    existing = set(scene.index())
    template_to_scene: Dict[str, str] = {t.id: _new_id(existing) for t in template_nodes}

    root_template_ids = set(template_root_ids)
    root_nodes: List[Node] = []
    nested_template_ids = {t.id for t in template_nodes if t.nested_assembly_id}
    for template_node in template_nodes:
        scene_node = Node(
            id=template_to_scene[template_node.id],
            name=template_node.name,
            type=template_node.type,
            transform=template_node.transform.model_copy(deep=True),
        )
        scene_node.parent_id = (
            template_to_scene[template_node.parent_id]
            if template_node.parent_id in template_to_scene
            else instance.parent_id if template_node.id in root_template_ids else None
        )
        scene_node.children = [
            template_to_scene[cid] for cid in template_node.children if cid in template_to_scene
        ]
        scene_node.assembly = AssemblyBinding(
            assembly_id=definition_id,
            instance_id=instance.id,
            template_id=template_node.id,
            nested_assembly_id=template_node.nested_assembly_id,
        )
        if template_node.id in root_template_ids:
            scene_node.transform = instance.transform.model_copy(deep=True)
            instance.node_map["__root__"] = scene_node.id
            root_nodes.append(scene_node)
        elif template_node.id not in nested_template_ids:
            override = instance.overrides.get(template_node.id)
            if override:
                scene_node.transform = _override_transform(template_node.transform, override)
        scene.nodes.append(scene_node)
        instance.node_map[template_node.id] = scene_node.id

    for root in root_nodes:
        if instance.parent_id is None:
            scene.root_ids.append(root.id)
        else:
            parent = scene.index().get(instance.parent_id)
            if parent:
                parent.children.append(root.id)

    existing_children = {child.host_template_id: child for child in _instance_child_instances(scene, instance)}
    existing_children.update(_PENDING_CHILDREN.pop(instance.id, {}))
    for template_node in template_nodes:
        nested_id = template_node.nested_assembly_id
        if not nested_id:
            continue
        socket_node_id = template_to_scene[template_node.id]
        if instance.detached:
            # 脱离后的子装配件引用同样烘焙：展开成普通节点树挂到占位下
            nested_def = definitions.get(nested_id)
            socket = scene.index()[socket_node_id]
            socket.assembly = None
            socket.type = "assembly"
            if nested_def is not None:
                _bake_definition_under(scene, nested_def, socket_node_id, existing)
            continue
        child = existing_children.get(template_node.id)
        if child is None:
            nested_def = definitions.get(nested_id)
            if nested_def is None:
                scene.index()[socket_node_id].assembly = None
                continue
            child = AssemblyInstance(
                id=_new_id(existing),
                name=nested_def.name,
                assembly_id=nested_id,
                assembly_version=nested_def.version,
                baseline_version=nested_def.version,
                parent_instance_id=instance.id,
                host_template_id=template_node.id,
            )
            scene.assembly_instances.append(child)
        child.parent_instance_id = instance.id
        child.host_template_id = template_node.id
        child.parent_id = socket_node_id
        socket = scene.index()[socket_node_id]
        if socket.assembly:
            socket.assembly = socket.assembly.model_copy(update={"child_instance_id": child.id})
        _materialize_instance(scene, child)


def _refresh_linked_instances(scene: Scene, assembly_id: str, *, only: Optional[str] = None) -> None:
    for instance in list(scene.assembly_instances):
        if instance.assembly_id == assembly_id and not instance.detached:
            if only is None or instance.id == only:
                _materialize_instance(scene, instance)


def _bake_definition_under(
    scene: Scene,
    definition: AssemblyDefinition,
    socket_node_id: str,
    existing: set,
) -> None:
    """把一个装配件定义按当前版本展开成普通节点树，挂到 socket 节点下。"""
    id_map: Dict[str, str] = {t.id: _new_id(existing) for t in definition.nodes}
    socket = scene.index()[socket_node_id]
    for template_node in definition.nodes:
        plain = Node(
            id=id_map[template_node.id],
            name=template_node.name,
            type=template_node.type,
            transform=template_node.transform.model_copy(deep=True),
        )
        plain.parent_id = (
            id_map[template_node.parent_id]
            if template_node.parent_id in id_map
            else socket_node_id if template_node.id in definition.root_ids else None
        )
        plain.children = [id_map[c] for c in template_node.children if c in id_map]
        scene.nodes.append(plain)
    for rid in definition.root_ids:
        socket.children.append(id_map[rid])
    for template_node in definition.nodes:
        if template_node.nested_assembly_id:
            nested_def = _assembly_index(scene).get(template_node.nested_assembly_id)
            if nested_def is not None:
                _bake_definition_under(scene, nested_def, id_map[template_node.id], existing)


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


def create_assembly(scene: Scene, root_id: str, name: Optional[str] = None) -> Scene:
    scene = scene.model_copy(deep=True)
    index = scene.index()
    root = _require(index, root_id)
    if root.assembly:
        raise SceneError("请先脱离装配件实例，再把它保存为新的可复用装配件")
    ids = subtree_ids(index, root_id)
    existing = set(index) | {item.id for item in scene.assembly_defs} | {item.id for item in scene.assembly_instances}
    assembly_id = _new_id(existing)
    definition = AssemblyDefinition(id=assembly_id, name=name or f"装配件 {len(scene.assembly_defs) + 1}")
    # 子树中若包含嵌套装配件实例，记录其根节点（顶层嵌入的子实例）
    nested_roots: Dict[str, AssemblyInstance] = {}
    for old_id in ids:
        source = index[old_id]
        if source.assembly:
            nested_inst = _instance_index(scene).get(source.assembly.instance_id)
            nested_def = _assembly_index(scene).get(source.assembly.assembly_id)
            if nested_inst and nested_def and old_id == nested_inst.node_map.get("__root__"):
                nested_roots[old_id] = nested_inst
    id_remap: Dict[str, str] = {}
    for old_id in ids:
        id_remap[old_id] = _new_id(existing)
    for old_id in ids:
        source = index[old_id]
        template = source.model_copy(deep=True)
        template.id = id_remap[old_id]
        template.parent_id = id_remap[source.parent_id] if source.parent_id in ids else None
        template.children = [id_remap[cid] for cid in source.children if cid in ids]
        if old_id in nested_roots:
            nested_inst = nested_roots[old_id]
            template.type = "assembly"
            template.nested_assembly_id = nested_inst.assembly_id
            template.assembly = None
        else:
            template.assembly = None
        definition.nodes.append(template)
    definition.root_ids = [id_remap[root_id]]
    scene.assembly_defs.append(definition)
    _assert_no_assembly_cycle(scene, definition.id)

    instance = AssemblyInstance(
        id=_new_id(existing),
        name=definition.name,
        assembly_id=assembly_id,
        assembly_version=definition.version,
        baseline_version=definition.version,
        parent_id=root.parent_id,
        transform=root.transform.model_copy(deep=True),
    )
    # 移除原子树节点，但保留嵌套子实例的实例记录（改挂到新实例下）
    nested_children = {
        id_remap[old_root_id]: inst for old_root_id, inst in nested_roots.items()
    }
    removed_ids = set(ids) - set(nested_roots.keys())
    for child_inst in nested_children.values():
        child_inst.parent_instance_id = instance.id
        # host_template_id 在物化时按占位模板重新建立
        child_inst.host_template_id = None
    if root.parent_id is None:
        scene.root_ids = [rid for rid in scene.root_ids if rid != root_id]
    else:
        scene.index()[root.parent_id].children = [
            cid for cid in scene.index()[root.parent_id].children if cid != root_id
        ]
    # 保留子实例节点本身：先把子实例记录从表中摘掉再删旧节点，最后交回新父实例
    nested_instance_ids = {item.id for item in nested_children.values()}
    kept_nested_nodes: set = set()
    for item in nested_children.values():
        kept_nested_nodes |= _generated_node_ids(item)
    scene.nodes = [
        node for node in scene.nodes if node.id not in removed_ids and node.id not in kept_nested_nodes
    ]
    scene.assembly_instances = [
        item for item in scene.assembly_instances if item.id not in nested_instance_ids
    ]
    _materialize_nested_into_new_instance(scene, instance, definition, nested_children)
    return scene


def _materialize_nested_into_new_instance(
    scene: Scene,
    instance: AssemblyInstance,
    definition: AssemblyDefinition,
    nested_roots: Dict[str, AssemblyInstance],
) -> None:
    """物化新建实例，并把原场景中的嵌套子实例接回到对应占位下。"""
    existing = set(scene.index()) | {item.id for item in scene.assembly_instances} | {instance.id}
    instance.node_map = {}
    template_to_scene: Dict[str, str] = {t.id: _new_id(existing) for t in definition.nodes}
    root_template_ids = set(definition.root_ids)
    root_nodes: List[Node] = []
    for template_node in definition.nodes:
        scene_node = Node(
            id=template_to_scene[template_node.id],
            name=template_node.name,
            type=template_node.type,
            transform=template_node.transform.model_copy(deep=True),
        )
        scene_node.parent_id = (
            template_to_scene[template_node.parent_id]
            if template_node.parent_id in template_to_scene
            else instance.parent_id if template_node.id in root_template_ids else None
        )
        scene_node.children = [
            template_to_scene[cid] for cid in template_node.children if cid in template_to_scene
        ]
        scene_node.assembly = AssemblyBinding(
            assembly_id=definition.id,
            instance_id=instance.id,
            template_id=template_node.id,
            nested_assembly_id=template_node.nested_assembly_id,
        )
        if template_node.id in root_template_ids:
            scene_node.transform = instance.transform.model_copy(deep=True)
            instance.node_map["__root__"] = scene_node.id
            root_nodes.append(scene_node)
        elif not template_node.nested_assembly_id:
            override = instance.overrides.get(template_node.id)
            if override:
                scene_node.transform = _override_transform(template_node.transform, override)
        scene.nodes.append(scene_node)
        instance.node_map[template_node.id] = scene_node.id
    for root in root_nodes:
        if instance.parent_id is None:
            scene.root_ids.append(root.id)
        else:
            scene.index()[instance.parent_id].children.append(root.id)
    scene.assembly_instances.append(instance)
    for template_socket_id, child in nested_roots.items():
        socket_node_id = template_to_scene[template_socket_id]
        child.parent_instance_id = instance.id
        child.host_template_id = template_socket_id
        child.parent_id = socket_node_id
        socket = scene.index()[socket_node_id]
        socket.assembly = socket.assembly.model_copy(update={"child_instance_id": child.id})
        scene.assembly_instances.append(child)
        _materialize_instance(scene, child)


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
    existing = {node.id for node in scene.nodes} | {item.id for item in scene.assembly_instances}
    instance = AssemblyInstance(
        id=_new_id(existing),
        name=definition.name,
        assembly_id=assembly_id,
        assembly_version=definition.version,
        baseline_version=definition.version,
        parent_id=parent_id,
        transform=Transform(position=list(position) if position else [0.0, 0.0, 0.0]),
    )
    scene.assembly_instances.append(instance)
    _materialize_instance(scene, instance)
    return scene


def reparent(
    scene: Scene, node_id: str, new_parent_id: Optional[str], keep_world_transform: bool = True
) -> Scene:
    """把节点（含整棵子树）换到另一个组。

    - 禁止挂到自己或自己的后代下（循环挂接）。
    - keep_world_transform=True 时按新父级反算局部 TRS，眼前位置不变。
    """
    if node_id == new_parent_id:
        raise SceneError("不能把节点挂到自己下面")
    source_instance = _instance_for_node(scene, node_id)
    if source_instance:
        _assert_is_instance_root(scene, source_instance, node_id)
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
        saved_world = None
        new_parent_world = None

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
    if source_instance:
        moved_instance = _instance_index(scene)[source_instance.id]
        moved_instance.parent_id = new_parent_id
        moved_instance.transform = node.transform.model_copy(deep=True)
    return scene


def _duplicate_instance_tree(scene: Scene, source: AssemblyInstance) -> AssemblyInstance:
    """深复制实例记录（含嵌套子实例记录），分配新 id 并挂到原父级。"""
    existing = {node.id for node in scene.nodes} | {item.id for item in scene.assembly_instances}
    copied = source.model_copy(deep=True)
    copied.id = _new_id(existing)
    copied.overrides = {key: value.model_copy(deep=True) for key, value in source.overrides.items()}
    copied.part_policies = dict(source.part_policies)
    child_map: Dict[str, AssemblyInstance] = {}
    for child in _instance_child_instances(scene, source):
        child_copy = _duplicate_instance_tree(scene, child)
        child_copy.parent_instance_id = copied.id
        child_map[child.host_template_id] = child_copy
    _PENDING_CHILDREN[copied.id] = child_map
    scene.assembly_instances.append(copied)
    return copied


def duplicate_subtree(scene: Scene, node_id: str) -> Scene:
    """深复制整个组（含全部后代），父子关系完整保留，副本放在同一父级。"""
    source_instance = _instance_for_node(scene, node_id)
    definitions = _assembly_index(scene)
    if source_instance:
        _assert_is_instance_root(scene, source_instance, node_id)
        scene = scene.model_copy(deep=True)
        copied = _duplicate_instance_tree(scene, _instance_index(scene)[source_instance.id])
        copied.name = f"{source_instance.name} 副本"
        copied.transform.position = [
            source_instance.transform.position[0] + 1.0,
            source_instance.transform.position[1],
            source_instance.transform.position[2],
        ]
        _materialize_instance(scene, copied)
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
        clone.children = []  # 深拷贝会带旧子 id，统一在下面重新挂载
        clone.name = f"{old.name} 副本"
        clones.append(clone)

    # 先全部加入节点表，再挂父子关系
    scene.nodes.extend(clones)
    new_index = scene.index()
    for clone in clones:
        if clone.parent_id is None:
            scene.root_ids.append(clone.id)
        else:
            new_index[clone.parent_id].children.append(clone.id)

    new_root = next(c for c in clones if c.id == id_map[node_id])
    new_root.transform.position = [
        new_root.transform.position[0] + 1.0,
        new_root.transform.position[1],
        new_root.transform.position[2],
    ]
    return scene


def delete_subtree(scene: Scene, node_id: str) -> Scene:
    scene = scene.model_copy(deep=True)
    index = scene.index()
    node = _require(index, node_id)
    instance = _instance_index(scene).get(node.assembly.instance_id) if node.assembly else None
    if instance:
        _assert_is_instance_root(scene, instance, node_id)
        _remove_instance_nodes(scene, instance)
        return scene
    removed = set(subtree_ids(index, node_id))

    if node.parent_id is None:
        scene.root_ids = [rid for rid in scene.root_ids if rid != node_id]
    else:
        parent = index[node.parent_id]
        parent.children = [c for c in parent.children if c != node_id]
    scene.nodes = [n for n in scene.nodes if n.id not in removed]
    scene.assembly_instances = [
        item for item in scene.assembly_instances if not set(item.node_map.values()) & removed
    ]
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


def update_assembly_instance_transform(
    scene: Scene,
    node_id: str,
    position=None,
    rotation_euler=None,
    scale=None,
) -> Scene:
    from .transforms import quat_from_euler_xyz

    scene = scene.model_copy(deep=True)
    node = _require(scene.index(), node_id)
    if not node.assembly:
        return update_transform(scene, node_id, position, rotation_euler, scale)
    instance = _instance_index(scene).get(node.assembly.instance_id)
    definition = _assembly_index(scene).get(node.assembly.assembly_id)
    if not instance or not definition or node.assembly.template_id not in definition.root_ids:
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


def set_assembly_override(
    scene: Scene,
    node_id: str,
    position=None,
    rotation_euler=None,
    scale=None,
) -> Scene:
    from .transforms import quat_from_euler_xyz

    scene = scene.model_copy(deep=True)
    node = _require(scene.index(), node_id)
    if not node.assembly:
        raise SceneError("只有装配件实例零件能设置覆盖")
    instance = _instance_index(scene).get(node.assembly.instance_id)
    definition = _assembly_index(scene).get(node.assembly.assembly_id)
    if not instance or not definition or node.assembly.template_id in definition.root_ids:
        raise SceneError("装配件根节点变换直接保存在实例上，不需要覆盖")

    template = next(item for item in definition.nodes if item.id == node.assembly.template_id)
    override = instance.overrides.setdefault(node.assembly.template_id, AssemblyOverride())
    if position is not None:
        override.position = [float(v) for v in position]
    if rotation_euler is not None:
        override.rotation = [float(v) for v in quat_from_euler_xyz(*rotation_euler)]
    if scale is not None:
        override.scale = [float(v) for v in scale]
    node.transform = _override_transform(template.transform, override)
    return scene


def clear_assembly_override(scene: Scene, node_id: str) -> Scene:
    scene = scene.model_copy(deep=True)
    node = _require(scene.index(), node_id)
    if not node.assembly:
        raise SceneError("只有装配件实例零件能清除覆盖")
    instance = _instance_index(scene).get(node.assembly.instance_id)
    definition = _assembly_index(scene).get(node.assembly.assembly_id)
    if not instance or not definition:
        raise SceneError("装配件实例不存在")
    instance.overrides.pop(node.assembly.template_id, None)
    template = next(item for item in definition.nodes if item.id == node.assembly.template_id)
    node.transform = template.transform.model_copy(deep=True)
    return scene


def update_assembly_template_transform(
    scene: Scene,
    node_id: str,
    position=None,
    rotation_euler=None,
    scale=None,
) -> Scene:
    from .transforms import quat_from_euler_xyz

    scene = scene.model_copy(deep=True)
    node = _require(scene.index(), node_id)
    if not node.assembly:
        raise SceneError("请在装配件实例节点上编辑原件")
    definition = _assembly_index(scene).get(node.assembly.assembly_id)
    if not definition:
        raise SceneError("装配件原件不存在")
    template = next(item for item in definition.nodes if item.id == node.assembly.template_id)
    if node.assembly.template_id in definition.root_ids:
        raise SceneError("原件根节点变换来自实例位置；请修改内部零件")
    edited_instance_id = node.assembly.instance_id
    _snapshot_other_instances(scene, definition, edited_instance_id)
    if position is not None:
        template.transform.position = [float(v) for v in position]
    if rotation_euler is not None:
        template.transform.rotation = [float(v) for v in quat_from_euler_xyz(*rotation_euler)]
    if scale is not None:
        template.transform.scale = [float(v) for v in scale]
    definition.version += 1
    _advance_edited_instance(scene, definition, edited_instance_id)
    return scene


def _snapshot_other_instances(scene: Scene, definition: AssemblyDefinition, edited_instance_id: str) -> None:
    """原件第一次被改动时：给其他仍链接实例建立选择性更新基线。"""
    snapshot = [item.model_copy(deep=True) for item in definition.nodes]
    snapshot_roots = list(definition.root_ids)
    for instance in scene.assembly_instances:
        if instance.assembly_id != definition.id or instance.detached:
            continue
        if instance.id == edited_instance_id:
            continue
        if instance.baseline_version < definition.version:
            continue  # 已有未应用的基线，保持最初的「上游变化」
        instance.baseline_nodes = snapshot
        instance.baseline_root_ids = snapshot_roots
        # baseline_version 保持当前版本号；版本号在原件 version 自增后自然落后


def _advance_edited_instance(scene: Scene, definition: AssemblyDefinition, edited_instance_id: str) -> None:
    instance = _instance_index(scene).get(edited_instance_id)
    if instance and not instance.detached:
        instance.baseline_version = definition.version
        instance.baseline_nodes = []
        instance.baseline_root_ids = []
        _materialize_instance(scene, instance)


def reparent_assembly_template(
    scene: Scene,
    node_id: str,
    new_parent_node_id: Optional[str],
    keep_world_transform: bool = True,
) -> Scene:
    node = _require(scene.index(), node_id)
    target = _require(scene.index(), new_parent_node_id) if new_parent_node_id is not None else None
    if not node.assembly or (target and not target.assembly):
        raise SceneError("装配件原件换组需要选择装配件内部的新父级")
    if target and (node.assembly.instance_id != target.assembly.instance_id or node.assembly.assembly_id != target.assembly.assembly_id):
        raise SceneError("不能跨装配件调整原件层级")
    definition = _assembly_index(scene).get(node.assembly.assembly_id)
    if not definition:
        raise SceneError("装配件原件不存在")
    template_id = node.assembly.template_id
    new_template_parent_id = target.assembly.template_id if target else None
    if template_id == new_template_parent_id:
        raise SceneError("不能把原件节点挂到自己下面")
    template_scene = Scene(nodes=definition.nodes, root_ids=definition.root_ids)
    template_index = template_scene.index()
    if is_ancestor(template_index, template_id, new_template_parent_id):
        raise SceneError("检测到循环挂接：不能把装配件零件挂到它自己的子物体下面")
    if template_id in definition.root_ids and new_template_parent_id is not None:
        raise SceneError("装配件原件根不能成为另一个零件的子级")

    scene = scene.model_copy(deep=True)
    definition = _assembly_index(scene)[node.assembly.assembly_id]
    template = next(item for item in definition.nodes if item.id == template_id)
    if template.parent_id == new_template_parent_id:
        return scene
    edited_instance_id = node.assembly.instance_id
    _snapshot_other_instances(scene, definition, edited_instance_id)
    matrices = world_matrices(Scene(nodes=definition.nodes, root_ids=definition.root_ids))
    saved_world = matrices[template_id]
    new_parent_world = matrices[new_template_parent_id] if new_template_parent_id else None
    if template.parent_id is None:
        definition.root_ids.remove(template_id)
    else:
        next(item for item in definition.nodes if item.id == template.parent_id).children.remove(template_id)
    template.parent_id = new_template_parent_id
    if new_template_parent_id is None:
        definition.root_ids.append(template_id)
    else:
        next(item for item in definition.nodes if item.id == new_template_parent_id).children.append(template_id)
    if keep_world_transform:
        basis = inverse(new_parent_world) if new_parent_world is not None else np.identity(4)
        pos, quat, scl = decompose(multiply(basis, saved_world))
        template.transform = Transform(
            position=[float(v) for v in pos],
            rotation=[float(v) for v in quat],
            scale=[float(v) for v in scl],
        )
    definition.version += 1
    _advance_edited_instance(scene, definition, edited_instance_id)
    return scene


def detach_assembly_instance(scene: Scene, node_id: str) -> Scene:
    scene = scene.model_copy(deep=True)
    node = _require(scene.index(), node_id)
    if not node.assembly:
        return scene
    instance = _instance_index(scene).get(node.assembly.instance_id)
    if not instance:
        return scene
    _detach_instance_subtree(scene, instance)
    return scene


def delete_assembly_definition(scene: Scene, assembly_id: str) -> Scene:
    scene = scene.model_copy(deep=True)
    definition = _assembly_index(scene).get(assembly_id)
    if not definition:
        raise SceneError("装配件原件不存在")
    for item in [i for i in scene.assembly_instances if i.assembly_id == assembly_id]:
        _detach_instance_subtree(scene, item)
    scene.assembly_defs = [item for item in scene.assembly_defs if item.id != assembly_id]
    return scene


# ---------- 选择性接收原件更新 ----------


def _pending_instances(scene: Scene) -> List[AssemblyInstance]:
    result = []
    definitions = _assembly_index(scene)
    for instance in scene.assembly_instances:
        if instance.detached:
            continue
        definition = definitions.get(instance.assembly_id)
        if definition and instance.baseline_version < definition.version and instance.baseline_nodes:
            result.append(instance)
    return result


def _change_entries(scene: Scene, instance: AssemblyInstance) -> List[dict]:
    definition = _assembly_index(scene)[instance.assembly_id]
    old_index = {node.id: node for node in instance.baseline_nodes}
    new_index = {node.id: node for node in definition.nodes}
    entries: List[dict] = []
    for tid, old_node in old_index.items():
        new_node = new_index.get(tid)
        if new_node is None:
            kind = "removed"
        elif not _transform_equal(old_node.transform, new_node.transform) or old_node.parent_id != new_node.parent_id:
            kind = "changed"
        else:
            continue
        entries.append(
            {
                "template_id": tid,
                "name": new_node.name if new_node else old_node.name,
                "kind": kind,
                "has_local_override": tid in instance.overrides,
                "policy": instance.part_policies.get(tid, "follow"),
            }
        )
    for tid, new_node in new_index.items():
        if tid not in old_index:
            entries.append(
                {
                    "template_id": tid,
                    "name": new_node.name,
                    "kind": "added",
                    "has_local_override": False,
                    "policy": "follow",
                }
            )
    return entries


def _transform_equal(a: Transform, b: Transform) -> bool:
    return (
        list(a.position) == list(b.position)
        and list(a.rotation) == list(b.rotation)
        and list(a.scale) == list(b.scale)
    )


def assembly_update_preview(scene: Scene) -> dict:
    """返回等待选择性更新的实例，及每个实例中受影响/失去对应关系的部件（不修改场景）。"""
    instances = []
    definitions = _assembly_index(scene)
    for instance in _pending_instances(scene):
        definition = definitions[instance.assembly_id]
        instances.append(
            {
                "instance_id": instance.id,
                "name": instance.name,
                "assembly_id": definition.id,
                "assembly_name": definition.name,
                "from_version": instance.baseline_version,
                "to_version": definition.version,
                "root_node_id": instance.node_map.get("__root__"),
                "changes": _change_entries(scene, instance),
            }
        )
    return {"pending": instances}


def apply_assembly_updates(scene: Scene, choices: Optional[Dict[str, Dict[str, str]]] = None) -> Scene:
    """按每个部件的选择应用原件更新；放弃/不调用本接口时现场不变。"""
    choices = choices or {}
    scene = scene.model_copy(deep=True)
    pending_ids = {item.id for item in _pending_instances(scene)}
    for instance_id, part_choices in choices.items():
        if instance_id not in pending_ids:
            continue
        instance = _instance_index(scene)[instance_id]
        definition = _assembly_index(scene)[instance.assembly_id]
        for tid, policy in part_choices.items():
            instance.part_policies[tid] = policy
            if policy == "follow":
                instance.overrides.pop(tid, None)
        # “保留”的部件：若基线部件在新版中仍然存在，用其当前场景值固化为覆盖
        old_index = {node.id: node for node in instance.baseline_nodes}
        new_ids = {node.id for node in definition.nodes}
        for tid, policy in part_choices.items():
            if policy == "keep" and tid in new_ids:
                current_scene_id = instance.node_map.get(tid)
                current_node = scene.index().get(current_scene_id) if current_scene_id else None
                if current_node:
                    instance.overrides[tid] = AssemblyOverride(
                        position=list(current_node.transform.position),
                        rotation=list(current_node.transform.rotation),
                        scale=list(current_node.transform.scale),
                    )
                elif tid in old_index:
                    old = old_index[tid]
                    instance.overrides[tid] = AssemblyOverride(
                        position=list(old.transform.position),
                        rotation=list(old.transform.rotation),
                        scale=list(old.transform.scale),
                    )
        # 选择“保留”的、已失去对应关系的部件：在重化物化后作为普通节点保留在实例根下
        kept_removed = [
            tid for tid, policy in part_choices.items()
            if policy == "keep" and tid in old_index and tid not in new_ids
        ]
        kept_nodes: List[Node] = []
        root_scene_id_pre = instance.node_map.get("__root__")
        for tid in kept_removed:
            current_scene_id = instance.node_map.get(tid)
            current_node = scene.index().get(current_scene_id) if current_scene_id else None
            if current_node:
                clone_ids: Dict[str, str] = {}
                clone_existing = {n.id for n in scene.nodes} | {n.id for n in kept_nodes}
                subtree = subtree_ids(scene.index(), current_scene_id)
                for old_id in subtree:
                    clone_ids[old_id] = _new_id(clone_existing)
                for old_id in subtree:
                    old = scene.index()[old_id]
                    clone = old.model_copy(deep=True)
                    clone.id = clone_ids[old_id]
                    clone.assembly = None
                    clone.parent_id = (
                        clone_ids[old.parent_id]
                        if old.parent_id in clone_ids
                        else root_scene_id_pre if old_id == current_scene_id else None
                    )
                    clone.children = [clone_ids[c] for c in old.children if c in clone_ids]
                    kept_nodes.append(clone)
        instance.baseline_version = definition.version
        instance.baseline_nodes = []
        instance.baseline_root_ids = []
        _materialize_instance(scene, instance)
        root_scene_id = instance.node_map.get("__root__")
        for kept_node in kept_nodes:
            kept_node.assembly = None
            kept_node.parent_id = root_scene_id
            scene.nodes.append(kept_node)
            if root_scene_id:
                scene.index()[root_scene_id].children.append(kept_node.id)
    return scene


# ---------- 选中对象的稳定路径（保存/重开后保持） ----------


def selection_path_for_node(scene: Scene, node_id: str) -> Optional[str]:
    """把场景节点 id 转成不随实例重新生成而变化的稳定路径。"""
    index = scene.index()
    if node_id not in index:
        return None
    segments: List[str] = []
    current: Optional[str] = node_id
    while current is not None:
        node = index.get(current)
        if not node:
            break
        if node.assembly:
            segments.append(f"i:{node.assembly.instance_id}:{node.assembly.template_id}")
        else:
            segments.append(f"n:{node.id}")
        current = node.parent_id
    return "/".join(reversed(segments))


def node_for_selection_path(scene: Scene, path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    index = scene.index()
    current_id: Optional[str] = None
    for segment in path.split("/"):
        if segment.startswith("i:"):
            _, instance_id, template_id = segment.split(":", 2)
            instance = _instance_index(scene).get(instance_id)
            if not instance:
                return None
            candidate = instance.node_map.get(template_id)
            if not candidate or candidate not in index:
                return None
            current_id = candidate
        else:
            raw_id = segment[2:]
            node = index.get(raw_id)
            if not node:
                return None
            if current_id is not None and node.parent_id != current_id:
                return None
            current_id = raw_id
    return current_id


def set_selection(scene: Scene, node_id: Optional[str]) -> Scene:
    scene = scene.model_copy(deep=True)
    scene.selected_path = selection_path_for_node(scene, node_id) if node_id else None
    return scene


def resolve_selection(scene: Scene) -> Optional[str]:
    return node_for_selection_path(scene, scene.selected_path)

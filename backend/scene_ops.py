"""场景编辑的纯函数：全部基于传入的 scene 返回新 scene（请求级无状态）。"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional

import numpy as np

from .models import AssemblyBinding, AssemblyDefinition, AssemblyInstance, AssemblyOverride, Node, Scene, Transform
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


def _assembly_index(scene: Scene):
    return {item.id: item for item in scene.assembly_defs}


def _instance_index(scene: Scene):
    return {item.id: item for item in scene.assembly_instances}


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
    generated = set(instance.node_map.values())
    root_node_id = instance.node_map.get("__root__", "")
    if root_node_id:
        if instance.parent_id is None:
            scene.root_ids = [rid for rid in scene.root_ids if rid != root_node_id]
        elif root_node_id in scene.index():
            parent = scene.index().get(instance.parent_id)
            if parent:
                parent.children = [cid for cid in parent.children if cid != root_node_id]
    scene.nodes = [node for node in scene.nodes if node.id not in generated]
    scene.assembly_instances = [item for item in scene.assembly_instances if item.id != instance.id]


def _materialize_instance(scene: Scene, instance: AssemblyInstance, definition: AssemblyDefinition) -> None:
    template_index = {node.id: node for node in definition.nodes}
    old = _instance_index(scene).get(instance.id)
    if old:
        generated = set(old.node_map.values())
        root_node_id = old.node_map.get("__root__", "")
        if root_node_id:
            if old.parent_id is None:
                scene.root_ids = [rid for rid in scene.root_ids if rid != root_node_id]
            else:
                old_parent = scene.index().get(old.parent_id)
                if old_parent:
                    old_parent.children = [cid for cid in old_parent.children if cid != root_node_id]
        scene.nodes = [node for node in scene.nodes if node.id not in generated]

    instance.assembly_version = definition.version
    instance.node_map = {}
    existing = set(scene.index())
    template_to_scene: Dict[str, str] = {}
    for template_node in definition.nodes:
        template_to_scene[template_node.id] = _new_id(existing)

    root_template_ids = set(definition.root_ids)
    root_nodes: List[Node] = []
    for template_node in definition.nodes:
        scene_node = template_node.model_copy(deep=True)
        scene_node.id = template_to_scene[template_node.id]
        scene_node.parent_id = (
            template_to_scene[template_node.parent_id]
            if template_node.parent_id in template_to_scene
            else instance.parent_id if template_node.id in root_template_ids else None
        )
        scene_node.children = [template_to_scene[cid] for cid in template_node.children if cid in template_to_scene]
        scene_node.assembly = AssemblyBinding(
            assembly_id=definition.id,
            instance_id=instance.id,
            template_id=template_node.id,
        )
        override = instance.overrides.get(template_node.id)
        if template_node.id in root_template_ids:
            scene_node.transform = instance.transform.model_copy(deep=True)
            instance.node_map["__root__"] = scene_node.id
            root_nodes.append(scene_node)
        elif override:
            scene_node.transform = _override_transform(template_node.transform, override)
        scene.nodes.append(scene_node)
        instance.node_map[template_node.id] = scene_node.id

    for root in root_nodes:
        if instance.parent_id is None:
            scene.root_ids.append(root.id)
        else:
            scene.index()[instance.parent_id].children.append(root.id)


def _refresh_linked_instances(scene: Scene, assembly_id: str) -> None:
    definitions = _assembly_index(scene)
    definition = definitions.get(assembly_id)
    if not definition:
        return
    for instance in list(scene.assembly_instances):
        if instance.assembly_id == assembly_id:
            _materialize_instance(scene, instance, definition)


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
    for old_id in ids:
        source = index[old_id]
        template = source.model_copy(deep=True)
        template.parent_id = source.parent_id if source.parent_id in ids else None
        template.children = [cid for cid in source.children if cid in ids]
        template.assembly = None
        definition.nodes.append(template)
    definition.root_ids = [root_id]
    scene.assembly_defs.append(definition)

    instance = AssemblyInstance(
        id=_new_id(existing),
        name=definition.name,
        assembly_id=assembly_id,
        assembly_version=definition.version,
        parent_id=root.parent_id,
        transform=root.transform.model_copy(deep=True),
    )
    scene.assembly_instances.append(instance)
    if root.parent_id is None:
        scene.root_ids = [rid for rid in scene.root_ids if rid != root.id]
    else:
        scene.index()[root.parent_id].children = [
            cid for cid in scene.index()[root.parent_id].children if cid != root.id
        ]
    _materialize_instance(scene, instance, definition)
    old_root = root_id
    if root.parent_id is None:
        scene.root_ids = [rid for rid in scene.root_ids if rid != old_root]
    else:
        scene.index()[root.parent_id].children = [
            cid for cid in scene.index()[root.parent_id].children if cid != old_root
        ]
    scene.nodes = [node for node in scene.nodes if node.id not in set(ids)]
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
        parent_id=parent_id,
        transform=Transform(position=list(position) if position else [0.0, 0.0, 0.0]),
    )
    scene.assembly_instances.append(instance)
    _materialize_instance(scene, instance, definition)
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
    source_definition = _assembly_index(scene).get(source_instance.assembly_id) if source_instance else None
    if source_instance and not (
        source_definition and node_id in {
            source_instance.node_map.get(tid)
            for tid in source_definition.root_ids
        }
    ):
        raise SceneError("不能单独移动装配件内部零件；请移动装配件根节点或先脱离原件")
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


def duplicate_subtree(scene: Scene, node_id: str) -> Scene:
    """深复制整个组（含全部后代），父子关系完整保留，副本放在同一父级。"""
    source_instance = _instance_for_node(scene, node_id)
    definitions = _assembly_index(scene)
    if source_instance:
        definition = definitions.get(source_instance.assembly_id)
        if not definition or node_id not in {source_instance.node_map.get(tid) for tid in definition.root_ids}:
            raise SceneError("不能复制装配件内部零件；请复制装配件根节点或先脱离原件")
        scene = scene.model_copy(deep=True)
        copied = _instance_index(scene)[source_instance.id].model_copy(deep=True)
        existing = {node.id for node in scene.nodes} | {item.id for item in scene.assembly_instances}
        copied.id = _new_id(existing)
        copied.name = f"{source_instance.name} 副本"
        copied.transform.position = [
            source_instance.transform.position[0] + 1.0,
            source_instance.transform.position[1],
            source_instance.transform.position[2],
        ]
        copied.overrides = {key: value.model_copy(deep=True) for key, value in source_instance.overrides.items()}
        scene.assembly_instances.append(copied)
        _materialize_instance(scene, copied, definitions[source_instance.assembly_id])
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
        template_id = node.assembly.template_id
        definition = _assembly_index(scene).get(instance.assembly_id)
        if not definition or template_id not in definition.root_ids:
            raise SceneError("不能删除装配件内部零件；请删除整个装配件或先脱离原件")
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
    if position is not None:
        template.transform.position = [float(v) for v in position]
    if rotation_euler is not None:
        template.transform.rotation = [float(v) for v in quat_from_euler_xyz(*rotation_euler)]
    if scale is not None:
        template.transform.scale = [float(v) for v in scale]
    definition.version += 1
    _refresh_linked_instances(scene, definition.id)
    return scene


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
    _refresh_linked_instances(scene, definition.id)
    return scene


def detach_assembly_instance(scene: Scene, node_id: str) -> Scene:
    scene = scene.model_copy(deep=True)
    node = _require(scene.index(), node_id)
    if not node.assembly:
        return scene
    instance = _instance_index(scene).get(node.assembly.instance_id)
    if not instance:
        return scene
    generated = set(instance.node_map.values())
    for scene_node in scene.nodes:
        if scene_node.id in generated:
            scene_node.assembly = None
    scene.assembly_instances = [item for item in scene.assembly_instances if item.id != instance.id]
    return scene


def delete_assembly_definition(scene: Scene, assembly_id: str) -> Scene:
    scene = scene.model_copy(deep=True)
    definition = _assembly_index(scene).get(assembly_id)
    if not definition:
        raise SceneError("装配件原件不存在")
    linked_instance_ids = {
        item.id for item in scene.assembly_instances if item.assembly_id == assembly_id
    }
    linked_node_ids = {
        node.id
        for node in scene.nodes
        if node.assembly and node.assembly.instance_id in linked_instance_ids
    }
    for node in scene.nodes:
        if node.id in linked_node_ids:
            node.assembly = None
    scene.assembly_instances = [
        item for item in scene.assembly_instances if item.id not in linked_instance_ids
    ]
    scene.assembly_defs = [item for item in scene.assembly_defs if item.id != assembly_id]
    return scene

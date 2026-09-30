"""场景编辑的纯函数：全部基于传入的 scene 返回新 scene（请求级无状态）。"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional

import numpy as np

from .models import AssemblyDefinition, AssemblyLink, AssemblyNode, Node, Scene, Transform
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
    return {assembly.id: assembly for assembly in scene.assemblies}


def _instance_id(node: Node) -> Optional[str]:
    return node.assembly.instance_id if node.assembly else None


def _snapshot_assembly(assembly_id: str, name: str, index: Dict[str, Node], root_id: str) -> AssemblyDefinition:
    nodes: List[AssemblyNode] = []
    for nid in subtree_ids(index, root_id):
        node = index[nid]
        nodes.append(
            AssemblyNode(
                id=nid,
                name=node.name,
                type=node.type,
                children=list(node.children),
                transform=node.transform.model_copy(deep=True),
            )
        )
    return AssemblyDefinition(id=assembly_id, name=name, root_id=root_id, nodes=nodes)


def _is_assembly_root(node: Node, index: Dict[str, Node]) -> bool:
    return node.assembly is not None and (
        node.parent_id is None or _instance_id(index[node.parent_id]) != node.assembly.instance_id
    )


def _add_override(node: Node, key: str) -> None:
    if node.assembly and key not in node.assembly.overrides:
        node.assembly.overrides.append(key)


def _apply_overrides(target: Node, source: Node) -> None:
    if not target.assembly or not source.assembly:
        return
    overrides = list(source.assembly.overrides)
    if "position" in overrides:
        target.transform.position = list(source.transform.position)
    if "rotation" in overrides:
        target.transform.rotation = list(source.transform.rotation)
    if "scale" in overrides:
        target.transform.scale = list(source.transform.scale)
    if "name" in overrides:
        target.name = source.name
    target.assembly.overrides = overrides
    target.assembly.assembly_version = source.assembly.assembly_version


def create_assembly(scene: Scene, root_id: str, name: Optional[str] = None) -> Scene:
    """把现有子树登记为装配件原件，并把这棵子树标记为第一个链接实例。"""
    scene = scene.model_copy(deep=True)
    index = scene.index()
    root = _require(index, root_id)
    if root.assembly is not None:
        raise SceneError("选中节点已经是装配件实例")

    existing = set(index)
    assembly_id = f"asm_{_new_id(existing)}"
    instance_id = f"ins_{_new_id(existing)}"
    definition = _snapshot_assembly(assembly_id, name or f"{root.name} 装配件", index, root_id)
    scene.assemblies.append(definition)

    for nid in subtree_ids(index, root_id):
        index[nid].assembly = AssemblyLink(
            assembly_id=assembly_id,
            instance_id=instance_id,
            part_id=nid,
            assembly_version=1,
            overrides=[],
        )
    return scene


def _attach_assembly_nodes(
    scene: Scene,
    definition: AssemblyDefinition,
    instance_id: str,
    parent_id: Optional[str],
    root_node_id: Optional[str] = None,
    preserve_root_offset: bool = True,
) -> str:
    index = scene.index()
    existing = set(index)
    part_to_node: Dict[str, str] = {}
    for part in definition.nodes:
        part_to_node[part.id] = root_node_id if part.id == definition.root_id and root_node_id else _new_id(existing)

    clones: List[Node] = []
    for part in definition.nodes:
        node_id = part_to_node[part.id]
        template_parent = next((p for p in definition.nodes if part.id in p.children), None)
        if part.id == definition.root_id:
            node_parent = parent_id
        elif template_parent is not None:
            node_parent = part_to_node[template_parent.id]
        else:
            raise SceneError("装配件定义缺少父部件")
        clones.append(
            Node(
                id=node_id,
                name=part.name,
                type=part.type,
                parent_id=node_parent,
                children=[part_to_node[cid] for cid in part.children],
                transform=part.transform.model_copy(deep=True),
                assembly=AssemblyLink(
                    assembly_id=definition.id,
                    instance_id=instance_id,
                    part_id=part.id,
                    assembly_version=definition.version,
                    overrides=["position"] if part.id == definition.root_id else [],
                ),
            )
        )

    new_root_id = part_to_node[definition.root_id]
    new_root = next(node for node in clones if node.id == new_root_id)
    if preserve_root_offset:
        new_root.transform.position = [new_root.transform.position[0] + 1.0, *new_root.transform.position[1:]]
    scene.nodes.extend(clones)
    if parent_id is None:
        scene.root_ids.append(new_root_id)
    else:
        index[parent_id].children.append(new_root_id)
    return new_root_id


def instantiate_assembly(scene: Scene, assembly_id: str, parent_id: Optional[str] = None) -> Scene:
    scene = scene.model_copy(deep=True)
    definition = _require(_assembly_index(scene), assembly_id)
    if parent_id is not None:
        parent = _require(scene.index(), parent_id)
        if parent.assembly is not None:
            raise SceneError("不能把装配件实例直接嵌套到另一个装配件部件中")
    existing = set(scene.index())
    instance_id = f"ins_{_new_id(existing)}"
    _attach_assembly_nodes(scene, definition, instance_id, parent_id)
    return scene


def detach_assembly(scene: Scene, root_id: str) -> Scene:
    """把实例当前样子烘焙成普通节点；之后保存也不会重新绑定。"""
    scene = scene.model_copy(deep=True)
    index = scene.index()
    root = _require(index, root_id)
    if root.assembly is None:
        raise SceneError("选中节点不是装配件实例")
    for nid in subtree_ids(index, root_id):
        index[nid].assembly = None
    return scene


def publish_assembly(scene: Scene, root_id: str) -> Scene:
    """发布选中实例的当前层级，明确同步同一装配件的其他链接实例。"""
    scene = scene.model_copy(deep=True)
    index = scene.index()
    root = _require(index, root_id)
    if not _is_assembly_root(root, index):
        raise SceneError("请选择装配件实例根节点")

    assembly_id = root.assembly.assembly_id
    definitions = _assembly_index(scene)
    definition = _require(definitions, assembly_id)
    selected_instance_id = root.assembly.instance_id
    old_part_ids = {part.id for part in definition.nodes}

    # 当前实例即新原件。给新增节点补 part_id，并清空当前实例的覆盖。
    new_part_ids: Dict[str, str] = {}
    existing = set(index)
    for nid in subtree_ids(index, root_id):
        node = index[nid]
        if node.assembly and node.assembly.assembly_id == assembly_id and node.assembly.instance_id == selected_instance_id:
            new_part_ids[nid] = node.assembly.part_id
        else:
            part_id = nid if nid not in old_part_ids else f"part_{_new_id(existing)}"
            new_part_ids[nid] = part_id
    for nid, part_id in new_part_ids.items():
        index[nid].assembly = AssemblyLink(
            assembly_id=assembly_id,
            instance_id=selected_instance_id,
            part_id=part_id,
            assembly_version=definition.version + 1,
            overrides=[],
        )

    new_nodes: List[AssemblyNode] = []
    for nid in subtree_ids(index, root_id):
        source = index[nid]
        new_nodes.append(
            AssemblyNode(
                id=new_part_ids[nid],
                name=source.name,
                type=source.type,
                children=[new_part_ids[cid] for cid in source.children],
                transform=source.transform.model_copy(deep=True),
            )
        )
    new_definition = AssemblyDefinition(
        id=assembly_id,
        name=definition.name,
        version=definition.version + 1,
        root_id=new_part_ids[root_id],
        nodes=new_nodes,
    )

    other_roots = [
        node
        for node in scene.nodes
        if node.assembly
        and node.assembly.assembly_id == assembly_id
        and node.assembly.instance_id != selected_instance_id
        and _is_assembly_root(node, index)
    ]

    for old_root in other_roots:
        instance_id = old_root.assembly.instance_id
        parent_id = old_root.parent_id
        preserved: Dict[str, Node] = {}
        old_instance_nodes = [index[nid] for nid in subtree_ids(index, old_root.id)]
        for node in old_instance_nodes:
            if node.assembly and node.assembly.part_id in {part.id for part in new_definition.nodes}:
                preserved[node.assembly.part_id] = node

        if parent_id is None:
            scene.root_ids = [rid for rid in scene.root_ids if rid != old_root.id]
        else:
            index[parent_id].children = [cid for cid in index[parent_id].children if cid != old_root.id]
        removed = {n.id for n in old_instance_nodes}
        scene.nodes = [node for node in scene.nodes if node.id not in removed]
        for node in scene.nodes:
            node.children = [cid for cid in node.children if cid not in removed]

        new_root_node_id = old_root.id
        _attach_assembly_nodes(
            scene,
            new_definition,
            instance_id,
            parent_id,
            root_node_id=new_root_node_id,
            preserve_root_offset=False,
        )
        new_index = scene.index()
        rebuilt_root = new_index[new_root_node_id]
        part_map = {}
        for nid in subtree_ids(new_index, rebuilt_root.id):
            n = new_index[nid]
            if n.assembly:
                part_map[n.assembly.part_id] = n
        for part_id, old_node in preserved.items():
            target = part_map.get(part_id)
            if not target or not target.assembly:
                continue
            old_node.assembly.assembly_version = new_definition.version
            _apply_overrides(target, old_node)

    scene.assemblies = [new_definition if item.id == assembly_id else item for item in scene.assemblies]
    return scene


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
    parent = index.get(parent_id) if parent_id else None
    if parent is not None and parent.assembly is not None:
        node.assembly = AssemblyLink(
            assembly_id=parent.assembly.assembly_id,
            instance_id=parent.assembly.instance_id,
            part_id=nid,
            assembly_version=parent.assembly.assembly_version,
            overrides=[],
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
    linked_children = [index[cid].assembly for cid in child_ids if index[cid].assembly]
    if linked_children:
        instance_ids = {link.instance_id for link in linked_children}
        if len(instance_ids) != 1:
            raise SceneError("不能把不同装配件实例的部件成组到一起")
        link = linked_children[0]
        group.assembly = AssemblyLink(
            assembly_id=link.assembly_id,
            instance_id=link.instance_id,
            part_id=group_id,
            assembly_version=link.assembly_version,
            overrides=[],
        )
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


def reparent(
    scene: Scene, node_id: str, new_parent_id: Optional[str], keep_world_transform: bool = True
) -> Scene:
    """把节点（含整棵子树）换到另一个组。

    - 禁止挂到自己或自己的后代下（循环挂接）。
    - keep_world_transform=True 时按新父级反算局部 TRS，眼前位置不变。
    """
    if node_id == new_parent_id:
        raise SceneError("不能把节点挂到自己下面")
    scene = scene.model_copy(deep=True)
    index = scene.index()
    node = _require(index, node_id)
    if new_parent_id is not None:
        _require(index, new_parent_id)
    if is_ancestor(index, node_id, new_parent_id):
        raise SceneError("检测到循环挂接：不能把组挂到它自己的子物体下面")
    if node.parent_id == new_parent_id:
        return scene
    new_parent = index[new_parent_id] if new_parent_id is not None else None
    if node.assembly is not None and not _is_assembly_root(node, index):
        if new_parent is None or new_parent.assembly is None or new_parent.assembly.instance_id != node.assembly.instance_id:
            raise SceneError("装配件内部部件不能单独换出；请先脱离原件或移动实例根节点")
    if node.assembly is not None and _is_assembly_root(node, index) and new_parent is not None:
        if new_parent.assembly is not None and new_parent.assembly.instance_id != node.assembly.instance_id:
            raise SceneError("不能把装配件实例根嵌入另一个装配件内部")
    if node.assembly is None and new_parent is not None and new_parent.assembly is not None:
        raise SceneError("普通节点不能直接移入装配件实例；请在原件中新增部件后发布")

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
        if _is_assembly_root(node, scene.index()):
            node.assembly.overrides = [
                key for key in node.assembly.overrides if key in ("name",)
            ]
            for key in ("position", "rotation", "scale"):
                _add_override(node, key)
    return scene


def duplicate_subtree(scene: Scene, node_id: str) -> Scene:
    """复制节点；装配件实例根复制为新的链接实例，普通节点深复制。"""
    scene = scene.model_copy(deep=True)
    index = scene.index()
    node = _require(index, node_id)

    if _is_assembly_root(node, index):
        definition = _require(_assembly_index(scene), node.assembly.assembly_id)
        existing = set(index)
        instance_id = f"ins_{_new_id(existing)}"
        new_root_id = _attach_assembly_nodes(scene, definition, instance_id, node.parent_id)
        new_index = scene.index()
        source_parts = {
            item.assembly.part_id: item
            for item_id in subtree_ids(index, node_id)
            for item in [index[item_id]]
            if item.assembly
        }
        for new_id in subtree_ids(new_index, new_root_id):
            target = new_index[new_id]
            source = source_parts.get(target.assembly.part_id) if target.assembly else None
            if source is not None:
                _apply_overrides(target, source)
        new_root = new_index[new_root_id]
        new_root.name = f"{node.name} 副本"
        _add_override(new_root, "name")
        new_root.transform.position[0] += 1.0
        return scene

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
        if clone.assembly is not None:
            clone.assembly.part_id = clone.id
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
    removed = set(subtree_ids(index, node_id))

    if node.parent_id is None:
        scene.root_ids = [rid for rid in scene.root_ids if rid != node_id]
    else:
        parent = index[node.parent_id]
        parent.children = [c for c in parent.children if c != node_id]
    scene.nodes = [n for n in scene.nodes if n.id not in removed]
    return scene


def update_name(scene: Scene, node_id: str, name: str) -> Scene:
    scene = scene.model_copy(deep=True)
    node = _require(scene.index(), node_id)
    node.name = name
    _add_override(node, "name")
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
    if position is not None:
        node.transform.position = [float(v) for v in position]
        _add_override(node, "position")
    if rotation_euler is not None:
        node.transform.rotation = [float(v) for v in quat_from_euler_xyz(*rotation_euler)]
        _add_override(node, "rotation")
    if scale is not None:
        node.transform.scale = [float(v) for v in scale]
        _add_override(node, "scale")
    return scene

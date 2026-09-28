"""场景编辑的纯函数：全部基于传入的 scene 返回新 scene（请求级无状态）。"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional

import numpy as np

from .models import Node, Scene, Transform
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
    return scene


def duplicate_subtree(scene: Scene, node_id: str) -> Scene:
    """深复制整个组（含全部后代），父子关系完整保留，副本放在同一父级。"""
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
    removed = set(subtree_ids(index, node_id))

    if node.parent_id is None:
        scene.root_ids = [rid for rid in scene.root_ids if rid != node_id]
    else:
        parent = index[node.parent_id]
        parent.children = [c for c in parent.children if c != node_id]
    scene.nodes = [n for n in scene.nodes if n.id not in removed]
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
    if rotation_euler is not None:
        node.transform.rotation = [float(v) for v in quat_from_euler_xyz(*rotation_euler)]
    if scale is not None:
        node.transform.scale = [float(v) for v in scale]
    return scene

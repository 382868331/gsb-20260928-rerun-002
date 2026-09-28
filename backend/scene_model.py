"""Editable scene document model.

A scene document is a flat map of nodes (not a nested JSON tree) plus
root order.  Keeping nodes flat makes reparenting, cycle checks and
persistence straightforward while parent->child links stay explicit.
"""
from __future__ import annotations

import copy
import uuid

from . import scene_math as math3d

OBJECT_TYPES = ("cube", "sphere", "cylinder", "plane", "cone")
NODE_TYPES = OBJECT_TYPES + ("group",)


class SceneError(ValueError):
    """Validation / operation error with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _v3(node, key, default):
    val = node.get(key, [default, default, default])
    if not isinstance(val, list) or len(val) != 3 or not all(isinstance(v, (int, float)) for v in val):
        raise SceneError("invalid_transform", f"node {node.get('id')}: {key} must be [x, y, z] numbers")
    return [float(v) for v in val]


def new_id():
    return uuid.uuid4().hex[:12]


_DEFAULTS = {"group": "Group", "cube": "Cube", "sphere": "Sphere",
             "cylinder": "Cylinder", "plane": "Plane", "cone": "Cone"}


def make_node(node_type, name=None, position=(0.0, 0.0, 0.0),
              rotation=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0), node_id=None):
    if node_type not in NODE_TYPES:
        raise SceneError("invalid_type", f"unknown node type: {node_type}")
    nid = node_id or new_id()
    return {
        "id": nid,
        "name": name or _DEFAULTS[node_type],
        "type": node_type,
        "parent": None,
        "children": [],
        "position": [float(v) for v in position],
        "rotation": [float(v) for v in rotation],
        "scale": [float(v) for v in scale],
    }


def new_scene():
    return {"version": 1, "rootOrder": [], "nodes": {},
            "activeCamera": {"position": [6, 6, 8], "target": [0, 0, 0]}}


def validate(doc):
    if not isinstance(doc, dict) or "nodes" not in doc:
        raise SceneError("invalid_scene", "scene must contain a nodes map")
    nodes = doc["nodes"]
    if not isinstance(nodes, dict):
        raise SceneError("invalid_scene", "nodes must be a map")

    for nid, node in nodes.items():
        if not isinstance(node, dict):
            raise SceneError("invalid_node", f"{nid} is not an object")
        if node.get("id") != nid:
            raise SceneError("id_mismatch", f"node key {nid} != id field {node.get('id')}")
        if node.get("type") not in NODE_TYPES:
            raise SceneError("invalid_type", f"node {nid}: bad type {node.get('type')}")
        _v3(node, "position", 0.0)
        _v3(node, "rotation", 0.0)
        _v3(node, "scale", 1.0)
        parent = node.get("parent")
        if parent is not None:
            if parent not in nodes:
                raise SceneError("dangling_parent", f"node {nid} references missing parent {parent}")
            if nid not in nodes[parent].get("children", []):
                raise SceneError("broken_link", f"parent {parent} does not list child {nid}")
        for child in node.get("children", []):
            if child not in nodes:
                raise SceneError("dangling_child", f"node {nid} references missing child {child}")
            if nodes[child].get("parent") != nid:
                raise SceneError("broken_link", f"child {child} does not point back to parent {nid}")

    roots = doc.get("rootOrder")
    if roots is None:
        doc["rootOrder"] = [n["id"] for n in nodes.values() if n.get("parent") is None]
    else:
        for rid in roots:
            if rid not in nodes:
                raise SceneError("dangling_root", f"root {rid} does not exist")
            if nodes[rid].get("parent") is not None:
                raise SceneError("invalid_root", f"root {rid} has a parent")
        actual = {n["id"] for n in nodes.values() if n.get("parent") is None}
        if set(roots) != actual:
            raise SceneError("root_mismatch", "rootOrder must list exactly all parentless nodes")


def is_ancestor(doc, ancestor_id, node_id):
    nodes = doc["nodes"]
    cur = node_id
    seen = set()
    while cur is not None:
        if cur == ancestor_id:
            return True
        if cur in seen:
            raise SceneError("cycle_detected", f"cycle at {cur}")
        seen.add(cur)
        cur = nodes[cur].get("parent")
    return False


def subtree_ids(doc, node_id):
    nodes = doc["nodes"]
    out = []
    stack = [node_id]
    while stack:
        nid = stack.pop()
        out.append(nid)
        stack.extend(reversed(nodes[nid].get("children", [])))
    return out


def local_matrix(node):
    return math3d.compose(node["position"], node.get("rotation", [0, 0, 0]),
                          node.get("scale", [1, 1, 1]))


def world_matrices(doc):
    nodes = doc["nodes"]
    matrices = {}

    def visit(nid, inherited):
        world = math3d.multiply(inherited, local_matrix(nodes[nid]))
        matrices[nid] = world
        for child in nodes[nid].get("children", []):
            visit(child, world)

    root_mat = math3d.identity()
    for rid in doc["rootOrder"]:
        visit(rid, root_mat)
    return matrices


def world_trs(doc):
    out = {}
    for nid, mat in world_matrices(doc).items():
        pos, rot, scl = math3d.decompose(mat)
        out[nid] = {"position": pos, "rotation": rot, "scale": scl, "matrix": mat}
    return out


def add_node(doc, node, parent_id=None):
    nid = node["id"]
    if nid in doc["nodes"]:
        raise SceneError("duplicate_id", f"node {nid} already exists")
    node.setdefault("children", [])
    node["parent"] = parent_id
    doc["nodes"][nid] = node
    if parent_id is None:
        doc["rootOrder"].append(nid)
    else:
        doc["nodes"][parent_id]["children"].append(nid)
    return node


def _detach(doc, node_id):
    node = doc["nodes"][node_id]
    parent_id = node.get("parent")
    if parent_id is None:
        doc["rootOrder"].remove(node_id)
    else:
        doc["nodes"][parent_id]["children"].remove(node_id)
    node["parent"] = None


def _attach(doc, node_id, parent_id, index=None):
    node = doc["nodes"][node_id]
    node["parent"] = parent_id
    lst = doc["rootOrder"] if parent_id is None else doc["nodes"][parent_id]["children"]
    if index is None:
        lst.append(node_id)
    else:
        lst.insert(index, node_id)


def reparent(doc, node_id, new_parent_id, preserve_world=True, index=None):
    """Move node_id under new_parent_id.

    preserve_world=True keeps the node at exactly the same world pose:
    the backend recomputes local TRS from inverse(parent world) * world.
    False keeps local TRS (object jumps with the new parent frame).
    """
    nodes = doc["nodes"]
    if node_id not in nodes:
        raise SceneError("not_found", f"node {node_id} not found")
    if new_parent_id is not None and new_parent_id not in nodes:
        raise SceneError("not_found", f"parent {new_parent_id} not found")
    if node_id == new_parent_id:
        raise SceneError("invalid_parent", "cannot parent a node to itself")
    if new_parent_id is not None and is_ancestor(doc, node_id, new_parent_id):
        raise SceneError("cycle_detected",
                         f"moving {node_id} under {new_parent_id} would create a cycle")

    old_parent = nodes[node_id].get("parent")
    if old_parent == new_parent_id:
        return

    old_world = world_matrices(doc)[node_id] if preserve_world else None
    parent_world = math3d.identity() if new_parent_id is None else world_matrices(doc)[new_parent_id]
    _detach(doc, node_id)
    _attach(doc, node_id, new_parent_id, index)

    if preserve_world and old_world is not None:
        new_local = math3d.multiply(math3d.invert(parent_world), old_world)
        pos, rot, scl = math3d.decompose(new_local)
        node = nodes[node_id]
        node["position"], node["rotation"], node["scale"] = pos, rot, scl


def update_transform(doc, node_id, position=None, rotation=None, scale=None):
    node = doc["nodes"][node_id]
    if position is not None:
        node["position"] = [float(v) for v in position]
    if rotation is not None:
        node["rotation"] = [float(v) for v in rotation]
    if scale is not None:
        node["scale"] = [float(v) for v in scale]


def rename(doc, node_id, name):
    doc["nodes"][node_id]["name"] = name


def duplicate_subtree(doc, node_id, offset=(2.0, 0.0, 0.0)):
    """Deep-copy a node and all descendants as a sibling.

    Local TRS of every copied node is preserved (children stay attached
    to copied parents); the copy root is shifted by offset in its parent
    frame so the two copies do not overlap. Returns the new root id.
    """
    if node_id not in doc["nodes"]:
        raise SceneError("not_found", f"node {node_id} not found")
    id_map = {}

    def clone(nid):
        src = doc["nodes"][nid]
        dst = copy.deepcopy(src)
        dst["id"] = new_id()
        dst["children"] = []
        id_map[nid] = dst
        for child_id in src["children"]:
            child_copy = clone(child_id)
            child_copy["parent"] = dst["id"]
            dst["children"].append(child_copy["id"])
        return dst

    new_root = clone(node_id)
    new_root["position"] = [v + d for v, d in zip(new_root["position"], offset)]
    parent_id = doc["nodes"][node_id]["parent"]
    new_root["parent"] = parent_id
    for node in id_map.values():
        doc["nodes"][node["id"]] = node
    if parent_id is None:
        doc["rootOrder"].append(new_root["id"])
    else:
        doc["nodes"][parent_id]["children"].append(new_root["id"])
    return new_root["id"]


def delete_subtree(doc, node_id):
    if node_id not in doc["nodes"]:
        raise SceneError("not_found", f"node {node_id} not found")
    ids = subtree_ids(doc, node_id)
    _detach(doc, node_id)
    for nid in ids:
        del doc["nodes"][nid]


def group_nodes(doc, node_ids, name="Group"):
    """Wrap several current siblings in a new group at their shared parent."""
    if not node_ids:
        raise SceneError("empty_selection", "nothing to group")
    parents = {doc["nodes"][i]["parent"] for i in node_ids}
    if len(parents) != 1:
        raise SceneError("not_siblings", "group targets must share a parent")
    parent_id = parents.pop()
    siblings = doc["rootOrder"] if parent_id is None else doc["nodes"][parent_id]["children"]
    first_index = min(siblings.index(i) for i in node_ids)

    group = make_node("group", name)
    add_node(doc, group, parent_id)
    _detach(doc, group["id"])
    if parent_id is None:
        doc["rootOrder"].insert(first_index, group["id"])
    else:
        doc["nodes"][parent_id]["children"].insert(first_index, group["id"])
    for nid in node_ids:
        reparent(doc, nid, group["id"], preserve_world=True)
    return group["id"]

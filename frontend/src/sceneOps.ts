import * as THREE from "three";
import type { SceneDoc, SceneNode, NodeType, WorldInfo } from "./types";

export const OBJECT_TYPES: NodeType[] = ["cube", "sphere", "cylinder", "plane", "cone"];

const DEFAULT_NAMES: Record<NodeType, string> = {
  group: "分组",
  cube: "立方体",
  sphere: "球体",
  cylinder: "圆柱体",
  plane: "平面",
  cone: "圆锥体",
};

export function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID().replace(/-/g, "").slice(0, 12);
  return Math.random().toString(36).slice(2, 14);
}

export function newScene(): SceneDoc {
  return {
    version: 1,
    rootOrder: [],
    nodes: {},
    activeCamera: { position: [6, 6, 8], target: [0, 0, 0] },
  };
}

export function makeNode(
  type: NodeType,
  name?: string,
  position: [number, number, number] = [0, 0, 0],
  rotation: [number, number, number] = [0, 0, 0],
  scale: [number, number, number] = [1, 1, 1],
): SceneNode {
  return {
    id: newId(),
    name: name ?? DEFAULT_NAMES[type],
    type,
    parent: null,
    children: [],
    position: [...position],
    rotation: [...rotation],
    scale: [...scale],
  };
}

export class SceneError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

export function isAncestor(doc: SceneDoc, ancestorId: string, nodeId: string): boolean {
  let cur: string | null = nodeId;
  const seen = new Set<string>();
  while (cur !== null) {
    if (cur === ancestorId) return true;
    if (seen.has(cur)) throw new SceneError("cycle_detected", `在 ${cur} 处检测到循环`);
    seen.add(cur);
    cur = doc.nodes[cur].parent;
  }
  return false;
}

export function subtreeIds(doc: SceneDoc, id: string): string[] {
  const out: string[] = [];
  const stack = [id];
  while (stack.length) {
    const nid = stack.pop()!;
    out.push(nid);
    stack.push(...[...doc.nodes[nid].children].reverse());
  }
  return out;
}

// All mutations below operate on the passed document; the store clones
// documents before/after so history (undo/redo) stays intact.

export function addNode(doc: SceneDoc, node: SceneNode, parentId: string | null = null): void {
  if (doc.nodes[node.id]) throw new SceneError("duplicate_id", "节点已存在");
  node.parent = parentId;
  doc.nodes[node.id] = node;
  if (parentId === null) doc.rootOrder.push(node.id);
  else doc.nodes[parentId].children.push(node.id);
}

function detach(doc: SceneDoc, id: string): void {
  const node = doc.nodes[id];
  if (node.parent === null) doc.rootOrder = doc.rootOrder.filter((r) => r !== id);
  else doc.nodes[node.parent].children = doc.nodes[node.parent].children.filter((c) => c !== id);
  node.parent = null;
}

function attach(doc: SceneDoc, id: string, parentId: string | null, index?: number): void {
  const node = doc.nodes[id];
  node.parent = parentId;
  const list = parentId === null ? doc.rootOrder : doc.nodes[parentId].children;
  if (index === undefined) list.push(id);
  else list.splice(index, 0, id);
}

const _v = new THREE.Vector3();
const _e = new THREE.Euler(0, 0, 0, "XYZ");
const _q = new THREE.Quaternion();
const _s = new THREE.Vector3();
const _m = new THREE.Matrix4();
const _nm = new THREE.Matrix4();

function localMatrixOf(node: SceneNode, out: THREE.Matrix4): THREE.Matrix4 {
  _v.set(...node.position);
  _e.set(node.rotation[0], node.rotation[1], node.rotation[2], "XYZ");
  _q.setFromEuler(_e);
  _s.set(...node.scale);
  return out.compose(_v, _q, _s);
}

/** Final world matrix of every node, same traversal semantics as the backend. */
export function worldMatrices(doc: SceneDoc): Record<string, THREE.Matrix4> {
  const result: Record<string, THREE.Matrix4> = {};
  const visit = (id: string, parentWorld: THREE.Matrix4) => {
    const local = localMatrixOf(doc.nodes[id], _m);
    const world = parentWorld.clone().multiply(local);
    result[id] = world;
    for (const c of doc.nodes[id].children) visit(c, world);
  };
  const identity = new THREE.Matrix4();
  for (const rid of doc.rootOrder) visit(rid, identity);
  return result;
}

export function worldTRS(doc: SceneDoc): Record<string, WorldInfo> {
  const out: Record<string, WorldInfo> = {};
  for (const [id, mat] of Object.entries(worldMatrices(doc))) {
    const p = new THREE.Vector3();
    const q = new THREE.Quaternion();
    const s = new THREE.Vector3();
    mat.decompose(p, q, s);
    const e = new THREE.Euler().setFromQuaternion(q, "XYZ");
    out[id] = {
      position: [p.x, p.y, p.z],
      rotation: [e.x, e.y, e.z],
      scale: [s.x, s.y, s.z],
      matrix: Array.from(mat.elements),
    };
  }
  return out;
}

/**
 * Move `id` under newParentId. preserveWorld keeps the node at exactly the
 * same world pose by recomputing local TRS from inverse(parent world)*world
 * (three.js Object3D.attach convention).
 */
export function reparent(
  doc: SceneDoc,
  id: string,
  newParentId: string | null,
  preserveWorld = true,
  index?: number,
): void {
  if (!doc.nodes[id]) throw new SceneError("not_found", "节点不存在");
  if (newParentId !== null && !doc.nodes[newParentId]) throw new SceneError("not_found", "目标组不存在");
  if (id === newParentId) throw new SceneError("invalid_parent", "不能把节点挂到自己下面");
  if (newParentId !== null && isAncestor(doc, id, newParentId)) {
    throw new SceneError("cycle_detected", "不能挂到自己的子孙节点下（会形成循环）");
  }
  const oldParent = doc.nodes[id].parent;
  if (oldParent === newParentId) return;

  const oldWorld = preserveWorld ? worldMatrices(doc)[id] : null;
  const parentWorld =
    newParentId === null ? new THREE.Matrix4() : worldMatrices(doc)[newParentId].clone();

  detach(doc, id);
  attach(doc, id, newParentId, index);

  if (preserveWorld && oldWorld) {
    _nm.copy(parentWorld).invert().multiply(oldWorld);
    const p = new THREE.Vector3();
    const q = new THREE.Quaternion();
    const s = new THREE.Vector3();
    _nm.decompose(p, q, s);
    const e = new THREE.Euler().setFromQuaternion(q, "XYZ");
    const node = doc.nodes[id];
    node.position = [p.x, p.y, p.z];
    node.rotation = [e.x, e.y, e.z];
    node.scale = [s.x, s.y, s.z];
  }
}

export function updateTransform(
  doc: SceneDoc,
  id: string,
  patch: Partial<Pick<SceneNode, "position" | "rotation" | "scale">>,
): void {
  const node = doc.nodes[id];
  if (patch.position) node.position = [...patch.position];
  if (patch.rotation) node.rotation = [...patch.rotation];
  if (patch.scale) node.scale = [...patch.scale];
}

export function rename(doc: SceneDoc, id: string, name: string): void {
  doc.nodes[id].name = name;
}

export function duplicateSubtree(doc: SceneDoc, id: string, offset: [number, number, number] = [2, 0, 0]): string {
  if (!doc.nodes[id]) throw new SceneError("not_found", "节点不存在");
  const map: Record<string, SceneNode> = {};
  const clone = (nid: string): SceneNode => {
    const src = doc.nodes[nid];
    const dst: SceneNode = {
      ...structuredClone(src),
      id: newId(),
      children: [],
      position: [...src.position],
      rotation: [...src.rotation],
      scale: [...src.scale],
    };
    map[nid] = dst;
    for (const cid of src.children) {
      const cc = clone(cid);
      cc.parent = dst.id;
      dst.children.push(cc.id);
    }
    return dst;
  };
  const newRoot = clone(id);
  newRoot.position = [newRoot.position[0] + offset[0], newRoot.position[1] + offset[1], newRoot.position[2] + offset[2]];
  const parentId = doc.nodes[id].parent;
  newRoot.parent = parentId;
  for (const node of Object.values(map)) doc.nodes[node.id] = node;
  if (parentId === null) doc.rootOrder.push(newRoot.id);
  else doc.nodes[parentId].children.push(newRoot.id);
  return newRoot.id;
}

export function deleteSubtree(doc: SceneDoc, id: string): void {
  if (!doc.nodes[id]) throw new SceneError("not_found", "节点不存在");
  const ids = subtreeIds(doc, id);
  detach(doc, id);
  for (const nid of ids) delete doc.nodes[nid];
}

export function groupNodes(doc: SceneDoc, ids: string[], name = "分组"): string {
  if (ids.length === 0) throw new SceneError("empty_selection", "未选择节点");
  const parents = new Set(ids.map((i) => doc.nodes[i].parent));
  if (parents.size !== 1) throw new SceneError("not_siblings", "只能把同级节点成组");
  const parentId = [...parents][0] ?? null;
  const siblings = parentId === null ? doc.rootOrder : doc.nodes[parentId].children;
  const firstIndex = Math.min(...ids.map((i) => siblings.indexOf(i)));
  const group = makeNode("group", name);
  addNode(doc, group, parentId);
  detach(doc, group.id);
  attach(doc, group.id, parentId, firstIndex);
  for (const nid of ids) reparent(doc, nid, group.id, true);
  return group.id;
}

import { describe, it, expect } from "vitest";
import * as THREE from "three";
import * as ops from "../src/sceneOps";
import type { SceneDoc } from "../src/types";
import goldenDeep from "../../backend/fixtures/deep_nested.json";
import goldenReparent from "../../backend/fixtures/reparent.json";

const EPS = 1e-6;

function expectMatrixClose(got: THREE.Matrix4, flat: number[]) {
  const els = Array.from(got.elements);
  expect(els.length).toBe(16);
  for (let i = 0; i < 16; i++) {
    expect(els[i], `matrix[${i}]`).toBeCloseTo(flat[i], 5);
  }
}

describe("frontend world matrices vs backend golden", () => {
  it("deep nested scene with rotations and non-uniform scale", () => {
    const doc = goldenDeep.doc as unknown as SceneDoc;
    const fe = ops.worldTRS(doc);
    for (const [id, info] of Object.entries(goldenDeep.world)) {
      expect(fe[id], `node ${id} exists`).toBeTruthy();
      expectMatrixClose(new THREE.Matrix4().fromArray(fe[id].matrix), info.matrix);
      fe[id].position.forEach((v, i) => expect(v).toBeCloseTo(info.position[i], 5));
    }
  });

  it("post-reparent document (server recomputed local TRS) matches", () => {
    const doc = goldenReparent.doc as unknown as SceneDoc;
    const fe = ops.worldTRS(doc);
    for (const [id, info] of Object.entries(goldenReparent.world)) {
      expectMatrixClose(new THREE.Matrix4().fromArray(fe[id].matrix), info.matrix);
    }
  });
});

describe("reparenting", () => {
  function build() {
    const doc = ops.newScene();
    const a = ops.makeNode("group", "A", [0, 0, 0], [0, Math.PI / 2, 0], [2, 2, 2]);
    const b = ops.makeNode("group", "B", [1, 2, 3], [Math.PI / 4, 0, 0], [1, 1, 1]);
    const c = ops.makeNode("cube", "C", [0.5, 0, -1], [0, 0, 0.3], [1, 1, 1]);
    ops.addNode(doc, a);
    ops.addNode(doc, b, a.id);
    ops.addNode(doc, c, b.id);
    return { doc, a, b, c };
  }

  it("keeps world pose exactly with uniformly scaled chain", () => {
    const { doc, c } = build();
    const before = ops.worldMatrices(doc)[c.id].clone();
    const d = ops.makeNode("group", "D", [5, 0, 0], [0, 0, Math.PI / 3], [2, 2, 2]);
    ops.addNode(doc, d);
    ops.reparent(doc, c.id, d.id, true);
    expect(doc.nodes[c.id].parent).toBe(d.id);
    const after = ops.worldMatrices(doc)[c.id];
    for (let i = 0; i < 16; i++) expect(after.elements[i]).toBeCloseTo(before.elements[i], 9);
  });

  it("recomputes local position when moving under a rotated group", () => {
    const { doc, c } = build();
    const before = [...ops.worldMatrices(doc)[c.id].elements];
    const d = ops.makeNode("group", "D", [0, 0, 0], [0, Math.PI / 2, 0], [1, 1, 1]);
    ops.addNode(doc, d);
    ops.reparent(doc, c.id, d.id, true);
    // world position unchanged while local changed
    expect(doc.nodes[c.id].position.some((v, i) => Math.abs(v - [0.5, 0, -1][i]) > 1e-9)).toBe(true);
    const after = ops.worldMatrices(doc)[c.id].elements;
    after.forEach((v, i) => expect(v).toBeCloseTo(before[i], 9));
  });

  it("blocks self-parenting and descendant cycles", () => {
    const { doc, a, b, c } = build();
    expect(() => ops.reparent(doc, a.id, a.id)).toThrowError(/自己/);
    expect(() => ops.reparent(doc, a.id, c.id)).toThrowError(/循环/);
    // unchanged after rejected ops
    expect(doc.nodes[b.id].parent).toBe(a.id);
    expect(doc.nodes[c.id].parent).toBe(b.id);
  });

  it("preserveWorld=false keeps local TRS", () => {
    const { doc, c } = build();
    const localPos = [...c.position];
    ops.reparent(doc, c.id, null, false);
    expect(doc.nodes[c.id].position).toEqual(localPos);
    expect(doc.rootOrder).toContain(c.id);
  });
});

describe("duplicate and group", () => {
  it("deep copy keeps parent/child links and offsets the root", () => {
    const doc = ops.newScene();
    const g = ops.makeNode("group", "G", [1, 0, 0]);
    const inner = ops.makeNode("group", "Inner");
    const cube = ops.makeNode("cube", "C", [0, 1, 0]);
    ops.addNode(doc, g);
    ops.addNode(doc, inner, g.id);
    ops.addNode(doc, cube, inner.id);

    const copyId = ops.duplicateSubtree(doc, g.id);
    expect(copyId).not.toBe(g.id);
    expect(doc.nodes[copyId].position).toEqual([3, 0, 0]);
    const copiedInner = doc.nodes[copyId].children[0];
    expect(doc.nodes[copiedInner].parent).toBe(copyId);
    const copiedCube = doc.nodes[copiedInner].children[0];
    expect(doc.nodes[copiedCube].parent).toBe(copiedInner);
    expect(doc.nodes[copiedCube].position).toEqual([0, 1, 0]);
    // original intact
    expect(doc.nodes[g.id].children[0]).toBe(inner.id);
  });

  it("groupNodes wraps selection and keeps world pose", () => {
    const doc = ops.newScene();
    const a = ops.makeNode("cube", "A", [1, 0, 0]);
    const b = ops.makeNode("sphere", "B", [0, 2, 0]);
    ops.addNode(doc, a);
    ops.addNode(doc, b);
    const before = { [a.id]: ops.worldMatrices(doc)[a.id].clone(), [b.id]: ops.worldMatrices(doc)[b.id].clone() };
    const gid = ops.groupNodes(doc, [a.id, b.id]);
    expect(doc.nodes[a.id].parent).toBe(gid);
    const after = ops.worldMatrices(doc);
    for (const k of [a.id, b.id]) {
      for (let i = 0; i < 16; i++) expect(after[k].elements[i]).toBeCloseTo(before[k].elements[i], 9);
    }
  });
});

import { describe, it, expect } from "vitest";
import * as THREE from "three";
import example from "../../../shared/nested-world.example.json";
import { syncObjects } from "../components/Viewport";
import type { Scene, SceneNode, Transform } from "../lib/types";

// 后端 build_nested 生成的同一组 TRS（四元数来自后端 XYZ 欧拉）
function qFromEuler(x: number, y: number, z: number) {
  return new THREE.Quaternion().setFromEuler(new THREE.Euler(x, y, z, "XYZ"));
}

function node(
  id: string,
  name: string,
  type: SceneNode["type"],
  parent_id: string | null,
  transform: Partial<Transform> & { position: [number, number, number]; rotation: [number, number, number, number]; scale: [number, number, number] },
  children: string[] = []
): SceneNode {
  return { id, name, type, parent_id, children, transform };
}

const A = "A", B = "B", C = "C", D = "D";
const qZ90 = qFromEuler(0, 0, Math.PI / 2).toArray() as [number, number, number, number];
const qY90 = qFromEuler(0, Math.PI / 2, 0).toArray() as [number, number, number, number];
const qX90 = qFromEuler(Math.PI / 2, 0, 0).toArray() as [number, number, number, number];
const ID: [number, number, number, number] = [0, 0, 0, 1];

function buildScene(): Scene {
  return {
    version: 1,
    root_ids: [A, D],
    nodes: [
      node(A, "A", "group", null, { position: [1, 2, 3], rotation: qZ90, scale: [2, 2, 2] }, [B]),
      node(B, "B", "cube", A, { position: [1, 0, 0], rotation: qY90, scale: [0.5, 2, 1] }, [C]),
      node(C, "C", "sphere", B, { position: [0, 0, 2], rotation: ID, scale: [1, 1, 1] }),
      node(D, "D", "cone", null, { position: [0, 1, 0], rotation: qX90, scale: [1, 1, 1] }),
    ],
  };
}

// 后端导出时的真实 id -> 语义 id 映射
// ids 为 语义id -> 后端真实id，需要反转
const realToSemantic = Object.fromEntries(
  Object.entries(example.ids as Record<string, string>).map(([semantic, real]) => [real, semantic])
);
const backendById = Object.fromEntries(
  (example.world as Array<{ id: string; matrix: number[]; position: number[] }>).map((w) => [
    realToSemantic[w.id],
    w,
  ])
);

describe("页面 three.js 与后端世界矩阵一致", () => {
  it("层层嵌套 + 旋转缩放下逐元素一致", () => {
    const root = new THREE.Group();
    syncObjects(root, buildScene(), null);
    root.updateMatrixWorld(true);

    const objects = new Map<string, THREE.Object3D>();
    root.traverse((o) => {
      if (o.userData.nodeId) objects.set(o.userData.nodeId, o);
    });

    for (const semantic of [A, B, C, D]) {
      const elements = objects.get(semantic)!.matrixWorld.elements;
      const backend = backendById[semantic];
      expect(backend).toBeTruthy();
      for (let i = 0; i < 16; i++) {
        expect(elements[i]).toBeCloseTo(backend.matrix[i], 9);
      }
    }

    // 抽查世界位置
    const cPos = objects.get(C)!.getWorldPosition(new THREE.Vector3());
    expect([cPos.x, cPos.y, cPos.z].map((v) => Number(v.toFixed(6)))).toEqual([1, 8, 3]);
  });

  it("重建父子层级：group 挂子物体、根节点顺序保留", () => {
    const root = new THREE.Group();
    syncObjects(root, buildScene(), null);
    const objects = new Map<string, THREE.Object3D>();
    root.traverse((o) => {
      if (o.userData.nodeId) objects.set(o.userData.nodeId, o);
    });
    expect(objects.get(B)!.parent).toBe(objects.get(A));
    expect(objects.get(C)!.parent).toBe(objects.get(B));
    expect(objects.get(A)!.parent).toBe(root);
    expect(objects.get(D)!.parent).toBe(root);
    expect(root.children.map((c) => c.userData.nodeId)).toEqual([A, D]);
  });
});

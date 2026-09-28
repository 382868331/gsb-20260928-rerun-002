import { describe, it, expect } from "vitest";
import * as THREE from "three";
import type { Scene, SceneNode } from "../lib/types";

// 前端侧独立验证“换组保持眼前位置”的数学：
// newLocal = inverse(parentWorld) * savedWorld（与后端 multiply 约定一致）
function compose(pos: number[], quat: THREE.Quaternion, scl: number[]) {
  const m = new THREE.Matrix4();
  m.compose(
    new THREE.Vector3(...(pos as [number, number, number])),
    quat,
    new THREE.Vector3(...(scl as [number, number, number]))
  );
  return m;
}

describe("换组保持世界位置", () => {
  it("挂到带旋转缩放的新父级后，世界矩阵不变", () => {
    const parentWorld = compose(
      [1, 2, 3],
      new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, Math.PI / 2)),
      [2, 2, 2]
    );
    const savedWorld = compose(
      [1, 8, 3],
      new THREE.Quaternion(0.1, 0.2, 0.3, 1).normalize(),
      [1, 4, 2]
    );
    const newLocal = new THREE.Matrix4().copy(parentWorld).invert().multiply(savedWorld);

    const recomposedWorld = new THREE.Matrix4().multiplyMatrices(parentWorld, newLocal);
    for (let i = 0; i < 16; i++) {
      expect(recomposedWorld.elements[i]).toBeCloseTo(savedWorld.elements[i], 10);
    }
  });
});

// 用真实 three.js 重建后端 build_nested 场景，逐元素比对后端导出的世界矩阵。
// 运行：cd frontend && node ../shared/check-three.mjs
import * as THREE from 'three';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const here = dirname(fileURLToPath(import.meta.url));
const data = JSON.parse(
  readFileSync(join(here, 'nested-world.example.json'), 'utf-8')
);

function make(quat, p, s) {
  const o = new THREE.Object3D();
  o.quaternion.set(...quat);
  o.position.set(...p);
  o.scale.set(...s);
  return o;
}

const A = make([0, 0, Math.SQRT1_2, Math.SQRT1_2], [1, 2, 3], [2, 2, 2]);
const B = make(
  new THREE.Quaternion().setFromEuler(new THREE.Euler(0, Math.PI / 2, 0)).toArray(),
  [1, 0, 0],
  [0.5, 2, 1]
);
const C = make([0, 0, 0, 1], [0, 0, 2], [1, 1, 1]);
const D = make(
  new THREE.Quaternion().setFromEuler(new THREE.Euler(Math.PI / 2, 0, 0)).toArray(),
  [0, 1, 0],
  [1, 1, 1]
);
A.add(B);
B.add(C);
const scene = new THREE.Scene();
scene.add(A, D);
scene.updateMatrixWorld(true);

const map = {
  [data.ids.A]: A,
  [data.ids.B]: B,
  [data.ids.C]: C,
  [data.ids.D]: D,
};

let maxErr = 0;
for (const w of data.world) {
  const e = map[w.id].matrixWorld.elements;
  const err = Math.max(...e.map((v, i) => Math.abs(v - w.matrix[i])));
  maxErr = Math.max(maxErr, err);
  console.log(w.name, 'maxErr =', err.toExponential(2));
}
console.log(
  maxErr < 1e-9
    ? 'PASS: three.js 世界矩阵与后端完全一致'
    : 'FAIL maxErr=' + maxErr
);
process.exit(maxErr < 1e-9 ? 0 : 1);

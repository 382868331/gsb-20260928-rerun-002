import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Scene, SceneNode } from "../lib/types";
import { useStore } from "../lib/store";

const GEOMETRIES: Record<string, THREE.BufferGeometry> = {
  cube: new THREE.BoxGeometry(1, 1, 1),
  sphere: new THREE.SphereGeometry(0.6, 32, 24),
  cylinder: new THREE.CylinderGeometry(0.5, 0.5, 1.2, 32),
  cone: new THREE.ConeGeometry(0.6, 1.2, 32),
  plane: new THREE.PlaneGeometry(2, 2),
};

function hashId(id: string): number {
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) | 0;
  return Math.abs(h);
}

function makeObject(node: SceneNode): THREE.Object3D {
  if (node.type === "group") {
    const group = new THREE.Group();
    group.add(new THREE.AxesHelper(0.9));
    return group;
  }
  const material = new THREE.MeshStandardMaterial({
    color: new THREE.Color().setHSL(
      0.5 + (hashId(node.id) % 40) / 120,
      0.55,
      0.6
    ),
    roughness: 0.55,
    metalness: 0.1,
    side: node.type === "plane" ? THREE.DoubleSide : THREE.FrontSide,
  });
  const mesh = new THREE.Mesh(GEOMETRIES[node.type], material);
  if (node.type === "plane") mesh.rotation.x = -Math.PI / 2;
  return mesh;
}

function syncObjects(
  contentRoot: THREE.Group,
  scene: Scene,
  selectedId: string | null
) {
  const existing = new Map<string, THREE.Object3D>();
  contentRoot.traverse((obj) => {
    if (obj.userData.nodeId) existing.set(obj.userData.nodeId, obj);
  });

  const index = new Map(scene.nodes.map((n) => [n.id, n]));
  for (const node of scene.nodes) {
    let obj = existing.get(node.id);
    if (!obj) {
      obj = makeObject(node);
      obj.userData.nodeId = node.id;
    }
    obj.name = node.name;
    obj.position.set(...node.transform.position);
    obj.quaternion.set(...node.transform.rotation);
    obj.scale.set(...node.transform.scale);
    const selected = node.id === selectedId;
    obj.traverse((child) => {
      const mesh = child as THREE.Mesh;
      if (mesh.isMesh && mesh.material) {
        (mesh.material as THREE.MeshStandardMaterial).emissive.set(
          selected ? 0x2a5a96 : 0x000000
        );
      }
    });
    const parentObject =
      node.parent_id && index.has(node.parent_id)
        ? existing.get(node.parent_id) ?? contentRoot
        : contentRoot;
    if (obj.parent !== parentObject) parentObject.add(obj);
    existing.set(node.id, obj);
  }

  for (const [id, obj] of existing) {
    if (!index.has(id)) obj.removeFromParent();
  }
  contentRoot.updateMatrixWorld(true);
}

export function Viewport() {
  const mountRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<THREE.Group | null>(null);
  const scene = useStore((s) => s.scene);
  const selectedId = useStore((s) => s.selectedId);

  useEffect(() => {
    const mount = mountRef.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    const threeScene = new THREE.Scene();
    threeScene.background = new THREE.Color(0x14181f);
    const camera = new THREE.PerspectiveCamera(
      55,
      mount.clientWidth / mount.clientHeight,
      0.1,
      500
    );
    camera.position.set(8, 7, 11);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    threeScene.add(new THREE.AmbientLight(0xffffff, 0.75));
    const key = new THREE.DirectionalLight(0xffffff, 1.3);
    key.position.set(6, 12, 8);
    threeScene.add(key);
    threeScene.add(new THREE.GridHelper(30, 30, 0x3a4456, 0x232a36));

    const contentRoot = new THREE.Group();
    threeScene.add(contentRoot);
    contentRef.current = contentRoot;

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const onClick = (event: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(contentRoot.children, true);
      for (const hit of hits) {
        let obj: THREE.Object3D | null = hit.object;
        while (obj && !obj.userData.nodeId) obj = obj.parent;
        if (obj?.userData.nodeId) {
          useStore.getState().select(obj.userData.nodeId);
          break;
        }
      }
    };
    renderer.domElement.addEventListener("click", onClick);

    let frame = 0;
    const animate = () => {
      frame = requestAnimationFrame(animate);
      controls.update();
      renderer.render(threeScene, camera);
    };
    animate();

    const onResize = () => {
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
      renderer.domElement.removeEventListener("click", onClick);
      controls.dispose();
      renderer.dispose();
      mount.removeChild(renderer.domElement);
      contentRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (contentRef.current) syncObjects(contentRef.current, scene, selectedId);
  }, [scene, selectedId]);

  return <div ref={mountRef} className="viewport" />;
}

export { syncObjects };

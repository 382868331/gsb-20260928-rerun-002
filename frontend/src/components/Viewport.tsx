import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { TransformControls } from "three/examples/jsm/controls/TransformControls.js";
import type { SceneDoc, SceneNode } from "../types";
import { useStore } from "../store";

function makeGeometry(type: SceneNode["type"]): THREE.BufferGeometry | null {
  switch (type) {
    case "cube": return new THREE.BoxGeometry(1, 1, 1);
    case "sphere": return new THREE.SphereGeometry(0.6, 32, 24);
    case "cylinder": return new THREE.CylinderGeometry(0.5, 0.5, 1.2, 32);
    case "cone": return new THREE.ConeGeometry(0.6, 1.2, 32);
    case "plane": {
        const geo = new THREE.PlaneGeometry(2, 2);
        geo.rotateX(-Math.PI / 2);
        return geo;
      }
    default: return null;
  }
}

const PALETTE = [0x6aa6ff, 0x66d1a5, 0xf2c14e, 0xe8786a, 0x9b8cf0, 0x4cc5d9];

function colorFor(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

export function Viewport() {
  const mountRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<{
    renderer: THREE.WebGLRenderer;
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    orbit: OrbitControls;
    transform: TransformControls;
    groupRoot: THREE.Group;
    objects: Map<string, THREE.Object3D>;
    selectionBox: THREE.BoxHelper;
  } | null>(null);

  // one-time engine setup
  useEffect(() => {
    const mount = mountRef.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1b1e25);
    const camera = new THREE.PerspectiveCamera(50, mount.clientWidth / mount.clientHeight, 0.1, 200);
    camera.position.set(6, 6, 8);

    const orbit = new OrbitControls(camera, renderer.domElement);
    orbit.enableDamping = true;
    orbit.target.set(0, 0.5, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(6, 10, 6);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x88aaff, 0.35);
    fill.position.set(-6, 4, -6);
    scene.add(fill);

    const grid = new THREE.GridHelper(30, 30, 0x444a55, 0x2c3038);
    (grid.material as THREE.Material).transparent = true;
    (grid.material as THREE.Material).opacity = 0.6;
    scene.add(grid);

    const groupRoot = new THREE.Group();
    groupRoot.name = "__sceneRoot__";
    scene.add(groupRoot);

    const transform = new TransformControls(camera, renderer.domElement);
    transform.setSize(0.8);
    const gizmo = transform.getHelper ? transform.getHelper() : (transform as unknown as THREE.Object3D);
    scene.add(gizmo);

    const selectionBox = new THREE.BoxHelper(new THREE.Object3D(), 0xffd166);
    selectionBox.visible = false;
    scene.add(selectionBox);

    let frame = 0;
    const render = () => {
      frame = requestAnimationFrame(render);
      orbit.update();
      renderer.render(scene, camera);
    };
    render();

    const onResize = () => {
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
    };
    window.addEventListener("resize", onResize);

    engineRef.current = {
      renderer, scene, camera, orbit, transform, groupRoot,
      objects: new Map(), selectionBox,
    };

    // disable orbit while dragging the gizmo
    transform.addEventListener("dragging-changed", (event) => {
      const dragging = event.value as boolean;
      orbit.enabled = !dragging;
      const st = useStore.getState();
      if (dragging) st.beginLiveEdit("拖动变换");
      else st.endLiveEdit();
    });
    transform.addEventListener("objectChange", () => {
      const obj = transform.object as THREE.Object3D | null;
      if (!obj) return;
      const id = obj.userData.nodeId as string | undefined;
      if (!id) return;
      useStore.getState().liveUpdate(id, {
        position: [obj.position.x, obj.position.y, obj.position.z],
        rotation: [obj.rotation.x, obj.rotation.y, obj.rotation.z],
        scale: [obj.scale.x, obj.scale.y, obj.scale.z],
      });
    });

    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      const t = transform;
      if (e.key === "w") t.setMode("translate");
      if (e.key === "e") t.setMode("rotate");
      if (e.key === "r") t.setMode("scale");
    };
    window.addEventListener("keydown", onKey);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("keydown", onKey);
      transform.dispose();
      renderer.dispose();
      mount.removeChild(renderer.domElement);
      engineRef.current = null;
    };
  }, []);

  // click-to-select
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine) return;
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let down = { x: 0, y: 0 };
    const dom = engine.renderer.domElement;

    const onPointerDown = (e: PointerEvent) => { down = { x: e.clientX, y: e.clientY }; };
    const onPointerUp = (e: PointerEvent) => {
      if (Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4) return;
      const rect = dom.getBoundingClientRect();
      pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, engine.camera);
      const meshes = [...engine.objects.values()].filter((o) => o.userData.pickable);
      const hits = raycaster.intersectObjects(meshes, false);
      useStore.getState().selectOnly(hits.length ? (hits[0].object.userData.nodeId as string) : null);
    };
    dom.addEventListener("pointerdown", onPointerDown);
    dom.addEventListener("pointerup", onPointerUp);
    return () => {
      dom.removeEventListener("pointerdown", onPointerDown);
      dom.removeEventListener("pointerup", onPointerUp);
    };
  }, []);

  // sync scene graph whenever the doc changes
  const doc = useStore((s) => s.doc);
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine) return;
    const { groupRoot, objects } = engine;

    const seen = new Set<string>();
    const ensure = (node: SceneNode): THREE.Object3D => {
      seen.add(node.id);
      let obj = objects.get(node.id);
      if (!obj) {
        if (node.type === "group") {
          obj = new THREE.Group();
          obj.add(new THREE.AxesHelper(0.6));
        } else {
          const geo = makeGeometry(node.type);
          const mat = new THREE.MeshStandardMaterial({ color: colorFor(node.id), roughness: 0.6, metalness: 0.1 });
          obj = new THREE.Mesh(geo!, mat);
          obj.userData.pickable = true;
        }
        obj.userData.nodeId = node.id;
        objects.set(node.id, obj);
      }
      return obj;
    };

    // ensure all objects exist, then wire parents
    for (const id of Object.keys(doc.nodes)) ensure(doc.nodes[id]);
    for (const [id, node] of Object.entries(doc.nodes)) {
      const obj = objects.get(id)!;
      const parent: THREE.Object3D = node.parent ? (objects.get(node.parent) ?? groupRoot) : groupRoot;
      if (obj.parent !== parent) parent.add(obj);
      if (obj.position.toArray().some((v, i) => Math.abs(v - node.position[i]) > 1e-6)) obj.position.set(...node.position);
      if (Math.abs(obj.rotation.x - node.rotation[0]) > 1e-6 || Math.abs(obj.rotation.y - node.rotation[1]) > 1e-6 || Math.abs(obj.rotation.z - node.rotation[2]) > 1e-6) {
        obj.rotation.set(node.rotation[0], node.rotation[1], node.rotation[2]);
      }
      if (obj.scale.toArray().some((v, i) => Math.abs(v - node.scale[i]) > 1e-6)) obj.scale.set(...node.scale);
      obj.name = node.name;
    }

    // remove deleted
    for (const [id, obj] of [...objects]) {
      if (!seen.has(id)) {
        obj.parent?.remove(obj);
        objects.delete(id);
      }
    }
    groupRoot.updateMatrixWorld(true);
  }, [doc]);

  // attach gizmo + highlight to selection
  const selectedIds = useStore((s) => s.selectedIds);
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine) return;
    const id = selectedIds[0] ?? null;
    const target = id ? engine.objects.get(id) ?? null : null;
    if (target) {
      engine.transform.attach(target);
      engine.selectionBox.setFromObject(target);
      engine.selectionBox.visible = true;
    } else {
      engine.transform.detach();
      engine.selectionBox.visible = false;
    }
  }, [selectedIds, doc]);

  // highlight refresh during interaction
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine) return;
    const id = useStore.getState().selectedIds[0];
    const target = id ? engine.objects.get(id) : undefined;
    if (target) engine.selectionBox.setFromObject(target);
  });

  return <div ref={mountRef} className="viewport" />;
}

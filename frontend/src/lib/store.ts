import { create } from "zustand";
import * as THREE from "three";
import { api } from "./api";
import type { Scene, SceneNode, Vec3, WorldInfo } from "./types";

const HISTORY_LIMIT = 100;

function eulerOf(node: SceneNode): Vec3 {
  const q = new THREE.Quaternion(...node.transform.rotation);
  const e = new THREE.Euler().setFromQuaternion(q, "XYZ");
  return [e.x, e.y, e.z];
}

function cloneScene(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene));
}

interface State {
  sceneId: string | null;
  scene: Scene;
  selectedId: string | null;
  world: WorldInfo[];
  past: Scene[];
  future: Scene[];
  busy: string | null;
  error: string | null;
  dirty: boolean;

  init: () => Promise<void>;
  loadScene: (id: string) => Promise<void>;
  newScene: () => Promise<void>;
  save: () => Promise<void>;

  apply: (next: Scene, opts?: { record?: boolean }) => void;
  undo: () => void;
  redo: () => void;

  select: (id: string | null) => void;
  addNode: (type: string) => Promise<void>;
  groupSelected: () => Promise<void>;
  reparent: (parentId: string | null, keepWorld: boolean) => Promise<void>;
  duplicate: () => Promise<void>;
  createAssembly: () => Promise<void>;
  instantiateAssembly: (assemblyId: string) => Promise<void>;
  publishAssembly: () => Promise<void>;
  detachAssembly: () => Promise<void>;
  renameSelected: (name: string) => Promise<void>;
  remove: () => Promise<void>;
  updateTransform: (
    patch: Partial<{ position: Vec3; rotationEuler: Vec3; scale: Vec3 }>
  ) => Promise<void>;

  refreshWorld: () => Promise<void>;
  eulerOfSelected: () => Vec3 | null;
}

export const useStore = create<State>((set, get) => {
  const nodeIndex = (scene: Scene) =>
    new Map(scene.nodes.map((n) => [n.id, n]));

  const commit = async (
    promise: Promise<{ scene: Scene }>,
    selectId?: string
  ) => {
    set({ busy: "操作中…", error: null });
    try {
      const { scene } = await promise;
      const prev = get().scene;
      set((s) => ({
        scene,
        past: [...s.past, prev].slice(-HISTORY_LIMIT),
        future: [],
        busy: null,
        dirty: true,
        selectedId: selectId ?? s.selectedId,
      }));
      await get().refreshWorld();
    } catch (err) {
      set({ busy: null, error: (err as Error).message });
    }
  };

  return {
    sceneId: null,
    scene: { version: 1, nodes: [], root_ids: [], assemblies: [] },
    selectedId: null,
    world: [],
    past: [],
    future: [],
    busy: null,
    error: null,
    dirty: false,

    async init() {
      const list = await api.listScenes().catch(() => ({ scenes: [] }));
      if (list.scenes.length > 0) {
        await get().loadScene(list.scenes[0].scene_id);
      } else {
        await get().newScene();
      }
    },

    async newScene() {
      const { scene_id, scene } = await api.createScene();
      set({
        sceneId: scene_id,
        scene,
        past: [],
        future: [],
        selectedId: null,
        world: [],
        dirty: false,
        error: null,
      });
    },

    async loadScene(id) {
      const { scene } = await api.loadScene(id);
      set({
        sceneId: id,
        scene,
        past: [],
        future: [],
        selectedId: null,
        dirty: false,
        error: null,
      });
      await get().refreshWorld();
    },

    async save() {
      const { sceneId, scene } = get();
      if (!sceneId) return;
      set({ busy: "保存中…" });
      try {
        await api.saveScene(sceneId, scene);
        set({ busy: null, dirty: false });
      } catch (err) {
        set({ busy: null, error: (err as Error).message });
      }
    },

    apply(next, opts = { record: true }) {
      const prev = get().scene;
      set((s) => ({
        scene: next,
        past: opts.record ? [...s.past, prev].slice(-HISTORY_LIMIT) : s.past,
        future: [],
        dirty: true,
      }));
      void get().refreshWorld();
    },

    undo() {
      const { past, future, scene } = get();
      if (past.length === 0) return;
      const previous = past[past.length - 1];
      set({
        scene: previous,
        past: past.slice(0, -1),
        future: [scene, ...future].slice(0, HISTORY_LIMIT),
      });
      void get().refreshWorld();
    },

    redo() {
      const { past, future, scene } = get();
      if (future.length === 0) return;
      const next = future[0];
      set({
        scene: next,
        past: [...past, scene].slice(-HISTORY_LIMIT),
        future: future.slice(1),
      });
      void get().refreshWorld();
    },

    select(id) {
      set({ selectedId: id });
    },

    async addNode(type) {
      const { scene, selectedId } = get();
      const selected = selectedId ? nodeIndex(scene).get(selectedId) : undefined;
      // 选中组：加到组里；选中普通物体：加到它所在的父组（没有父级则到根）
      const parent = !selected
        ? null
        : selected.type === "group"
          ? selected.id
          : selected.parent_id;
      await commit(api.addNode(scene, type, parent));
    },

    async groupSelected() {
      const { scene, selectedId } = get();
      if (!selectedId) return;
      // 成组当前选中节点与其同级的所有选中项；第一版只组单个节点也可以
      await commit(api.group(scene, [selectedId]));
    },

    async reparent(parentId, keepWorld) {
      const { scene, selectedId } = get();
      if (!selectedId) return;
      await commit(api.reparent(scene, selectedId, parentId, keepWorld));
    },

    async duplicate() {
      const { scene, selectedId } = get();
      if (!selectedId) return;
      await commit(api.duplicate(scene, selectedId));
    },

    async createAssembly() {
      const { scene, selectedId } = get();
      if (!selectedId) return;
      await commit(api.createAssembly(scene, selectedId));
    },

    async instantiateAssembly(assemblyId) {
      const { scene, selectedId } = get();
      const selected = selectedId ? nodeIndex(scene).get(selectedId) : undefined;
      const parentId = selected?.type === "group" ? selectedId : null;
      await commit(api.instantiateAssembly(scene, assemblyId, parentId));
    },

    async publishAssembly() {
      const { scene, selectedId } = get();
      if (!selectedId) return;
      await commit(api.publishAssembly(scene, selectedId));
    },

    async detachAssembly() {
      const { scene, selectedId } = get();
      if (!selectedId) return;
      await commit(api.detachAssembly(scene, selectedId));
    },

    async renameSelected(name) {
      const { scene, selectedId } = get();
      if (!selectedId || !name.trim()) return;
      await commit(api.rename(scene, selectedId, name.trim()));
    },

    async remove() {
      const { scene, selectedId } = get();
      if (!selectedId) return;
      const next = await api.delete(scene, selectedId);
      set({ selectedId: null });
      await commit(Promise.resolve(next));
    },

    async updateTransform(patch) {
      const { scene, selectedId } = get();
      if (!selectedId) return;
      const node = nodeIndex(scene).get(selectedId);
      if (!node) return;
      const body: Parameters<typeof api.transform>[2] = {};
      if (patch.position) body.position = patch.position;
      if (patch.rotationEuler) body.rotation_euler = patch.rotationEuler;
      if (patch.scale) body.scale = patch.scale;
      await commit(api.transform(scene, selectedId, body));
    },

    async refreshWorld() {
      const { scene } = get();
      if (scene.nodes.length === 0) {
        set({ world: [] });
        return;
      }
      try {
        const { world } = await api.worldTransforms(scene);
        set({ world });
      } catch {
        // 后端不可用时静默：视口仍能本地渲染
      }
    },

    eulerOfSelected() {
      const { scene, selectedId } = get();
      const node = selectedId ? nodeIndex(scene).get(selectedId) : undefined;
      return node ? eulerOf(node) : null;
    },
  };
});

export { cloneScene, eulerOf };

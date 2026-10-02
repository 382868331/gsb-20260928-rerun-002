import { create } from "zustand";
import * as THREE from "three";
import { api } from "./api";
import type {
  AssemblyUpdatePreview,
  ReleaseBatchPreview,
  ReleaseBatchStatus,
  ReleaseDerivePreview,
  Scene,
  SceneNode,
  SelectionRef,
  Vec3,
  WorldInfo,
} from "./types";

const HISTORY_LIMIT = 100;

function eulerOf(node: SceneNode): Vec3 {
  const q = new THREE.Quaternion(...node.transform.rotation);
  const e = new THREE.Euler().setFromQuaternion(q, "XYZ");
  return [e.x, e.y, e.z];
}

function cloneScene(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene));
}

function withAssemblyCollections(scene: Scene): Scene {
  return {
    ...scene,
    assembly_defs: scene.assembly_defs ?? [],
    assembly_instances: scene.assembly_instances ?? [],
    assembly_history: scene.assembly_history ?? [],
    releases: scene.releases ?? [],
  };
}

function collectNestedIds(
  root: import("./types").AssemblyInstance
): Array<{ inst: typeof root; path: string[] }> {
  const result: Array<{ inst: typeof root; path: string[] }> = [{ inst: root, path: [] }];
  for (const child of root.nested_instances ?? []) {
    for (const entry of collectNestedIds(child)) {
      result.push({ inst: entry.inst, path: [child.slot_key ?? child.id, ...entry.path] });
    }
  }
  return result;
}

export function makeSelectionRef(scene: Scene, nodeId: string | null): SelectionRef | null {
  if (!nodeId) return null;
  const node = scene.nodes.find((n) => n.id === nodeId);
  if (!node) return null;
  if (!node.assembly) return { node_id: nodeId };
  for (const top of scene.assembly_instances) {
    for (const entry of collectNestedIds(top)) {
      if (entry.inst.id === node.assembly.instance_id) {
        return {
          top_instance_id: top.id,
          path: entry.path,
          template_id: node.assembly.template_id,
          node_id: nodeId,
        };
      }
    }
  }
  return { node_id: nodeId };
}

export function resolveSelectionRef(
  scene: Scene,
  ref: SelectionRef | null | undefined
): string | null {
  if (!ref) return null;
  if (ref.node_id && scene.nodes.some((n) => n.id === ref.node_id)) return ref.node_id;
  if (!ref.top_instance_id || !ref.template_id) return null;
  const top = scene.assembly_instances.find((item) => item.id === ref.top_instance_id);
  if (!top) return null;
  let current: typeof top | undefined = top;
  for (const key of ref.path ?? []) {
    current = current.nested_instances?.find(
      (item) => item.slot_key === key || item.id === key
    );
    if (!current) return null;
  }
  return current.node_map[ref.template_id] ?? null;
}

export type { AssemblyUpdatePreview };

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
  assemblyEditMode: "override" | "template";

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
  reparent: (parentId: string | null, keepWorld: boolean, targetOverride?: string | null) => Promise<void>;
  duplicate: () => Promise<void>;
  remove: () => Promise<void>;
  updateTransform: (
    patch: Partial<{ position: Vec3; rotationEuler: Vec3; scale: Vec3 }>,
    mode?: "instance" | "override" | "template"
  ) => Promise<void>;
  createAssembly: (name?: string) => Promise<void>;
  instantiateAssembly: (assemblyId: string) => Promise<void>;
  clearOverride: () => Promise<void>;
  detachAssembly: () => Promise<void>;
  deleteAssemblyDefinition: () => Promise<void>;
  addNestedSlot: (childAssemblyId: string) => Promise<void>;
  fetchUpdatePreview: (assemblyId?: string | null) => Promise<AssemblyUpdatePreview[]>;
  publishRelease: (name?: string) => Promise<void>;
  openRelease: (releaseId: string) => Promise<void>;
  deriveRelease: (releaseId: string, upgrades: Record<string, number>) => Promise<void>;
  fetchDerivePreview: (
    releaseId: string,
    upgrades: Record<string, number>
  ) => Promise<ReleaseDerivePreview>;
  fetchBatchPreview: (
    releaseId: string,
    instanceIds: string[],
    instanceTargets: Record<string, Record<string, number>>
  ) => Promise<ReleaseBatchPreview>;
  confirmBatchUpgrade: (
    releaseId: string,
    instanceIds: string[],
    instanceTargets: Record<string, Record<string, number>>,
    batchName?: string
  ) => Promise<void>;
  withdrawBatch: (batchId: string) => Promise<void>;
  fetchBatchStatus: (releaseId: string) => Promise<ReleaseBatchStatus>;
  applyAssemblyUpdate: (
    assemblyId: string,
    choices: {
      instanceIds?: string[];
      overrides?: Record<string, "follow" | "keep">;
      dropRemoved?: boolean;
    }
  ) => Promise<void>;
  setAssemblyEditMode: (mode: "override" | "template") => void;

  refreshWorld: () => Promise<void>;
  eulerOfSelected: () => Vec3 | null;
  pendingUpdates: AssemblyUpdatePreview[];
  setPendingUpdates: (items: AssemblyUpdatePreview[]) => void;
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
      const { scene: returned } = await promise;
      const scene = withAssemblyCollections(returned);
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
    scene: { version: 1, nodes: [], root_ids: [], assembly_defs: [], assembly_instances: [] },
    selectedId: null,
    world: [],
    past: [],
    future: [],
    busy: null,
    error: null,
    dirty: false,
    assemblyEditMode: "override",
    pendingUpdates: [],

    async init() {
      try {
        const list = await api.listScenes().catch(() => ({ scenes: [] }));
        if (list.scenes.length > 0) {
          await get().loadScene(list.scenes[0].scene_id);
        } else {
          await get().newScene();
        }
      } catch (err) {
        // 读取失败绝不把现场清空：保留当前场景（可能为空骨架）并给出可解释错误，
        // 用户仍可在界面上重试打开或新建，已保存内容不会被空场景覆盖保存。
        set({ busy: null, error: "场景读取失败：" + (err as Error).message });
      }
    },

    async newScene() {
      const { scene_id, scene: created } = await api.createScene();
      const scene = withAssemblyCollections(created);
      set({
        sceneId: scene_id,
        scene,
        past: [],
        future: [],
        selectedId: null,
        world: [],
        dirty: false,
        error: null,
        assemblyEditMode: "override",
      });
    },

    async loadScene(id) {
      const previous = get();
      set({ busy: "加载中…", error: null });
      try {
        const { scene: loaded } = await api.loadScene(id);
        const scene = withAssemblyCollections(loaded);
        const selectedId = resolveSelectionRef(scene, scene.selection ?? null);
        set({
          sceneId: id,
          scene,
          past: [],
          future: [],
          selectedId,
          dirty: false,
          error: null,
          busy: null,
          assemblyEditMode: "override",
          pendingUpdates: [],
        });
        await get().refreshWorld();
      } catch (err) {
        // 保留原选择与现场，仅展示错误；切换下拉框的尝试不覆盖任何已保存文档。
        set({
          busy: null,
          error: `场景「${id}」读取失败：${(err as Error).message}（已保留当前现场，未覆盖保存内容）`,
          sceneId: previous.sceneId,
          selectedId: previous.selectedId,
        });
      }
    },

    async save() {
      const { sceneId, scene } = get();
      if (!sceneId) return;
      set({ busy: "保存中…" });
      try {
        const selection = makeSelectionRef(scene, get().selectedId);
        await api.saveScene(sceneId, { ...scene, selection });
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
        selectedId: previous.nodes.some((n) => n.id === get().selectedId)
          ? get().selectedId
          : null,
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
        selectedId: next.nodes.some((n) => n.id === get().selectedId)
          ? get().selectedId
          : null,
      });
      void get().refreshWorld();
    },

    select(id) {
      const scene = get().scene;
      const nextScene = { ...scene, selection: makeSelectionRef(scene, id) };
      set({ selectedId: id, scene: nextScene, dirty: get().dirty || false });
    },

    setPendingUpdates(items) {
      set({ pendingUpdates: items });
    },

    setAssemblyEditMode(mode) {
      set({ assemblyEditMode: mode });
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

    async reparent(parentId, keepWorld, targetOverride?: string | null) {
      const { scene, selectedId } = get();
      if (!selectedId) return;
      const dragged = nodeIndex(scene).get(selectedId);
      const targetId = targetOverride ?? parentId;
      const target = targetId ? nodeIndex(scene).get(targetId) : undefined;
      if (
        get().assemblyEditMode === "template" &&
        dragged?.assembly &&
        target?.assembly &&
        dragged.assembly.instance_id === target.assembly.instance_id
      ) {
        const binding = dragged.assembly;
        const result = await api.assemblyTemplateReparent(
          scene,
          selectedId,
          targetId,
          keepWorld
        );
        const next = withAssemblyCollections(result.scene);
        await commit(
          Promise.resolve({ scene: next }),
          selectedId
        );
      } else {
        if (dragged?.assembly && target?.assembly && dragged.assembly.instance_id === target.assembly.instance_id) {
          set({ error: "当前是实例覆盖视角；切到检查器的修改原件模式后才能调整原件层级。" });
          return;
        }
        await commit(api.reparent(scene, selectedId, parentId, keepWorld));
      }
    },

    async duplicate() {
      const { scene, selectedId } = get();
      if (!selectedId) return;
      await commit(api.duplicate(scene, selectedId));
    },

    async remove() {
      const { scene, selectedId } = get();
      if (!selectedId) return;
      const next = await api.delete(scene, selectedId);
      set({ selectedId: null });
      await commit(Promise.resolve(next));
    },

    async updateTransform(patch, mode = "instance") {
      const { scene, selectedId } = get();
      if (!selectedId) return;
      const node = nodeIndex(scene).get(selectedId);
      if (!node) return;
      const body: Parameters<typeof api.transform>[2] = {};
      if (patch.position) body.position = patch.position;
      if (patch.rotationEuler) body.rotation_euler = patch.rotationEuler;
      if (patch.scale) body.scale = patch.scale;
      if (!node.assembly) {
        await commit(api.transform(scene, selectedId, body));
      } else if (mode === "override") {
        await commit(api.assemblyOverride(scene, selectedId, body));
      } else if (mode === "template") {
        const binding = node.assembly;
        const result = await api.assemblyTemplateTransform(scene, selectedId, body);
        const next = withAssemblyCollections(result.scene);
        await commit(
          Promise.resolve({ scene: next }),
          selectedId
        );
      } else {
        await commit(api.assemblyTransform(scene, selectedId, body));
      }
    },

    async createAssembly(name) {
      const { scene, selectedId } = get();
      if (!selectedId) return;
      const result = await api.createAssembly(scene, selectedId, name);
      const beforeIds = new Set(scene.assembly_instances.map((item) => item.id));
      const next = withAssemblyCollections(result.scene);
      const created = next.assembly_instances.find((item) => !beforeIds.has(item.id));
      await commit(Promise.resolve({ scene: next }), created?.node_map.__root__);
    },

    async instantiateAssembly(assemblyId) {
      const { scene, selectedId } = get();
      const selected = selectedId ? nodeIndex(scene).get(selectedId) : undefined;
      const parentId = selected?.type === "group" && !selected.assembly ? selected.id : null;
      const beforeIds = new Set(scene.assembly_instances.map((item) => item.id));
      const result = await api.instantiateAssembly(scene, assemblyId, parentId, [0, 0, 0]);
      const next = withAssemblyCollections(result.scene);
      const created = next.assembly_instances.find((item) => !beforeIds.has(item.id));
      await commit(Promise.resolve({ scene: next }), created?.node_map.__root__);
    },

    async clearOverride() {
      const { scene, selectedId } = get();
      if (!selectedId) return;
      await commit(api.clearAssemblyOverride(scene, selectedId));
    },

    async detachAssembly() {
      const { scene, selectedId } = get();
      if (!selectedId) return;
      await commit(api.detachAssembly(scene, selectedId));
    },

    async deleteAssemblyDefinition() {
      const { scene, selectedId } = get();
      const node = selectedId ? nodeIndex(scene).get(selectedId) : undefined;
      if (!node?.assembly) return;
      set({ selectedId: null });
      await commit(
        api.deleteAssemblyDefinition(scene, node.assembly.assembly_id)
      );
    },

    async addNestedSlot(childAssemblyId) {
      const { scene, selectedId, assemblyEditMode } = get();
      const node = selectedId ? nodeIndex(scene).get(selectedId) : undefined;
      if (!node?.assembly || assemblyEditMode !== "template") {
        set({
          error: "请在「修改原件」模式下选中外层原件内的父部件，再放入嵌套装配件。",
        });
        return;
      }
      const binding = node.assembly;
      const definition = scene.assembly_defs.find((d) => d.id === binding.assembly_id);
      if (!definition) return;
      await commit(
        api.addAssemblySlot(
          scene,
          binding.assembly_id,
          binding.template_id,
          childAssemblyId
        )
      );
    },

    async fetchUpdatePreview(assemblyId = null) {
      const { scene } = get();
      const { updates } = await api.assemblyUpdatePreview(scene, assemblyId);
      set({ pendingUpdates: updates });
      return updates;
    },

    async publishRelease(name) {
      const { scene } = get();
      await commit(api.publishRelease(scene, name));
    },

    async openRelease(releaseId) {
      const { scene } = get();
      await commit(api.openRelease(scene, releaseId));
    },

    async deriveRelease(releaseId, upgrades) {
      const { scene } = get();
      await commit(api.deriveRelease(scene, releaseId, upgrades));
    },

    async fetchDerivePreview(releaseId, upgrades) {
      const { scene } = get();
      return api.releaseDerivePreview(scene, releaseId, upgrades);
    },

    async fetchBatchPreview(releaseId, instanceIds, instanceTargets) {
      const { scene } = get();
      return api.releaseBatchPreview(scene, releaseId, instanceIds, instanceTargets);
    },

    async confirmBatchUpgrade(releaseId, instanceIds, instanceTargets, batchName) {
      const { scene } = get();
      await commit(
        api.releaseBatchConfirm(scene, releaseId, instanceIds, instanceTargets, batchName)
      );
    },

    async withdrawBatch(batchId) {
      const { scene } = get();
      await commit(api.releaseBatchWithdraw(scene, batchId));
    },

    async fetchBatchStatus(releaseId) {
      const { scene } = get();
      return api.releaseBatchStatus(scene, releaseId);
    },

    async applyAssemblyUpdate(assemblyId, choices) {
      const { scene } = get();
      const result = await api.assemblyUpdateApply(scene, {
        assembly_id: assemblyId,
        instance_ids: choices.instanceIds,
        overrides: choices.overrides,
        drop_removed: choices.dropRemoved,
      });
      await commit(Promise.resolve(result));
      set({ pendingUpdates: get().pendingUpdates.filter((item) => item.assembly_id !== assemblyId) });
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

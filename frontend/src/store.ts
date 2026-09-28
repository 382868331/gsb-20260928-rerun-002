import { create } from "zustand";
import type { SceneDoc, SceneNode, NodeType } from "./types";
import * as ops from "./sceneOps";
import { api } from "./api";

const HISTORY_LIMIT = 100;

interface LiveEdit {
  before: SceneDoc;
  label: string;
}

interface State {
  sceneId: string;
  doc: SceneDoc;
  past: SceneDoc[];
  future: SceneDoc[];
  pastSel: string[][];
  futureSel: string[][];
  selectedIds: string[];
  preserveWorld: boolean;
  dirty: boolean;
  saving: boolean;
  lastError: string | null;
  savedLabel: string | null;
  liveEdit: LiveEdit | null;

  setScene: (sceneId: string, doc: SceneDoc) => void;
  commit: (label: string, mutate: (draft: SceneDoc) => Record<string, unknown> | void) => void;
  undo: () => void;
  redo: () => void;
  selectOnly: (id: string | null) => void;
  toggleSelection: (id: string) => void;
  setPreserveWorld: (v: boolean) => void;

  addObject: (type: NodeType, parentId?: string | null) => void;
  addEmptyGroup: () => void;
  reparent: (id: string, parentId: string | null, index?: number) => void;
  groupSelected: () => void;
  duplicate: (id: string) => void;
  remove: (id: string) => void;
  updateNodeImmediate: (id: string, patch: Partial<Pick<SceneNode, "name" | "position" | "rotation" | "scale">>, label?: string) => void;
  beginLiveEdit: (label: string) => void;
  liveUpdate: (id: string, patch: Partial<Pick<SceneNode, "position" | "rotation" | "scale">>) => void;
  endLiveEdit: () => void;
  save: () => Promise<void>;
  reload: () => Promise<void>;
  newSceneRemote: (id: string) => Promise<void>;
  dismissError: () => void;
}

const cloneDoc = (doc: SceneDoc): SceneDoc => structuredClone(doc);

export const useStore = create<State>((set, get) => {
  const guard = (fn: () => void) => {
    try {
      fn();
    } catch (err) {
      const message = err instanceof ops.SceneError ? err.message : String(err);
      set({ lastError: message });
    }
  };

  const commit = (label: string, mutate: (draft: SceneDoc) => Record<string, unknown> | void) => guard(() => {
    // IMPORTANT: mutate() must run outside the setState updater so it can
    // read live state via get() and throw (guard) with normal semantics.
    const base = get().doc;
    const draft = cloneDoc(base);
    const extra = mutate(draft) ?? {};
    set((prev) => ({
      ...extra,
      doc: draft,
      past: [...prev.past, prev.doc].slice(-HISTORY_LIMIT),
      pastSel: [...prev.pastSel, prev.selectedIds].slice(-HISTORY_LIMIT),
      future: [],
      futureSel: [],
      dirty: true,
      lastError: null,
    }));
    void label;
  });

  const applyNodePatch = (draft: SceneDoc, id: string,
                          patch: Partial<Pick<SceneNode, "name" | "position" | "rotation" | "scale">>) => {
    const node = draft.nodes[id];
    if (!node) return;
    if (patch.name !== undefined) node.name = patch.name;
    if (patch.position) ops.updateTransform(draft, id, { position: [...patch.position] });
    if (patch.rotation) ops.updateTransform(draft, id, { rotation: [...patch.rotation] });
    if (patch.scale) ops.updateTransform(draft, id, { scale: [...patch.scale] });
  };

  return {
    sceneId: "default",
    doc: ops.newScene(),
    past: [],
    future: [],
    pastSel: [],
    futureSel: [],
    selectedIds: [],
    preserveWorld: true,
    dirty: false,
    saving: false,
    lastError: null,
    savedLabel: null,
    liveEdit: null,

    setScene: (sceneId, doc) => set({
      sceneId, doc, past: [], future: [], pastSel: [], futureSel: [], selectedIds: [], dirty: false,
      lastError: null, savedLabel: `已载入场景 ${sceneId}`, liveEdit: null,
    }),

    commit,

    undo: () => {
      const { past, future, doc, pastSel, futureSel, selectedIds } = get();
      if (past.length === 0) return;
      const previous = past[past.length - 1];
      const previousSel = pastSel[pastSel.length - 1] ?? [];
      const validSel = previousSel.filter((id) => id in previous.nodes);
      set({
        past: past.slice(0, -1), pastSel: pastSel.slice(0, -1),
        future: [doc, ...future], futureSel: [selectedIds, ...futureSel],
        doc: previous, selectedIds: validSel, dirty: true,
      });
    },

    redo: () => {
      const { past, future, doc, pastSel, futureSel, selectedIds } = get();
      if (future.length === 0) return;
      const next = future[0];
      const nextSelRaw = futureSel[0] ?? [];
      const validSel = nextSelRaw.filter((id) => id in next.nodes);
      set({
        past: [...past, doc], pastSel: [...pastSel, selectedIds],
        future: future.slice(1), futureSel: futureSel.slice(1),
        doc: next, selectedIds: validSel, dirty: true,
      });
    },

    selectOnly: (id) => set({ selectedIds: id ? [id] : [] }),
    toggleSelection: (id) => set((s) => ({
      selectedIds: s.selectedIds.includes(id)
        ? s.selectedIds.filter((x) => x !== id)
        : [...s.selectedIds, id],
    })),
    setPreserveWorld: (v) => set({ preserveWorld: v }),

    addObject: (type, parentId) => commit(`添加${type}`, (draft) => {
      const target = parentId === undefined ? get().selectedIds[0] ?? null : parentId;
      const node = ops.makeNode(type);
      ops.addNode(draft, node, target);
      return { selectedIds: [node.id] };
    }),

    addEmptyGroup: () => guard(() => commit("添加空组", (draft) => {
      const node = ops.makeNode("group");
      ops.addNode(draft, node, null);
      return { selectedIds: [node.id] };
    })),

    reparent: (id, parentId, index) => guard(() => commit("移动到新组", (draft) => {
      ops.reparent(draft, id, parentId, get().preserveWorld, index);
    })),

    groupSelected: () => guard(() => {
      const ids = get().selectedIds;
      if (ids.length === 0) return;
      commit("成组", (draft) => {
        const gid = ops.groupNodes(draft, ids);
        return { selectedIds: [gid] };
      });
    }),

    duplicate: (id) => guard(() => commit("复制组", (draft) => {
      const newId = ops.duplicateSubtree(draft, id);
      return { selectedIds: [newId] };
    })),

    remove: (id) => guard(() => commit("删除", (draft) => {
      ops.deleteSubtree(draft, id);
      return { selectedIds: get().selectedIds.filter((x) => x !== id && x in draft.nodes) };
    })),

    updateNodeImmediate: (id, patch, _label) => commit(_label ?? "调整变换", (draft) => {
      applyNodePatch(draft, id, patch);
    }),

    beginLiveEdit: (label) => {
      if (get().liveEdit) return;
      set({ liveEdit: { before: cloneDoc(get().doc), label } });
    },

    liveUpdate: (id, patch) => {
      if (!get().liveEdit) return;
      const draft = cloneDoc(get().doc);
      applyNodePatch(draft, id, patch);
      set({ doc: draft, dirty: true });
    },

    endLiveEdit: () => {
      const { liveEdit, doc } = get();
      if (!liveEdit) return;
      set((s) => ({
        liveEdit: null,
        past: [...s.past, liveEdit.before].slice(-HISTORY_LIMIT),
        future: [],
      }));
      void doc;
    },

    save: async () => {
      set({ saving: true, lastError: null });
      try {
        await api.save(get().sceneId, get().doc);
        set({ dirty: false, saving: false, savedLabel: `已保存 ${new Date().toLocaleTimeString()}` });
      } catch (err) {
        set({ saving: false, lastError: err instanceof Error ? err.message : String(err) });
      }
    },

    reload: async () => {
      try {
        const { doc } = await api.get(get().sceneId);
        get().setScene(get().sceneId, doc);
      } catch (err) {
        set({ lastError: err instanceof Error ? err.message : String(err) });
      }
    },

    newSceneRemote: async (id) => {
      try {
        await api.create(id);
        const { doc } = await api.get(id);
        get().setScene(id, doc);
      } catch (err) {
        set({ lastError: err instanceof Error ? err.message : String(err) });
      }
    },

    dismissError: () => set({ lastError: null }),
  };
});

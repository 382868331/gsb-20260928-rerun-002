import type {
  AssemblyUpdatePreview,
  ReleaseBatchPreview,
  ReleaseBatchStatus,
  ReleaseDerivePreview,
  Scene,
  SelectionRef,
  WorldInfo,
} from "./types";

const BASE = "/api";

async function request<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "请求失败: " + res.status);
  }
  return res.json();
}

function put<T>(path: string, body: unknown): Promise<T> {
  return fetch(BASE + path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(async (res) => {
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "保存失败");
    return res.json();
  });
}

export interface SceneMeta {
  scene_id: string;
  node_count: number;
  updated_at: number;
}

export const api = {
  listScenes: () => request<{ scenes: SceneMeta[] }>("/scenes"),
  createScene: () => request<{ scene_id: string; scene: Scene }>("/scenes", {}),
  loadScene: (id: string) =>
    request<{ scene_id: string; scene: Scene }>(`/scenes/${id}`),
  saveScene: (id: string, scene: Scene) =>
    put<{ saved: boolean }>(`/scenes/${id}`, { scene }),
  addNode: (scene: Scene, type: string, parent_id: string | null) =>
    request<{ scene: Scene }>("/ops/add-node", { scene, type, parent_id }),
  group: (scene: Scene, child_ids: string[]) =>
    request<{ scene: Scene }>("/ops/group", { scene, child_ids }),
  reparent: (
    scene: Scene,
    node_id: string,
    new_parent_id: string | null,
    keep_world_transform: boolean
  ) =>
    request<{ scene: Scene }>("/ops/reparent", {
      scene,
      node_id,
      new_parent_id,
      keep_world_transform,
    }),
  duplicate: (scene: Scene, node_id: string) =>
    request<{ scene: Scene }>("/ops/duplicate", { scene, node_id }),
  delete: (scene: Scene, node_id: string) =>
    request<{ scene: Scene }>("/ops/delete", { scene, node_id }),
  transform: (
    scene: Scene,
    node_id: string,
    patch: { position?: Vec3; rotation_euler?: Vec3; scale?: Vec3 }
  ) => request<{ scene: Scene }>("/ops/transform", { scene, node_id, ...patch }),
  worldTransforms: (scene: Scene) =>
    request<{ world: WorldInfo[] }>("/ops/world-transforms", { scene }),
  createAssembly: (scene: Scene, node_id: string, name?: string) =>
    request<{ scene: Scene; root_id?: string }>("/ops/assembly/create", { scene, node_id, name }),
  instantiateAssembly: (
    scene: Scene,
    assembly_id: string,
    parent_id: string | null = null,
    position?: Vec3
  ) =>
    request<{ scene: Scene; root_id?: string }>("/ops/assembly/instantiate", {
      scene,
      assembly_id,
      parent_id,
      position,
    }),
  assemblyTransform: (
    scene: Scene,
    node_id: string,
    patch: { position?: Vec3; rotation_euler?: Vec3; scale?: Vec3 }
  ) =>
    request<{ scene: Scene }>("/ops/assembly/transform", { scene, node_id, ...patch }),
  assemblyOverride: (
    scene: Scene,
    node_id: string,
    patch: { position?: Vec3; rotation_euler?: Vec3; scale?: Vec3 }
  ) =>
    request<{ scene: Scene }>("/ops/assembly/override", { scene, node_id, ...patch }),
  clearAssemblyOverride: (scene: Scene, node_id: string) =>
    request<{ scene: Scene }>("/ops/assembly/override/clear", { scene, node_id }),
  assemblyTemplateTransform: (
    scene: Scene,
    node_id: string,
    patch: { position?: Vec3; rotation_euler?: Vec3; scale?: Vec3 }
  ) =>
    request<{ scene: Scene }>("/ops/assembly/template-transform", { scene, node_id, ...patch }),
  assemblyTemplateReparent: (
    scene: Scene,
    node_id: string,
    new_parent_node_id: string | null,
    keep_world_transform: boolean
  ) =>
    request<{ scene: Scene }>("/ops/assembly/template-reparent", {
      scene,
      node_id,
      new_parent_node_id,
      keep_world_transform,
    }),
  detachAssembly: (scene: Scene, node_id: string) =>
    request<{ scene: Scene }>("/ops/assembly/detach", { scene, node_id }),
  deleteAssemblyDefinition: (scene: Scene, assembly_id: string) =>
    request<{ scene: Scene }>("/ops/assembly/delete-definition", {
      scene,
      assembly_id,
    }),
  addAssemblySlot: (
    scene: Scene,
    parent_definition_id: string,
    parent_template_node_id: string,
    assembly_id: string,
    position?: Vec3
  ) =>
    request<{ scene: Scene }>("/ops/assembly/add-slot", {
      scene,
      parent_definition_id,
      parent_template_node_id,
      assembly_id,
      position,
    }),
  assemblyUpdatePreview: (scene: Scene, assembly_id?: string | null) =>
    request<{ updates: AssemblyUpdatePreview[] }>("/ops/assembly/update-preview", {
      scene,
      assembly_id: assembly_id ?? null,
    }),
  assemblyUpdateApply: (
    scene: Scene,
    payload: {
      assembly_id: string;
      instance_ids?: string[];
      overrides?: Record<string, "follow" | "keep">;
      drop_removed?: boolean;
    }
  ) =>
    request<{ scene: Scene }>("/ops/assembly/update-apply", {
      scene,
      ...payload,
    }),
  resolveSelection: (scene: Scene, selection: SelectionRef | null) =>
    request<{ node_id: string | null }>("/ops/selection", { scene, selection }),
  publishRelease: (scene: Scene, name?: string, note?: string) =>
    request<{ scene: Scene }>("/ops/release/publish", { scene, name, note }),
  openRelease: (scene: Scene, release_id: string) =>
    request<{ scene: Scene }>("/ops/release/open", { scene, release_id }),
  deriveRelease: (scene: Scene, release_id: string, upgrades: Record<string, number>) =>
    request<{ scene: Scene }>("/ops/release/derive", { scene, release_id, upgrades }),
  releaseDerivePreview: (scene: Scene, release_id: string, upgrades: Record<string, number>) =>
    request<ReleaseDerivePreview>("/ops/release/derive-preview", {
      scene,
      release_id,
      upgrades,
    }),
  releaseBatchPreview: (
    scene: Scene,
    releaseId: string,
    instanceIds: string[],
    instanceTargets: Record<string, Record<string, number>>
  ) =>
    request<ReleaseBatchPreview>("/ops/release/batch-preview", {
      scene,
      release_id: releaseId,
      instance_ids: instanceIds,
      instance_targets: instanceTargets,
    }),
  releaseBatchConfirm: (
    scene: Scene,
    releaseId: string,
    instanceIds: string[],
    instanceTargets: Record<string, Record<string, number>>,
    batchName?: string
  ) =>
    request<{ scene: Scene }>("/ops/release/batch-confirm", {
      scene,
      release_id: releaseId,
      instance_ids: instanceIds,
      instance_targets: instanceTargets,
      batch_name: batchName ?? null,
    }),
  releaseBatchWithdraw: (scene: Scene, batchId: string) =>
    request<{ scene: Scene }>("/ops/release/batch-withdraw", {
      scene,
      batch_id: batchId,
    }),
  releaseBatchStatus: (scene: Scene, releaseId: string) =>
    request<ReleaseBatchStatus>("/ops/release/batch-status", {
      scene,
      release_id: releaseId,
    }),
};

type Vec3 = [number, number, number];

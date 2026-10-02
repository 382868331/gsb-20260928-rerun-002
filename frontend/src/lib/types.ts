export type Vec3 = [number, number, number];
export type Quat = [number, number, number, number];
export type NodeType =
  | "group"
  | "cube"
  | "sphere"
  | "cylinder"
  | "cone"
  | "plane";

export interface Transform {
  position: Vec3;
  rotation: Quat;
  scale: Vec3;
}

export interface SceneNode {
  id: string;
  name: string;
  type: NodeType;
  parent_id: string | null;
  children: string[];
  transform: Transform;
  assembly?: AssemblyBinding | null;
}

export interface Scene {
  version: number;
  nodes: SceneNode[];
  root_ids: string[];
  assembly_defs: AssemblyDefinition[];
  assembly_instances: AssemblyInstance[];
  assembly_history: AssemblyDefinition[];
  releases: ReleaseSnapshot[];
  upgrade_batches: UpgradeBatch[];
  selection?: SelectionRef | null;
}

export interface BatchDecision {
  top_instance_id: string;
  path: string[];
  instance_name?: string;
  action: "keep" | "upgrade";
}

export interface BatchRollback {
  top_instance_id: string;
  path: string[];
  assembly_id: string;
  from_version: number;
  to_version: number;
  snapshot: unknown;
}

export interface UpgradeBatch {
  id: string;
  name: string;
  assembly_id: string;
  candidate_version: number;
  created_at: number;
  status: "open" | "confirmed" | "withdrawn";
  decisions: BatchDecision[];
  rollback: BatchRollback[];
  warnings: string[];
}

export interface BatchOverrideInfo {
  template_id: string;
  name: string;
  position: Vec3 | null;
  rotation: Quat | null;
  scale: Vec3 | null;
  template_position: Vec3 | null;
  template_scale: Vec3 | null;
  removed_in_candidate: boolean;
}

export interface BatchPreviewItem extends ReleasePreviewItem {
  top_instance_id: string;
  path: string[];
  overrides: BatchOverrideInfo[];
  selection_ref_impact: { lost_refs: string[]; top_instance_id: string; path: string[] };
  up_to_date: boolean;
}

export interface BatchUpgradePreview {
  items: BatchPreviewItem[];
  missing: {
    top_instance_id: string;
    path: string[];
    instance_id: string;
    instance_name: string;
    assembly_id: string;
    assembly_name: string;
    version: number;
    reason: string;
  }[];
}

export interface AssemblyBinding {
  assembly_id: string;
  instance_id: string;
  template_id: string;
}

export interface AssemblyOverride extends Partial<Transform> {}

export interface AssemblyDefinition {
  id: string;
  name: string;
  version: number;
  root_ids: string[];
  nodes: SceneNode[];
  slots?: AssemblySlot[];
}

export interface AssemblyInstance {
  id: string;
  name: string;
  assembly_id: string;
  assembly_version: number;
  parent_id: string | null;
  transform: Transform;
  node_map: Record<string, string>;
  overrides: Record<string, AssemblyOverride>;
  pinned_version: number;
  nested_instances?: AssemblyInstance[];
  detached_slots?: Record<string, DetachedSlot>;
  parent_instance_id?: string | null;
  slot_key?: string | null;
  derived_from?: string | null;
  source_instance_id?: string | null;
}

export interface ReleaseInstanceState {
  instance_id: string;
  slot_key?: string | null;
  parent_id?: string | null;
  assembly_id: string;
  pinned_version: number;
  name: string;
  transform: Transform;
  overrides: Record<string, AssemblyOverride>;
  detached_nodes?: Record<string, SceneNode[]>;
  nested?: ReleaseInstanceState[];
}

export interface ReleaseSnapshot {
  id: string;
  name: string;
  note?: string | null;
  created_at: number;
  definitions: AssemblyDefinition[];
  instances: ReleaseInstanceState[];
}

export interface ReleasePreviewItem {
  instance_id: string;
  instance_name: string;
  assembly_id: string;
  assembly_name: string;
  from_version: number;
  to_version: number;
  changed: AssemblyChangeItem[];
  removed: AssemblyChangeItem[];
  added: AssemblyChangeItem[];
  slots_removed: SlotChangeItem[];
  slots_added: SlotChangeItem[];
}

export interface ReleaseDerivePreview {
  items: ReleasePreviewItem[];
  kept: { assembly_id: string; assembly_name: string; version: number }[];
  missing: {
    instance_id: string;
    instance_name: string;
    assembly_id: string;
    assembly_name: string;
    version: number;
  }[];
}

export interface SelectionRef {
  top_instance_id?: string | null;
  path?: string[];
  template_id?: string | null;
  node_id?: string | null;
}

export interface AssemblyChangeItem {
  template_id: string;
  name: string;
  path: string;
  has_local_override?: boolean;
  live_node_id?: string | null;
}

export interface SlotChangeItem {
  slot_key: string;
  assembly_id: string;
  name: string;
  detached?: boolean;
}

export interface AssemblyUpdatePreview {
  assembly_id: string;
  assembly_name: string;
  instance_id: string;
  top_instance_id: string;
  instance_name: string;
  from_version: number;
  to_version: number;
  path: string[];
  changed: AssemblyChangeItem[];
  removed: AssemblyChangeItem[];
  added: AssemblyChangeItem[];
  slots_removed: SlotChangeItem[];
  slots_added: SlotChangeItem[];
}

export interface WorldInfo {
  id: string;
  name: string;
  type: NodeType;
  parent_id: string | null;
  position: Vec3;
  quaternion: Quat;
  rotation_euler: Vec3;
  scale: Vec3;
  matrix: number[];
  assembly?: AssemblyBinding | null;
}

export const PRIMITIVE_TYPES: NodeType[] = [
  "cube",
  "sphere",
  "cylinder",
  "cone",
  "plane",
];

export interface AssemblySlot {
  key: string;
  assembly_id: string;
  pinned_version: number;
  parent_template_id: string;
  transform: Transform;
}

export interface DetachedSlot {
  node_ids: string[];
}

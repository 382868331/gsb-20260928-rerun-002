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
  assembly_history?: AssemblyDefinition[];
  releases?: AssemblyRelease[];
  selection?: SelectionRef | null;
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
  source_release_id?: string | null;
}

export interface ReleasePin {
  assembly_id: string;
  version: number;
}

export interface AssemblyRelease {
  id: string;
  name: string;
  seq: number;
  source_release_id?: string | null;
  root_assembly_id: string;
  root_name: string;
  pins: Record<string, ReleasePin>;
  overrides: Record<string, Record<string, AssemblyOverride>>;
  transform: Transform;
  upgrades: Record<string, [number, number]>;
}

export interface DerivePreviewItem {
  path: string;
  label: string;
  assembly_id: string;
  assembly_name: string;
  from_version: number;
  to_version: number;
  upstream_changed: AssemblyChangeItem[];
  upstream_added: AssemblyChangeItem[];
  parts_removed: AssemblyChangeItem[];
  override_impacts: { template_id: string; path: string; part_removed: boolean }[];
  slots_removed: SlotChangeItem[];
  slots_added: SlotChangeItem[];
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

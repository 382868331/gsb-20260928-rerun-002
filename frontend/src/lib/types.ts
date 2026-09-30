export type Vec3 = [number, number, number];
export type Quat = [number, number, number, number];
export type NodeType =
  | "group"
  | "cube"
  | "sphere"
  | "cylinder"
  | "cone"
  | "plane"
  | "assembly";

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
  nested_assembly_id?: string | null;
}

export interface Scene {
  version: number;
  nodes: SceneNode[];
  root_ids: string[];
  assembly_defs: AssemblyDefinition[];
  assembly_instances: AssemblyInstance[];
  selected_path?: string | null;
}

export interface AssemblyBinding {
  assembly_id: string;
  instance_id: string;
  template_id: string;
  nested_assembly_id?: string | null;
  child_instance_id?: string | null;
}

export interface AssemblyOverride extends Partial<Transform> {}

export interface AssemblyDefinition {
  id: string;
  name: string;
  version: number;
  root_ids: string[];
  nodes: SceneNode[];
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
  parent_instance_id?: string | null;
  host_template_id?: string | null;
  part_policies?: Record<string, string>;
  baseline_version: number;
  baseline_nodes: SceneNode[];
  baseline_root_ids: string[];
  detached?: boolean;
  detached_nodes?: SceneNode[];
  detached_root_ids?: string[];
}

export interface AssemblyChange {
  template_id: string;
  name: string;
  kind: "changed" | "added" | "removed";
  has_local_override: boolean;
  policy: "follow" | "keep";
}

export interface AssemblyPending {
  instance_id: string;
  name: string;
  assembly_id: string;
  assembly_name: string;
  from_version: number;
  to_version: number;
  root_node_id?: string;
  changes: AssemblyChange[];
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

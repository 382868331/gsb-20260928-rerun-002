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
  assembly?: AssemblyLink | null;
}

export type TransformOverride = "position" | "rotation" | "scale" | "name";

export interface AssemblyLink {
  assembly_id: string;
  instance_id: string;
  part_id: string;
  assembly_version: number;
  overrides: TransformOverride[];
}

export interface AssemblyNode {
  id: string;
  name: string;
  type: NodeType;
  children: string[];
  transform: Transform;
}

export interface AssemblyDefinition {
  id: string;
  name: string;
  version: number;
  root_id: string;
  nodes: AssemblyNode[];
}

export interface Scene {
  version: number;
  nodes: SceneNode[];
  root_ids: string[];
  assemblies: AssemblyDefinition[];
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
}

export const PRIMITIVE_TYPES: NodeType[] = [
  "cube",
  "sphere",
  "cylinder",
  "cone",
  "plane",
];

export type ObjectType = "cube" | "sphere" | "cylinder" | "plane" | "cone";
export type NodeType = ObjectType | "group";

export interface SceneNode {
  id: string;
  name: string;
  type: NodeType;
  parent: string | null;
  children: string[];
  position: [number, number, number];
  rotation: [number, number, number];
  scale: [number, number, number];
}

export interface SceneDoc {
  version: number;
  rootOrder: string[];
  nodes: Record<string, SceneNode>;
  activeCamera?: { position: [number, number, number]; target: [number, number, number] };
}

export interface WorldInfo {
  position: [number, number, number];
  rotation: [number, number, number];
  scale: [number, number, number];
  matrix: number[];
}

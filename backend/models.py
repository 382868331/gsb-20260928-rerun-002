"""可继续编辑的场景文档模型（持久化为 JSON，而非截图）。"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .transforms import quat_from_euler_xyz

Vec3 = List[float]
Quat = List[float]
NodeType = Literal["group", "cube", "sphere", "cylinder", "cone", "plane"]


class Transform(BaseModel):
    position: Vec3 = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: Quat = Field(default_factory=lambda: [0.0, 0.0, 0.0, 1.0])
    scale: Vec3 = Field(default_factory=lambda: [1.0, 1.0, 1.0])


class Node(BaseModel):
    id: str
    name: str
    type: NodeType
    parent_id: Optional[str] = None
    children: List[str] = Field(default_factory=list)
    transform: Transform = Field(default_factory=Transform)
    assembly: Optional["AssemblyLink"] = None


TransformOverride = Literal["position", "rotation", "scale", "name"]


class AssemblyLink(BaseModel):
    assembly_id: str
    instance_id: str
    part_id: str
    assembly_version: int
    overrides: List[TransformOverride] = Field(default_factory=list)


class AssemblyNode(BaseModel):
    id: str
    name: str
    type: NodeType
    children: List[str] = Field(default_factory=list)
    transform: Transform = Field(default_factory=Transform)


class AssemblyDefinition(BaseModel):
    id: str
    name: str
    version: int = 1
    root_id: str
    nodes: List[AssemblyNode] = Field(default_factory=list)


class Scene(BaseModel):
    version: int = 1
    nodes: List[Node] = Field(default_factory=list)
    root_ids: List[str] = Field(default_factory=list)
    assemblies: List[AssemblyDefinition] = Field(default_factory=list)

    def index(self) -> dict:
        return {node.id: node for node in self.nodes}


class AddNodeRequest(BaseModel):
    scene: Scene
    type: NodeType
    parent_id: Optional[str] = None
    name: Optional[str] = None
    position: Optional[Vec3] = None


class NameRequest(BaseModel):
    scene: Scene
    node_id: str
    name: str


class ReparentRequest(BaseModel):
    scene: Scene
    node_id: str
    new_parent_id: Optional[str] = None
    keep_world_transform: bool = True


class IdRequest(BaseModel):
    scene: Scene
    node_id: str


class TransformRequest(BaseModel):
    scene: Scene
    node_id: str
    position: Optional[Vec3] = None
    rotation_euler: Optional[Vec3] = None
    scale: Optional[Vec3] = None


class AssemblyCreateRequest(BaseModel):
    scene: Scene
    node_id: str
    name: Optional[str] = None


class AssemblyInstanceRequest(BaseModel):
    scene: Scene
    assembly_id: str
    parent_id: Optional[str] = None


class AssemblyIdRequest(BaseModel):
    scene: Scene
    node_id: str


class SceneId(BaseModel):
    scene_id: str


def transform_from_euler(position=None, euler=None, scale=None) -> Transform:
    return Transform(
        position=list(position) if position else [0.0, 0.0, 0.0],
        rotation=quat_from_euler_xyz(*(euler if euler else [0.0, 0.0, 0.0])),
        scale=list(scale) if scale else [1.0, 1.0, 1.0],
    )


Node.model_rebuild()

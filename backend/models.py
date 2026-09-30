"""可继续编辑的场景文档模型（持久化为 JSON，而非截图）。"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .transforms import quat_from_euler_xyz

Vec3 = List[float]
Quat = List[float]
NodeType = Literal["group", "cube", "sphere", "cylinder", "cone", "plane", "assembly"]


class Transform(BaseModel):
    position: Vec3 = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: Quat = Field(default_factory=lambda: [0.0, 0.0, 0.0, 1.0])
    scale: Vec3 = Field(default_factory=lambda: [1.0, 1.0, 1.0])


class AssemblyBinding(BaseModel):
    assembly_id: str
    instance_id: str
    template_id: str
    # 原件中该模板节点若是一个子装配件占位，则指向子装配件定义；
    # 场景中对应节点上记录这里面是哪个子实例（child_instance_id）。
    nested_assembly_id: Optional[str] = None
    child_instance_id: Optional[str] = None


class Node(BaseModel):
    id: str
    name: str
    type: NodeType
    parent_id: Optional[str] = None
    children: List[str] = Field(default_factory=list)
    transform: Transform = Field(default_factory=Transform)
    assembly: Optional[AssemblyBinding] = None
    # 仅用于装配件定义里的模板节点：该占位引用的子装配件
    nested_assembly_id: Optional[str] = None


class AssemblyOverride(BaseModel):
    position: Optional[Vec3] = None
    rotation: Optional[Quat] = None
    scale: Optional[Vec3] = None


class AssemblyDefinition(BaseModel):
    id: str
    name: str
    version: int = 1
    root_ids: List[str] = Field(default_factory=list)
    nodes: List[Node] = Field(default_factory=list)


class AssemblyInstance(BaseModel):
    id: str
    name: str
    assembly_id: str
    assembly_version: int
    parent_id: Optional[str] = None
    transform: Transform = Field(default_factory=Transform)
    node_map: dict[str, str] = Field(default_factory=dict)
    overrides: dict[str, AssemblyOverride] = Field(default_factory=dict)
    # 父实例（当本实例是某个装配件内部的子装配件时）与占位模板节点
    parent_instance_id: Optional[str] = None
    host_template_id: Optional[str] = None
    # 更新策略（选择式接收原件更新）：follow = 跟随原件；keep = 保留本实例现状
    part_policies: dict[str, str] = Field(default_factory=dict)
    # 选择性更新基线：版本低于定义版本时，保存当时的定义，供预览/应用更新使用
    baseline_version: int = 1
    baseline_nodes: List[Node] = Field(default_factory=list)
    baseline_root_ids: List[str] = Field(default_factory=list)
    # 脱离原件后烘焙的定义快照：此后不再跟随任何原件更新
    detached: bool = False
    detached_nodes: List[Node] = Field(default_factory=list)
    detached_root_ids: List[str] = Field(default_factory=list)


class Scene(BaseModel):
    version: int = 1
    nodes: List[Node] = Field(default_factory=list)
    root_ids: List[str] = Field(default_factory=list)
    assembly_defs: List[AssemblyDefinition] = Field(default_factory=list)
    assembly_instances: List[AssemblyInstance] = Field(default_factory=list)
    # 选中对象的稳定路径（保存/重开后保持选中）
    selected_path: Optional[str] = None

    def index(self) -> dict:
        return {node.id: node for node in self.nodes}


class AddNodeRequest(BaseModel):
    scene: Scene
    type: NodeType
    parent_id: Optional[str] = None
    name: Optional[str] = None
    position: Optional[Vec3] = None


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


class CreateAssemblyRequest(BaseModel):
    scene: Scene
    node_id: str
    name: Optional[str] = None


class InstantiateAssemblyRequest(BaseModel):
    scene: Scene
    assembly_id: str
    parent_id: Optional[str] = None
    position: Optional[Vec3] = None


class AssemblyTemplateReparentRequest(BaseModel):
    scene: Scene
    node_id: str
    new_parent_node_id: Optional[str] = None
    keep_world_transform: bool = True


class AssemblyUpdateApplyRequest(BaseModel):
    scene: Scene
    # 受影响实例 id -> {模板节点 id: "follow" | "keep"}
    choices: dict[str, dict[str, str]] = Field(default_factory=dict)


class SceneId(BaseModel):
    scene_id: str


def transform_from_euler(position=None, euler=None, scale=None) -> Transform:
    return Transform(
        position=list(position) if position else [0.0, 0.0, 0.0],
        rotation=quat_from_euler_xyz(*(euler if euler else [0.0, 0.0, 0.0])),
        scale=list(scale) if scale else [1.0, 1.0, 1.0],
    )

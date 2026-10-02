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


class AssemblyBinding(BaseModel):
    assembly_id: str
    instance_id: str
    template_id: str
    path: List[str] = Field(default_factory=list)


class Node(BaseModel):
    id: str
    name: str
    type: NodeType
    parent_id: Optional[str] = None
    children: List[str] = Field(default_factory=list)
    transform: Transform = Field(default_factory=Transform)
    assembly: Optional[AssemblyBinding] = None


class AssemblyOverride(BaseModel):
    position: Optional[Vec3] = None
    rotation: Optional[Quat] = None
    scale: Optional[Vec3] = None


class AssemblySlot(BaseModel):
    """原件中嵌套的另一个装配件的引用。"""

    key: str
    assembly_id: str
    pinned_version: int
    parent_template_id: str
    transform: Transform = Field(default_factory=Transform)


class DetachedSlot(BaseModel):
    """实例中已脱离原件的嵌套装配件所保留下来的节点子树。"""

    node_ids: List[str] = Field(default_factory=list)


class AssemblyDefinition(BaseModel):
    id: str
    name: str
    version: int = 1
    root_ids: List[str] = Field(default_factory=list)
    nodes: List[Node] = Field(default_factory=list)
    slots: List[AssemblySlot] = Field(default_factory=list)


class AssemblyInstance(BaseModel):
    id: str
    name: str
    assembly_id: str
    assembly_version: int
    parent_id: Optional[str] = None
    transform: Transform = Field(default_factory=Transform)
    node_map: dict[str, str] = Field(default_factory=dict)
    overrides: dict[str, AssemblyOverride] = Field(default_factory=dict)
    pinned_version: int = 1
    nested_instances: List["AssemblyInstance"] = Field(default_factory=list)
    detached_slots: dict[str, DetachedSlot] = Field(default_factory=dict)
    parent_instance_id: Optional[str] = None
    slot_key: Optional[str] = None
    # 派生来源：记录该实例由哪个发布版本 / 哪个实例派生而来，便于追溯
    derived_from: Optional[str] = None
    source_instance_id: Optional[str] = None


class ReleaseInstanceState(BaseModel):
    """发布时冻结的实例状态：钉住的版本、实例覆盖、脱离槽现场与嵌套层。"""

    instance_id: str
    slot_key: Optional[str] = None
    parent_id: Optional[str] = None
    assembly_id: str
    pinned_version: int
    name: str
    transform: Transform = Field(default_factory=Transform)
    overrides: dict[str, AssemblyOverride] = Field(default_factory=dict)
    detached_nodes: dict[str, List[Node]] = Field(default_factory=dict)
    nested: List["ReleaseInstanceState"] = Field(default_factory=list)


class ReleaseSnapshot(BaseModel):
    """可重开的发布版本：锁定各层子装配的具体版本与发布时的实例覆盖。"""

    id: str
    name: str
    note: Optional[str] = None
    created_at: float = 0.0
    definitions: List[AssemblyDefinition] = Field(default_factory=list)
    instances: List[ReleaseInstanceState] = Field(default_factory=list)


class BatchDecision(BaseModel):
    """批次内一个实例（按 顶层实例 + 槽路径 定位）的采用决定。"""

    top_instance_id: str
    path: List[str] = Field(default_factory=list)
    instance_name: str = ""
    action: Literal["keep", "upgrade"] = "keep"


class BatchRollback(BaseModel):
    """批次确认时记录的单实例升级前现场，用于撤回该批而不影响其他批次。

    snapshot 是与具体节点 id 无关的递归结构：
    {pinned_version, overrides, detached, children: {slot_key: snapshot}}。
    """

    top_instance_id: str
    path: List[str] = Field(default_factory=list)
    assembly_id: str
    from_version: int
    to_version: int
    snapshot: dict = Field(default_factory=dict)


class UpgradeBatch(BaseModel):
    """一次分批采用记录：同一发布总成的若干实例在本批中保留旧版或采用候选版。"""

    id: str
    name: str = ""
    assembly_id: str
    candidate_version: int
    created_at: float = 0.0
    status: Literal["open", "confirmed", "withdrawn"] = "open"
    decisions: List[BatchDecision] = Field(default_factory=list)
    rollback: List[BatchRollback] = Field(default_factory=list)
    # 撤回 / 继续时缺失版本而保留下来的实例及可解释原因
    warnings: List[str] = Field(default_factory=list)


class SelectionRef(BaseModel):
    """稳定的选中对象引用：刷新重生成节点 id 后仍能定位同一部件。"""

    top_instance_id: Optional[str] = None
    path: List[str] = Field(default_factory=list)
    template_id: Optional[str] = None
    node_id: Optional[str] = None


class Scene(BaseModel):
    version: int = 1
    nodes: List[Node] = Field(default_factory=list)
    root_ids: List[str] = Field(default_factory=list)
    assembly_defs: List[AssemblyDefinition] = Field(default_factory=list)
    assembly_instances: List[AssemblyInstance] = Field(default_factory=list)
    assembly_history: List[AssemblyDefinition] = Field(default_factory=list)
    releases: List[ReleaseSnapshot] = Field(default_factory=list)
    upgrade_batches: List[UpgradeBatch] = Field(default_factory=list)
    selection: Optional[SelectionRef] = None

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


class AssemblySlotRequest(BaseModel):
    scene: Scene
    parent_definition_id: str
    parent_template_node_id: str
    assembly_id: str
    position: Optional[Vec3] = None


class AssemblyUpdatePreviewRequest(BaseModel):
    scene: Scene
    assembly_id: Optional[str] = None


class AssemblyUpdateApplyRequest(BaseModel):
    scene: Scene
    assembly_id: str
    instance_ids: List[str] = Field(default_factory=list)
    # follow = 跟随原件丢弃覆盖；keep = 保留局部覆盖
    overrides: dict[str, Literal["follow", "keep"]] = Field(default_factory=dict)
    drop_removed: bool = False


class SelectionRequest(BaseModel):
    scene: Scene
    selection: Optional[SelectionRef] = None


class PublishReleaseRequest(BaseModel):
    scene: Scene
    name: Optional[str] = None
    note: Optional[str] = None


class ReleaseRequest(BaseModel):
    scene: Scene
    release_id: str


class DeriveReleaseRequest(BaseModel):
    scene: Scene
    release_id: str
    # {assembly_id: 目标版本}；未列出的装配件保持发布时钉住的旧版本
    upgrades: dict[str, int] = Field(default_factory=dict)


class BatchPreviewRequest(BaseModel):
    scene: Scene
    release_id: Optional[str] = None
    assembly_id: str
    candidate_version: int


class BatchCreateRequest(BaseModel):
    scene: Scene
    release_id: Optional[str] = None
    assembly_id: str
    candidate_version: int
    name: Optional[str] = None


class BatchDecideRequest(BaseModel):
    scene: Scene
    batch_id: str
    decisions: List[BatchDecision] = Field(default_factory=list)


class BatchIdRequest(BaseModel):
    scene: Scene
    batch_id: str


class SceneId(BaseModel):
    scene_id: str


def transform_from_euler(position=None, euler=None, scale=None) -> Transform:
    return Transform(
        position=list(position) if position else [0.0, 0.0, 0.0],
        rotation=quat_from_euler_xyz(*(euler if euler else [0.0, 0.0, 0.0])),
        scale=list(scale) if scale else [1.0, 1.0, 1.0],
    )


AssemblyInstance.model_rebuild()
ReleaseInstanceState.model_rebuild()
UpgradeBatch.model_rebuild()

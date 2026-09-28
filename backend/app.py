"""三维场景创作平台 HTTP API。

编辑类接口都是无状态的：请求体带上当前场景文档，后端执行操作后返回新文档，
由前端决定何时保存（保存的是可继续编辑的 JSON 场景，不是截图）。
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import scene_ops
from .models import (
    AddNodeRequest,
    IdRequest,
    ReparentRequest,
    Scene,
    TransformRequest,
)
from .storage import delete_scene, list_scenes, load_scene, save_scene

app = FastAPI(title="三维场景创作平台 API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SceneResponse(BaseModel):
    scene: Scene


class GroupRequest(BaseModel):
    scene: Scene
    child_ids: list[str]


class SaveRequest(BaseModel):
    scene: Scene


class CreateRequest(BaseModel):
    scene_id: str | None = None


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/scenes")
async def scenes_list():
    return {"scenes": list_scenes()}


@app.post("/api/scenes")
async def scenes_create(req: CreateRequest):
    scene_id = req.scene_id or uuid.uuid4().hex[:16]
    scene = Scene()
    save_scene(scene_id, scene)
    return {"scene_id": scene_id, "scene": scene}


@app.get("/api/scenes/{scene_id}")
async def scenes_get(scene_id: str):
    try:
        return {"scene_id": scene_id, "scene": load_scene(scene_id)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="场景不存在")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/scenes/{scene_id}")
async def scenes_save(scene_id: str, req: SaveRequest):
    save_scene(scene_id, req.scene)
    return {"scene_id": scene_id, "saved": True, "node_count": len(req.scene.nodes)}


@app.delete("/api/scenes/{scene_id}")
async def scenes_delete(scene_id: str):
    return {"deleted": delete_scene(scene_id)}


def _run(fn, *args):
    try:
        return {"scene": fn(*args)}
    except scene_ops.SceneError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ops/add-node")
async def op_add_node(req: AddNodeRequest):
    return _run(scene_ops.add_node, req.scene, req.type, req.parent_id, req.name, req.position)


@app.post("/api/ops/group")
async def op_group(req: GroupRequest):
    return _run(scene_ops.create_group_with_selection, req.scene, req.child_ids)


@app.post("/api/ops/reparent")
async def op_reparent(req: ReparentRequest):
    return _run(scene_ops.reparent, req.scene, req.node_id, req.new_parent_id, req.keep_world_transform)


@app.post("/api/ops/duplicate")
async def op_duplicate(req: IdRequest):
    return _run(scene_ops.duplicate_subtree, req.scene, req.node_id)


@app.post("/api/ops/delete")
async def op_delete(req: IdRequest):
    return _run(scene_ops.delete_subtree, req.scene, req.node_id)


@app.post("/api/ops/transform")
async def op_transform(req: TransformRequest):
    return _run(
        scene_ops.update_transform,
        req.scene,
        req.node_id,
        req.position,
        req.rotation_euler,
        req.scale,
    )


@app.post("/api/ops/world-transforms")
async def op_world_transforms(req: SaveRequest):
    try:
        return {"world": scene_ops.world_summary(req.scene)}
    except scene_ops.SceneError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

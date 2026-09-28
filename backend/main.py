"""FastAPI app: scene CRUD, hierarchy ops, and server-side world math.

Endpoints are async on purpose: on Python 3.14 anyio's sync-endpoint worker
pool deadlocks in this sandbox; the handlers do pure in-memory/file work so
there is no benefit in running them in a thread anyway.
"""
from __future__ import annotations
import copy
import os

from fastapi import FastAPI, HTTPException
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import scene_model as sm
from . import storage

STORAGE_DIR = os.environ.get(
    "SCENE_STORAGE_DIR",
    os.path.join(os.path.dirname(__file__), "..", "scenes"))

app = FastAPI(title="3D Scene Platform - hierarchy API", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class TransformIn(BaseModel):
    position: list[float] | None = None
    rotation: list[float] | None = None
    scale: list[float] | None = None


class AddNodeIn(BaseModel):
    parentId: str | None = None
    type: str
    name: str | None = None
    position: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: list[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0])


class ReparentIn(BaseModel):
    nodeId: str
    newParentId: str | None = None
    preserveWorld: bool = True
    index: int | None = None


class GroupIn(BaseModel):
    nodeIds: list[str]
    name: str = "Group"


class RenameIn(BaseModel):
    name: str


def _load(scene_id: str) -> dict:
    if not storage.exists(STORAGE_DIR, scene_id):
        raise HTTPException(404, detail={"code": "not_found",
                                         "message": f"scene {scene_id} not found"})
    try:
        doc = storage.load_scene(STORAGE_DIR, scene_id)
        sm.validate(doc)
        return doc
    except sm.SceneError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": exc.message})


def _save(doc: dict, scene_id: str) -> None:
    try:
        sm.validate(doc)
        storage.save_scene(STORAGE_DIR, scene_id, doc)
    except sm.SceneError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": exc.message})


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/scenes")
async def list_scenes():
    return {"scenes": storage.list_scenes(STORAGE_DIR)}


@app.post("/api/scenes/{scene_id}")
async def create_scene(scene_id: str, request: Request):
    if storage.exists(STORAGE_DIR, scene_id):
        raise HTTPException(409, detail={"code": "exists", "message": "scene already exists"})
    raw = await request.body()
    if raw:
        import json
        doc = copy.deepcopy(json.loads(raw))
    else:
        doc = sm.new_scene()
    _save(doc, scene_id)
    return {"sceneId": scene_id, "doc": doc}


@app.get("/api/scenes/{scene_id}/doc")
async def get_scene(scene_id: str):
    return {"sceneId": scene_id, "doc": _load(scene_id)}


@app.put("/api/scenes/{scene_id}/doc")
async def replace_scene(scene_id: str, doc: dict):
    """Save the full editable document (after undo/redo/multi-edit)."""
    _save(doc, scene_id)
    return {"sceneId": scene_id, "doc": doc}


@app.post("/api/scenes/{scene_id}/nodes")
async def add_node(scene_id: str, payload: AddNodeIn):
    doc = _load(scene_id)
    node = sm.make_node(payload.type, payload.name, payload.position,
                        payload.rotation, payload.scale)
    try:
        sm.add_node(doc, node, payload.parentId)
        _save(doc, scene_id)
    except sm.SceneError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": exc.message})
    return {"node": node, "doc": doc}


@app.post("/api/scenes/{scene_id}/reparent")
async def reparent(scene_id: str, payload: ReparentIn):
    doc = _load(scene_id)
    try:
        sm.reparent(doc, payload.nodeId, payload.newParentId,
                    preserve_world=payload.preserveWorld, index=payload.index)
        _save(doc, scene_id)
    except sm.SceneError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": exc.message})
    return {"doc": doc}


@app.post("/api/scenes/{scene_id}/group")
async def group(scene_id: str, payload: GroupIn):
    doc = _load(scene_id)
    try:
        gid = sm.group_nodes(doc, payload.nodeIds, payload.name)
        _save(doc, scene_id)
    except sm.SceneError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": exc.message})
    return {"groupId": gid, "doc": doc}


@app.post("/api/scenes/{scene_id}/nodes/{node_id}/duplicate")
async def duplicate(scene_id: str, node_id: str):
    doc = _load(scene_id)
    try:
        new_id = sm.duplicate_subtree(doc, node_id)
        _save(doc, scene_id)
    except sm.SceneError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": exc.message})
    return {"newRootId": new_id, "doc": doc}


@app.delete("/api/scenes/{scene_id}/nodes/{node_id}")
async def delete(scene_id: str, node_id: str):
    doc = _load(scene_id)
    try:
        sm.delete_subtree(doc, node_id)
        _save(doc, scene_id)
    except sm.SceneError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": exc.message})
    return {"doc": doc}


@app.put("/api/scenes/{scene_id}/nodes/{node_id}/transform")
async def set_transform(scene_id: str, node_id: str, payload: TransformIn):
    doc = _load(scene_id)
    try:
        sm.update_transform(doc, node_id, position=payload.position,
                            rotation=payload.rotation, scale=payload.scale)
        _save(doc, scene_id)
    except sm.SceneError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": exc.message})
    return {"doc": doc}


@app.put("/api/scenes/{scene_id}/nodes/{node_id}/rename")
async def rename(scene_id: str, node_id: str, payload: RenameIn):
    doc = _load(scene_id)
    try:
        sm.rename(doc, node_id, payload.name)
        _save(doc, scene_id)
    except sm.SceneError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": exc.message})
    return {"doc": doc}


@app.get("/api/scenes/{scene_id}/world")
async def world(scene_id: str):
    """Server-computed final world TRS + matrices for cross-checking."""
    return {"world": sm.world_trs(_load(scene_id))}


@app.post("/api/compute/world")
async def compute_world(doc: dict):
    """Stateless world-matrix computation for any document (used by tests)."""
    try:
        sm.validate(doc)
    except sm.SceneError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": exc.message})
    return {"world": sm.world_trs(doc)}


# Serve the built frontend in production (single-port deployment).
import os as _os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_DIST = _os.path.join(_os.path.dirname(__file__), "..", "frontend", "dist")
if _os.path.isdir(_DIST):
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        candidate = _os.path.join(_DIST, full_path)
        if full_path and _os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(_os.path.join(_DIST, "index.html"))

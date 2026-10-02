"""场景文档持久化：每个场景一个 JSON 文件，可随时重新载入继续编辑。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import List

from .models import ReleaseSnapshot, Scene, UpgradeBatch


def store_dir() -> Path:
    path = Path(os.environ.get("SCENE_STORE_DIR", Path(__file__).resolve().parent.parent / "runtime" / "scenes"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(scene_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", scene_id):
        raise ValueError("非法场景 id")
    return store_dir() / f"{scene_id}.json"


class SceneLoadError(Exception):
    """场景文档无法解析：携带原始 JSON，调用方不得用空场景覆盖已保存内容。"""

    def __init__(self, message: str, raw: dict | None = None):
        super().__init__(message)
        self.raw = raw


def save_scene(scene_id: str, scene: Scene) -> None:
    payload = {"scene_id": scene_id, "scene": scene.model_dump()}
    tmp = _path(scene_id).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_path(scene_id))


def load_scene(scene_id: str) -> Scene:
    scene, _ = load_scene_with_warning(scene_id)
    return scene


def load_scene_with_warning(scene_id: str) -> tuple[Scene, str | None]:
    """加载场景；结构损坏时抛出 SceneLoadError（保留 raw），个别字段异常时宽松修复并给出原因。"""
    text = _path(scene_id).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SceneLoadError(f"场景 JSON 已损坏（{exc.msg}，第 {exc.lineno} 行）；已保留文件内容，请修复或另存")
    payload = data.get("scene")
    if not isinstance(payload, dict):
        raise SceneLoadError("场景文档缺少 scene 对象；已保留文件内容，未用空场景覆盖", data)
    warning: str | None = None
    try:
        return Scene.model_validate(payload), None
    except Exception as exc:
        repaired, dropped = _repair_scene_payload(payload)
        try:
            scene = Scene.model_validate(repaired)
        except Exception:
            raise SceneLoadError(f"场景文档无法解析：{exc}；已保留原始内容，未做覆盖", data)
        warning = f"部分发布/批次记录无法读取，已原样保留并跳过：{dropped or exc}"
        return scene, warning


def _repair_scene_payload(payload: dict) -> tuple[dict, list[str]]:
    """尽力保留节点/原件现场；只丢弃无法解析的发布快照与批次记录，保证场景可操作。"""
    repaired = dict(payload)
    dropped: list[str] = []
    for key, model_cls in (
        ("releases", ReleaseSnapshot),
        ("upgrade_batches", UpgradeBatch),
    ):
        items = repaired.get(key)
        if not isinstance(items, list):
            continue
        kept = []
        for item in items:
            try:
                kept.append(model_cls.model_validate(item).model_dump())
            except Exception as exc:
                name = ""
                if isinstance(item, dict):
                    name = str(item.get("name") or item.get("id") or "")
                dropped.append(f"{key}:{name or '?'}（{exc}）")
        repaired[key] = kept
    return repaired, dropped


def load_raw_scene(scene_id: str) -> dict:
    """读取原始落盘文档（加载失败时用于抢救，绝不回写覆盖）。"""
    return json.loads(_path(scene_id).read_text(encoding="utf-8"))


def delete_scene(scene_id: str) -> bool:
    p = _path(scene_id)
    if p.exists():
        p.unlink()
        return True
    return False


def list_scenes() -> List[dict]:
    result = []
    for p in sorted(store_dir().glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            scene = Scene.model_validate(data["scene"])
            result.append(
                {
                    "scene_id": data.get("scene_id", p.stem),
                    "node_count": len(scene.nodes),
                    "updated_at": p.stat().st_mtime,
                    "load_error": None,
                }
            )
        except Exception:
            result.append(
                {
                    "scene_id": p.stem,
                    "node_count": -1,
                    "updated_at": p.stat().st_mtime if p.exists() else 0,
                    "load_error": "场景文档无法读取",
                }
            )
    return result

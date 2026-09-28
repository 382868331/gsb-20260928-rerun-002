"""场景文档持久化：每个场景一个 JSON 文件，可随时重新载入继续编辑。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import List

from .models import Scene


def store_dir() -> Path:
    path = Path(os.environ.get("SCENE_STORE_DIR", Path(__file__).resolve().parent.parent / "runtime" / "scenes"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(scene_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", scene_id):
        raise ValueError("非法场景 id")
    return store_dir() / f"{scene_id}.json"


def save_scene(scene_id: str, scene: Scene) -> None:
    payload = {"scene_id": scene_id, "scene": scene.model_dump()}
    tmp = _path(scene_id).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_path(scene_id))


def load_scene(scene_id: str) -> Scene:
    data = json.loads(_path(scene_id).read_text(encoding="utf-8"))
    return Scene.model_validate(data["scene"])


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
                }
            )
        except Exception:
            continue
    return result

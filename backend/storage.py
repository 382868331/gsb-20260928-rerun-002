"""File-backed persistence for editable scene documents.

Scenes are saved as JSON scene graphs (the same structure the editor
works with), so reloading always restores full parent/child links and
local transforms -- never a rendered image.
"""
from __future__ import annotations

import json
import os
import threading

_LOCK = threading.Lock()


def _path(storage_dir: str, scene_id: str) -> str:
    safe = "".join(c for c in scene_id if c.isalnum() or c in "-_")
    if not safe or safe != scene_id:
        raise ValueError("invalid scene id")
    return os.path.join(storage_dir, f"{safe}.json")


def save_scene(storage_dir: str, scene_id: str, doc: dict) -> None:
    os.makedirs(storage_dir, exist_ok=True)
    data = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True)
    path = _path(storage_dir, scene_id)
    tmp = path + ".tmp"
    with _LOCK:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, path)


def load_scene(storage_dir: str, scene_id: str) -> dict:
    with open(_path(storage_dir, scene_id), encoding="utf-8") as fh:
        return json.load(fh)


def list_scenes(storage_dir: str) -> list[str]:
    if not os.path.isdir(storage_dir):
        return []
    return sorted(f[:-5] for f in os.listdir(storage_dir)
                  if f.endswith(".json"))


def exists(storage_dir: str, scene_id: str) -> bool:
    return os.path.exists(_path(storage_dir, scene_id))

"""场景读取失败时保留原内容：不抛裸异常覆盖，不允许空场景回写已保存文档。"""

import asyncio
import json

import httpx
import pytest

from backend.app import app
from backend.models import Scene
from backend.storage import SceneLoadError, load_scene_with_warning


def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    )


def test_corrupt_json_raises_load_error_not_blank(monkeypatch, tmp_path):
    monkeypatch.setenv("SCENE_STORE_DIR", str(tmp_path))
    p = tmp_path / "broken.json"
    p.write_text("{ not json", encoding="utf-8")
    with pytest.raises(SceneLoadError):
        load_scene_with_warning("broken")
    assert p.read_text(encoding="utf-8") == "{ not json"


def test_bad_release_record_is_skipped_but_scene_still_loads(monkeypatch, tmp_path):
    monkeypatch.setenv("SCENE_STORE_DIR", str(tmp_path))
    scene = Scene()
    payload = json.loads(scene.model_dump_json())
    payload["releases"] = [{"id": "bad", "definitions": "not-a-list"}]
    (tmp_path / "partial.json").write_text(
        json.dumps({"scene_id": "partial", "scene": payload}, ensure_ascii=False),
        encoding="utf-8",
    )
    loaded, warning = load_scene_with_warning("partial")
    assert loaded.releases == []
    assert warning and "发布" in warning


def test_api_refuses_empty_overwrite_and_reports_corrupt(monkeypatch, tmp_path):
    monkeypatch.setenv("SCENE_STORE_DIR", str(tmp_path))

    async def main():
        async with _client() as client:
            created = (await client.post("/api/scenes", json={})).json()
            sid = created["scene_id"]
            path = tmp_path / f"{sid}.json"
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["scene"]["nodes"].append(
                {
                    "id": "real-node",
                    "name": "真实节点",
                    "type": "cube",
                    "parent_id": None,
                    "children": [],
                    "transform": {
                        "position": [0, 0, 0],
                        "rotation": [0, 0, 0, 1],
                        "scale": [1, 1, 1],
                    },
                }
            )
            raw["scene"]["root_ids"] = ["real-node"]
            path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

            resp = await client.put(f"/api/scenes/{sid}", json={"scene": Scene().model_dump()})
            assert resp.status_code == 409
            assert "拒绝用空场景覆盖" in resp.json()["detail"]

            (tmp_path / "corrupt.json").write_text("{bad", encoding="utf-8")
            resp = await client.get("/api/scenes/corrupt")
            assert resp.status_code == 422
            assert "保留" in resp.json()["detail"]

    asyncio.run(main())

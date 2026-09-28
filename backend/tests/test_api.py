import math
import os

import pytest

from backend import main, scene_model as sm
from backend.tests.asgi_call import ASGIClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "STORAGE_DIR", str(tmp_path / "scenes"))
    return ASGIClient(main.app)


def test_full_lifecycle(client):
    sid = "demo"
    assert client.request("POST", f"/api/scenes/{sid}", None).status_code == 200

    r = client.request("POST", f"/api/scenes/{sid}/nodes",
                       {"type": "group", "name": "Rig",
                        "rotation": [0, math.pi / 2, 0], "scale": [2, 2, 2]}).json()
    g = r["node"]
    r = client.request("POST", f"/api/scenes/{sid}/nodes",
                       {"type": "cube", "name": "Part", "parentId": g["id"],
                        "position": [1, 0, 0]}).json()
    cube = r["node"]

    world_pos = client.request("GET", f"/api/scenes/{sid}/world").json()["world"][cube["id"]]["position"]
    assert world_pos != [1, 0, 0]

    r = client.request("POST", f"/api/scenes/{sid}/nodes/{g['id']}/duplicate")
    assert r.status_code == 200
    new_root = r.json()["newRootId"]

    doc = client.request("GET", f"/api/scenes/{sid}/doc").json()["doc"]
    assert len(doc["rootOrder"]) == 2
    copied_child = doc["nodes"][new_root]["children"][0]
    assert doc["nodes"][copied_child]["parent"] == new_root

    home = client.request("POST", f"/api/scenes/{sid}/nodes",
                          {"type": "group", "name": "NewHome",
                           "rotation": [0.1, 0.2, 0.3], "scale": [3, 3, 3]}).json()["node"]
    before = client.request("GET", f"/api/scenes/{sid}/world").json()["world"][cube["id"]]["matrix"]
    resp = client.request("POST", f"/api/scenes/{sid}/reparent",
                          {"nodeId": cube["id"], "newParentId": home["id"], "preserveWorld": True})
    assert resp.status_code == 200, resp.body
    after = client.request("GET", f"/api/scenes/{sid}/world").json()["world"][cube["id"]]["matrix"]
    assert all(abs(a - b) < 1e-9 for a, b in zip(before, after))

    resp = client.request("POST", f"/api/scenes/{sid}/reparent",
                          {"nodeId": home["id"], "newParentId": cube["id"], "preserveWorld": True})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "cycle_detected"

    doc2 = client.request("GET", f"/api/scenes/{sid}/doc").json()["doc"]
    assert client.request("PUT", f"/api/scenes/{sid}/doc", doc2).status_code == 200


def test_broken_document_rejected(client):
    client.request("POST", "/api/scenes/x", None)
    bad = {"version": 1, "rootOrder": ["a"], "nodes": {
        "a": {"id": "a", "name": "a", "type": "cube", "parent": "ghost",
              "children": [], "position": [0, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1]}}}
    resp = client.request("PUT", "/api/scenes/x/doc", bad)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "dangling_parent"


def test_compute_world_stateless(client):
    doc = sm.new_scene()
    g = sm.make_node("group", "G", rotation=[0, math.pi / 4, 0], scale=[2, 2, 2])
    n = sm.make_node("cube", "C", position=[1, 0, 0])
    sm.add_node(doc, g)
    sm.add_node(doc, n, g["id"])
    resp = client.request("POST", "/api/compute/world", doc)
    assert resp.status_code == 200
    pos = resp.json()["world"][n["id"]]["position"]
    assert pos[0] == pytest.approx(2.0 / math.sqrt(2), abs=1e-9)
    assert pos[2] == pytest.approx(-2.0 / math.sqrt(2), abs=1e-9)

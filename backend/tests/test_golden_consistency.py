"""Backend-side invariant checks for the golden fixtures.

Frontend vitest loads the same JSON and checks three.js matrices against
the recorded backend matrices; this test guards the fixtures themselves.
"""
import json
import os

import pytest

from backend import scene_model as sm

FIX = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")


@pytest.mark.parametrize("name", ["deep_nested", "reparent"])
def test_fixture_records_match_compute(name):
    with open(os.path.join(FIX, f"{name}.json"), encoding="utf-8") as fh:
        payload = json.load(fh)
    doc = payload["doc"]
    sm.validate(doc)
    fresh = sm.world_trs(doc)
    for node_id, info in payload["world"].items():
        for i, (a, b) in enumerate(zip(fresh[node_id]["matrix"], info["matrix"])):
            assert a == pytest.approx(b, abs=1e-12), (name, node_id, i)


def test_deep_nested_has_nesting_rotation_and_nonuniform_scale():
    with open(os.path.join(FIX, "deep_nested.json"), encoding="utf-8") as fh:
        doc = json.load(fh)["doc"]
    # at least one node is 4 levels deep
    depth = {"root": 0}
    pending = ["root"]
    while pending:
        nid = pending.pop()
        for child in doc["nodes"][nid]["children"]:
            depth[child] = depth[nid] + 1
            pending.append(child)
    assert max(depth.values()) >= 4
    scales = [tuple(doc["nodes"][n]["scale"]) for n in depth]
    assert any(len(set(round(v, 6) for v in s)) > 1 for s in scales)
    rotations = [doc["nodes"][n]["rotation"] for n in depth]
    assert any(any(abs(v) > 0.01 for v in r) for r in rotations)

import copy
import math

import pytest

from backend import scene_model as sm
from backend import scene_math as m3d


def build_nested():
    """root A (rot Y 90) -> B (rot X 45, non-uniform scale, pos) -> cube."""
    doc = sm.new_scene()
    a = sm.make_node("group", "A", rotation=[0, math.pi / 2, 0], node_id="a")
    b = sm.make_node("group", "B", position=[1, 2, 3],
                     rotation=[math.pi / 4, 0, 0], scale=[2, 0.5, 2], node_id="b")
    c = sm.make_node("cube", "C", position=[0.5, 0, -1],
                     rotation=[0, 0, 0.3], scale=[1, 2, 1], node_id="c")
    sm.add_node(doc, a)
    sm.add_node(doc, b, "a")
    sm.add_node(doc, c, "b")
    return doc


def build_nested_uniform():
    """Same nesting/rotations, uniform scale (shear-free reparenting)."""
    doc = sm.new_scene()
    a = sm.make_node("group", "A", rotation=[0, math.pi / 2, 0], node_id="a")
    b = sm.make_node("group", "B", position=[1, 2, 3],
                     rotation=[math.pi / 4, 0, 0], scale=[2, 2, 2], node_id="b")
    c = sm.make_node("cube", "C", position=[0.5, 0, -1],
                     rotation=[0, 0, 0.3], scale=[1, 1, 1], node_id="c")
    sm.add_node(doc, a)
    sm.add_node(doc, b, "a")
    sm.add_node(doc, c, "b")
    return doc


def test_world_matrix_matches_manual_chain():
    doc = build_nested()
    world = sm.world_matrices(doc)
    ma = m3d.compose([0, 0, 0], [0, math.pi / 2, 0], [1, 1, 1])
    mb = m3d.compose([1, 2, 3], [math.pi / 4, 0, 0], [2, 0.5, 2])
    mc = m3d.compose([0.5, 0, -1], [0, 0, 0.3], [1, 2, 1])
    expected_c = m3d.multiply(m3d.multiply(ma, mb), mc)
    for got, exp in zip(world["c"], expected_c):
        assert got == pytest.approx(exp, abs=1e-12)


def test_compose_decompose_roundtrip():
    cases = [
        ([1.5, -2, 0.25], [0.3, -1.1, 2.0], [1.5, 0.7, 2.0]),
        ([0, 0, 0], [math.pi / 2, 0, 0], [1, 1, 1]),
        ([3, 1, -4], [0.1, 0.2, -0.3], [0.5, 2.5, 1.0]),
    ]
    for p, r, s in cases:
        mat = m3d.compose(p, r, s)
        p2, r2, s2 = m3d.decompose(mat)
        rebuilt = m3d.compose(p2, r2, s2)
        for i in range(16):
            assert rebuilt[i] == pytest.approx(mat[i], abs=1e-9)


def test_reparent_preserves_world_position():
    doc = build_nested_uniform()
    before = sm.world_matrices(doc)["c"]

    d = sm.make_node("group", "D", position=[5, 0, 0],
                     rotation=[0, 0, math.pi / 3], scale=[2, 2, 2], node_id="d")
    sm.add_node(doc, d)  # second root
    sm.reparent(doc, "c", "d", preserve_world=True)

    assert doc["nodes"]["c"]["parent"] == "d"
    assert "c" not in doc["nodes"]["b"]["children"]
    after = sm.world_matrices(doc)["c"]
    for i in range(16):
        assert after[i] == pytest.approx(before[i], abs=1e-9)


def test_reparent_to_root_preserves_world():
    doc = build_nested_uniform()
    before = sm.world_matrices(doc)["c"]
    sm.reparent(doc, "c", None, preserve_world=True)
    after = sm.world_matrices(doc)["c"]
    for i in range(16):
        assert after[i] == pytest.approx(before[i], abs=1e-9)
    assert "c" in doc["rootOrder"]


def test_reparent_without_preserve_keeps_local():
    doc = build_nested()
    local_before = copy.deepcopy(doc["nodes"]["c"]["position"])
    sm.reparent(doc, "c", None, preserve_world=False)
    assert doc["nodes"]["c"]["position"] == local_before


def test_cycle_self_and_descendant_blocked():
    doc = build_nested()
    with pytest.raises(sm.SceneError) as e1:
        sm.reparent(doc, "a", "a")
    assert e1.value.code == "invalid_parent"

    with pytest.raises(sm.SceneError) as e2:
        sm.reparent(doc, "a", "c")
    assert e2.value.code == "cycle_detected"

    # failed operation must not mutate structure
    assert doc["nodes"]["a"]["parent"] is None
    assert doc["nodes"]["b"]["parent"] == "a"
    assert doc["nodes"]["c"]["parent"] == "b"


def test_duplicate_subtree_keeps_relationships_and_offset():
    doc = build_nested()
    new_root = sm.duplicate_subtree(doc, "b", offset=(10, 0, 0))
    assert new_root != "b"
    new_b = doc["nodes"][new_root]
    assert new_b["parent"] == "a"
    assert len(new_b["children"]) == 1
    new_c_id = new_b["children"][0]
    assert new_c_id != "c"
    assert doc["nodes"][new_c_id]["parent"] == new_root
    # local TRS preserved except root offset
    assert new_b["position"] == pytest.approx([11, 2, 3])
    assert doc["nodes"][new_c_id]["position"] == [0.5, 0, -1]
    # original intact
    assert doc["nodes"]["c"]["parent"] == "b"
    # relative child world pose inside the copy matches original
    w = sm.world_matrices(doc)
    rel_orig = m3d.multiply(m3d.invert(w["b"]), w["c"])
    rel_copy = m3d.multiply(m3d.invert(w[new_root]), w[new_c_id])
    for i in range(16):
        assert rel_copy[i] == pytest.approx(rel_orig[i], abs=1e-12)


def test_group_nodes_preserves_world():
    doc = sm.new_scene()
    a = sm.make_node("cube", "A", position=[1, 0, 0], node_id="a")
    b = sm.make_node("sphere", "B", position=[0, 2, 0], node_id="b")
    sm.add_node(doc, a)
    sm.add_node(doc, b)
    before = {nid: sm.world_matrices(doc)[nid] for nid in ("a", "b")}
    gid = sm.group_nodes(doc, ["a", "b"], "G")
    after = sm.world_matrices(doc)
    for nid in ("a", "b"):
        assert doc["nodes"][nid]["parent"] == gid
        for i in range(16):
            assert after[nid][i] == pytest.approx(before[nid][i], abs=1e-12)


def test_validate_catches_broken_and_cyclic_links():
    doc = build_nested()
    # fabricate a cycle a -> c -> a
    doc["nodes"]["a"]["parent"] = "c"
    doc["nodes"]["c"]["children"].append("a")
    with pytest.raises(sm.SceneError) as e:
        sm.reparent(doc, "b", "a")
    assert e.value.code == "cycle_detected"

    doc2 = build_nested()
    doc2["nodes"]["c"]["parent"] = "missing"
    doc2["nodes"]["b"]["children"].remove("c")
    with pytest.raises(sm.SceneError) as e2:
        sm.validate(doc2)
    assert e2.value.code == "dangling_parent"


def test_delete_subtree():
    doc = build_nested()
    sm.delete_subtree(doc, "b")
    assert "b" not in doc["nodes"]
    assert "c" not in doc["nodes"]
    assert doc["nodes"]["a"]["children"] == []

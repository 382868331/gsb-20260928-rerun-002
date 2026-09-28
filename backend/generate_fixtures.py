"""Generate golden scene fixtures + server world matrices.

The frontend vitest suite loads these JSON files, rebuilds each scene in
a three.js scene graph, and compares every node's world matrix against
the backend numbers.  Fixtures include deep nesting, rotations and
(non-uniform) scales.
"""
import json
import math
import os

from . import scene_model as sm

HERE = os.path.dirname(__file__)


def deep_nested():
    """4 levels with mixed rotations and non-uniform scales."""
    doc = sm.new_scene()
    root = sm.make_node("group", "Root", rotation=[0, 0.3, 0], scale=[1.5, 1.5, 1.5], node_id="root")
    rig = sm.make_node("group", "Rig", position=[2, 0, 0], rotation=[0.4, 0, 0.2], scale=[2, 0.5, 1], node_id="rig")
    arm = sm.make_node("group", "Arm", position=[0, 1, -1], rotation=[0, math.pi / 3, 0], scale=[1, 1, 2], node_id="arm")
    hand = sm.make_node("group", "Hand", position=[1, 0, 0], rotation=[math.pi / 5, 0.2, 0], scale=[0.5, 1.5, 1], node_id="hand")
    a = sm.make_node("cube", "A", position=[0.5, 0, 0], rotation=[0, 0, 0.25], scale=[1, 1, 1], node_id="a")
    b = sm.make_node("sphere", "B", position=[-0.5, 0.3, 0.2], rotation=[0.1, -0.4, 0.9], scale=[0.8, 1.2, 0.6], node_id="b")
    c = sm.make_node("cylinder", "C", position=[0, 0, 1], rotation=[math.pi / 2, 0, 0], scale=[1, 1, 1], node_id="c")
    for n, p in ((root, None), (rig, "root"), (arm, "rig"), (hand, "arm"),
                 (a, "hand"), (b, "hand"), (c, "arm")):
        sm.add_node(doc, n, p)
    # second independent root
    d = sm.make_node("cone", "Solo", position=[-3, 2, 1], rotation=[0.2, 0.7, -0.3], scale=[1, 2, 1], node_id="d")
    sm.add_node(doc, d)
    sm.validate(doc)
    return doc


def reparent_case():
    """Document state after a preserve-world reparent into a rotated parent."""
    doc = sm.new_scene()
    g1 = sm.make_node("group", "G1", position=[1, 2, 3], rotation=[0, math.pi / 4, 0], scale=[2, 2, 2], node_id="g1")
    g2 = sm.make_node("group", "G2", position=[-2, 0, 1], rotation=[0.5, 0.1, -0.3], scale=[1.5, 1.5, 1.5], node_id="g2")
    n = sm.make_node("cube", "Moving", position=[1, 0, 0], rotation=[0.2, 0.4, 0.1], scale=[1, 1, 1], node_id="n")
    sm.add_node(doc, g1)
    sm.add_node(doc, g2)
    sm.add_node(doc, n, "g1")
    sm.reparent(doc, "n", "g2", preserve_world=True)
    sm.validate(doc)
    return doc


def main():
    out_dir = os.path.join(HERE, "fixtures")
    os.makedirs(out_dir, exist_ok=True)
    for name, builder in (("deep_nested", deep_nested), ("reparent", reparent_case)):
        doc = builder()
        payload = {"doc": doc, "world": sm.world_trs(doc)}
        with open(os.path.join(out_dir, f"{name}.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"wrote {name}: {len(doc['nodes'])} nodes")


if __name__ == "__main__":
    main()

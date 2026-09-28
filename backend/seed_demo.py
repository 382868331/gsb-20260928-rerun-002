"""Create a demo scene: deeply nested groups with rotation/scale.

Run after starting storage setup: .venv/bin/python -m backend.seed_demo
"""
import math

from . import scene_model as sm
from . import storage
import os

STORAGE = os.environ.get("SCENE_STORAGE_DIR",
                         os.path.join(os.path.dirname(__file__), "..", "scenes"))


def build():
    doc = sm.new_scene()
    root = sm.make_node("group", "底座", rotation=[0, 0.3, 0], scale=[1.5, 1.5, 1.5], node_id="root")
    rig = sm.make_node("group", "机械臂", position=[2, 0, 0], rotation=[0.4, 0, 0.2], scale=[2, 0.5, 1], node_id="rig")
    arm = sm.make_node("group", "小臂", position=[0, 1, -1], rotation=[0, math.pi / 3, 0], scale=[1, 1, 2], node_id="arm")
    hand = sm.make_node("group", "抓手", position=[1, 0, 0], rotation=[math.pi / 5, 0.2, 0], scale=[0.5, 1.5, 1], node_id="hand")
    cube = sm.make_node("cube", "红色夹块", position=[0.5, 0, 0], rotation=[0, 0, 0.25], node_id="cube")
    sphere = sm.make_node("sphere", "传感器", position=[-0.5, 0.3, 0.2], rotation=[0.1, -0.4, 0.9], scale=[0.8, 1.2, 0.6], node_id="sphere")
    cyl = sm.make_node("cylinder", "立柱", position=[0, 0, 1], rotation=[math.pi / 2, 0, 0], node_id="cyl")
    solo = sm.make_node("cone", "地面路标", position=[-3, 2, 1], rotation=[0.2, 0.7, -0.3], scale=[1, 2, 1], node_id="solo")
    for n, p in ((root, None), (rig, "root"), (arm, "rig"), (hand, "arm"),
                 (cube, "hand"), (sphere, "hand"), (cyl, "arm"), (solo, None)):
        sm.add_node(doc, n, p)
    sm.validate(doc)
    return doc


def main():
    doc = build()
    storage.save_scene(STORAGE, "demo", doc)
    print("saved scene 'demo' with", len(doc["nodes"]), "nodes ->", STORAGE)


if __name__ == "__main__":
    main()

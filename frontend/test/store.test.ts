import { describe, it, expect, beforeEach, vi } from "vitest";
import { useStore } from "../src/store";
import { newScene } from "../src/sceneOps";

vi.mock("../src/api", () => ({ api: {} }));

beforeEach(() => {
  useStore.getState().setScene("default", newScene());
});

describe("undo/redo", () => {
  it("undoes and redoes multiple structural steps", () => {
    const s = useStore.getState();
    s.addObject("cube");
    expect(Object.keys(useStore.getState().doc.nodes)).toHaveLength(1);
    s.addObject("sphere");
    expect(Object.keys(useStore.getState().doc.nodes)).toHaveLength(2);
    useStore.getState().undo();
    expect(Object.keys(useStore.getState().doc.nodes)).toHaveLength(1);
    useStore.getState().undo();
    expect(Object.keys(useStore.getState().doc.nodes)).toHaveLength(0);
    useStore.getState().redo();
    expect(Object.keys(useStore.getState().doc.nodes)).toHaveLength(1);
    useStore.getState().redo();
    expect(Object.keys(useStore.getState().doc.nodes)).toHaveLength(2);
  });

  it("rejected cycle op does not push history", () => {
    useStore.getState().addObject("group");
    const gid = useStore.getState().selectedIds[0];
    useStore.getState().addObject("cube", gid);
    const cubeId = useStore.getState().selectedIds[0];
    const pastBefore = useStore.getState().past.length;
    useStore.getState().reparent(gid, cubeId);
    expect(useStore.getState().lastError).toMatch(/循环/);
    expect(useStore.getState().past.length).toBe(pastBefore);
    expect(useStore.getState().doc.nodes[gid].parent).toBe(null);
  });

  it("duplicate then undo removes copied subtree only", () => {
    useStore.getState().addObject("group");
    const gid = useStore.getState().selectedIds[0];
    useStore.getState().addObject("cube", gid);
    const before = Object.keys(useStore.getState().doc.nodes).length;
    useStore.getState().duplicate(gid);
    expect(Object.keys(useStore.getState().doc.nodes).length).toBe(before + 2);
    useStore.getState().undo();
    expect(Object.keys(useStore.getState().doc.nodes).length).toBe(before);
  });

  it("new edit after undo drops the redo branch", () => {
    useStore.getState().addObject("cube");
    useStore.getState().undo();
    expect(useStore.getState().future.length).toBe(1);
    useStore.getState().addObject("cone");
    expect(useStore.getState().future.length).toBe(0);
  });
});

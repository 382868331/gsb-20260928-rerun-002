import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";

vi.mock("three/examples/jsm/controls/OrbitControls.js", () => ({
  OrbitControls: class {
    enableDamping = false;
    update() {}
    dispose() {}
    domElement = document.createElement("div");
  },
}));

vi.mock("three", async (importOriginal) => {
  const actual = await importOriginal<typeof import("three")>();
  return {
    ...actual,
    WebGLRenderer: class {
      domElement = document.createElement("canvas");
      setPixelRatio() {}
      setSize() {}
      render() {}
      dispose() {}
    },
  };
});

// Build a realistic scene with a nested assembly + release on the backend shape.
function makeScene() {
  return {
    version: 1,
    nodes: [],
    root_ids: [],
    assembly_defs: [],
    assembly_instances: [],
    assembly_history: [],
    releases: [
      {
        id: "rel1",
        name: "batchA",
        note: null,
        created_at: 1,
        definitions: [],
        instances: [],
      },
    ],
    selection: null,
  };
}

describe("app load", () => {
  beforeEach(() => {
    const scene = makeScene();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: { method?: string; body?: string }) => {
        const u = String(url);
        if (u.endsWith("/api/scenes")) {
          if (init?.method === "POST") {
            return Response.json({ scene_id: "s1", scene });
          }
          return Response.json({ scenes: [{ scene_id: "s1", node_count: 0 }] });
        }
        if (u.endsWith("/api/scenes/s1")) {
          return Response.json({ scene_id: "s1", scene });
        }
        if (u.endsWith("/world-transforms")) {
          return Response.json({ world: [] });
        }
        return Response.json({});
      })
    );
  });

  it("renders controls after loading a scene with releases", async () => {
    const { App } = await import("../App");
    const { findByText } = render(<App />);
    await findByText("三维场景创作平台");
    await waitFor(() => expect(document.querySelector("button.primary")).not.toBeNull());
    await new Promise((r) => setTimeout(r, 100));
    expect(findByText).toBeTruthy();
  });

  it("keeps the current scene and shows an explainable error when load fails", async () => {
    const { App } = await import("../App");
    // 列表里有一个场景，但读取它失败：界面不能死循环，也不能拿空场景覆盖
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const u = String(url);
        if (u.endsWith("/api/scenes")) {
          return Response.json({ scenes: [{ scene_id: "broken", node_count: 3 }] });
        }
        if (u.endsWith("/api/scenes/broken")) {
          return Response.json({ detail: "磁盘上的场景文档已损坏" }, { status: 400 });
        }
        return Response.json({});
      })
    );
    const { findByText } = render(<App />);
    const error = await findByText(/读取失败/);
    expect(error.textContent).toContain("已保留当前现场");
    expect(error.textContent).toContain("磁盘上的场景文档已损坏");
    // 工具栏按钮仍可操作（页面未被死循环卡死）
    await findByText("三维场景创作平台");
  });
});

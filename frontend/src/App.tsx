import { useEffect } from "react";
import { Toolbar } from "./components/Toolbar";
import { HierarchyTree } from "./components/HierarchyTree";
import { Inspector } from "./components/Inspector";
import { Viewport } from "./components/Viewport";
import { ConsistencyPanel } from "./components/ConsistencyPanel";
import { useStore } from "./store";
import { api } from "./api";

export default function App() {
  useEffect(() => {
    const st = useStore.getState();
    api.get(st.sceneId)
      .then(({ doc }) => st.setScene(st.sceneId, doc))
      .catch(async () => {
        await api.create(st.sceneId);
        const { doc } = await api.get(st.sceneId);
        st.setScene(st.sceneId, doc);
      });
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      const st = useStore.getState();
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); st.undo(); }
      if (mod && (e.key.toLowerCase() === "y" || (e.shiftKey && e.key.toLowerCase() === "z"))) { e.preventDefault(); st.redo(); }
      if (mod && e.key.toLowerCase() === "d" && st.selectedIds[0]) { e.preventDefault(); st.duplicate(st.selectedIds[0]); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const lastError = useStore((s) => s.lastError);
  const dismiss = useStore((s) => s.dismissError);
  const savedLabel = useStore((s) => s.savedLabel);

  return (
    <div className="app">
      <Toolbar />
      <div className="main">
        <aside className="panel left-panel">
          <h3>场景层级</h3>
          <p className="hint small">拖动词条换组；拖到空白处移到根级。循环挂交会被拦截。</p>
          <HierarchyTree />
          <ConsistencyPanel />
        </aside>
        <main className="stage">
          <Viewport />
          <div className="stage-hud">W 移动 · E 旋转 · R 缩放 · Ctrl+Z 撤销 · Ctrl+D 复制{savedLabel ? ` ｜ ${savedLabel}` : ""}</div>
        </main>
        <aside className="panel right-panel">
          <Inspector />
        </aside>
      </div>
      {lastError && <div className="toast error" onClick={dismiss}>⚠ {lastError}（点击关闭）</div>}
    </div>
  );
}

import { useEffect } from "react";
import { useStore } from "./lib/store";
import { Toolbar } from "./components/Toolbar";
import { HierarchyTree } from "./components/HierarchyTree";
import { Inspector } from "./components/Inspector";
import { Viewport } from "./components/Viewport";
import { UpdateDialog } from "./components/UpdateDialog";

export function App() {
  const init = useStore((s) => s.init);
  const undo = useStore((s) => s.undo);
  const redo = useStore((s) => s.redo);

  useEffect(() => {
    void init();
  }, [init]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "SELECT") return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
        e.preventDefault();
        undo();
      } else if (
        (e.ctrlKey || e.metaKey) &&
        (e.key.toLowerCase() === "y" || (e.shiftKey && e.key.toLowerCase() === "z"))
      ) {
        e.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);

  return (
    <div className="app">
      <Toolbar />
      <div className="workspace">
        <HierarchyTree />
        <Viewport />
        <Inspector />
      </div>
      <UpdateDialog />
    </div>
  );
}

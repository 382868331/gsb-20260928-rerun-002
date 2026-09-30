import { useEffect, useState } from "react";
import { useStore } from "../lib/store";
import { PRIMITIVE_TYPES } from "../lib/types";
import { api, type SceneMeta } from "../lib/api";

const LABELS: Record<string, string> = {
  cube: "立方体",
  sphere: "球体",
  cylinder: "圆柱",
  cone: "圆锥",
  plane: "平面",
};

export function Toolbar() {
  const addNode = useStore((s) => s.addNode);
  const groupSelected = useStore((s) => s.groupSelected);
  const duplicate = useStore((s) => s.duplicate);
  const remove = useStore((s) => s.remove);
  const undo = useStore((s) => s.undo);
  const redo = useStore((s) => s.redo);
  const save = useStore((s) => s.save);
  const newScene = useStore((s) => s.newScene);
  const loadScene = useStore((s) => s.loadScene);
  const sceneId = useStore((s) => s.sceneId);
  const busy = useStore((s) => s.busy);
  const error = useStore((s) => s.error);
  const dirty = useStore((s) => s.dirty);
  const canUndo = useStore((s) => s.past.length > 0);
  const canRedo = useStore((s) => s.future.length > 0);
  const selectedId = useStore((s) => s.selectedId);
  const assemblies = useStore((s) => s.scene.assembly_defs);
  const createAssembly = useStore((s) => s.createAssembly);
  const instantiateAssembly = useStore((s) => s.instantiateAssembly);
  const detachAssembly = useStore((s) => s.detachAssembly);
  const deleteAssemblyDefinition = useStore((s) => s.deleteAssemblyDefinition);
  const selectedNode = useStore((s) =>
    s.scene.nodes.find((n) => n.id === s.selectedId) ?? null
  );
  const [assemblyChoice, setAssemblyChoice] = useState("");

  const [scenes, setScenes] = useState<SceneMeta[]>([]);

  const refresh = () => {
    api.listScenes().then((r) => setScenes(r.scenes)).catch(() => {});
  };
  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="toolbar">
      <div className="brand">三维场景创作平台</div>
      <div className="tool-group">
        {PRIMITIVE_TYPES.map((t) => (
          <button key={t} onClick={() => void addNode(t)}>
            + {LABELS[t]}
          </button>
        ))}
      </div>
      <div className="tool-group">
        <button
          disabled={!selectedId}
          title="把选中节点（及整棵子树）放进新组，自动保持世界位置"
          onClick={() => void groupSelected()}
        >
          成组
        </button>
        <button disabled={!selectedId} onClick={() => void duplicate()}>
          复制组
        </button>
        <button disabled={!selectedId} onClick={() => void createAssembly()}>
          制作装配件
        </button>
        <button className="danger" disabled={!selectedId} onClick={() => void remove()}>
          删除
        </button>
        {selectedNode?.assembly && (
          <>
            <button onClick={() => void detachAssembly()}>脱离原件</button>
            <button
              title="删除原件；所有现有实例会自动脱离并保留在场景中"
              onClick={() => void deleteAssemblyDefinition()}
            >
              删除原件
            </button>
          </>
        )}
      </div>
      <div className="tool-group">
        <select
          value={assemblyChoice}
          onChange={(e) => setAssemblyChoice(e.target.value)}
          disabled={assemblies.length === 0}
          title="选择要再次放入场景的装配件"
        >
          <option value="">装配件…</option>
          {assemblies.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} v{item.version}
            </option>
          ))}
        </select>
        <button
          disabled={!assemblyChoice}
          onClick={() => void instantiateAssembly(assemblyChoice)}
        >
          放入实例
        </button>
      </div>
      <div className="tool-group">
        <button disabled={!canUndo} onClick={undo} title="Ctrl+Z">
          撤销
        </button>
        <button disabled={!canRedo} onClick={redo} title="Ctrl+Y">
          重做
        </button>
      </div>
      <div className="spacer" />
      <select
        value={sceneId ?? ""}
        onChange={(e) => {
          if (e.target.value === "__new") void newScene().then(refresh);
          else void loadScene(e.target.value);
        }}
      >
        {scenes.map((s) => (
          <option key={s.scene_id} value={s.scene_id}>
            {s.scene_id}（{s.node_count} 节点）
          </option>
        ))}
        <option value="__new">＋ 新建场景…</option>
      </select>
      <button className="primary" onClick={() => void save().then(refresh)}>
        保存{dirty ? " ●" : ""}
      </button>
      <span className="status">{error ? "⚠ " + error : busy ?? ""}</span>
    </div>
  );
}

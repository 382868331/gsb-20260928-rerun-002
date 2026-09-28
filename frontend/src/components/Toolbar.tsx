import { useEffect, useState } from "react";
import {
  Undo2, Redo2, Save, FolderOpen, FolderPlus, Boxes, Box, Circle, Cylinder, Triangle, Square,
} from "lucide-react";
import { useStore } from "../store";
import { api } from "../api";
import type { NodeType } from "../types";

const ADD_BUTTONS: { type: NodeType; label: string; Icon: typeof Box }[] = [
  { type: "cube", label: "立方体", Icon: Box },
  { type: "sphere", label: "球体", Icon: Circle },
  { type: "cylinder", label: "圆柱", Icon: Cylinder },
  { type: "cone", label: "圆锥", Icon: Triangle },
  { type: "plane", label: "平面", Icon: Square },
];

export function Toolbar() {
  const s = useStore();
  const [scenes, setScenes] = useState<string[]>([]);
  const [newId, setNewId] = useState("");

  const refresh = () => api.list().then((r) => setScenes(r.scenes)).catch(() => undefined);
  useEffect(() => { refresh(); }, [s.savedLabel]);

  return (
    <div className="toolbar">
      <div className="brand">三维场景平台 <small>v0.1 · 场景层级</small></div>

      <div className="tb-group">
        {ADD_BUTTONS.map(({ type, label, Icon }) => (
          <button key={type} className="tb-btn" title={`添加${label}`} onClick={() => s.addObject(type)}>
            <Icon size={16} /> {label}
          </button>
        ))}
        <button className="tb-btn" onClick={s.addEmptyGroup}><FolderPlus size={16} /> 空组</button>
        <button className="tb-btn" onClick={s.groupSelected} disabled={s.selectedIds.length === 0}>
          <Boxes size={16} /> 成组
        </button>
      </div>

      <div className="tb-group">
        <button className="tb-btn icon-only" title="撤销 (Ctrl+Z)" onClick={s.undo} disabled={s.past.length === 0}><Undo2 size={16} /></button>
        <button className="tb-btn icon-only" title="重做 (Ctrl+Y)" onClick={s.redo} disabled={s.future.length === 0}><Redo2 size={16} /></button>
        <label className="preserve">
          <input type="checkbox" checked={s.preserveWorld} onChange={(e) => s.setPreserveWorld(e.target.checked)} />
          换组时保持眼前位置
        </label>
      </div>

      <div className="tb-group right">
        <button className="tb-btn primary" onClick={s.save} disabled={s.saving}>
          <Save size={16} /> {s.dirty ? "保存*" : "保存"}
        </button>
        <button className="tb-btn" onClick={s.reload}><FolderOpen size={16} /> 重新载入</button>
        <select value={s.sceneId} onChange={(e) => { if (e.target.value) s.newSceneRemote(e.target.value); }}>
          {scenes.map((id) => <option key={id} value={id}>{id === s.sceneId ? `● ${id}` : id}</option>)}
        </select>
        <input className="new-id" placeholder="新场景 id" value={newId} onChange={(e) => setNewId(e.target.value)} />
        <button className="tb-btn" disabled={!newId.trim()} onClick={() => { s.newSceneRemote(newId.trim()); setNewId(""); }}>新建</button>
      </div>
    </div>
  );
}

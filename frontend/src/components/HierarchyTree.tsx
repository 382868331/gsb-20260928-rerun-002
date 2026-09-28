import { useState } from "react";
import {
  Box, Circle, Cylinder, Triangle, Square, Folder, FolderOpen,
  ChevronRight, ChevronDown,
} from "lucide-react";
import type { NodeType, SceneDoc } from "../types";
import { useStore } from "../store";

const ICONS: Record<NodeType, typeof Box> = {
  cube: Box, sphere: Circle, cylinder: Cylinder, cone: Triangle, plane: Square, group: Folder,
};

function TypeIcon({ type, open }: { type: NodeType; open?: boolean }) {
  if (type === "group") {
    return open ? <FolderOpen size={15} className="icon folder" /> : <Folder size={15} className="icon folder" />;
  }
  const Icon = ICONS[type];
  return <Icon size={15} className="icon" />;
}

export function HierarchyTree() {
  const doc = useStore((s) => s.doc) as SceneDoc;
  const selectedIds = useStore((s) => s.selectedIds);
  const selectOnly = useStore((s) => s.selectOnly);
  const toggleSelection = useStore((s) => s.toggleSelection);
  const reparent = useStore((s) => s.reparent);
  const duplicate = useStore((s) => s.duplicate);
  const remove = useStore((s) => s.remove);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropRoot, setDropRoot] = useState(false);
  const [dropInto, setDropInto] = useState<string | null>(null);

  const toggleCollapse = (id: string) => setCollapsed((c) => {
    const next = new Set(c);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const finishDrop = (targetId: string | null) => {
    const dragged = dragId;
    setDragId(null); setDropRoot(false); setDropInto(null);
    if (dragged && dragged !== targetId) reparent(dragged, targetId);
  };

  const renderNode = (id: string, depth: number) => {
    const node = doc.nodes[id];
    if (!node) return null;
    const isGroup = node.type === "group";
    const open = !collapsed.has(id);
    const selected = selectedIds.includes(id);

    return (
      <div key={id}>
        <div
          className={"tree-row" + (selected ? " selected" : "") + (dropInto === id ? " drop-target" : "")}
          style={{ paddingLeft: 8 + depth * 16 }}
          draggable
          onDragStart={(e) => { setDragId(id); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", id); }}
          onDragEnd={() => { setDragId(null); setDropRoot(false); setDropInto(null); }}
          onDragOver={(e) => {
            if (!dragId) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            setDropInto(id); setDropRoot(false);
          }}
          onDragLeave={() => setDropInto((cur) => (cur === id ? null : cur))}
          onDrop={(e) => { e.preventDefault(); finishDrop(id); }}
          onClick={(e) => (e.metaKey || e.ctrlKey ? toggleSelection(id) : selectOnly(id))}
          title={isGroup ? "拖到该节点上可放入此组" : node.name}
        >
          <span className="twisty" onClick={(e) => { e.stopPropagation(); if (isGroup) toggleCollapse(id); }}>
            {isGroup ? (open ? <ChevronDown size={13} /> : <ChevronRight size={13} />) : <span className="dot" />}
          </span>
          <TypeIcon type={node.type} open={open} />
          <span className="tree-name">{node.name}</span>
          <span className="row-actions">
            <button title="复制整个节点（保留全部父子关系）" onClick={(e) => { e.stopPropagation(); duplicate(id); }}>⧉</button>
            <button title="删除（含全部子物体）" onClick={(e) => { e.stopPropagation(); remove(id); }}>✕</button>
          </span>
        </div>
        {isGroup && open && node.children.map((c) => renderNode(c, depth + 1))}
      </div>
    );
  };

  return (
    <div
      className={"tree" + (doc.rootOrder.length === 0 ? " empty" : "") + (dropRoot ? " root-drop" : "")}
      onDragOver={(e) => {
        if (!dragId) return;
        e.preventDefault();
        setDropRoot(true); setDropInto(null);
      }}
      onDragLeave={() => setDropRoot(false)}
      onDrop={(e) => { e.preventDefault(); finishDrop(null); }}
    >
      {doc.rootOrder.length === 0 && <div className="tree-empty">场景为空，从顶部工具条添加基础物体</div>}
      {doc.rootOrder.map((id) => renderNode(id, 0))}
      {dropRoot && <div className="root-drop-hint">松开以移到场景根级</div>}
    </div>
  );
}

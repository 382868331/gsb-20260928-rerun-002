import { useState } from "react";
import {
  Box,
  Circle,
  Cylinder,
  Triangle,
  Square,
  Folder,
  FolderOpen,
  Trash2,
  Copy,
} from "lucide-react";
import type { Scene, SceneNode } from "../lib/types";
import { useStore } from "../lib/store";

const TYPE_ICON: Record<string, React.ReactNode> = {
  group: <Folder size={15} />,
  cube: <Box size={15} />,
  sphere: <Circle size={15} />,
  cylinder: <Cylinder size={15} />,
  cone: <Triangle size={15} />,
  plane: <Square size={15} />,
};

function isDescendant(scene: Scene, ancestorId: string, nodeId: string | null) {
  if (!nodeId) return false;
  const index = new Map(scene.nodes.map((n) => [n.id, n]));
  let current: string | null = nodeId;
  const seen = new Set<string>();
  while (current && !seen.has(current)) {
    if (current === ancestorId) return true;
    seen.add(current);
    current = index.get(current)?.parent_id ?? null;
  }
  return false;
}

function assemblyRootOf(scene: Scene, nodeId: string): SceneNode | null {
  const index = new Map(scene.nodes.map((n) => [n.id, n]));
  let current = index.get(nodeId) ?? null;
  let root = current;
  while (current?.assembly && current.parent_id) {
    const parent = index.get(current.parent_id);
    if (parent?.assembly?.instance_id !== current.assembly.instance_id) break;
    current = parent;
    root = current;
  }
  return root && root.assembly ? root : null;
}

export function HierarchyTree() {
  const scene = useStore((s) => s.scene);
  const selectedId = useStore((s) => s.selectedId);
  const select = useStore((s) => s.select);
  const reparent = useStore((s) => s.reparent);
  const duplicate = useStore((s) => s.duplicate);
  const remove = useStore((s) => s.remove);

  const [dragId, setDragId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [askKeep, setAskKeep] = useState<{
    nodeId: string;
    parentId: string | null;
  } | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const index = new Map(scene.nodes.map((n) => [n.id, n]));

  const requestMove = (nodeId: string, parentId: string | null) => {
    const node = index.get(nodeId);
    if (!node || node.parent_id === parentId) return;
    setAskKeep({ nodeId, parentId });
  };

  const confirmMove = async (keepWorld: boolean) => {
    if (!askKeep) return;
    const { nodeId, parentId } = askKeep;
    setAskKeep(null);
    await reparent(parentId, keepWorld);
  };

  const renderNode = (node: SceneNode, depth: number): React.ReactNode => {
    const isGroup = node.type === "group";
    const isOpen = !collapsed.has(node.id);
    const selected = node.id === selectedId;
    const dragover = dropTarget === node.id;
    const assemblyRoot = assemblyRootOf(scene, node.id);
    const isAssemblyRoot = assemblyRoot?.id === node.id;
    const invalidDrop =
      dragId !== null &&
      (dragId === node.id || isDescendant(scene, dragId, node.id));

    return (
      <div key={node.id}>
        <div
          className={"tree-row" + (selected ? " selected" : "") + (dragover ? " dragover" : "")}
          style={{ paddingLeft: 8 + depth * 16 }}
          draggable
          onDragStart={() => setDragId(node.id)}
          onDragEnd={() => {
            setDragId(null);
            setDropTarget(null);
          }}
          onDragOver={(e) => {
            if (!dragId || invalidDrop) return;
            e.preventDefault();
            setDropTarget(node.id);
          }}
          onDragLeave={() => setDropTarget((t) => (t === node.id ? null : t))}
          onDrop={(e) => {
            e.preventDefault();
            if (dragId && !invalidDrop && isGroup) requestMove(dragId, node.id);
            setDragId(null);
            setDropTarget(null);
          }}
          onClick={() => select(node.id)}
        >
          <span
            className="tree-caret"
            onClick={(e) => {
              e.stopPropagation();
              if (!isGroup) return;
              setCollapsed((prev) => {
                const next = new Set(prev);
                if (next.has(node.id)) next.delete(node.id);
                else next.add(node.id);
                return next;
              });
            }}
          >
            {isGroup ? (isOpen ? "▾" : "▸") : ""}
          </span>
          <span className="tree-icon">
            {isGroup && !isOpen ? <FolderOpen size={15} /> : TYPE_ICON[node.type]}
          </span>
          <span className="tree-name" title={node.id}>
            {node.name}
          </span>
          {node.assembly && (
            <span className={"badge" + (isAssemblyRoot ? " linked" : " part")} title={`装配件 v${node.assembly.assembly_version}`}>
              {isAssemblyRoot ? "装配件" : "部件"}
            </span>
          )}
          <span className="tree-actions">
            <button
              title="复制整个组（含子物体）"
              onClick={(e) => {
                e.stopPropagation();
                select(node.id);
                void duplicate();
              }}
            >
              <Copy size={13} />
            </button>
            <button
              title="删除（含整个子树）"
              onClick={(e) => {
                e.stopPropagation();
                select(node.id);
                void remove();
              }}
            >
              <Trash2 size={13} />
            </button>
          </span>
        </div>
        {isOpen &&
          node.children.map((cid) => {
            const child = index.get(cid);
            return child ? renderNode(child, depth + 1) : null;
          })}
      </div>
    );
  };

  return (
    <div className="panel hierarchy">
      <div className="panel-title">场景层级</div>
      <div
        className={"tree-root-zone" + (dropTarget === "__root__" ? " dragover" : "")}
        onDragOver={(e) => {
          if (dragId) e.preventDefault();
          setDropTarget("__root__");
        }}
        onDragLeave={() => setDropTarget((t) => (t === "__root__" ? null : t))}
        onDrop={(e) => {
          e.preventDefault();
          if (dragId) requestMove(dragId, null);
          setDragId(null);
          setDropTarget(null);
        }}
      >
        {scene.root_ids.length === 0 && (
          <div className="tree-empty">空场景，从左侧工具栏添加物体</div>
        )}
        {scene.root_ids.map((rid) => {
          const node = index.get(rid);
          return node ? renderNode(node, 0) : null;
        })}
        <div className="tree-root-hint">拖到此处 = 移到场景根层级</div>
      </div>

      {askKeep && (
        <div className="modal-backdrop" onClick={() => setAskKeep(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>换到另一个组</h3>
            <p>是否保持眼前的世界位置？</p>
            <p className="modal-hint">
              保持位置时，后台会按新父级的旋转/缩放重新计算该节点的相对位置。
            </p>
            <div className="modal-actions">
              <button className="primary" onClick={() => void confirmMove(true)}>
                保持眼前位置
              </button>
              <button onClick={() => void confirmMove(false)}>
                保留局部数值（位置会跟着变）
              </button>
              <button onClick={() => setAskKeep(null)}>取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

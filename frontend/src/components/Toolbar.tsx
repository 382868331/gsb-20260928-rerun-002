import { useEffect, useState } from "react";
import { useStore } from "../lib/store";
import { PRIMITIVE_TYPES } from "../lib/types";
import { api, type SceneMeta } from "../lib/api";
import { ReleasePanel } from "./ReleasePanel";

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
  const fetchUpdatePreview = useStore((s) => s.fetchUpdatePreview);
  const pendingUpdates = useStore((s) => s.pendingUpdates);
  const setPendingUpdates = useStore((s) => s.setPendingUpdates);
  const applyAssemblyUpdate = useStore((s) => s.applyAssemblyUpdate);
  const selectedNode = useStore((s) =>
    s.scene.nodes.find((n) => n.id === s.selectedId) ?? null
  );
  const [assemblyChoice, setAssemblyChoice] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [showReleases, setShowReleases] = useState(false);

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
        <button
          title="查看原件有更新的实例，逐项决定跟随原件还是保留局部覆盖"
          onClick={async () => {
            setPreviewing(true);
            try {
              await fetchUpdatePreview();
            } finally {
              setPreviewing(false);
            }
          }}
        >
          {previewing ? "检查中…" : "检查原件更新"}
        </button>
        <button
          title="把整个总成锁定为可重开的发布版本；派生、对比不同供应批次"
          onClick={() => setShowReleases(true)}
        >
          发布版本…
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
      {pendingUpdates.length > 0 && (
        <UpdateDialog
          updates={pendingUpdates}
          onClose={() => setPendingUpdates([])}
          onApply={(assemblyId, choices) =>
            applyAssemblyUpdate(assemblyId, choices).then(() => {
              void fetchUpdatePreview();
            })
          }
        />
      )}
      {showReleases && <ReleasePanel onClose={() => setShowReleases(false)} />}
    </div>
  );
}

function UpdateDialog({
  updates,
  onClose,
  onApply,
}: {
  updates: import("../lib/types").AssemblyUpdatePreview[];
  onClose: () => void;
  onApply: (
    assemblyId: string,
    choices: {
      instanceIds?: string[];
      overrides?: Record<string, "follow" | "keep">;
      dropRemoved?: boolean;
    }
  ) => Promise<void>;
}) {
  const grouped = new Map<string, typeof updates>();
  for (const item of updates) {
    const list = grouped.get(item.assembly_id) ?? [];
    list.push(item);
    grouped.set(item.assembly_id, list);
  }
  const [choices, setChoices] = useState<Record<string, "follow" | "keep">>({});
  const [dropRemoved, setDropRemoved] = useState(false);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal update-dialog" onClick={(e) => e.stopPropagation()}>
        <h3>原件更新预览</h3>
        <p className="modal-hint">
          放弃更新不会改变场景；按装配件分组，逐个实例决定跟随原件或保留局部覆盖。
        </p>
        {[...grouped.entries()].map(([assemblyId, items]) => (
          <div key={assemblyId} className="update-group">
            <div className="update-group-title">
              {items[0].assembly_name}（v{items[0].from_version} → v{items[0].to_version}）
            </div>
            {items.map((item) => (
              <div key={item.instance_id} className="update-instance">
                <div className="update-instance-head">
                  <strong>{item.instance_name}</strong>
                  <select
                    value={choices[item.instance_id] ?? "follow"}
                    onChange={(e) =>
                      setChoices((prev) => ({
                        ...prev,
                        [item.instance_id]: e.target.value as "follow" | "keep",
                      }))
                    }
                  >
                    <option value="follow">跟随原件（丢弃本实例覆盖）</option>
                    <option value="keep">保留局部覆盖（作为普通部件脱离）</option>
                  </select>
                </div>
                {item.changed.length > 0 && (
                  <ul className="update-list">
                    {item.changed.map((change) => (
                      <li key={change.template_id}>
                        变化：{change.path}
                        {change.has_local_override ? <em className="warn"> · 有局部覆盖</em> : null}
                      </li>
                    ))}
                  </ul>
                )}
                {item.removed.length > 0 && (
                  <ul className="update-list">
                    {item.removed.map((change) => (
                      <li key={change.template_id} className="warn">
                        失去对应关系：{change.path}
                      </li>
                    ))}
                  </ul>
                )}
                {item.slots_removed.length > 0 && (
                  <ul className="update-list">
                    {item.slots_removed.map((slot) => (
                      <li key={slot.slot_key} className={slot.detached ? "" : "warn"}>
                        嵌套装配件移除：{slot.name}
                        {slot.detached ? "（此前已脱离）" : ""}
                      </li>
                    ))}
                  </ul>
                )}
                {item.added.length > 0 && (
                  <ul className="update-list">
                    {item.added.map((change) => (
                      <li key={change.template_id}>新增：{change.path}</li>
                    ))}
                  </ul>
                )}
                {item.slots_added.length > 0 && (
                  <ul className="update-list">
                    {item.slots_added.map((slot) => (
                      <li key={slot.slot_key}>新增嵌套装配件槽</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
            <label className="drop-removed">
              <input
                type="checkbox"
                checked={dropRemoved}
                onChange={(e) => setDropRemoved(e.target.checked)}
              />
              删除失去对应关系的部件（默认保留为普通节点）
            </label>
            <div className="modal-actions">
              <button
                className="primary"
                onClick={() =>
                  void onApply(assemblyId, {
                    instanceIds: items.map((item) => item.instance_id),
                    overrides: choices,
                    dropRemoved,
                  })
                }
              >
                应用本次更新（可撤销）
              </button>
              <button onClick={onClose}>放弃更新</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

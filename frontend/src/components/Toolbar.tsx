import { useEffect, useState } from "react";
import { useStore } from "../lib/store";
import { PRIMITIVE_TYPES, type ReleaseDerivePreview, type ReleaseSnapshot } from "../lib/types";
import { BatchDialog } from "./BatchDialog";
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
  const fetchUpdatePreview = useStore((s) => s.fetchUpdatePreview);
  const pendingUpdates = useStore((s) => s.pendingUpdates);
  const setPendingUpdates = useStore((s) => s.setPendingUpdates);
  const applyAssemblyUpdate = useStore((s) => s.applyAssemblyUpdate);
  const releases = useStore((s) => s.scene.releases) ?? [];
  const assemblyHistory = useStore((s) => s.scene.assembly_history) ?? [];
  const publishRelease = useStore((s) => s.publishRelease);
  const openRelease = useStore((s) => s.openRelease);
  const deriveRelease = useStore((s) => s.deriveRelease);
  const fetchDerivePreview = useStore((s) => s.fetchDerivePreview);
  const confirmBatchUpgrade = useStore((s) => s.confirmBatchUpgrade);
  const fetchBatchPreview = useStore((s) => s.fetchBatchPreview);
  const withdrawBatch = useStore((s) => s.withdrawBatch);
  const fetchBatchStatus = useStore((s) => s.fetchBatchStatus);
  const hasInstances = useStore((s) => s.scene.assembly_instances.length > 0);
  const liveInstances = useStore((s) => s.scene.assembly_instances);
  const nodes = useStore((s) => s.scene.nodes);
  const selectedNode = nodes.find((n) => n.id === selectedId) ?? null;
  const [assemblyChoice, setAssemblyChoice] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [releaseChoice, setReleaseChoice] = useState("");
  const [deriving, setDeriving] = useState<ReleaseSnapshot | null>(null);
  const [batching, setBatching] = useState<ReleaseSnapshot | null>(null);

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
      </div>
      <div className="tool-group">
        <button disabled={!canUndo} onClick={undo} title="Ctrl+Z">
          撤销
        </button>
        <button disabled={!canRedo} onClick={redo} title="Ctrl+Y">
          重做
        </button>
      </div>
      <div className="tool-group">
        <button
          disabled={!hasInstances}
          title="把当前总成（含各层子装配版本与实例覆盖）锁定为可重开的发布版本"
          onClick={() => {
            const name = window.prompt("发布版本名称", "发布 " + (releases.length + 1));
            if (name !== null) void publishRelease(name || undefined);
          }}
        >
          发布为版本
        </button>
        <select
          value={releaseChoice}
          onChange={(e) => setReleaseChoice(e.target.value)}
          disabled={releases.length === 0}
          title="选择已锁定的发布版本"
        >
          <option value="">发布版本…</option>
          {releases.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <button
          disabled={!releaseChoice}
          title="按发布时的状态重开总成；原件后来的更新不会混入（可撤销）"
          onClick={() => void openRelease(releaseChoice)}
        >
          打开
        </button>
        <button
          disabled={!releaseChoice}
          title="从该发布版派生新方案：可只升级部分子装配，其余层级保留旧版"
          onClick={() => {
            const release = releases.find((item) => item.id === releaseChoice);
            if (release) setDeriving(release);
          }}
        >
          派生…
        </button>
        <button
          disabled={!releaseChoice}
          title="按使用批次分批采用子装配升级：同批各实例可分别选择保留旧版或采用候选版"
          onClick={() => {
            const release = releases.find((item) => item.id === releaseChoice);
            if (release) setBatching(release);
          }}
        >
          分批升级…
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
      {deriving && (
        <DeriveDialog
          release={deriving}
          currentDefs={assemblies}
          history={assemblyHistory}
          onPreview={(upgrades) => fetchDerivePreview(deriving.id, upgrades)}
          onApply={async (upgrades) => {
            await deriveRelease(deriving.id, upgrades);
            setDeriving(null);
          }}
          onClose={() => setDeriving(null)}
        />
      )}
      {batching && (
        <BatchDialog
          release={batching}
          currentDefs={assemblies}
          history={assemblyHistory}
          liveInstances={liveInstances}
          onPreview={(instanceIds, targets) =>
            fetchBatchPreview(batching.id, instanceIds, targets)
          }
          onApply={async (instanceIds, targets, batchName) => {
            await confirmBatchUpgrade(batching.id, instanceIds, targets, batchName);
            setBatching(null);
          }}
          onWithdraw={(batchId) => withdrawBatch(batchId)}
          onStatus={() => fetchBatchStatus(batching.id)}
          onClose={() => setBatching(null)}
        />
      )}
    </div>
  );
}

function DeriveDialog({
  release,
  currentDefs,
  history,
  onPreview,
  onApply,
  onClose,
}: {
  release: ReleaseSnapshot;
  currentDefs: { id: string; name: string; version: number }[];
  history: { id: string; version: number }[];
  onPreview: (upgrades: Record<string, number>) => Promise<ReleaseDerivePreview>;
  onApply: (upgrades: Record<string, number>) => Promise<void>;
  onClose: () => void;
}) {
  // 发布快照里出现的各装配件及其钉住版本
  const pinned = new Map<string, { name: string; version: number }>();
  const walk = (states: ReleaseSnapshot["instances"]) => {
    for (const state of states) {
      const def = release.definitions.find(
        (d) => d.id === state.assembly_id && d.version === state.pinned_version
      );
      pinned.set(state.assembly_id, {
        name: def?.name ?? state.name,
        version: state.pinned_version,
      });
      walk(state.nested ?? []);
    }
  };
  walk(release.instances);

  const versionsOf = (assemblyId: string): number[] => {
    const set = new Set<number>();
    for (const def of currentDefs) if (def.id === assemblyId) set.add(def.version);
    for (const def of history) if (def.id === assemblyId) set.add(def.version);
    for (const def of release.definitions) if (def.id === assemblyId) set.add(def.version);
    return [...set].sort((a, b) => a - b);
  };

  const [upgrades, setUpgrades] = useState<Record<string, number>>({});
  const [preview, setPreview] = useState<ReleaseDerivePreview | null>(null);
  const [busy, setBusy] = useState(false);

  const refreshPreview = async (next: Record<string, number>) => {
    setBusy(true);
    try {
      setPreview(await onPreview(next));
    } finally {
      setBusy(false);
    }
  };

  const blocked = preview !== null && preview.missing.length > 0;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal update-dialog" onClick={(e) => e.stopPropagation()}>
        <h3>从「{release.name}」派生新方案</h3>
        <p className="modal-hint">
          默认全部保留发布时的旧版；只为需要升级的子装配选择新版本。放弃不会改动场景。
        </p>
        {[...pinned.entries()].map(([assemblyId, info]) => (
          <div key={assemblyId} className="update-instance-head">
            <strong>
              {info.name}（发布时 v{info.version}）
            </strong>
            <select
              value={upgrades[assemblyId] ?? info.version}
              onChange={(e) => {
                const version = Number(e.target.value);
                const next = { ...upgrades };
                if (version === info.version) delete next[assemblyId];
                else next[assemblyId] = version;
                setUpgrades(next);
                setPreview(null);
              }}
            >
              {versionsOf(assemblyId).map((version) => (
                <option key={version} value={version}>
                  {version === info.version ? "保持 v" + version : "升级到 v" + version}
                </option>
              ))}
            </select>
          </div>
        ))}
        <div className="modal-actions">
          <button disabled={busy} onClick={() => void refreshPreview(upgrades)}>
            {busy ? "预览中…" : "预览差异"}
          </button>
          <button
            className="primary"
            disabled={blocked}
            onClick={() => void onApply(upgrades)}
          >
            应用派生（可撤销）
          </button>
          <button onClick={onClose}>放弃升级</button>
        </div>
        {preview && (
          <div className="update-group">
            {preview.missing.length > 0 && (
              <ul className="update-list">
                {preview.missing.map((item) => (
                  <li key={item.instance_id + item.assembly_id} className="warn">
                    版本不可用：{item.instance_name} 需要 {item.assembly_name} v
                    {item.version}（已保留现场，不会用最新版代替）
                  </li>
                ))}
              </ul>
            )}
            {preview.kept.length > 0 && (
              <div className="update-group-title">
                保留旧版：
                {preview.kept.map((k) => k.assembly_name + " v" + k.version).join("、")}
              </div>
            )}
            {preview.items.map((item) => (
              <div key={item.instance_id + item.assembly_id} className="update-instance">
                <div className="update-instance-head">
                  <strong>
                    {item.instance_name}：{item.assembly_name} v{item.from_version} → v
                    {item.to_version}
                  </strong>
                </div>
                {item.changed.length > 0 && (
                  <ul className="update-list">
                    {item.changed.map((change) => (
                      <li key={change.template_id}>
                        上游升级：{change.path}
                        {change.has_local_override ? (
                          <em className="warn"> · 该实例有局部覆盖</em>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )}
                {item.removed.length > 0 && (
                  <ul className="update-list">
                    {item.removed.map((change) => (
                      <li key={change.template_id} className="warn">
                        部件删除：{change.path}
                      </li>
                    ))}
                  </ul>
                )}
                {item.added.length > 0 && (
                  <ul className="update-list">
                    {item.added.map((change) => (
                      <li key={change.template_id}>新增部件：{change.path}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
            {preview.items.length === 0 && preview.missing.length === 0 && (
              <p className="modal-hint">所有层级均保持发布时的版本，无差异。</p>
            )}
          </div>
        )}
      </div>
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

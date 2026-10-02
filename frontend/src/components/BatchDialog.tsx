import { useEffect, useMemo, useState } from "react";
import {
  type AssemblyInstance,
  type ReleaseBatchPreview,
  type ReleaseBatchStatus,
  type ReleaseSnapshot,
} from "../lib/types";

type DefLike = { id: string; name: string; version: number };

export function BatchDialog({
  release,
  currentDefs,
  history,
  liveInstances,
  onPreview,
  onApply,
  onWithdraw,
  onStatus,
  onClose,
}: {
  release: ReleaseSnapshot;
  currentDefs: DefLike[];
  history: DefLike[];
  liveInstances: AssemblyInstance[];
  onPreview: (
    instanceIds: string[],
    targets: Record<string, Record<string, number>>
  ) => Promise<ReleaseBatchPreview>;
  onApply: (
    instanceIds: string[],
    targets: Record<string, Record<string, number>>,
    batchName?: string
  ) => Promise<void>;
  onWithdraw: (batchId: string) => Promise<void>;
  onStatus: () => Promise<ReleaseBatchStatus>;
  onClose: () => void;
}) {
  // 发布快照中出现的装配件及各实例发布时钉住的版本
  const assemblies = useMemo(() => {
    const map = new Map<string, { name: string; version: number }>();
    const walk = (states: ReleaseSnapshot["instances"]) => {
      for (const state of states) {
        if (!map.has(state.assembly_id)) {
          const def = release.definitions.find(
            (d) => d.id === state.assembly_id && d.version === state.pinned_version
          );
          map.set(state.assembly_id, {
            name: def?.name ?? state.name,
            version: state.pinned_version,
          });
        }
        walk(state.nested ?? []);
      }
    };
    walk(release.instances);
    return map;
  }, [release]);

  const versionsOf = (assemblyId: string): number[] => {
    const set = new Set<number>();
    for (const def of currentDefs) if (def.id === assemblyId) set.add(def.version);
    for (const def of history) if (def.id === assemblyId) set.add(def.version);
    for (const def of release.definitions) if (def.id === assemblyId) set.add(def.version);
    return [...set].sort((a, b) => a - b);
  };

  const topIds = release.instances.map((s) => s.instance_id);
  const [checked, setChecked] = useState<Record<string, boolean>>(
    Object.fromEntries(topIds.map((id) => [id, false]))
  );
  const [targets, setTargets] = useState<Record<string, Record<string, number>>>({});
  const [preview, setPreview] = useState<ReleaseBatchPreview | null>(null);
  const [status, setStatus] = useState<ReleaseBatchStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [batchName, setBatchName] = useState("");

  const refreshStatus = async () => {
    try {
      setStatus(await onStatus());
    } catch {
      // 状态查询失败不阻塞选择
    }
  };
  useEffect(() => {
    void refreshStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [release.id]);

  const selectedIds = topIds.filter((id) => checked[id]);
  // 只把真正改变的版本作为升级目标，保留旧版的实例仍包含在本批（记录“本批决定保留”）
  const effectiveTargets = () => {
    const out: Record<string, Record<string, number>> = {};
    for (const id of selectedIds) {
      const entry = targets[id] ?? {};
      const filtered: Record<string, number> = {};
      for (const [assemblyId, version] of Object.entries(entry)) {
        const pinned = assemblies.get(assemblyId)?.version;
        if (pinned !== undefined && version !== pinned) filtered[assemblyId] = version;
      }
      out[id] = filtered;
    }
    return out;
  };

  const doPreview = async () => {
    setBusy(true);
    try {
      setPreview(await onPreview(selectedIds, effectiveTargets()));
    } finally {
      setBusy(false);
    }
  };

  const doApply = async () => {
    setBusy(true);
    try {
      await onApply(
        selectedIds,
        effectiveTargets(),
        batchName.trim() || undefined
      );
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const doWithdraw = async (batchId: string) => {
    setBusy(true);
    try {
      await onWithdraw(batchId);
      await refreshStatus();
      setPreview(null);
    } finally {
      setBusy(false);
    }
  };

  const blocked = preview !== null && preview.missing.length > 0;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal update-dialog" onClick={(e) => e.stopPropagation()}>
        <h3>分批采用升级：{release.name}</h3>
        <p className="modal-hint">
          勾选本批次确认的实例；每个实例可分别选择保留旧版或采用候选版。
          未勾选的实例仍保持原版本；两批共用的子装配不会互相带走选择。
        </p>

        {status && status.batches.length > 0 && (
          <div className="update-group">
            <div className="update-group-title">已保存的批次决定（从记录继续）</div>
            {status.batches.map((b) => (
              <div key={b.batch_id} className="update-instance-head">
                <span>{b.name}</span>
                <button
                  disabled={busy}
                  title="撤回该批：只还原该批自己的版本与覆盖，其余已确认批次不回退"
                  onClick={() => void doWithdraw(b.batch_id)}
                >
                  撤回此批
                </button>
              </div>
            ))}
            <ul className="update-list">
              {status.instances.map((info) => (
                <li key={info.instance_id}>
                  {info.instance_name}：发布时 v{info.released_version}，现场 v
                  {info.live_version ?? "—"}
                  {info.confirmed && info.last_batch_name ? `（已由「${info.last_batch_name}」确认）` : "（未确认）"}
                </li>
              ))}
            </ul>
          </div>
        )}

        {release.instances.map((state) => {
          const live = liveInstances.find((i) => i.id === state.instance_id);
          return (
            <div key={state.instance_id} className="update-group">
              <div className="update-instance-head">
                <label>
                  <input
                    type="checkbox"
                    checked={Boolean(checked[state.instance_id])}
                    onChange={(e) =>
                      setChecked((prev) => ({ ...prev, [state.instance_id]: e.target.checked }))
                    }
                  />
                  <strong>{state.name}</strong>
                  <em className="modal-hint">
                    现场 v{live?.pinned_version ?? "不存在"}
                  </em>
                </label>
              </div>
              {checked[state.instance_id] && (
                <NestedVersionPickers
                  state={state}
                  release={release}
                  versionsOf={versionsOf}
                  value={targets[state.instance_id] ?? {}}
                  onChange={(next) =>
                    setTargets((prev) => ({ ...prev, [state.instance_id]: next }))
                  }
                />
              )}
            </div>
          );
        })}

        <div className="modal-actions">
          <input
            value={batchName}
            onChange={(e) => setBatchName(e.target.value)}
            placeholder="批次名称（可选）"
          />
          <button disabled={busy || selectedIds.length === 0} onClick={() => void doPreview()}>
            {busy ? "处理中…" : "预览本批差异"}
          </button>
          <button className="primary" disabled={busy || blocked || selectedIds.length === 0} onClick={() => void doApply()}>
            确认本批（可撤销）
          </button>
          <button onClick={onClose}>关闭</button>
        </div>

        {preview && (
          <PreviewBody preview={preview} selectedIds={selectedIds} />
        )}
      </div>
    </div>
  );
}

function NestedVersionPickers({
  state,
  release,
  versionsOf,
  value,
  onChange,
}: {
  state: ReleaseSnapshot["instances"][number];
  release: ReleaseSnapshot;
  versionsOf: (id: string) => number[];
  value: Record<string, number>;
  onChange: (next: Record<string, number>) => void;
}) {
  const rows: Array<{ key: string; label: string; assemblyId: string; pinned: number }> = [];
  const walk = (
    s: ReleaseSnapshot["instances"][number],
    label: string
  ) => {
    rows.push({ key: s.instance_id, label, assemblyId: s.assembly_id, pinned: s.pinned_version });
    for (const child of s.nested ?? []) {
      walk(child, `${label} / ${child.slot_key ?? child.instance_id}`);
    }
  };
  walk(state, state.name);
  return (
    <div>
      {rows.map((row) => {
        const def = release.definitions.find(
          (d) => d.id === row.assemblyId && d.version === row.pinned
        );
        const name = def?.name ?? row.assemblyId;
        const current = value[row.assemblyId] ?? row.pinned;
        return (
          <div key={row.key} className="update-instance-head">
            <span title={row.label}>{row.label}</span>
            <select
              value={current}
              onChange={(e) =>
                onChange({ ...value, [row.assemblyId]: Number(e.target.value) })
              }
            >
              {versionsOf(row.assemblyId).map((version) => (
                <option key={version} value={version}>
                  {version === row.pinned ? `保留${name} v${version}` : `采用${name} v${version}`}
                </option>
              ))}
            </select>
          </div>
        );
      })}
    </div>
  );
}

function PreviewBody({
  preview,
  selectedIds,
}: {
  preview: ReleaseBatchPreview;
  selectedIds: string[];
}) {
  return (
    <div className="update-group">
      {preview.missing.length > 0 && (
        <ul className="update-list">
          {preview.missing.map((item) => (
            <li key={item.assembly_id + item.version} className="warn">
              版本不可用：实例 {item.instance_names.join("、")} 需要 {item.assembly_name} v
              {item.version}（{item.reason}）；已保留现场，不会用最新版代替
            </li>
          ))}
        </ul>
      )}
      {preview.not_in_batch.length > 0 && (
        <div className="update-group-title">
          本批不确认，仍保持原版本：
          {preview.not_in_batch.map((i) => i.instance_name).join("、")}
        </div>
      )}
      {preview.items.map((item) => (
        <div key={item.instance_id + item.assembly_id} className="update-instance">
          <div className="update-instance-head">
            <strong>
              {item.instance_name}：{item.assembly_name} v{item.from_version} → v{item.to_version}
            </strong>
          </div>
          {item.overrides.map((ov) => (
            <div key={ov.template_id} className="modal-hint">
              覆盖值 {ov.path}：
              {ov.scale ? ` 缩放 ${ov.scale.join("/")}` : ""}
              {ov.position ? ` 位置 ${ov.position.map((v) => v.toFixed(2)).join(",")}` : ""}
              — {ov.effect}
            </div>
          ))}
          {item.removed.map((change) => (
            <div key={change.template_id} className="warn">
              被删除部件：{change.path}（保留为普通节点，不再链接原件）
            </div>
          ))}
          {item.selection_refs.map((ref) => (
            <div key={ref.template_id} className="warn">
              选中引用影响：{ref.effect}
            </div>
          ))}
          {item.changed.map((change) => (
            <div key={change.template_id}>
              上游升级：{change.path}
              {change.has_local_override ? "（该实例覆盖会遮盖此变化）" : ""}
            </div>
          ))}
          {item.added.map((change) => (
            <div key={change.template_id}>新增部件：{change.path}</div>
          ))}
        </div>
      ))}
      {selectedIds.length > 0 && preview.items.length === 0 && preview.missing.length === 0 && (
        <p className="modal-hint">本批实例全部选择保留旧版，现场不会发生版本变化。</p>
      )}
    </div>
  );
}

import { useState } from "react";
import { useStore } from "../lib/store";
import type { AssemblyRelease, DerivePreviewItem } from "../lib/types";

function useAssemblyName() {
  const scene = useStore((s) => s.scene);
  return (assemblyId: string) =>
    scene.assembly_defs.find((d) => d.id === assemblyId)?.name ??
    scene.assembly_history?.find((d) => d.id === assemblyId)?.name ??
    assemblyId;
}

function useVersionsOf() {
  const scene = useStore((s) => s.scene);
  return (assemblyId: string) => {
    const versions = new Set<number>();
    for (const item of scene.assembly_history ?? []) {
      if (item.id === assemblyId) versions.add(item.version);
    }
    for (const item of scene.assembly_defs) {
      if (item.id === assemblyId) versions.add(item.version);
    }
    return [...versions].sort((a, b) => a - b);
  };
}

function pinLabel(release: AssemblyRelease, path: string) {
  if (!path) return (release.root_name || "总成") + "（根）";
  return (release.root_name || "总成") + " / " + path.split("/").join(" / ");
}

export function ReleasePanel({ onClose }: { onClose: () => void }) {
  const scene = useStore((s) => s.scene);
  const selectedId = useStore((s) => s.selectedId);
  const publishRelease = useStore((s) => s.publishRelease);
  const openRelease = useStore((s) => s.openRelease);
  const deleteRelease = useStore((s) => s.deleteRelease);
  const [publishName, setPublishName] = useState("");
  const [deriving, setDeriving] = useState<AssemblyRelease | null>(null);

  const releases = scene.releases ?? [];
  const selectedNode = scene.nodes.find((n) => n.id === selectedId);
  const canPublish = Boolean(selectedNode?.assembly);
  const releaseName = (id: string | null | undefined) =>
    releases.find((r) => r.id === id)?.name ?? null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal update-dialog" onClick={(e) => e.stopPropagation()}>
        <h3>发布版本（锁定总成）</h3>
        <p className="modal-hint">
          发布会把整个总成的各层子装配版本与当前实例覆盖锁定；原件后来更新，
          已发布版本仍按当时状态打开，不会自动混入新部件。
        </p>
        <div className="release-publish">
          <input
            placeholder="发布版本名称（可选）"
            value={publishName}
            onChange={(e) => setPublishName(e.target.value)}
          />
          <button
            className="primary"
            disabled={!canPublish}
            title={canPublish ? "把选中的顶层实例锁定为发布版本" : "请先选中一个装配件实例"}
            onClick={() =>
              void publishRelease(publishName || undefined).then(() => setPublishName(""))
            }
          >
            发布选中总成
          </button>
        </div>
        {releases.length === 0 && <p className="modal-hint">还没有发布版本。</p>}
        {releases.map((release) => (
          <div key={release.id} className="update-group">
            <div className="update-group-title">
              #{release.seq} {release.name}
              {release.source_release_id && (
                <span className="badge">
                  派生自 {releaseName(release.source_release_id) ?? "已删除发布版"}
                </span>
              )}
            </div>
            <ul className="update-list">
              {Object.entries(release.pins).map(([path, pin]) => (
                <li key={path || "__root"}>
                  {pinLabel(release, path)}：<PinName pin={pin} />
                  {release.upgrades[path] && (
                    <em>
                      {" "}
                      （本次升级 v{release.upgrades[path][0]} → v{release.upgrades[path][1]}）
                    </em>
                  )}
                </li>
              ))}
            </ul>
            <div className="modal-actions">
              <button onClick={() => void openRelease(release.id)}>打开到场景</button>
              <button onClick={() => setDeriving(release)}>派生新方案…</button>
              <button className="danger" onClick={() => void deleteRelease(release.id)}>
                删除
              </button>
            </div>
          </div>
        ))}
        <div className="modal-actions">
          <button onClick={onClose}>关闭</button>
        </div>
        {deriving && <DeriveDialog release={deriving} onClose={() => setDeriving(null)} />}
      </div>
    </div>
  );
}

function PinName({ pin }: { pin: { assembly_id: string; version: number } }) {
  const nameOf = useAssemblyName();
  return (
    <code className="assembly-version">
      {nameOf(pin.assembly_id)} v{pin.version}
    </code>
  );
}

function DeriveDialog({
  release,
  onClose,
}: {
  release: AssemblyRelease;
  onClose: () => void;
}) {
  const deriveReleasePreview = useStore((s) => s.deriveReleasePreview);
  const deriveRelease = useStore((s) => s.deriveRelease);
  const nameOf = useAssemblyName();
  const versionsOf = useVersionsOf();
  const [choices, setChoices] = useState<Record<string, number>>({});
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<DerivePreviewItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const upgrades = Object.fromEntries(
    Object.entries(choices).filter(([path, v]) => v !== release.pins[path]?.version)
  );

  const doPreview = async () => {
    setError(null);
    try {
      setPreview(await deriveReleasePreview(release.id, upgrades));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal update-dialog" onClick={(e) => e.stopPropagation()}>
        <h3>从「{release.name}」派生新方案</h3>
        <p className="modal-hint">
          只升级选中的子装配，其余层级继续保留旧版；放弃派生不会改变任何记录。
        </p>
        {Object.entries(release.pins).map(([path, pin]) => (
          <div key={path || "__root"} className="update-instance-head">
            <strong>
              {pinLabel(release, path)}：{nameOf(pin.assembly_id)}
            </strong>
            <select
              value={choices[path] ?? pin.version}
              onChange={(e) => {
                setChoices((prev) => ({ ...prev, [path]: Number(e.target.value) }));
                setPreview(null);
              }}
            >
              {versionsOf(pin.assembly_id).map((v) => (
                <option key={v} value={v}>
                  v{v}
                  {v === pin.version ? "（当前锁定）" : ""}
                </option>
              ))}
            </select>
          </div>
        ))}
        <input
          placeholder="新方案名称（可选）"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        {error && <p className="warn">⚠ {error}</p>}
        {preview && (
          <div>
            {preview.length === 0 && <p className="modal-hint">所选版本与当前锁定一致，没有差异。</p>}
            {preview.map((item) => (
              <div key={item.path || "__root"} className="update-instance">
                <div className="update-instance-head">
                  <strong>
                    {item.label}：{item.assembly_name}（v{item.from_version} → v{item.to_version}）
                  </strong>
                </div>
                {item.upstream_changed.length > 0 && (
                  <ul className="update-list">
                    {item.upstream_changed.map((c) => (
                      <li key={c.template_id}>上游升级变化：{c.path}</li>
                    ))}
                  </ul>
                )}
                {item.upstream_added.length > 0 && (
                  <ul className="update-list">
                    {item.upstream_added.map((c) => (
                      <li key={c.template_id}>上游新增部件：{c.path}</li>
                    ))}
                  </ul>
                )}
                {item.parts_removed.length > 0 && (
                  <ul className="update-list">
                    {item.parts_removed.map((c) => (
                      <li key={c.template_id} className="warn">
                        部件删除：{c.path}
                      </li>
                    ))}
                  </ul>
                )}
                {item.override_impacts.length > 0 && (
                  <ul className="update-list">
                    {item.override_impacts.map((c) => (
                      <li key={c.template_id}>
                        实例覆盖受影响：{c.path}
                        {c.part_removed ? <em className="warn">（该部件已被删除）</em> : null}
                      </li>
                    ))}
                  </ul>
                )}
                {item.slots_removed.length > 0 && (
                  <ul className="update-list">
                    {item.slots_removed.map((s) => (
                      <li key={s.slot_key} className="warn">
                        嵌套装配件移除：{nameOf(s.assembly_id)}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
        <div className="modal-actions">
          <button disabled={Object.keys(upgrades).length === 0} onClick={() => void doPreview()}>
            预览差异
          </button>
          <button
            className="primary"
            disabled={Object.keys(upgrades).length === 0}
            onClick={() =>
              void deriveRelease(release.id, upgrades, name || undefined).then(onClose)
            }
          >
            生成派生版本（可撤销）
          </button>
          <button onClick={onClose}>放弃派生</button>
        </div>
      </div>
    </div>
  );
}

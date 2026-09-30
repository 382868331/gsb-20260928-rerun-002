import { useEffect, useMemo, useState } from "react";
import { useStore } from "../lib/store";
import type { AssemblyPending } from "../lib/types";

const KIND_LABEL: Record<string, string> = {
  changed: "有上游变化",
  added: "新增部件",
  removed: "失去对应关系",
};

export function UpdateDialog() {
  const pendingUpdates = useStore((s) => s.pendingUpdates);
  const applyAssemblyUpdates = useStore((s) => s.applyAssemblyUpdates);
  const select = useStore((s) => s.select);
  const [open, setOpen] = useState(false);
  const [choices, setChoices] = useState<
    Record<string, Record<string, "follow" | "keep">>
  >({});

  const affectedCount = useMemo(
    () => pendingUpdates.reduce((sum, p) => sum + p.changes.length, 0),
    [pendingUpdates]
  );

  useEffect(() => {
    if (!open) return;
    const initial: typeof choices = {};
    for (const pending of pendingUpdates) {
      initial[pending.instance_id] = {};
      for (const change of pending.changes) {
        initial[pending.instance_id][change.template_id] =
          change.has_local_override || change.kind === "removed" ? "keep" : "follow";
      }
    }
    setChoices(initial);
  }, [open, pendingUpdates]);

  if (pendingUpdates.length === 0) return null;

  const setChoice = (
    instanceId: string,
    templateId: string,
    policy: "follow" | "keep"
  ) =>
    setChoices((prev) => ({
      ...prev,
      [instanceId]: { ...prev[instanceId], [templateId]: policy },
    }));

  const locate = (pending: AssemblyPending) => {
    if (pending.root_node_id) {
      select(pending.root_node_id);
      setOpen(false);
    }
  };

  return (
    <>
      <button className="update-banner" onClick={() => setOpen(true)}>
        {pendingUpdates.length} 个实例有原件更新（{affectedCount} 个部件待决定）
      </button>
      {open && (
        <div className="modal-backdrop" onClick={() => setOpen(false)}>
          <div className="modal update-modal" onClick={(e) => e.stopPropagation()}>
            <h3>选择性接收原件更新</h3>
            <p className="modal-hint">
              逐项决定「跟随原件」还是「保留本地」。放弃更新不会改变现场；整次应用后可用 Ctrl+Z 撤销。
            </p>
            {pendingUpdates.map((pending) => (
              <div key={pending.instance_id} className="update-instance">
                <div className="update-instance-head">
                  <strong>{pending.name}</strong>
                  <span className="badge">
                    {pending.assembly_name} v{pending.from_version} → v{pending.to_version}
                  </span>
                  <button onClick={() => locate(pending)}>在层级中定位</button>
                </div>
                {pending.changes.map((change) => (
                  <div key={change.template_id} className="update-part">
                    <span className="update-part-name" title={change.template_id}>
                      {change.name}
                    </span>
                    <span className={"update-kind kind-" + change.kind}>
                      {KIND_LABEL[change.kind]}
                      {change.has_local_override ? " · 有局部覆盖" : ""}
                    </span>
                    <select
                      value={choices[pending.instance_id]?.[change.template_id] ?? "follow"}
                      onChange={(e) =>
                        setChoice(
                          pending.instance_id,
                          change.template_id,
                          e.target.value as "follow" | "keep"
                        )
                      }
                    >
                      {change.kind === "removed" ? (
                        <option value="keep">保留为独立部件</option>
                      ) : (
                        <option value="follow">跟随原件</option>
                      )}
                      {change.kind === "removed" ? (
                        <option value="follow">跟随删除</option>
                      ) : (
                        <option value="keep">保留本地</option>
                      )}
                    </select>
                  </div>
                ))}
              </div>
            ))}
            <div className="modal-actions">
              <button
                className="primary"
                onClick={() => {
                  void applyAssemblyUpdates(choices).then(() => setOpen(false));
                }}
              >
                按选择应用更新
              </button>
              <button onClick={() => setOpen(false)}>放弃更新（现场不变）</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

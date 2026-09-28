import { useEffect, useState } from "react";
import type { SceneNode } from "../types";
import { useStore } from "../store";
import { worldTRS } from "../sceneOps";

const AXES = ["X", "Y", "Z"] as const;
const RAD2DEG = 180 / Math.PI;
const DEG2RAD = Math.PI / 180;

function NumberField({ label, value, onCommit, step = 0.1 }: {
  label: string; value: number; step?: number;
  onCommit: (v: number) => void;
}) {
  const [text, setText] = useState(String(Number(value.toFixed(4))));
  useEffect(() => setText(String(Number(value.toFixed(4)))), [value]);
  return (
    <label className="num-field">
      <span>{label}</span>
      <input
        type="number" step={step} value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => { const v = parseFloat(text); if (!Number.isNaN(v)) onCommit(v); else setText(String(value)); }}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
      />
    </label>
  );
}

function Vec3Editor({ title, values, degrees, onChange }: {
  title: string; values: readonly number[]; degrees?: boolean;
  onChange: (v: [number, number, number]) => void;
}) {
  return (
    <fieldset className="vec3">
      <legend>{title}</legend>
      <div className="vec3-row">
        {AXES.map((axis, i) => (
          <NumberField
            key={axis} label={axis}
            value={degrees ? values[i] * RAD2DEG : values[i]}
            step={degrees ? 5 : 0.1}
            onCommit={(v) => {
              const next = [...values] as [number, number, number];
              next[i] = degrees ? v * DEG2RAD : v;
              onChange(next);
            }}
          />
        ))}
      </div>
    </fieldset>
  );
}

export function Inspector() {
  const doc = useStore((s) => s.doc);
  const selectedIds = useStore((s) => s.selectedIds);
  const update = useStore((s) => s.updateNodeImmediate);
  const id = selectedIds[0] ?? null;
  const node: SceneNode | null = id ? doc.nodes[id] ?? null : null;

  if (!node) {
    return (
      <div className="inspector">
        <h3>检视面板</h3>
        <p className="hint">在层级树或 3D 视图中点选一个节点后，可在此调整位置、旋转和缩放。</p>
      </div>
    );
  }

  const world = worldTRS(doc)[node.id];

  return (
    <div className="inspector">
      <h3>检视面板</h3>
      <label className="name-edit">
        <span>名称</span>
        <input value={node.name} onChange={(e) => update(node.id, { name: e.target.value }, "重命名")} />
      </label>
      <div className="meta-line">类型：<b>{node.type}</b> ｜ 父级：<b>{node.parent ? doc.nodes[node.parent]?.name : "场景根级"}</b></div>

      <Vec3Editor title="位置 Position（相对父级）" values={node.position}
        onChange={(v) => update(node.id, { position: v })} />
      <Vec3Editor title="旋转 Rotation（度）" values={node.rotation} degrees
        onChange={(v) => update(node.id, { rotation: v })} />
      <Vec3Editor title="缩放 Scale" values={node.scale}
        onChange={(v) => update(node.id, { scale: v })} />

      <fieldset className="vec3 world">
        <legend>最终世界位置（前端计算）</legend>
        <div className="world-pos">
          {world.position.map((v, i) => <span key={i}>{AXES[i]} {v.toFixed(3)}</span>)}
        </div>
      </fieldset>
    </div>
  );
}

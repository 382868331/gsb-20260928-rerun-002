import { useEffect, useState } from "react";
import * as THREE from "three";
import { useStore } from "../lib/store";
import type { SceneNode, Vec3 } from "../lib/types";

const RAD2DEG = 180 / Math.PI;
const DEG2RAD = Math.PI / 180;

function eulerFromNode(node: SceneNode): Vec3 {
  const q = new THREE.Quaternion(...node.transform.rotation);
  const e = new THREE.Euler().setFromQuaternion(q, "XYZ");
  return [e.x, e.y, e.z];
}

function NumberRow({
  label,
  values,
  step,
  suffix,
  onChange,
}: {
  label: string;
  values: number[];
  step: number;
  suffix: string;
  onChange: (next: Vec3) => void;
}) {
  const axes = ["X", "Y", "Z"];
  return (
    <div className="num-row">
      <span className="num-label">{label}</span>
      {values.map((v, i) => (
        <label key={i}>
          <em>{axes[i]}</em>
          <input
            type="number"
            step={step}
            value={Number(v.toFixed(4))}
            onChange={(e) => {
              const next = [...values] as Vec3;
              next[i] = parseFloat(e.target.value) || 0;
              onChange(next);
            }}
          />
          <i>{suffix}</i>
        </label>
      ))}
    </div>
  );
}

export function Inspector() {
  const scene = useStore((s) => s.scene);
  const selectedId = useStore((s) => s.selectedId);
  const updateTransform = useStore((s) => s.updateTransform);
  const clearOverride = useStore((s) => s.clearOverride);
  const detachAssembly = useStore((s) => s.detachAssembly);
  const assemblyEditMode = useStore((s) => s.assemblyEditMode);
  const setAssemblyEditMode = useStore((s) => s.setAssemblyEditMode);
  const assemblies = useStore((s) => s.scene.assembly_defs);
  const addNestedSlot = useStore((s) => s.addNestedSlot);
  const world = useStore((s) => s.world);
  const [nestedChoice, setNestedChoice] = useState("");

  const node = scene.nodes.find((n) => n.id === selectedId) ?? null;
  const [eulerDeg, setEulerDeg] = useState<Vec3>([0, 0, 0]);
  const [scaleDraft, setScaleDraft] = useState<Vec3>([1, 1, 1]);

  useEffect(() => {
    if (node) {
      const e = eulerFromNode(node);
      setEulerDeg([e[0] * RAD2DEG, e[1] * RAD2DEG, e[2] * RAD2DEG]);
      setScaleDraft([...node.transform.scale] as Vec3);
    }
  }, [node?.id, node?.transform.rotation.join(), node?.transform.scale.join()]);

  const worldInfo = world.find((w) => w.id === selectedId);
  const definition = node?.assembly
    ? scene.assembly_defs.find((item) => item.id === node.assembly!.assembly_id)
    : null;
  const instance = node?.assembly
    ? scene.assembly_instances.find((item) => item.id === node.assembly!.instance_id)
    : null;
  const isAssemblyRoot = Boolean(
    node?.assembly && definition && definition.root_ids.includes(node.assembly.template_id)
  );
  const activeMode = node?.assembly
    ? isAssemblyRoot
      ? "instance"
      : assemblyEditMode
    : "instance";
  const hasOverride = Boolean(
    node?.assembly && instance?.overrides[node.assembly.template_id]
  );
  const linkedInstances = node?.assembly
    ? scene.assembly_instances.filter(
        (item) => item.assembly_id === node.assembly?.assembly_id
      )
    : [];

  if (!node) {
    return (
      <div className="panel inspector">
        <div className="panel-title">检查器</div>
        <div className="inspector-empty">在层级或视口中选中一个节点</div>
      </div>
    );
  }

  return (
    <div className="panel inspector">
      <div className="panel-title">检查器</div>
      <div className="inspector-head">
        <strong>{node.name}</strong>
        <span className="badge">{node.type}</span>
      </div>

      {node.assembly && definition && (
        <>
          <div className="inspector-section">
            装配件：{definition.name}
            <code className="assembly-version">v{definition.version}</code>
          </div>
          <div className="assembly-actions">
            {!isAssemblyRoot && (
              <select
                value={activeMode}
                onChange={(e) =>
                  setAssemblyEditMode(e.target.value as "override" | "template")
                }
              >
                <option value="override">本实例覆盖</option>
                <option value="template">修改原件</option>
              </select>
            )}
            <button onClick={() => void detachAssembly()}>
              脱离原件
            </button>
            {hasOverride && (
              <button onClick={() => void clearOverride()}>清除覆盖</button>
            )}
          </div>
          <p className="modal-hint">
            {activeMode === "template"
              ? `正在修改原件 v${definition.version}，保存后仍链接该版本的实例会重新生成；已脱离实例不受影响。`
              : isAssemblyRoot
                ? "根节点位置保存在此实例上；复制实例可保留不同位置。"
                : `这些值只覆盖当前实例，不影响原件和其他 ${Math.max(linkedInstances.length - 1, 0)} 个实例。`}
          </p>
          {activeMode === "template" && (
            <p className="modal-hint">
              将更新 {linkedInstances.length} 个仍链接实例：
              {linkedInstances.map((item) => item.name).join("、")}
            </p>
          )}
          {activeMode === "template" && assemblies.length > 0 && (
            <div className="nested-slot">
              <select
                value={nestedChoice}
                onChange={(e) => setNestedChoice(e.target.value)}
                title="把另一个装配件作为嵌套引用放进当前原件"
              >
                <option value="">嵌套放入装配件…</option>
                {assemblies.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} v{item.version}
                  </option>
                ))}
              </select>
              <button
                disabled={!nestedChoice}
                onClick={() => void addNestedSlot(nestedChoice).then(() => setNestedChoice(""))}
              >
                放入
              </button>
            </div>
          )}
          {activeMode === "template" && (
            <p className="modal-hint">
              编辑原件只提升版本；点工具栏「检查原件更新」可预览受影响实例，
              相互引用的嵌套会被拒绝。
            </p>
          )}
        </>
      )}

      <div className="inspector-section">局部变换（相对父组）</div>
      <NumberRow
        label="位置"
        values={node.transform.position}
        step={0.1}
        suffix=""
        onChange={(position) => void updateTransform({ position }, activeMode)}
      />
      <NumberRow
        label="旋转"
        values={eulerDeg}
        step={5}
        suffix="°"
        onChange={(deg) => {
          setEulerDeg(deg);
          void updateTransform({
            rotationEuler: [deg[0] * DEG2RAD, deg[1] * DEG2RAD, deg[2] * DEG2RAD],
          }, activeMode);
        }}
      />
      <NumberRow
        label="缩放"
        values={scaleDraft}
        step={0.1}
        suffix="×"
        onChange={(scale) => {
          setScaleDraft(scale);
          void updateTransform({ scale }, activeMode);
        }}
      />

      <div className="inspector-section">
        世界变换（页面 three.js 与后端一致）
      </div>
      {worldInfo ? (
        <div className="world-info">
          <div>
            <span>世界位置</span>
            <code>
              ({worldInfo.position.map((v) => v.toFixed(3)).join(", ")})
            </code>
          </div>
          <div>
            <span>世界缩放</span>
            <code>({worldInfo.scale.map((v) => v.toFixed(3)).join(", ")})</code>
          </div>
          <div>
            <span>世界旋转(°)</span>
            <code>
              (
              {worldInfo.rotation_euler
                .map((v) => ((v * RAD2DEG) % 360).toFixed(1))
                .join(", ")}
              )
            </code>
          </div>
        </div>
      ) : (
        <div className="inspector-empty">等待后端计算…</div>
      )}
    </div>
  );
}

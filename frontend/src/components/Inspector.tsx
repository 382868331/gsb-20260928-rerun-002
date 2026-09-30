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
  const publishAssembly = useStore((s) => s.publishAssembly);
  const detachAssembly = useStore((s) => s.detachAssembly);
  const renameSelected = useStore((s) => s.renameSelected);
  const world = useStore((s) => s.world);

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
  const assemblyParent = node?.parent_id ? scene.nodes.find((n) => n.id === node.parent_id) : null;
  const isAssemblyRoot = Boolean(
    node?.assembly && assemblyParent?.assembly?.instance_id !== node.assembly.instance_id
  );

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
        <input
          defaultValue={node.name}
          onBlur={(e) => {
            if (e.target.value.trim() && e.target.value !== node.name) {
              void renameSelected(e.target.value);
            }
          }}
        />
        <span className="badge">{node.type}</span>
      </div>
      {node.assembly && (
        <div className="assembly-panel">
          <div>
            装配件实例 <code>v{node.assembly.assembly_version}</code>
          </div>
          <div className="assembly-overrides">
            覆盖：{node.assembly.overrides.length ? node.assembly.overrides.join("、") : "无"}
          </div>
          <div className="modal-actions">
            {isAssemblyRoot && (
              <button className="primary" onClick={() => void publishAssembly()} title="以当前实例更新原件，并同步其他链接实例">
                发布原件修改
              </button>
            )}
            <button onClick={() => void detachAssembly()} title="烘焙当前实例，之后不再随原件更新">
              脱离原件
            </button>
          </div>
        </div>
      )}

      <div className="inspector-section">局部变换（相对父组）</div>
      <NumberRow
        label="位置"
        values={node.transform.position}
        step={0.1}
        suffix=""
        onChange={(position) => void updateTransform({ position })}
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
          });
        }}
      />
      <NumberRow
        label="缩放"
        values={scaleDraft}
        step={0.1}
        suffix="×"
        onChange={(scale) => {
          setScaleDraft(scale);
          void updateTransform({ scale });
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

import { useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { worldTRS } from "../sceneOps";

interface Row {
  id: string;
  name: string;
  maxAbs: number;
  ok: boolean;
  fePos: number[];
  bePos: number[];
}

export function ConsistencyPanel() {
  const doc = useStore((s) => s.doc);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const fe = worldTRS(doc);
      const { world: be } = await api.computeWorld(doc);
      const out: Row[] = Object.keys(doc.nodes).map((id) => {
        const a = fe[id].matrix;
        const b = be[id].matrix;
        const maxAbs = Math.max(...a.map((v, i) => Math.abs(v - b[i])));
        return {
          id, name: doc.nodes[id].name, maxAbs, ok: maxAbs < 1e-6,
          fePos: fe[id].position, bePos: be[id].position,
        };
      });
      setRows(out.sort((x, y) => x.name.localeCompare(y.name)));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <details className="consistency">
      <summary>前后端最终位置一致性校验</summary>
      <button className="tb-btn small" onClick={run} disabled={busy}>{busy ? "校验中…" : "比对页面与后端矩阵"}</button>
      {error && <div className="error-line">{error}</div>}
      {rows && (
        <table>
          <thead><tr><th>节点</th><th>最大绝对误差</th><th>页面位置</th><th>后端位置</th><th></th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={r.ok ? "ok" : "bad"}>
                <td>{r.name}</td>
                <td>{r.maxAbs.toExponential(2)}</td>
                <td>({r.fePos.map((v) => v.toFixed(3)).join(", ")})</td>
                <td>({r.bePos.map((v) => v.toFixed(3)).join(", ")})</td>
                <td>{r.ok ? "✓ 一致" : "✗ 偏差"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {rows && rows.every((r) => r.ok) && <div className="ok-line">全部 {rows.length} 个节点的最终矩阵一致（容差 1e-6）</div>}
    </details>
  );
}

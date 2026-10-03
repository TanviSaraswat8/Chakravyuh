import { useEffect, useState } from "react";
import { api, pct } from "../lib/api";

const SPLITS: [string, string, string][] = [
  ["test_seen", "Known scam types, new wording", "Scam families seen in training, written with message wordings the models never saw."],
  ["test_evolved", "Evolved scams", "Mutations from the latest simulator generations, never used in training."],
  ["test_holdout", "A scam family never seen", "Fake e-challan scams, held out of training entirely."],
];
const SYSTEMS: [string, string][] = [
  ["rules", "Keyword rules"],
  ["per_txn_lightgbm", "Per-transaction model"],
  ["chakravyuh", "Chakravyuh"],
];

export default function Benchmark() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.meta().then(setData).catch((e) => setError(e.message)); }, []);
  const b = data?.benchmark;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Benchmark</h1>
          <p>Every system is scored on the same sessions. Recall is measured with the threshold set so only 1% of legitimate sessions would be flagged. The share of alerts that hit a real scam assumes 2% of sessions are scams, closer to real life than a test set.</p>
        </div>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {data && !b?.test_seen && <div className="panel"><p className="muted">No benchmark yet. Train the models with <code>make train</code>.</p></div>}
      <div className="stack">
        {b?.test_seen && SPLITS.map(([key, title, blurb]) => (
          <section key={key} className="panel">
            <div className="panel-title"><h2>{title}</h2><span>{blurb}</span></div>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>System</th>
                    <th className="num">Scams caught at 1% false-alarm rate</th>
                    <th className="num">Legit users nudged per 1,000</th>
                    <th className="num">Legit payments paused per 1,000</th>
                    <th className="num">Alerts that hit a real scam</th>
                    <th className="num">Warned stages before payment</th>
                  </tr>
                </thead>
                <tbody>
                  {SYSTEMS.map(([k, label]) => {
                    const r = b[key][k] ?? {};
                    const proj = r.projected_alerts_per_1000_users;
                    const useful = proj ? (proj - 0.98 * r.false_alerts_per_1000_legit) / proj : null;
                    return (
                      <tr key={k} className={k === "chakravyuh" ? "ours" : ""}>
                        <td>{label}</td>
                        <td className="num">{pct(r.recall_at_1pct_far)}</td>
                        <td className="num">{r.false_alerts_per_1000_legit ?? "–"}</td>
                        <td className="num">
                          {r.legit_interrupted_rate != null ? (r.legit_interrupted_rate * 1000).toFixed(1)
                            : r.false_alerts_per_1000_legit ?? "–"}
                        </td>
                        <td className="num">{pct(useful)}</td>
                        <td className="num">{r.mean_lead_stages ?? "–"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {b[key].chakravyuh?.expected_loss_prevented_share != null && (
              <p className="muted" style={{ marginTop: 12 }}>
                Expected share of money at stake that Chakravyuh's alerts would save: {pct(b[key].chakravyuh.expected_loss_prevented_share)}.
                Sessions flagged as matching no known family: {pct(b[key].unknown_flagged_share_of_scams)} of scams.
              </p>
            )}
          </section>
        ))}
        {b?.payee_model && (
          <section className="panel">
            <div className="panel-title"><h2>Models</h2></div>
            <dl className="kv">
              <dt>Sequence model parameters</dt><dd>{b.scamseq_params?.toLocaleString("en-IN")}</dd>
              <dt>Payee graph model, PR-AUC on held-out accounts</dt><dd>{b.payee_model.pr_auc?.toFixed(3)}</dd>
              <dt>Trained</dt><dd>{data.model?.trained_at ?? "–"}</dd>
            </dl>
            <p className="muted" style={{ marginTop: 12 }}>
              All numbers come from simulated sessions. Real-world performance must be measured with partner data during the beta.
              The legitimate sessions that still get nudged are genuine bank calls from unknown numbers with screen sharing;
              verified sender IDs (TRAI DLT headers) would separate them in production. A per-transaction rule can only
              act at the payment itself, so each of its false alerts pauses a legitimate payment.
            </p>
          </section>
        )}
      </div>
    </>
  );
}

import { useEffect, useState } from "react";
import { api, tacticLabel, TYPE_LABEL, type Campaign } from "../lib/api";

export default function Campaigns() {
  const [items, setItems] = useState<Campaign[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => api.campaigns().then(setItems).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const refresh = async () => {
    setBusy(true); setError(null);
    try {
      const r = await api.refreshCampaigns();
      setNote(`${r.created} new campaign${r.created === 1 ? "" : "s"} from ${r.unknown_sessions} sessions that matched no known scam.` +
        (r.drift_alarm ? ` Tactic mix has shifted from training data (PSI ${r.tactic_drift_psi.toFixed(2)}): schedule a simulator run.` : ""));
      await load();
    } catch (e: any) { setError(`Couldn't look for campaigns: ${e.message}`); }
    finally { setBusy(false); }
  };

  const decide = async (id: string, status: string) => {
    await api.setCampaign(id, status);
    await load();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Emerging campaigns</h1>
          <p>Risky sessions that don't match any scam family the models know are clustered together. Each cluster becomes a card an analyst can approve as a new pattern.</p>
        </div>
        <button className="btn indigo" onClick={refresh} disabled={busy}>{busy ? "Clustering sessions…" : "Look for new campaigns"}</button>
      </div>
      {note && <p className="chip saffron" style={{ marginBottom: 16 }}>{note}</p>}
      {error && <div className="error" role="alert">{error}</div>}
      {items.length === 0 && !busy && (
        <div className="panel"><p className="muted">No campaigns yet. Look for new campaigns to cluster unexplained risky sessions.</p></div>
      )}
      <div className="stack">
        {items.map((c) => (
          <article key={c.id} className="campaign">
            <div className="stack">
              <div className="row">
                <h2>{c.name}</h2>
                <span className={`chip ${c.status === "approved" ? "teal" : c.status === "rejected" ? "red" : ""}`}>
                  {c.status === "new" ? "Awaiting review" : c.status === "approved" ? "Approved" : "Rejected"}
                </span>
              </div>
              <div className="seq" aria-label="Typical sequence of events">
                {c.card.event_sequence.map((s, i) => <span key={i}>{TYPE_LABEL[s] ?? s}</span>)}
              </div>
              {c.card.example_message && <p className="quote">{c.card.example_message}</p>}
              <div>
                <h3 style={{ marginBottom: 6 }}>Draft detection rule</h3>
                <div className="rule">{c.card.draft_rule}</div>
              </div>
            </div>
            <div className="stack">
              <dl className="kv">
                <dt>Sessions</dt><dd>{c.size}</dd>
                <dt>Languages</dt><dd>{Object.keys(c.card.languages).join(", ")}</dd>
                <dt>Channels</dt><dd>{Object.keys(c.card.channels).join(", ")}</dd>
                <dt>Linked payees</dt><dd>{c.card.payee_clusters.length}</dd>
              </dl>
              <div className="tl-tags">{c.card.top_tactics.map((t) => <span key={t} className="chip">{tacticLabel(t)}</span>)}</div>
              {c.status === "new" && (
                <div className="row">
                  <button className="btn" onClick={() => decide(c.id, "approved")}>Approve pattern</button>
                  <button className="btn ghost" onClick={() => decide(c.id, "rejected")}>Reject</button>
                </div>
              )}
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

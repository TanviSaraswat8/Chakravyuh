import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Formation from "../components/Formation";
import Phone from "../components/Phone";
import { api, LEVELS, pct, tacticLabel, TYPE_LABEL, type Scenario, type ScenarioSummary } from "../lib/api";


function elapsed(seconds: number): string {
  if (seconds < 60) return `+${Math.round(seconds)}s`;
  if (seconds < 3600) return `+${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `+${(seconds / 3600).toFixed(1)}h`;
  return `+${(seconds / 86400).toFixed(1)}d`;
}

const riskColor = (p: number) => (p > 0.75 ? "var(--red)" : p > 0.4 ? "var(--saffron)" : "var(--teal)");

export default function LiveDemo() {
  const [list, setList] = useState<ScenarioSummary[]>([]);
  const [key, setKey] = useState("investment_group");
  const [sc, setSc] = useState<Scenario | null>(null);
  const [idx, setIdx] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [alertOpen, setAlertOpen] = useState<number | null>(null);
  const [stopped, setStopped] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    api.scenarios().then(setList).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    setSc(null); setIdx(-1); setPlaying(false); setAlertOpen(null); setStopped(false); setError(null);
    api.scenario(key).then(setSc).catch((e) => setError(`Couldn't load the scenario: ${e.message}. Is the API running on port 8000?`));
  }, [key]);

  const last = sc ? sc.events.length - 1 : -1;

  const advance = useCallback(() => {
    if (!sc) return;
    setIdx((i) => {
      const next = Math.min(i + 1, last);
      if (sc.scores[next]?.escalated) {
        setAlertOpen(next);
        setPlaying(false);
      }
      if (next >= last) setPlaying(false);
      return next;
    });
  }, [sc, last]);

  useEffect(() => {
    if (!playing) return;
    timer.current = window.setTimeout(advance, 1100);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [playing, idx, advance]);

  const step = idx >= 0 && sc ? sc.scores[idx] : null;
  const level = step?.level ?? 0;
  const p = step?.p ?? 0;

  const summary = useMemo(() => {
    if (!sc) return null;
    const firstPay = sc.events.findIndex((e) => e.type === "PAY" && !e.attrs.cancelled && (e.attrs.amount_ratio ?? 0) > 1.5);
    const ours = sc.scores.map((s, i) => (s.escalated ? i : -1)).filter((i) => i >= 0);
    const base = sc.baseline.map((b, i) => (b.alert ? i : -1)).filter((i) => i >= 0);
    const before = (arr: number[]) => (firstPay < 0 ? arr.length : arr.filter((i) => i < firstPay).length);
    return { firstPay, ours, base, oursBefore: before(ours), baseBefore: before(base) };
  }, [sc]);

  const reset = () => { setIdx(-1); setPlaying(false); setAlertOpen(null); setStopped(false); };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Live session</h1>
          <p>Watch a conversation unfold on a phone while Chakravyuh scores the whole session, not just the payment, and decides whether to speak.</p>
        </div>
      </div>

      <div className="scenario-tabs" role="group" aria-label="Choose a scenario">
        {list.map((s) => (
          <button key={s.key} className="scenario-tab" aria-pressed={s.key === key} onClick={() => setKey(s.key)}>
            <span>{s.title}</span>
            <small>{s.kind === "legit" ? "Legitimate look-alike" : "Scam"}</small>
          </button>
        ))}
      </div>

      {error && <div className="error" role="alert">{error}</div>}

      {sc && (
        <div className="demo-grid">
          <Phone
            events={sc.events}
            upto={idx}
            title={sc.kind === "legit" ? "Contact" : "Unknown sender"}
            alert={alertOpen != null ? sc.alerts[String(alertOpen)] ?? null : null}
            onDismiss={() => { setAlertOpen(null); setPlaying(true); }}
            onCancel={() => { setAlertOpen(null); setStopped(true); setPlaying(false); }}
          />

          <section className="panel" aria-label="Session timeline">
            <div className="controls">
              <button className="btn indigo" onClick={() => { if (idx >= last) reset(); setPlaying((x) => !x); }}
                      disabled={alertOpen != null || stopped}>
                {playing ? "Pause" : idx >= last ? "Replay" : idx < 0 ? "Play" : "Resume"}
              </button>
              <button className="btn ghost" onClick={advance} disabled={idx >= last || alertOpen != null || stopped}>Next event</button>
              <button className="btn ghost" onClick={reset}>Reset</button>
              <span className="muted">{sc.blurb}</span>
            </div>
            {stopped && (
              <p className="chip teal" style={{ marginBottom: 12 }}>Payment stopped before money left the account.</p>
            )}
            <div className="timeline">
              {sc.events.map((e, i) => {
                const s = sc.scores[i];
                return (
                  <div key={i} className={`tl-row${i <= idx ? " seen" : ""}${i === idx ? " current" : ""}`}>
                    <div className="tl-time">{elapsed(e.t)}</div>
                    <div>
                      <div className="tl-type">
                        {TYPE_LABEL[e.type] ?? e.type}
                        {i <= idx && s.escalated && <span className="esc-mark"> {LEVELS[s.level]} sent</span>}
                        {i <= idx && sc.baseline[i]?.alert && <span className="base-mark"> Transaction rule fires</span>}
                      </div>
                      {e.text && <div className="tl-text">{e.text}</div>}
                      {i <= idx && s.tactics.length > 0 && (
                        <div className="tl-tags">{s.tactics.map((t) => <span key={t} className="chip">{tacticLabel(t)}</span>)}</div>
                      )}
                    </div>
                    <div className="tl-risk">
                      {i <= idx ? pct(s.p) : ""}
                      {i <= idx && <div className="tl-bar"><i style={{ width: pct(s.p), background: riskColor(s.p) }} /></div>}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <aside className="demo-side stack">
            <section className="panel">
              <Formation level={level} p={p} />
            </section>
            <section className="panel">
              <div className="panel-title"><h3>What the model sees</h3></div>
              <dl className="kv">
                <dt>Session risk (sequence model)</dt><dd>{pct(step?.p_seq)}</dd>
                <dt>Message risk (tactic tagger)</dt><dd>{pct(step?.p_msg)}</dd>
                <dt>Payee mule risk (graph)</dt><dd>{pct(step?.r_payee)}</dd>
                <dt>Likely next step</dt><dd>{step?.next_stage?.replace(/_/g, " ") ?? "–"}</dd>
                <dt>Closest known pattern</dt><dd>{p > 0.5 ? sc.family_guess?.replace(/_/g, " ") ?? "new pattern" : "–"}</dd>
              </dl>
            </section>
            {summary && (
              <section className="panel">
                <div className="panel-title"><h3>Against a transaction rule</h3></div>
                <div className="compare">
                  <div>
                    <strong>{summary.oursBefore}</strong>
                    <span className="muted">Chakravyuh alerts before money moves</span>
                  </div>
                  <div>
                    <strong>{summary.baseBefore}</strong>
                    <span className="muted">Per-transaction rule alerts before money moves</span>
                  </div>
                </div>
                <p className="muted" style={{ marginTop: 10, fontSize: "0.85rem" }}>
                  {sc.kind === "legit"
                    ? "A good result here is zero: this is a real person, and interrupting them costs trust."
                    : "The rule only sees the payment itself, so it can't warn while the scam is still being set up."}
                </p>
              </section>
            )}
          </aside>
        </div>
      )}
    </>
  );
}

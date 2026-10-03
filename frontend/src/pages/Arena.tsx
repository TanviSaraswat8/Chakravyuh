import { useState } from "react";
import { api, pct, tacticLabel, type AdaptResult, type ArenaGen } from "../lib/api";

function GenerationChart({ history }: { history: ArenaGen[] }) {
  const W = 640, H = 260, pad = { l: 48, r: 16, t: 16, b: 40 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const bw = iw / Math.max(history.length, 1);
  return (
    <svg className="gen-chart" viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label={`Defender detection rate per attacker generation: ${history.map((h) => pct(h.detection_rate)).join(", ")}`}>
      {[0, 0.25, 0.5, 0.75, 1].map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={W - pad.r} y1={pad.t + ih * (1 - v)} y2={pad.t + ih * (1 - v)} stroke="#dde2ea" />
          <text x={pad.l - 8} y={pad.t + ih * (1 - v) + 4} textAnchor="end" fontSize="12" fill="#7b8496">{pct(v)}</text>
        </g>
      ))}
      {history.map((h, i) => {
        const x = pad.l + i * bw + bw * 0.18, w = bw * 0.64, hh = ih * h.detection_rate;
        const color = h.detection_rate > 0.8 ? "#3D3FBF" : h.detection_rate > 0.5 ? "#E39B17" : "#C8312E";
        return (
          <g key={h.generation}>
            <rect x={x} y={pad.t + ih - hh} width={w} height={Math.max(hh, 1)} rx="4" fill={color} />
            <text x={x + w / 2} y={pad.t + ih - hh - 6} textAnchor="middle" fontSize="12" fontWeight="700" fill="#1B2333">
              {pct(h.detection_rate)}
            </text>
            <text x={x + w / 2} y={H - 16} textAnchor="middle" fontSize="12" fill="#4a5468">Gen {h.generation}</text>
          </g>
        );
      })}
    </svg>
  );
}

export default function Arena() {
  const [history, setHistory] = useState<ArenaGen[]>([]);
  const [busy, setBusy] = useState<"arena" | "adapt" | null>(null);
  const [adapt, setAdapt] = useState<AdaptResult | null>(null);
  const [gens, setGens] = useState(6);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy("arena"); setError(null); setAdapt(null);
    try { setHistory((await api.arena(gens, 24)).history); }
    catch (e: any) { setError(`The arena didn't run: ${e.message}`); }
    finally { setBusy(null); }
  };
  const learn = async () => {
    setBusy("adapt"); setError(null);
    try {
      const r = await api.adapt();
      if (r.error) setError(r.error); else setAdapt(r);
    } catch (e: any) { setError(`Adapting failed: ${e.message}`); }
    finally { setBusy(null); }
  };

  const lastGen = history[history.length - 1];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Arena</h1>
          <p>Attacker agents mutate their scams each generation. The ones that steal money without being caught survive and breed. Then the defender learns from what they invented.</p>
        </div>
        <div className="row">
          <label className="field" style={{ flexDirection: "row", alignItems: "center" }}>
            <span>Generations</span>
            <select value={gens} onChange={(e) => setGens(Number(e.target.value))} aria-label="Number of generations">
              {[3, 4, 5, 6, 7, 8].map((n) => <option key={n}>{n}</option>)}
            </select>
          </label>
          <button className="btn indigo" onClick={run} disabled={busy != null}>
            {busy === "arena" ? "Attackers evolving…" : "Run the attackers"}
          </button>
        </div>
      </div>

      {error && <div className="error" role="alert">{error}</div>}

      {history.length === 0 && !busy && (
        <div className="panel"><p className="muted">Run the attackers to see how quickly scams adapt to a fixed defender.</p></div>
      )}

      {history.length > 0 && (
        <div className="arena-grid">
          <section className="panel">
            <div className="panel-title">
              <h2>Defender catch rate by attacker generation</h2>
              <span>Scams detected before money moves</span>
            </div>
            <GenerationChart history={history} />
          </section>

          <div className="stack">
            <section className="panel stack">
              <h2>What the attackers learned</h2>
              {lastGen?.top_genome && (
                <dl className="kv">
                  <dt>Scam family</dt><dd>{String(lastGen.top_genome.family).replace(/_/g, " ")}</dd>
                  <dt>Disguised opener</dt><dd>{lastGen.top_genome.borrow_contact ? String(lastGen.top_genome.borrow_contact).replace(/_/g, " ") : "none"}</dd>
                  <dt>Steps skipped</dt><dd>{(lastGen.top_genome.drop_stages ?? []).join(", ") || "none"}</dd>
                  <dt>Text tricks</dt><dd>{(lastGen.top_genome.text_ops ?? []).join(", ") || "none"}</dd>
                  <dt>Language</dt><dd>{lastGen.top_genome.language}</dd>
                </dl>
              )}
              {lastGen?.missed_examples.slice(0, 2).map((m, i) => (
                <div key={i} className="missed">
                  <strong>Got through: {tacticLabel(m.family)}</strong>
                  <div>{m.message}</div>
                </div>
              ))}
            </section>

            <section className="panel stack">
              <h2>Defender's turn</h2>
              <p className="muted">Fine-tune the sequence model on the attackers' newest scams, mixed with earlier data so it doesn't forget, then test on fresh variants it hasn't seen.</p>
              <button className="btn" onClick={learn} disabled={busy != null}>
                {busy === "adapt" ? "Learning from the attackers…" : "Learn from these attacks"}
              </button>
              {adapt && (
                <>
                  <div className="before-after">
                    <div><span className="muted">Caught before</span><strong>{pct(adapt.detection_before)}</strong></div>
                    <div><span className="muted">Caught after</span><strong style={{ color: "var(--teal)" }}>{pct(adapt.detection_after)}</strong></div>
                  </div>
                  <p className="muted" style={{ fontSize: "0.88rem" }}>
                    Legitimate sessions wrongly flagged: {pct(adapt.legit_false_alarm_before, 1)} before, {pct(adapt.legit_false_alarm_after, 1)} after.
                    Tested on {adapt.tested_on.fresh_evolved} new attacker sessions and {adapt.tested_on.legit} legitimate ones.
                  </p>
                </>
              )}
            </section>
          </div>
        </div>
      )}
    </>
  );
}

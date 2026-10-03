import { useState } from "react";
import Formation from "../components/Formation";
import { api, LEVELS, pct, tacticLabel, TYPE_LABEL, type Alert, type ScoreOut } from "../lib/api";

interface Row { type: string; label: string; text?: string; p: number; level: number; tactics: string[]; escalated: boolean }

const SAMPLES: Record<string, string[]> = {
  en: [
    "Hi! Our mentor shares free IPO allotment calls daily. 4,000 members already earning. Join now.",
    "This is the Customs Department. A parcel in your name contains illegal items. Stay on the line.",
    "Your task is incomplete. Complete combo task with Rs 25,000 or previous earnings will be frozen.",
    "Hi didi, this is my new number, old phone got water damaged. Save this one.",
  ],
  hinglish: [
    "Aapko Smart Investors Club group me add kiya gaya hai. Is hafte members ne 30% kamaya.",
    "Main CBI se bol raha hoon. Aapke naam ke parcel me illegal items mile hain.",
    "Part time job! YouTube videos like karke roz Rs 3000 kamao. YES reply karo.",
    "Mummy ye mera naya number hai, purana phone kharab ho gaya. Save kar lo.",
  ],
  hi: [
    "आपको 'स्मार्ट इन्वेस्टर्स क्लब' ग्रुप में जोड़ा गया है। सदस्यों ने इस हफ्ते 30% कमाया।",
    "यह मुंबई साइबर सेल है। आपके नाम के पार्सल में अवैध सामान मिला है।",
    "घर से पार्ट-टाइम जॉब! यूट्यूब वीडियो लाइक करके रोज़ 3,000 रुपये कमाएं।",
  ],
};

export default function TryIt() {
  const [language, setLanguage] = useState<"en" | "hi" | "hinglish">("en");
  const [sid, setSid] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [last, setLast] = useState<ScoreOut | null>(null);
  const [alert, setAlert] = useState<Alert | null>(null);
  const [text, setText] = useState("");
  const [ratio, setRatio] = useState(20);
  const [clock, setClock] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answered, setAnswered] = useState<string | null>(null);

  const send = async (ev: { type: string; text?: string; attrs?: Record<string, any> }, label: string, advance = 120) => {
    setBusy(true); setError(null); setAnswered(null);
    try {
      let id = sid;
      if (!id) { id = (await api.createSession(language, "whatsapp")).id; setSid(id); }
      const t = clock + advance;
      setClock(t);
      const out = await api.addEvent(id, { ...ev, t });
      setLast(out);
      const s = out.latest;
      setRows((r) => [...r, { type: ev.type, label, text: ev.text, p: s.p, level: s.level, tactics: s.tactics, escalated: s.escalated }]);
      if (out.alert) setAlert(out.alert);
    } catch (e: any) {
      setError(`That event wasn't scored: ${e.message}. Is the API running?`);
    } finally { setBusy(false); }
  };

  const respond = async (r: "cancelled" | "legit") => {
    if (!alert?.id) return;
    await api.respondAlert(alert.id, r);
    setAnswered(r === "cancelled" ? "Recorded: you ended this conversation." : "Recorded: you know this person. It counts as a false alert.");
    setAlert(null);
  };

  const reset = () => { setSid(null); setRows([]); setLast(null); setAlert(null); setClock(0); setAnswered(null); setError(null); };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Try it</h1>
          <p>Build your own session. Type what the other person sends, add calls, screen sharing and payments, and see how the risk and the alert level change at every step. Each event goes through the live API and is stored.</p>
        </div>
        <div className="row">
          <label className="field" style={{ flexDirection: "row", alignItems: "center" }}>
            <span>Language</span>
            <select value={language} disabled={sid != null} onChange={(e) => setLanguage(e.target.value as any)} aria-label="Session language">
              <option value="en">English</option><option value="hinglish">Hinglish</option><option value="hi">Hindi</option>
            </select>
          </label>
          <button className="btn ghost" onClick={reset}>Start a new session</button>
        </div>
      </div>

      {error && <div className="error" role="alert" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="try-grid">
        <section className="panel stack" aria-label="Add events">
          <div className="field">
            <label htmlFor="msg">Message from the other person</label>
            <textarea id="msg" value={text} onChange={(e) => setText(e.target.value)} placeholder="Type or pick a sample below" />
          </div>
          <div className="row">
            <button className="btn indigo" disabled={busy || !text.trim()}
                    onClick={() => { send({ type: "MSG_RECV", text: text.trim(), attrs: { known_sender: false } }, "Message received"); setText(""); }}>
              Send as unknown contact
            </button>
            <button className="btn ghost" disabled={busy || !text.trim()}
                    onClick={() => { send({ type: "MSG_RECV", text: text.trim(), attrs: { known_sender: true } }, "Message from a saved contact"); setText(""); }}>
              Send as saved contact
            </button>
          </div>
          <div>
            <h3 style={{ marginBottom: 8 }}>Samples</h3>
            <div className="stack" style={{ gap: 6 }}>
              {(SAMPLES[language] ?? SAMPLES.en).map((s) => (
                <button key={s} className="sample" onClick={() => setText(s)}>{s}</button>
              ))}
            </div>
          </div>
          <div>
            <h3 style={{ marginBottom: 8 }}>What happens next</h3>
            <div className="action-grid">
              <button className="btn ghost" disabled={busy} onClick={() => send({ type: "CALL", attrs: { known: false, minutes: 45 } }, "45-min call from an unknown number", 2700)}>Unknown caller, 45 min</button>
              <button className="btn ghost" disabled={busy} onClick={() => send({ type: "SCREEN_SHARE" }, "Screen sharing started")}>Screen sharing starts</button>
              <button className="btn ghost" disabled={busy} onClick={() => send({ type: "LINK_OPEN" }, "Link opened")}>Link opened</button>
              <button className="btn ghost" disabled={busy} onClick={() => send({ type: "APK_INSTALL" }, "App sideloaded")}>App sideloaded</button>
              <button className="btn ghost" disabled={busy} onClick={() => send({ type: "MSG_SENT", text: "ok" }, "You replied")}>You reply "ok"</button>
              <button className="btn ghost" disabled={busy} onClick={() => send({ type: "UPI_OPEN" }, "UPI app opened")}>UPI app opened</button>
              <button className="btn ghost" disabled={busy} onClick={() => send({ type: "PAYEE_NEW", attrs: { payee: "acc00042@ybl", payee_age_days: 6 } }, "New payee added (6-day-old account)")}>New payee added</button>
              <button className="btn ghost" disabled={busy || !rows.length} onClick={() => {
                setClock((c) => c + 86400);
                setRows((r) => [...r, { type: "WAIT", label: "A day passes", p: r[r.length - 1]?.p ?? 0, level: r[r.length - 1]?.level ?? 0, tactics: [], escalated: false }]);
              }}>A day passes</button>
            </div>
          </div>
          <div className="row">
            <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <span>Pay</span>
              <input type="number" min={1} max={500} value={ratio} onChange={(e) => setRatio(Number(e.target.value))} style={{ width: 80 }} aria-label="Payment size" />
              <span>× your usual amount</span>
            </label>
            <button className="btn" disabled={busy}
                    onClick={() => send({ type: "PAY", attrs: { amount: ratio * 1500, amount_ratio: ratio, payee: "acc00042@ybl", first_time: true } }, `Payment, ${ratio}× usual`)}>
              Make the payment
            </button>
          </div>
        </section>

        <section className="stack" aria-label="Live result">
          <div className="panel">
            <Formation level={last?.latest.level ?? 0} p={last?.latest.p ?? 0} />
            {last && (
              <dl className="kv" style={{ marginTop: 16 }}>
                <dt>Likely next step</dt><dd>{last.latest.next_stage?.replace(/_/g, " ") ?? "–"}</dd>
                <dt>Closest known pattern</dt><dd>{last.family_guess?.replace(/_/g, " ") ?? "–"}</dd>
              </dl>
            )}
          </div>
          {alert && (
            <div className={`panel alert-card l${alert.level}`} role="alert">
              <span className="chip red">{LEVELS[alert.level]}</span>
              <h3 style={{ margin: "8px 0" }}>{alert.title}</h3>
              <p>{alert.message}</p>
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" onClick={() => respond("cancelled")}>This is a scam, end it</button>
                <button className="btn ghost" onClick={() => respond("legit")}>I know this person</button>
              </div>
            </div>
          )}
          {answered && <p className="chip teal">{answered}</p>}
          <div className="panel">
            <div className="panel-title"><h3>Session so far</h3><span>{rows.length} events</span></div>
            {rows.length === 0 && <p className="muted">Nothing yet. Send a message or pick a sample to start.</p>}
            <div className="timeline">
              {rows.map((r, i) => (
                <div key={i} className="tl-row seen">
                  <div className="tl-time">{i + 1}</div>
                  <div>
                    <div className="tl-type">
                      {r.label || TYPE_LABEL[r.type]}
                      {r.escalated && <span className="esc-mark"> {LEVELS[r.level]} sent</span>}
                    </div>
                    {r.text && <div className="tl-text">{r.text}</div>}
                    {r.tactics.length > 0 && <div className="tl-tags">{r.tactics.map((t) => <span key={t} className="chip">{tacticLabel(t)}</span>)}</div>}
                  </div>
                  <div className="tl-risk">{pct(r.p)}</div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
    </>
  );
}

import { useState, type FormEvent } from "react";
import { api } from "../lib/api";

export default function Beta() {
  // The tester key is shown once and kept only in this page's memory (never in browser storage).
  const [key, setKey] = useState<string | null>(null);
  const [signupMsg, setSignupMsg] = useState<string | null>(null);
  const [fbMsg, setFbMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const signup = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    const f = new FormData(e.currentTarget);
    try {
      const r = await api.signup({
        email: String(f.get("email")), name: String(f.get("name")),
        org: String(f.get("org") || "") || undefined, role: String(f.get("role")),
      });
      setKey(r.api_key);
      setSignupMsg(`You're in the ${r.cohort} cohort. Copy your key now: it is shown only once and isn't saved anywhere.`);
    } catch (err: any) { setError(`Sign-up failed: ${err.message}`); }
  };

  const sendFeedback = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    const form = e.currentTarget;
    const f = new FormData(form);
    try {
      await api.feedback({
        kind: String(f.get("kind")), rating: Number(f.get("rating")) || undefined,
        comment: String(f.get("comment") || ""), page: String(f.get("page") || ""),
      }, key ?? undefined);
      setFbMsg("Feedback sent. Thank you.");
      form.reset();
    } catch (err: any) { setError(`Feedback wasn't sent: ${err.message}`); }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Join the beta</h1>
          <p>Testers can report false alerts or missed scams. To run your own live sessions, create an account on the Account page. Every report goes straight to the team.</p>
        </div>
      </div>
      {error && <div className="error" role="alert" style={{ marginBottom: 16 }}>{error}</div>}
      <div className="two">
        <section className="panel">
          <div className="panel-title"><h2>Sign up</h2></div>
          {key ? (
            <div className="stack">
              <p>{signupMsg}</p>
              <div className="keybox" aria-label="Your API key">{key}</div>
              <p className="muted">It only links your feedback to you. Send it as the <code>X-API-Key</code> header when reporting; it gives no access to sessions or data.</p>
              <button className="btn ghost" onClick={() => { setKey(null); setSignupMsg(null); }}>
                Hide key
              </button>
            </div>
          ) : (
            <form className="stack" onSubmit={signup}>
              <div className="field"><label htmlFor="name">Name</label><input id="name" name="name" required /></div>
              <div className="field"><label htmlFor="email">Email</label><input id="email" name="email" type="email" required /></div>
              <div className="field"><label htmlFor="org">Organisation (optional)</label><input id="org" name="org" /></div>
              <div className="field">
                <label htmlFor="role">I'm joining as</label>
                <select id="role" name="role" defaultValue="tester">
                  <option value="tester">A tester trying the app</option>
                  <option value="analyst">A fraud analyst</option>
                </select>
              </div>
              <button className="btn indigo" type="submit">Get my tester key</button>
            </form>
          )}
        </section>

        <section className="panel">
          <div className="panel-title"><h2>Report something</h2></div>
          <form className="stack" onSubmit={sendFeedback}>
            <div className="field">
              <label htmlFor="kind">What happened?</label>
              <select id="kind" name="kind" defaultValue="general">
                <option value="false_alert">I was warned but it was genuine</option>
                <option value="missed_scam">A scam wasn't caught</option>
                <option value="bug">Something broke</option>
                <option value="general">General feedback</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="rating">How useful was the warning? (1 to 5)</label>
              <input id="rating" name="rating" type="number" min={1} max={5} />
            </div>
            <div className="field">
              <label htmlFor="page">Where were you?</label>
              <select id="page" name="page" defaultValue="live">
                <option value="live">Live session</option><option value="arena">Arena</option>
                <option value="campaigns">Campaigns</option><option value="other">Somewhere else</option>
              </select>
            </div>
            <div className="field"><label htmlFor="comment">Details</label><textarea id="comment" name="comment" /></div>
            <button className="btn" type="submit">Send feedback</button>
            {fbMsg && <p className="chip teal">{fbMsg}</p>}
          </form>
        </section>
      </div>
    </>
  );
}

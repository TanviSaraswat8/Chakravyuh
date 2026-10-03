import { useState, type FormEvent } from "react";
import { auth } from "../lib/api";
import { useAuth } from "../lib/auth";

const ROLE_TEXT: Record<string, string> = {
  VIEWER: "can read their own sessions",
  ANALYST: "can run live sessions and review campaigns",
  MODEL_ENGINEER: "can also update the defender model",
  ADMIN: "manages accounts and reads the audit log",
};

export default function Account() {
  const { user, ready, setUser } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const email = String(f.get("email")), password = String(f.get("password"));
    setBusy(true); setError(null); setMsg(null);
    try {
      if (mode === "register") await auth.register(email, password);
      setUser(await auth.login(email, password));
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  };

  const confirm = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    setError(null); setMsg(null);
    try {
      const r = await auth.reauth(String(new FormData(form).get("password")));
      setMsg(`Confirmed. High-risk actions are unlocked for ${Math.round(r.valid_seconds / 60)} minutes.`);
      form.reset();
    } catch (err: any) { setError(err.message); }
  };

  const signOut = async () => {
    try { await auth.logout(); } finally { setUser(null); }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Account</h1>
          <p>Live sessions you create are private to your account. Signing in uses a secure browser cookie; nothing is kept in browser storage.</p>
        </div>
      </div>
      {error && <div className="error" role="alert" style={{ marginBottom: 16 }}>{error}</div>}
      {!ready ? <div className="panel"><p className="muted">Checking your sign-in…</p></div> : user ? (
        <div className="two">
          <section className="panel">
            <div className="panel-title"><h2>Signed in</h2></div>
            <div className="stack">
              <p><strong>{user.email}</strong></p>
              <p className="chip teal">{user.role.replace("_", " ").toLowerCase()}: {ROLE_TEXT[user.role] ?? ""}</p>
              <button className="btn ghost" onClick={signOut}>Sign out</button>
            </div>
          </section>
          <section className="panel">
            <div className="panel-title"><h2>Confirm it's you</h2></div>
            <form className="stack" onSubmit={confirm}>
              <p className="muted">Saving a model update or changing someone's role needs your password again, within the last few minutes.</p>
              <div className="field"><label htmlFor="re-pw">Password</label><input id="re-pw" name="password" type="password" autoComplete="current-password" required /></div>
              <button className="btn" type="submit">Confirm</button>
              {msg && <p className="chip teal">{msg}</p>}
            </form>
          </section>
        </div>
      ) : (
        <section className="panel" style={{ maxWidth: 460 }}>
          <div className="panel-title"><h2>{mode === "login" ? "Sign in" : "Create an account"}</h2></div>
          <form className="stack" onSubmit={submit}>
            <div className="field"><label htmlFor="email">Email</label><input id="email" name="email" type="email" autoComplete="email" required /></div>
            <div className="field">
              <label htmlFor="password">Password{mode === "register" ? " (at least 12 characters)" : ""}</label>
              <input id="password" name="password" type="password" minLength={mode === "register" ? 12 : 1} maxLength={128}
                     autoComplete={mode === "login" ? "current-password" : "new-password"} required />
            </div>
            <button className="btn indigo" type="submit" disabled={busy}>{mode === "login" ? "Sign in" : "Create account"}</button>
            <button className="btn ghost" type="button" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}>
              {mode === "login" ? "New here? Create an account" : "Have an account? Sign in"}
            </button>
          </form>
        </section>
      )}
    </>
  );
}

import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./lib/api";
import Arena from "./pages/Arena";
import Benchmark from "./pages/Benchmark";
import Beta from "./pages/Beta";
import Campaigns from "./pages/Campaigns";
import LiveDemo from "./pages/LiveDemo";
import "./styles.css";

function Mark() {
  return (
    <svg width="34" height="34" viewBox="0 0 32 32" aria-hidden="true">
      <g fill="none" stroke="#9fa2f2" strokeWidth="2.2">
        <circle cx="16" cy="16" r="13" />
        <circle cx="16" cy="16" r="8.5" strokeDasharray="4 3" />
        <circle cx="16" cy="16" r="4" />
      </g>
      <circle cx="16" cy="16" r="1.6" fill="#ff7a6e" />
    </svg>
  );
}

function Shell() {
  const [status, setStatus] = useState<{ ok: boolean; text: string }>({ ok: false, text: "Connecting to the API" });
  useEffect(() => {
    api.health()
      .then((h) => setStatus({ ok: h.model.loaded, text: h.model.loaded ? "Models loaded" : "Running on rules only" }))
      .catch(() => setStatus({ ok: false, text: "API not reachable" }));
  }, []);

  const links: [string, string, string][] = [
    ["/live", "Live session", "Watch a scam unfold"],
    ["/arena", "Arena", "Attackers versus defender"],
    ["/campaigns", "Campaigns", "New scam patterns"],
    ["/benchmark", "Benchmark", "How it compares"],
    ["/beta", "Beta", "Sign up and feedback"],
  ];
  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <div className="brand">
          <Mark />
          <div>
            <div className="brand-name">Chakravyuh</div>
            <div className="brand-sub">Scam-session defence</div>
          </div>
        </div>
        <div className="nav">
          {links.map(([to, label, sub]) => (
            <NavLink key={to} to={to}>
              {label}
              <small>{sub}</small>
            </NavLink>
          ))}
        </div>
        <div className="rail-foot" role="status">
          <span className={`status-dot${status.ok ? " ok" : ""}`} />{status.text}
        </div>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/live" replace />} />
          <Route path="/live" element={<LiveDemo />} />
          <Route path="/arena" element={<Arena />} />
          <Route path="/campaigns" element={<Campaigns />} />
          <Route path="/benchmark" element={<Benchmark />} />
          <Route path="/beta" element={<Beta />} />
          <Route path="*" element={<Navigate to="/live" replace />} />
        </Routes>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  </StrictMode>,
);

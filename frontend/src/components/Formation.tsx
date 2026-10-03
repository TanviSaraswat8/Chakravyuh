import { LEVELS } from "../lib/api";

/**
 * The formation meter. Four rings close in around the payment, one per escalation level:
 * nudge (outer), check-in, cooling-off, hold (inner). An outer arc shows the risk score.
 */
const RINGS = [
  { r: 92, level: 1, color: "#E39B17" },
  { r: 72, level: 2, color: "#D8761C" },
  { r: 52, level: 3, color: "#C8312E" },
  { r: 32, level: 4, color: "#8F1F1D" },
];

export default function Formation({ level, p }: { level: number; p: number }) {
  const arcR = 108;
  const circ = 2 * Math.PI * arcR;
  const riskColor = p > 0.75 ? "#C8312E" : p > 0.4 ? "#E39B17" : "#1F8A70";
  return (
    <div className="formation-wrap">
      <svg viewBox="0 0 240 240" width="240" height="240" role="img"
           aria-label={`Escalation level ${level} of 4, ${LEVELS[level]}. Risk ${Math.round(p * 100)} percent.`}>
        <circle cx="120" cy="120" r={arcR} fill="none" stroke="#dde2ea" strokeWidth="6" />
        <circle cx="120" cy="120" r={arcR} fill="none" stroke={riskColor} strokeWidth="6" strokeLinecap="round"
                strokeDasharray={`${circ * Math.max(p, 0.004)} ${circ}`} transform="rotate(-90 120 120)"
                style={{ transition: "stroke-dasharray 400ms ease, stroke 400ms ease" }} />
        {RINGS.map((ring) => {
          const closed = level >= ring.level;
          return (
            <circle key={ring.r} cx="120" cy="120" r={ring.r} fill={closed ? ring.color : "none"}
                    fillOpacity={closed ? 0.1 : 0} stroke={closed ? ring.color : "#c3c9d4"}
                    strokeWidth={closed ? 3.5 : 1.5} strokeDasharray={closed ? undefined : "5 6"}
                    style={{ transition: "all 350ms ease" }} />
          );
        })}
        <circle cx="120" cy="120" r="13" fill={level >= 4 ? "#8F1F1D" : "#1B2333"} />
        <text x="120" y="124.5" textAnchor="middle" fontSize="11" fontWeight="700" fill="#fff">₹</text>
      </svg>
      <div className="formation-label">{LEVELS[level]}</div>
      <div className="muted" style={{ fontSize: "0.88rem" }}>Risk {Math.round(p * 100)}%</div>
    </div>
  );
}

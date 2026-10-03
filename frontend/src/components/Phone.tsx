import { useEffect, useRef } from "react";
import type { Alert, SimEvent } from "../lib/api";

const rupees = (n: number) => "₹" + Math.round(n).toLocaleString("en-IN");

function systemLine(e: SimEvent): { text: string; pay?: boolean } | null {
  const a = e.attrs ?? {};
  switch (e.type) {
    case "CALL": return { text: `${a.known ? "Call from a saved contact" : "Call from an unknown number"}, ${Math.round(a.minutes ?? 0)} min` };
    case "SCREEN_SHARE": return { text: "Screen sharing started" };
    case "REMOTE_APP": return { text: "Remote-access app installed" };
    case "LINK_OPEN": return { text: "Opened a link" };
    case "APK_INSTALL": return { text: "Installed an app from outside the Play Store" };
    case "UPI_OPEN": return { text: "UPI app opened" };
    case "PAYEE_NEW": return { text: `New payee added: ${a.payee ?? "unknown"}` };
    case "FD_BREAK": return { text: "Fixed deposit broken early" };
    case "RECV": return { text: `Received ${rupees(a.amount ?? 0)}` };
    case "PAY":
      return a.cancelled
        ? { text: `Payment of ${rupees(a.amount ?? 0)} cancelled` }
        : { text: `Paid ${rupees(a.amount ?? 0)} to ${a.payee ?? "payee"}`, pay: true };
    default: return null;
  }
}

interface Props {
  events: SimEvent[];
  upto: number;
  alert: Alert | null;
  title: string;
  onDismiss: () => void;
  onCancel: () => void;
}

export default function Phone({ events, upto, alert, title, onDismiss, onCancel }: Props) {
  const chatRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight });
  }, [upto, alert]);

  const shown = events.slice(0, upto + 1);
  return (
    <div className="phone" aria-label="Simulated phone">
      <div className="phone-screen">
        <div className="phone-top">
          <strong>{title}</strong>
          <small>{events[0]?.channel ?? "chat"}</small>
        </div>
        <div className="chat" ref={chatRef} aria-live="polite">
          {shown.map((e, i) => {
            if (e.type === "MSG_RECV" || e.type === "MSG_SENT") {
              return <div key={i} className={`bubble ${e.type === "MSG_RECV" ? "them" : "me"}`}>{e.text}</div>;
            }
            const line = systemLine(e);
            return line ? <div key={i} className={`sysline${line.pay ? " pay" : ""}`}>{line.text}</div> : null;
          })}
          {upto < 0 && <div className="sysline">Press play to start the conversation</div>}
        </div>
        {alert && (
          <div className={`phone-alert l${alert.level}`} role="alertdialog" aria-label={alert.title}>
            <h3>{alert.title}</h3>
            <p>{alert.message}</p>
            <div className="row">
              <button className="btn" onClick={onCancel}>{alert.level >= 3 ? "Stop this payment" : "This is a scam, end it"}</button>
              <button className="btn ghost" onClick={onDismiss}>I know this person</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

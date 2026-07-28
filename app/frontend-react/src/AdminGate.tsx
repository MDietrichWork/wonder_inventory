import { useEffect, useRef, useState } from "react";

// The MVP ships without real authentication. This is a lightweight client-side gate that keeps
// the Rule & Routing Admin out of casual reach — not a security boundary. The password is
// configurable at build time via VITE_ADMIN_PASSWORD, with a fallback for local dev.
// Injection-safe by construction: the entered value is only ever bound to a controlled <input>
// and compared as a string — it is never rendered as HTML, evaluated, or sent to the DOM raw.
const ADMIN_PASSWORD = (import.meta.env.VITE_ADMIN_PASSWORD || "wonder-admin").trim();

export function AdminGate({ onUnlock, onCancel }: { onUnlock: () => void; onCancel: () => void }) {
  const [pw, setPw] = useState("");
  const [error, setError] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (pw === ADMIN_PASSWORD) onUnlock();
    else { setError(true); setPw(""); inputRef.current?.focus(); }
  };

  return (
    <div className="gate-overlay" role="dialog" aria-modal="true" aria-label="Admin access">
      <form className="gate-card" onSubmit={submit}>
        <h3><span className="gate-lock">🔒</span> Restricted area</h3>
        <p className="sub">
          The Rule &amp; Routing Admin can change validation rules and ticket routing.
          Enter the admin password to continue.
        </p>
        <input
          ref={inputRef}
          type="password"
          className="gate-input"
          value={pw}
          onChange={(e) => { setPw(e.target.value); if (error) setError(false); }}
          placeholder="Admin password"
          autoComplete="off"
          aria-invalid={error}
          aria-describedby={error ? "gate-error" : undefined}
        />
        {error && <div id="gate-error" className="gate-error" role="alert">Incorrect password. Try again.</div>}
        <div className="gate-actions">
          <button type="button" className="btn sm" onClick={onCancel}>Cancel</button>
          <button type="submit" className="btn primary sm" disabled={!pw}>Unlock</button>
        </div>
      </form>
    </div>
  );
}

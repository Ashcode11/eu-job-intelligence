"use client";

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

import { VISA_LABEL, type VisaClass } from "@/lib/api";

export function ScoreRing({ score, size = 44 }: { score: number | null; size?: number }) {
  if (score == null) return <span className="score-empty" title="Not scored yet">—</span>;
  const tone = score >= 75 ? "good" : score >= 50 ? "mid" : "low";
  const r = 16;
  const c = 2 * Math.PI * r;
  return (
    <svg className={`score-ring ${tone}`} width={size} height={size} viewBox="0 0 40 40"
         role="img" aria-label={`Match score ${Math.round(score)} of 100`}>
      <circle cx="20" cy="20" r={r} className="track" />
      <circle cx="20" cy="20" r={r} className="value" strokeDasharray={`${(score / 100) * c} ${c}`}
              transform="rotate(-90 20 20)" />
      <text x="20" y="24" textAnchor="middle">{Math.round(score)}</text>
    </svg>
  );
}

export function VisaBadge({ value }: { value: VisaClass | null }) {
  if (!value) return <span className="badge muted">Not analysed</span>;
  const tone = {
    explicit_sponsorship: "good",
    potential_sponsorship: "info",
    not_mentioned: "muted",
    eu_authorization_required: "warn",
    not_suitable: "bad",
  }[value];
  return <span className={`badge ${tone}`}>{VISA_LABEL[value]}</span>;
}

export function Bar({ value, label }: { value: number; label: string }) {
  const tone = value >= 75 ? "good" : value >= 50 ? "mid" : "low";
  return (
    <div className="bar-row">
      <span className="bar-label">{label}</span>
      <div className="bar" role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}
           aria-label={label}>
        <div className={`bar-fill ${tone}`} style={{ width: `${Math.max(2, value)}%` }} />
      </div>
      <span className="bar-value">{Math.round(value)}</span>
    </div>
  );
}

export function Card({ title, actions, children, className = "" }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function Loading() {
  return <p className="empty" aria-busy="true">Loading…</p>;
}

export function ErrorNote({ error }: { error: string | null }) {
  return error ? <p className="error-note" role="alert">{error}</p> : null;
}

export function Tri({ value, yes = "Yes", no = "No" }: { value: boolean | null; yes?: string; no?: string }) {
  if (value == null) return <span className="tri unknown">Not stated</span>;
  return <span className={`tri ${value ? "yes" : "no"}`}>{value ? yes : no}</span>;
}

// --- toasts ------------------------------------------------------------------------
type Toast = { id: number; text: string; tone: "ok" | "err" };
const ToastCtx = createContext<(text: string, tone?: "ok" | "err") => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: "ok" | "err" = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.tone}`}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

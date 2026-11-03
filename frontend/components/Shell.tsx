"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { api, getApiKey, setApiKey } from "@/lib/api";
import { ToastProvider } from "./ui";

const NAV = [
  { href: "/", label: "Overview", icon: "◎" },
  { href: "/jobs", label: "Job Explorer", icon: "⌕" },
  { href: "/applications", label: "Applications", icon: "▤" },
  { href: "/profile", label: "Profile", icon: "◉" },
  { href: "/agents", label: "Agents", icon: "⚙" },
];

export default function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [ready, setReady] = useState(false);
  const [hasKey, setHasKey] = useState(false);

  useEffect(() => {
    setHasKey(Boolean(getApiKey()));
    setReady(true);
    const onUnauthorized = () => {
      setApiKey(null);
      setHasKey(false);
    };
    window.addEventListener("eujobs:unauthorized", onUnauthorized);
    return () => window.removeEventListener("eujobs:unauthorized", onUnauthorized);
  }, []);

  if (!ready) return null;
  if (!hasKey) return <KeyGate onDone={() => setHasKey(true)} />;

  return (
    <ToastProvider>
      <div className="shell">
        <nav className="sidebar" aria-label="Main">
          <div className="brand">
            <span className="brand-mark">EU</span>
            <span className="brand-text">Job Intelligence</span>
          </div>
          <ul>
            {NAV.map((n) => {
              const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
              return (
                <li key={n.href}>
                  <Link href={n.href} className={active ? "active" : ""}
                        aria-current={active ? "page" : undefined}>
                    <span className="nav-icon" aria-hidden>{n.icon}</span>
                    <span className="nav-label">{n.label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
          <button className="link sign-out" onClick={() => { setApiKey(null); setHasKey(false); }}>
            Forget API key
          </button>
        </nav>
        <main className="main">{children}</main>
      </div>
    </ToastProvider>
  );
}

function KeyGate({ onDone }: { onDone: () => void }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setApiKey(key.trim());
    try {
      await api("/agents/summary");
      onDone();
    } catch {
      setApiKey(null);
      setError("That key was not accepted. Use one of the values of API_KEYS in your .env file.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="gate">
      <form className="gate-card" onSubmit={submit}>
        <div className="brand big"><span className="brand-mark">EU</span> Job Intelligence</div>
        <p>Enter your API key to open the dashboard. It is stored only in this browser.</p>
        <label htmlFor="key">API key</label>
        <input id="key" type="password" autoComplete="off" value={key}
               onChange={(e) => setKey(e.target.value)} placeholder="From API_KEYS in .env" required />
        {error && <p className="error-note" role="alert">{error}</p>}
        <button className="primary" disabled={busy || !key.trim()}>
          {busy ? "Checking…" : "Open dashboard"}
        </button>
      </form>
    </div>
  );
}

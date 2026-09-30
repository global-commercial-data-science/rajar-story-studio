import type { ReactNode } from "react";

const icon = (d: ReactNode) => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);

export const Icons = {
  pulse: icon(<polyline points="2 12 6 12 9 5 13 19 16 12 22 12" />),
  search: icon(<><circle cx="11" cy="11" r="7" /><line x1="20" y1="20" x2="16.5" y2="16.5" /></>),
  send: icon(<><line x1="4" y1="12" x2="20" y2="12" /><polyline points="14 6 20 12 14 18" /></>),
  doc: icon(<><path d="M6 3h8l4 4v14H6z" /><line x1="9" y1="12" x2="15" y2="12" /><line x1="9" y1="16" x2="15" y2="16" /></>),
  chart: icon(<><rect x="3" y="3" width="18" height="18" rx="2" /><line x1="8" y1="16" x2="8" y2="11" /><line x1="12" y1="16" x2="12" y2="7" /><line x1="16" y1="16" x2="16" y2="13" /></>),
  external: icon(<><path d="M14 4h6v6" /><line x1="20" y1="4" x2="11" y2="13" /><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></>),
};

export const OMNI_URL = "https://global.omniapp.co/apps/30e25018";

export function Sidebar({ releaseLabel, refreshedAt }: { releaseLabel: string; refreshedAt: string | null }) {
  return (
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">{Icons.pulse}</span>RAJAR Pulse</div>
      <nav>
        <span className="nav-item active" aria-current="page">{Icons.doc}<span>Story Studio</span></span>
        <a className="nav-item nav-link" href={OMNI_URL} target="_blank" rel="noopener noreferrer">
          {Icons.chart}<span>Omni</span><span className="nav-ext">{Icons.external}</span>
        </a>
      </nav>
      <div className="release-card">
        <div className="eyebrow">Latest release</div>
        <div className="release-name">{releaseLabel}</div>
        <p>Period ending 28 June 2026.{refreshedAt ? ` Data refreshed from Snowflake at ${refreshedAt}.` : " Loading from Snowflake…"}</p>
      </div>
      <div className="user"><span className="avatar">TG</span>Team Ginger</div>
    </aside>
  );
}

export function TopBar({ chips, onAsk }: { chips: ReactNode; onAsk: (q: string) => void }) {
  return (
    <header className="topbar">
      <div className="topbar-brand"><span className="brand-mark">{Icons.pulse}</span>RAJAR Pulse</div>
      {chips}
      <a className="btn btn-small omni-top" href={OMNI_URL} target="_blank" rel="noopener noreferrer">{Icons.chart} Omni</a>
      <form className="ask" onSubmit={(e) => {
        e.preventDefault();
        const input = e.currentTarget.elements.namedItem("q") as HTMLInputElement;
        const q = input.value.trim();
        if (q) { onAsk(q); input.value = ""; }
      }}>
        {Icons.search}
        <input id="ask-input" name="q" placeholder="Ask Pulse anything about your brands" aria-label="Ask Pulse" autoComplete="off" />
      </form>
    </header>
  );
}

/** Thin animated bar across the top of the page while anything is loading. */
export function TopProgress({ active }: { active: boolean }) {
  return <div className={`top-progress ${active ? "on" : ""}`} role="progressbar" aria-hidden={!active} aria-label="Loading" />;
}

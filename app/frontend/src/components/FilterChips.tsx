import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Filters, Menu, MenuOption, StudioActionInput } from "../types";

type Act = (a: StudioActionInput) => void;

function Chip({ label, value, children }: { label: string; value: string; children: (close: () => void) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);
  return (
    <div className="chip-wrap" ref={ref}>
      <button className={`chip ${open ? "open" : ""}`} aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen(!open)}>
        <span className="chip-key">{label}</span><span className="chip-val">{value}</span>
        <svg className="chev" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
      </button>
      {open && <div className="popover" role="menu">{children(() => setOpen(false))}</div>}
    </div>
  );
}

function Options({ title, options, current, onPick }: { title: string; options: MenuOption[]; current: string | number; onPick: (v: string) => void }) {
  return (
    <div className="pop-section">
      <div className="pop-title">{title}</div>
      <div className="pop-options">
        {options.map((o) => (
          <button key={String(o.value)} role="menuitemradio" aria-checked={String(o.value) === String(current)}
            className={`pop-option ${String(o.value) === String(current) ? "on" : ""}`} onClick={() => onPick(String(o.value))}>
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function Questions({ items, onAsk }: { items: string[]; onAsk: (q: string) => void }) {
  return (
    <div className="pop-section">
      <div className="pop-title">Ask Pulse</div>
      {items.map((q) => <button key={q} role="menuitem" className="pop-question" onClick={() => onAsk(q)}>{q}</button>)}
    </div>
  );
}

function Run({ label, onRun }: { label: string; onRun: () => void }) {
  return <div className="pop-section"><button className="btn btn-small pop-run" onClick={onRun}>{label}</button></div>;
}

const labelOf = (opts: MenuOption[], v: string | number) => opts.find((o) => String(o.value) === String(v))?.label ?? String(v);

export function FilterChips({ menu, filters, setFilters, act, qoq, yoy }: {
  menu: Menu | null; filters: Filters; setFilters: (f: Partial<Filters>) => void; act: Act; qoq: string | null; yoy: string | null;
}) {
  if (!menu) return <div className="chips"><span className="chip"><span className="chip-key">Loading filters…</span></span></div>;
  const brand = labelOf(menu.brands, filters.brand);
  const audience = labelOf(menu.audiences, filters.audience);
  const area = labelOf(menu.areas, filters.area);
  const ask = (q: string, close: () => void) => { act({ kind: "question", text: q }); close(); };
  const fill = (q: string) => q.replace("{brand}", filters.brand === "all" ? "each Global brand" : brand)
    .replace("{audience}", audience).replace("{area}", area);
  const compareLabel = filters.compare === "both" ? [qoq, yoy].filter(Boolean).join(" · ") : labelOf(menu.compare, filters.compare);

  return (
    <div className="chips">
      <Chip label="Release" value={labelOf(menu.releases, filters.release)}>
        {(close) => <>
          <Options title="RAJAR release" options={menu.releases} current={filters.release}
            onPick={(v) => { setFilters({ release: Number(v) }); close(); }} />
          <Questions items={menu.questions.release} onAsk={(q) => ask(q, close)} />
        </>}
      </Chip>
      <Chip label="vs" value={compareLabel}>
        {(close) => <>
          <Options title="Compare with" options={menu.compare} current={filters.compare}
            onPick={(v) => { setFilters({ compare: v }); if (v !== "both") act({ kind: "preset", preset: "compare", value: v }); close(); }} />
          <p className="pop-note">Sets the comparison the writer leads with.</p>
          <Questions items={menu.questions.compare} onAsk={(q) => ask(q, close)} />
        </>}
      </Chip>
      <Chip label="Period" value="Quarterly">
        {(close) => <>
          <p className="pop-note">RAJAR is released quarterly. Global's brand totals use 6-month fieldwork; spin-off stations are quarterly.</p>
          <Run label="Show survey periods" onRun={() => { act({ kind: "preset", preset: "period", value: "all" }); close(); }} />
          <Questions items={menu.questions.period} onAsk={(q) => ask(q, close)} />
        </>}
      </Chip>
      <Chip label="Brands" value={brand}>
        {(close) => <>
          <Options title="Show angles for" options={menu.brands} current={filters.brand}
            onPick={(v) => { setFilters({ brand: v }); if (v !== "all") act({ kind: "preset", preset: "brand", value: v }); close(); }} />
          <Questions items={menu.questions.brand.map(fill)} onAsk={(q) => ask(q, close)} />
        </>}
      </Chip>
      <Chip label="Audience" value={audience}>
        {(close) => <>
          <Options title="Audience" options={menu.audiences} current={filters.audience}
            onPick={(v) => { setFilters({ audience: v }); act({ kind: "preset", preset: "audience", value: v }); close(); }} />
          <Questions items={menu.questions.audience.map(fill)} onAsk={(q) => ask(q, close)} />
        </>}
      </Chip>
      <Chip label="Area" value={area}>
        {(close) => <>
          <Options title="Where listeners live" options={menu.areas} current={filters.area}
            onPick={(v) => { setFilters({ area: v }); act({ kind: "preset", preset: "area", value: v }); close(); }} />
          <Questions items={menu.questions.area.map(fill)} onAsk={(q) => ask(q, close)} />
        </>}
      </Chip>
    </div>
  );
}

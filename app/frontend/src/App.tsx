import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Sidebar, TopBar, TopProgress } from "./components/Chrome";
import { FilterChips } from "./components/FilterChips";
import { StoryStudio } from "./components/StoryStudio";
import type { FactSet, Filters, Menu, StudioAction, StudioActionInput } from "./types";

export default function App() {
  const [filters, setFiltersState] = useState<Filters>({ release: 202602, compare: "both", brand: "all", audience: "adults", area: "uk" });
  const [facts, setFacts] = useState<FactSet | null>(null);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [refreshedAt, setRefreshedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<StudioAction | null>(null);
  const [busy, setBusy] = useState(false);

  const setFilters = useCallback((f: Partial<Filters>) => setFiltersState((prev) => ({ ...prev, ...f })), []);
  const act = useCallback((a: StudioActionInput) => setAction((prev) => ({ ...a, n: (prev?.n ?? 0) + 1 }) as StudioAction), []);

  useEffect(() => {
    setFacts(null);
    setError(null);
    api.facts(filters.release)
      .then((f) => {
        setFacts(f);
        setRefreshedAt(new Date().toLocaleTimeString("en-GB", { hour: "numeric", minute: "2-digit" }));
      })
      .catch((e) => setError(String(e)));
    api.menu(filters.release).then(setMenu).catch(() => setMenu(null));
  }, [filters.release]);

  return (
    <div className="app">
      <TopProgress active={busy || !facts} />
      <Sidebar releaseLabel={facts?.release_label ?? "…"} refreshedAt={refreshedAt} />
      <main className="main">
        <TopBar
          chips={<FilterChips menu={menu} filters={filters} setFilters={setFilters} act={act} qoq={facts?.qoq_label ?? null} yoy={facts?.yoy_label ?? null} />}
          onAsk={(q) => act({ kind: "question", text: q })} />
        <div className="content">
          {error && <div className="banner banner-warn">Couldn't load RAJAR figures: {error}. Is the API running?</div>}
          {facts
            ? <StoryStudio key={facts.release} facts={facts} filters={filters} action={action} onBusy={setBusy} />
            : !error && <div className="empty"><span className="spinner" /> Loading RAJAR figures from Snowflake…</div>}
        </div>
      </main>
    </div>
  );
}

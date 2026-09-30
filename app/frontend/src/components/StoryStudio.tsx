import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { Inline, MarkdownDoc, renderPlain } from "../render";
import { FORMATS, type Angle, type AngleGroup, type AnglesResult, type Draft, type Fact, type FactSet, type Filters, type Format, type JobProgress, type StudioAction } from "../types";
import { ChatPanel } from "./ChatPanel";
import { useElapsed } from "./useElapsed";

type Status = "Draft" | "Awaiting comms approval";
type Side = "facts" | "chat";
const TONES = ["Global house style", "Celebratory", "Measured and factual", "Punchy for trade press"];

const COMPARE_NOTE: Record<string, string> = {
  both: "",
  qoq: "Lead with changes versus the previous quarter.",
  yoy: "Lead with changes versus the same quarter last year.",
};

export function StoryStudio({ facts, filters, action, onBusy }: {
  facts: FactSet; filters: Filters; action: StudioAction | null; onBusy: (b: boolean) => void;
}) {
  const [angles, setAngles] = useState<AnglesResult | null>(null);
  const [anglesBusy, setAnglesBusy] = useState(false);
  const [format, setFormat] = useState<Format>("press_release");
  const [drafts, setDrafts] = useState<Partial<Record<Format, Draft>>>({});
  const [draftBusy, setDraftBusy] = useState(false);
  const [versions, setVersions] = useState<Partial<Record<Format, number>>>({});
  const [editing, setEditing] = useState(false);
  const [tone, setTone] = useState(TONES[0]);
  const [notes, setNotes] = useState("");
  const [notesFlash, setNotesFlash] = useState(false);

  function addToNotes(text: string) {
    setNotes((prev) => (prev.trim() ? `${prev.trim()}\n\n${text}` : text));
    setStale(true);
    setNotesFlash(true);
    setTimeout(() => setNotesFlash(false), 1200);
  }
  const [status, setStatus] = useState<Status>("Draft");
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [side, setSide] = useState<Side>("facts");
  const [progress, setProgress] = useState<{ p: JobProgress; elapsed: number } | null>(null);
  const [chatBusy, setChatBusy] = useState(false);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const draftElapsed = useElapsed(draftBusy);
  const runId = useRef(0);

  useEffect(() => { onBusy(anglesBusy || draftBusy || chatBusy); }, [anglesBusy, draftBusy, chatBusy, onBusy]);

  const factMap = useMemo(() => {
    const m: Record<string, Fact> = {};
    facts.facts.forEach((f) => (m[f.key] = f));
    angles?.extra_facts.forEach((f) => (m[f.key] = f));
    return m;
  }, [facts, angles]);

  const selected = angles?.angles.filter((a) => a.selected) ?? [];
  const draft = drafts[format];

  async function makeDraft(fmt: Format, angleList: Angle[], extra: Fact[], refresh = false) {
    if (!angleList.some((a) => a.selected)) return;
    setDraftBusy(true);
    setError(null);
    try {
      const editorNotes = [COMPARE_NOTE[filters.compare], notes].filter(Boolean).join("\n\n");
      const d = await api.draft({ release: facts.release, format: fmt, angles: angleList, extra_facts: extra, tone, editor_notes: editorNotes, refresh });
      setDrafts((prev) => ({ ...prev, [fmt]: d }));
      setVersions((prev) => ({ ...prev, [fmt]: (prev[fmt] ?? 0) + 1 }));
      setStale(false);
      if (d.error) setError(d.error);
    } catch (e) {
      setError(String(e));
    } finally {
      setDraftBusy(false);
    }
  }

  // Angles come from the agent; after the first run they are served from the local cache.
  async function loadAngles(refresh: boolean) {
    const id = ++runId.current;
    setAnglesBusy(true);
    setProgress(null);
    setError(null);
    try {
      const result = await api.anglesWithProgress(facts.release, refresh, (p, elapsed) => {
        if (id === runId.current) setProgress({ p, elapsed });
      });
      if (id !== runId.current) return;
      setAngles(result);
      setDrafts({});
      if (result.error) setError(result.error);
      makeDraft(format, result.angles, result.extra_facts);
    } catch (e) {
      setError(String(e));
    } finally {
      if (id === runId.current) setAnglesBusy(false);
    }
  }

  useEffect(() => { loadAngles(false); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [facts.release]);
  useEffect(() => { if (action) setSide("chat"); }, [action?.n]);

  function toggle(id: string) {
    if (!angles) return;
    const flip = (a: Angle) => (a.id === id ? { ...a, selected: !a.selected } : a);
    setAngles({ ...angles, angles: angles.angles.map(flip), groups: (angles.groups ?? []).map((g) => ({ ...g, angles: g.angles.map(flip) })) });
    setStale(true);
  }

  function switchFormat(fmt: Format) {
    setFormat(fmt);
    setEditing(false);
    if (!drafts[fmt] && angles) makeDraft(fmt, angles.angles, angles.extra_facts);
  }

  function editDraft(patch: Partial<Draft>) {
    if (draft) setDrafts({ ...drafts, [format]: { ...draft, ...patch } });
  }

  const docName = FORMATS.find((f) => f.id === format)!.doc;
  const usedFacts = draft ? draft.tokens_used.map((k) => factMap[k]).filter(Boolean) : [];
  const verified = usedFacts.filter((f) => f.status === "verified").length;
  const toConfirm = usedFacts.length - verified + (draft?.unverified_numbers.length ?? 0);

  return (
    <div className="studio">
      <div className="studio-head">
        <div className="studio-title">
          <h1 className="page-title">Story Studio</h1>
          <p className="page-sub">
            {docName} · RAJAR {facts.release_label} · Draft {versions[format] ?? 0} · {status === "Draft" ? "in progress" : "awaiting comms approval"}
          </p>
        </div>
        <div className="actions">
          <button className="btn" disabled={!draft} onClick={() => draft && api.exportDocx({
            release: facts.release, title: draft.title, subtitle_lines: draft.subtitle_lines, markdown: draft.markdown, extra_facts: angles?.extra_facts ?? [],
          }).catch((e) => setError(String(e)))}>Export to Word</button>
          <button className="btn" disabled={!draft} title="Copies the rendered draft so you can paste it into Google Docs" onClick={() => {
            if (!draft) return;
            const text = [draft.title, ...draft.subtitle_lines, "", draft.markdown].map((t) => renderPlain(t, factMap)).join("\n");
            navigator.clipboard.writeText(text).catch(() => setError("Copy failed: your browser blocked clipboard access."));
          }}>Copy for Google Docs</button>
          <button className="btn btn-primary" disabled={!draft || status !== "Draft"} onClick={() => setStatus("Awaiting comms approval")}>
            {status === "Draft" ? "Send for approval" : "Sent for approval"}
          </button>
        </div>
      </div>

      <div className="tabs" role="tablist" aria-label="Document type">
        {FORMATS.map((f) => (
          <button key={f.id} role="tab" aria-selected={format === f.id} className={`tab ${format === f.id ? "active" : ""}`} onClick={() => switchFormat(f.id)}>
            {f.label}
          </button>
        ))}
      </div>

      {error && <div className="banner banner-warn">{error}</div>}

      <div className="studio-grid">
        {/* Angles */}
        <section className="panel col-angles" aria-label="Angles">
          <div className="col-head">
            <h2>Angles</h2>
            <span className="muted">{angles ? `${selected.length} selected` : ""}</span>
          </div>
          {anglesBusy && <AngleProgress progress={progress} factCount={facts.facts.length} release={facts.release_label} refreshing={!!angles} />}
          {angles && (
            <div className={`groups ${anglesBusy ? "busy" : ""}`}>
              {visibleGroups(angles.groups ?? [], filters.brand).map((g) => {
                const n = g.angles.filter((a) => a.selected).length;
                const isCollapsed = collapsed[g.key] ?? false;
                return (
                  <div className="group" key={g.key}>
                    <button className="group-head" aria-expanded={!isCollapsed} onClick={() => setCollapsed({ ...collapsed, [g.key]: !isCollapsed })}>
                      <span className="group-name">{g.name}</span>
                      <span className="group-count">{n}/{g.angles.length}</span>
                      <svg className={`chev ${isCollapsed ? "" : "up"}`} width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
                    </button>
                    {!isCollapsed && (
                      <div className="angle-list">
                        {g.error && <p className="muted small">No angles: {g.error}</p>}
                        {g.angles.map((a) => (
                          <label key={a.id} className={`angle ${a.selected ? "on" : ""}`} title={a.why}>
                            <input type="checkbox" checked={a.selected} onChange={() => toggle(a.id)} />
                            <span>{a.headline}</span>
                          </label>
                        ))}
                        {g.also_moved.length > 0 && <div className="also-moved small-moved">Also moved: {g.also_moved.join(" · ")}</div>}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
          {angles && (
            <div className="angles-foot">
              <span className="muted small">
                {angles.used_llm
                  ? `${angles.cached ? "Saved" : "Found"} ${angles.cached_at ?? ""} · ${angles.model}${angles.tool_log.length ? ` · ${angles.tool_log.length} drill-downs` : ""}`
                  : "Rule-based angles (agent unavailable)"}
              </span>
              <button className="link-btn" disabled={anglesBusy} onClick={() => loadAngles(true)}>Refresh angles</button>
            </div>
          )}
        </section>

        {/* Draft */}
        <section className="panel col-draft" aria-label="Draft">
          <div className="draft-bar">
            <label className="tone">Tone
              <select id="tone" value={tone} onChange={(e) => { setTone(e.target.value); setStale(true); }}>
                {TONES.map((t) => <option key={t}>{t}</option>)}
              </select>
            </label>
            <textarea id="editor-notes" className={`notes ${notesFlash ? "flash" : ""}`} rows={notesRows(notes)}
              placeholder="Notes for the writer, e.g. 'lead with LBC' (add answers from Ask Pulse here)" value={notes}
              aria-label="Notes for the writer"
              onChange={(e) => { setNotes(e.target.value); setStale(true); }} />
            <button className="btn btn-small" disabled={draftBusy || !selected.length}
              onClick={() => angles && makeDraft(format, angles.angles, angles.extra_facts, !stale)}>
              {draftBusy ? "Writing…" : stale ? "Regenerate" : "Rewrite"}
            </button>
            <button className="btn btn-small btn-ghost" disabled={!draft} onClick={() => setEditing(!editing)}>
              {editing ? "Done" : "Edit"}
            </button>
          </div>
          {draftBusy && draft ? (
            <div className="draft-note busy-note"><span className="spinner" /> Rewriting the {docName.toLowerCase()}… <span className="elapsed">{draftElapsed}s</span></div>
          ) : (
            <p className="draft-note">Highlighted figures are live tokens, locked to PRESS_FACTS{draft?.cached ? ` · saved draft from ${draft.cached_at}` : ""}</p>
          )}
          <div className="draft-scroll">
            {!draft && (
              <div className="empty">
                {draftBusy ? <><span className="spinner" /> Writing the {docName.toLowerCase()} with the selected angles… <span className="elapsed">{draftElapsed}s</span></>
                  : anglesBusy || !angles ? "The draft appears once the angles are ready."
                  : selected.length ? "" : "Select at least one angle to write a draft."}
              </div>
            )}
            {draft && !editing && (
              <article className={`doc ${draftBusy ? "busy" : ""}`}>
                <h1 className="doc-title"><Inline text={draft.title} facts={factMap} /></h1>
                {draft.subtitle_lines.length > 0 && (
                  <div className="standfirst">{draft.subtitle_lines.map((s, i) => <div key={i}><Inline text={s} facts={factMap} /></div>)}</div>
                )}
                <MarkdownDoc markdown={draft.markdown} facts={factMap} cards={format === "social_cards"} />
              </article>
            )}
            {draft && editing && (
              <div className="editor">
                <label htmlFor="edit-title">Headline</label>
                <input id="edit-title" value={draft.title} onChange={(e) => editDraft({ title: e.target.value })} />
                <label htmlFor="edit-sub">Standfirst (one line each)</label>
                <textarea id="edit-sub" rows={3} value={draft.subtitle_lines.join("\n")} onChange={(e) => editDraft({ subtitle_lines: e.target.value.split("\n") })} />
                <label htmlFor="edit-body">Body: keep figures as {"{{tokens}}"} so they stay locked to RAJAR</label>
                <textarea id="edit-body" rows={18} value={draft.markdown} onChange={(e) => editDraft({ markdown: e.target.value })} />
              </div>
            )}
          </div>
        </section>

        {/* Fact check / Ask Pulse */}
        <section className="panel col-side" aria-label="Fact check and chat">
          <div className="seg" role="tablist" aria-label="Side panel">
            <button role="tab" aria-selected={side === "facts"} className={side === "facts" ? "on" : ""} onClick={() => setSide("facts")}>
              Fact check {draft && <span className="seg-count">{verified}/{usedFacts.length + (draft.unverified_numbers.length ?? 0)}</span>}
            </button>
            <button role="tab" aria-selected={side === "chat"} className={side === "chat" ? "on" : ""} onClick={() => setSide("chat")}>Ask Pulse</button>
          </div>
          <div className="side-body" hidden={side !== "facts"}>
            <p className="muted side-summary">{draft ? `${verified} verified · ${toConfirm} to confirm` : "Figures appear here once the draft is written."}</p>
            <FactCheck facts={usedFacts} draft={draft} factMap={factMap} />
          </div>
          <div className="side-body side-chat" hidden={side !== "chat"}>
            <ChatPanel facts={facts} factMap={factMap} angles={angles?.angles ?? []} extraFacts={angles?.extra_facts ?? []}
              draft={draft} action={action} filters={filters} onBusy={setChatBusy} onAddToNotes={addToNotes} />
          </div>
        </section>
      </div>
    </div>
  );
}

function FactCheck({ facts, draft, factMap }: { facts: Fact[]; draft?: Draft; factMap: Record<string, Fact> }) {
  if (!draft) return null;
  const tokensInEditedText = new Set(
    [draft.title, ...draft.subtitle_lines, draft.markdown].join("\n").match(/\{\{\s*([a-z0-9_]+)\s*\}\}/g)?.map((t) => t.replace(/[{}\s]/g, "")) ?? [],
  );
  const shown = [...new Map([...facts, ...[...tokensInEditedText].map((k) => factMap[k]).filter(Boolean)].map((f) => [f.key, f])).values()];
  return (
    <ul className="facts">
      {shown.map((f) => (
        <li key={f.key}>
          <div className="fact-row"><code>{f.key}</code><span className="fact-val">{signed(f)}</span></div>
          <span className={`badge ${f.status === "verified" ? "badge-ok" : "badge-warn"}`} title={f.source}>
            {f.status === "verified" ? `Verified${shortNote(f) ? ` · ${shortNote(f)}` : ""}` : f.note.split(" · ")[0]}
          </span>
        </li>
      ))}
      {draft.unverified_numbers.map((n) => (
        <li key={n}>
          <div className="fact-row"><code>unlinked number</code><span className="fact-val">{n}</span></div>
          <span className="badge badge-bad">Not tied to a RAJAR fact: replace with a token or confirm</span>
        </li>
      ))}
      {draft.unknown_tokens.map((k) => (
        <li key={k}><div className="fact-row"><code>{k}</code><span className="fact-val">?</span></div>
          <span className="badge badge-bad">Unknown token</span></li>
      ))}
    </ul>
  );
}

function signed(f: Fact) {
  if (!/_(qoq|yoy)(_pp)?$/.test(f.key)) return f.unit === "record" ? "record" : f.display;
  if (f.direction === "up") return `+${f.display}`;
  if (f.direction === "down") return `−${f.display}`;
  return f.display;
}

function shortNote(f: Fact) {
  if (f.key.endsWith("_pp")) return "written as points, not %";
  if (f.key.endsWith("_peak") || f.key.endsWith("_low")) return f.display.replace(/^the /, "");
  if (f.key.includes("_vs_")) return f.note.split(" · ")[0];
  if (/_(qoq|yoy)$/.test(f.key)) return "same survey period";
  return "";
}


function visibleGroups(groups: AngleGroup[], brand: string) {
  return brand === "all" ? groups : groups.filter((g) => g.key === brand);
}

function AngleProgress({ progress, factCount, release, refreshing }: {
  progress: { p: JobProgress; elapsed: number } | null; factCount: number; release: string; refreshing: boolean;
}) {
  const p = progress?.p;
  const pct = p ? Math.round((100 * p.done) / p.total) : 4;
  return (
    <div className="loading-card" role="status" aria-live="polite">
      <div className="loading-line"><span className="spinner" /> {refreshing ? "Refreshing angles" : `Pulse is analysing RAJAR ${release}`}</div>
      <div className="bar" aria-hidden="true"><div className="bar-fill" style={{ width: `${Math.max(pct, 4)}%` }} /></div>
      <div className="loading-meta">
        <span>{p ? p.stage : `Checking ${factCount} published figures`}</span>
        <span className="elapsed">{p ? `${p.done}/${p.total} · ${progress!.elapsed}s` : ""}</span>
      </div>
      {p && p.completed.length > 0 && (
        <div className="done-list">{p.completed.map((n) => <span key={n} className="done-chip">✓ {n}</span>)}</div>
      )}
      {!refreshing && <p className="muted small">Each brand family is analysed in parallel. The first run takes about a minute; after that the angles load instantly.</p>}
    </div>
  );
}


function notesRows(notes: string) {
  const lines = notes.split("\n").reduce((n, l) => n + Math.max(1, Math.ceil(l.length / 60)), 0);
  return Math.min(Math.max(lines, 1), 6);
}

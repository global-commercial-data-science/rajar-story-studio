import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { MarkdownDoc } from "../render";
import type { Angle, ChatMessage, Draft, Fact, FactSet, Filters, StudioAction } from "../types";
import { useElapsed } from "./useElapsed";
import { Icons } from "./Chrome";

const STARTERS = [
  "Which Global brand grew most year on year?",
  "How does LBC's audience split by age?",
  "What share of Heart London listening is on DAB?",
];

export function ChatPanel({ facts, factMap, angles, extraFacts, draft, action, filters, onBusy, onAddToNotes }: {
  facts: FactSet;
  factMap: Record<string, Fact>;
  angles: Angle[];
  extraFacts: Fact[];
  draft?: Draft;
  action: StudioAction | null;
  filters: Filters;
  onBusy: (busy: boolean) => void;
  onAddToNotes: (text: string) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusyState] = useState<string | false>(false);
  const elapsed = useElapsed(!!busy);
  const setBusy = (b: string | false) => { setBusyState(b); onBusy(!!b); };
  const [input, setInput] = useState("");
  const [added, setAdded] = useState<number | null>(null);

  /** Add the highlighted part of an answer (or the whole answer) to the writer notes. */
  function addToNotes(i: number, markdown: string) {
    const sel = window.getSelection();
    const node = document.getElementById(`msg-${i}`);
    const picked = sel && node && !sel.isCollapsed && node.contains(sel.anchorNode) ? sel.toString().trim() : "";
    onAddToNotes(picked || toNote(markdown));
    setAdded(i);
    setTimeout(() => setAdded((cur) => (cur === i ? null : cur)), 2000);
  }
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!action) return;
    if (action.kind === "question") send(action.text);
    else runPreset(action.preset, action.value);
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, [action?.n]);

  async function runPreset(kind: string, value: string) {
    setBusy("Running the prepared query…");
    try {
      const r = await api.preset({ release: facts.release, kind, value, audience: filters.audience, area: filters.area });
      setMessages((m) => [...m, { role: "assistant", content: r.markdown }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: String(e).replace(/^Error: /, ""), error: true }]);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" }); }, [messages, busy]);

  async function send(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    const history = messages.filter((m) => !m.error).map(({ role, content }) => ({ role, content }));
    setMessages((m) => [...m, { role: "user", content: q }]);
    setInput("");
    setBusy("Pulse is checking the data…");
    try {
      const r = await api.chat({
        release: facts.release, question: q, history, angles, extra_facts: extraFacts,
        draft_title: draft?.title ?? "", draft_markdown: draft?.markdown ?? "",
      });
      setMessages((m) => [...m, { role: "assistant", content: r.answer, facts_used: r.facts_used, suggestions: r.suggestions, sources: r.sources }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: String(e).replace(/^Error: /, ""), error: true }]);
    } finally {
      setBusy(false);
    }
  }

  const last = messages[messages.length - 1];
  return (
    <div className="chat">
      <div className="chat-log" ref={listRef} aria-live="polite">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p>Ask about any Global brand, competitor or audience in RAJAR {facts.release_label}. Published figures come back as verified tokens.</p>
            <div className="suggestions">
              {STARTERS.map((s) => <button key={s} className="suggestion" onClick={() => send(s)}>{s}</button>)}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} id={`msg-${i}`} className={`msg msg-${m.role} ${m.error ? "msg-error" : ""}`}>
            {m.role === "user" ? m.content : <MarkdownDoc markdown={m.content} facts={factMap} />}
            {m.sources && m.sources.length > 0 && <div className="msg-sources">{m.sources.join(" · ")}</div>}
            {m.role === "assistant" && !m.error && (
              <div className="msg-actions">
                <button className="link-btn" onClick={() => addToNotes(i, m.content)}
                  title="Adds this answer (or the text you've highlighted in it) to the notes for the writer">
                  {added === i ? "Added to notes ✓" : "+ Add to notes"}
                </button>
              </div>
            )}
          </div>
        ))}
        {busy && <div className="msg msg-assistant msg-busy"><span className="spinner" /> {busy} <span className="elapsed">{elapsed}s</span></div>}
        {!busy && last?.role === "assistant" && last.suggestions && last.suggestions.length > 0 && (
          <div className="suggestions">
            {last.suggestions.map((s) => <button key={s} className="suggestion" onClick={() => send(s)}>{s}</button>)}
          </div>
        )}
      </div>
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(input); }}>
        <textarea id="chat-input" rows={2} value={input} placeholder="Ask a question in plain English…" aria-label="Ask Pulse"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }} />
        <button className="btn btn-primary btn-icon" disabled={!!busy || !input.trim()} aria-label="Send">{Icons.send}</button>
      </form>
    </div>
  );
}


/** Chat answer -> plain note text: keeps {{tokens}} (so figures stay verified), drops Markdown styling. */
function toNote(markdown: string) {
  return markdown
    .split("\n")
    .filter((l) => !/^\s*\|?\s*:?-{3,}/.test(l))                       // table separator rows
    .map((l) => l.replace(/^\s*#{1,4}\s*/, "").replace(/\*\*(.+?)\*\*/g, "$1").replace(/^\s*[-*]\s+/, "- "))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

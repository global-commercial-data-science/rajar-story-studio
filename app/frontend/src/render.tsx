import { Fragment, type ReactNode } from "react";
import type { Fact } from "./types";

const TOKEN = /\{\{\s*([a-z0-9_]+)\s*\}\}/g;

export function renderPlain(text: string, facts: Record<string, Fact>): string {
  return text.replace(TOKEN, (_, k) => facts[k]?.display ?? `[unknown: ${k}]`);
}

/** Inline text: **bold** and {{token}} chips. */
export function Inline({ text, facts }: { text: string; facts: Record<string, Fact> }) {
  const parts: ReactNode[] = [];
  const re = /\*\*(.+?)\*\*|\{\{\s*([a-z0-9_]+)\s*\}\}/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    if (m[1] !== undefined) parts.push(<strong key={i++}><Inline text={m[1]} facts={facts} /></strong>);
    else parts.push(<Token key={i++} k={m[2]} facts={facts} />);
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

function Token({ k, facts }: { k: string; facts: Record<string, Fact> }) {
  const f = facts[k];
  if (!f) return <span className="token token-bad" title="Not a known fact">{`{{${k}}}`}</span>;
  return (
    <span className={`token ${f.status === "confirm" ? "token-confirm" : ""}`} title={`${k} · ${f.label}${f.note ? `\n${f.note}` : ""}`}>
      {f.display}
    </span>
  );
}

/** Minimal Markdown: paragraphs, bullets, headings, [Quote: …] placeholders, source line. */
export function MarkdownDoc({ markdown, facts, cards = false }: { markdown: string; facts: Record<string, Fact>; cards?: boolean }) {
  const blocks = markdown.trim().split(/\n\s*\n/);
  if (cards) {
    const cardBlocks = markdown.split(/\n(?=###\s)/).filter((b) => b.trim());
    return (
      <div className="cards">
        {cardBlocks.map((b, i) => {
          const [head, ...rest] = b.trim().split("\n");
          return (
            <div className="stat-card" key={i}>
              <div className="stat-card-head"><Inline text={head.replace(/^###\s*/, "")} facts={facts} /></div>
              {rest.filter((l) => l.trim()).map((l, j) => (
                <p key={j} className={l.trim().startsWith("#") ? "stat-card-tags" : ""}><Inline text={l} facts={facts} /></p>
              ))}
            </div>
          );
        })}
      </div>
    );
  }
  return (
    <>
      {blocks.map((block, i) => {
        const lines = block.split("\n").filter((l) => l.trim());
        if (!lines.length) return null;
        if (lines.every((l) => /^\s*[-*]\s/.test(l))) {
          return (
            <ul key={i}>
              {lines.map((l, j) => <li key={j}><Inline text={l.replace(/^\s*[-*]\s/, "")} facts={facts} /></li>)}
            </ul>
          );
        }
        if (lines.length >= 2 && lines.every((l) => l.trim().startsWith("|"))) {
          const cells = (l: string) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
          const body = lines.filter((l, j) => !(j === 1 && /^[\s|:-]+$/.test(l)));
          const [head, ...rows] = body;
          return (
            <div className="table-wrap" key={i}>
              <table>
                <thead><tr>{cells(head).map((c, j) => <th key={j}><Inline text={c} facts={facts} /></th>)}</tr></thead>
                <tbody>{rows.map((r, j) => <tr key={j}>{cells(r).map((c, k) => <td key={k}><Inline text={c} facts={facts} /></td>)}</tr>)}</tbody>
              </table>
            </div>
          );
        }
        const h = /^(#{1,4})\s+(.*)$/.exec(lines[0]);
        if (h) {
          return (
            <Fragment key={i}>
              <h3 className={`doc-h${h[1].length}`}><Inline text={h[2]} facts={facts} /></h3>
              {lines.length > 1 && <MarkdownDoc markdown={lines.slice(1).join("\n")} facts={facts} />}
            </Fragment>
          );
        }
        if (lines.every((l) => /^\s*\[Quote:.*\]\s*$/.test(l))) {
          return <Fragment key={i}>{lines.map((l, j) => <div className="quote-slot" key={j}>{l.trim()}</div>)}</Fragment>;
        }
        const text = lines.join(" ");
        if (/^Figures sourced from/i.test(text)) return <p className="source-line" key={i}>{text}</p>;
        return <p key={i}><Inline text={text} facts={facts} /></p>;
      })}
    </>
  );
}

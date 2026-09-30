import type { Angle, AnglesResult, ChatMessage, Draft, Fact, FactSet, Format, JobProgress, Menu } from "./types";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  facts: (release: number) => call<FactSet>(`/api/facts?release=${release}`),

  angles: (release: number, refresh = false, query = "") =>
    call<AnglesResult>("/api/angles", { method: "POST", body: JSON.stringify({ release, use_llm: true, refresh, query }) }),

  /** Start an angle run; resolves when done, reporting progress while it runs. */
  async anglesWithProgress(release: number, refresh: boolean, onProgress: (p: JobProgress, elapsed: number) => void, query = "") {
    const start = await call<{ job_id: string | null; status: string; result?: AnglesResult; progress?: JobProgress }>(
      "/api/angles/start", { method: "POST", body: JSON.stringify({ release, use_llm: true, refresh, query }) });
    if (!start.job_id) return start.result!;
    if (start.progress) onProgress(start.progress, 0);
    for (;;) {
      await new Promise((r) => setTimeout(r, 1000));
      const job = await call<{ status: string; progress: JobProgress; elapsed: number; result: AnglesResult | null; error: string | null }>(
        `/api/jobs/${start.job_id}`);
      onProgress(job.progress, job.elapsed);
      if (job.status === "done" && job.result) return job.result;
      if (job.status === "error") throw new Error(job.error ?? "Angle run failed");
    }
  },

  menu: (release: number) => call<Menu>(`/api/menu?release=${release}`),

  preset: (req: { release: number; kind: string; value: string; audience?: string; area?: string }) =>
    call<{ title: string; markdown: string }>("/api/preset", { method: "POST", body: JSON.stringify(req) }),

  draft: (req: {
    release: number;
    format: Format;
    angles: Angle[];
    extra_facts: Fact[];
    tone: string;
    editor_notes: string;
    refresh?: boolean;
  }) => call<Draft>("/api/draft", { method: "POST", body: JSON.stringify({ use_llm: true, ...req }) }),

  chat: (req: {
    release: number;
    question: string;
    history: { role: "user" | "assistant"; content: string }[];
    angles: Angle[];
    extra_facts: Fact[];
    draft_title: string;
    draft_markdown: string;
  }) => call<Required<Pick<ChatMessage, "facts_used" | "suggestions" | "sources">> & { answer: string }>(
    "/api/chat", { method: "POST", body: JSON.stringify(req) }),

  async exportDocx(req: { release: number; title: string; subtitle_lines: string[]; markdown: string; extra_facts: Fact[] }) {
    const res = await fetch("/api/export/docx", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!res.ok) throw new Error(`Export failed: ${res.status}`);
    const blob = await res.blob();
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? "draft.docx";
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    a.click();
    URL.revokeObjectURL(url);
  },
};

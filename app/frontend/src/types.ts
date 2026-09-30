export type Fact = {
  key: string;
  label: string;
  value: number;
  display: string;
  unit: string;
  brand: string | null;
  status: "verified" | "confirm";
  note: string;
  source: string;
  direction: string | null;
};

export type FactSet = {
  release: number;
  release_label: string;
  qoq_label: string | null;
  yoy_label: string | null;
  history_quarters: number;
  facts: Fact[];
};

export type Angle = {
  id: string;
  headline: string;
  brand: string | null;
  fact_keys: string[];
  why: string;
  strength: number;
  selected: boolean;
  family?: string | null;
};

export type AngleGroup = {
  key: string;
  name: string;
  angles: Angle[];
  also_moved: string[];
  error?: string | null;
};

export type JobProgress = { done: number; total: number; completed: string[]; stage: string };

export type MenuOption = { value: string | number; label: string };
export type Menu = {
  releases: MenuOption[];
  compare: MenuOption[];
  brands: MenuOption[];
  audiences: MenuOption[];
  areas: MenuOption[];
  questions: Record<"release" | "compare" | "period" | "brand" | "audience" | "area", string[]>;
};

export type Filters = { release: number; compare: string; brand: string; audience: string; area: string };

/** Something the top bar asks Story Studio to do: ask the chat, or show a prepared query result. */
export type StudioActionInput =
  | { kind: "question"; text: string }
  | { kind: "preset"; preset: "brand" | "audience" | "area" | "period" | "compare"; value: string };
export type StudioAction = StudioActionInput & { n: number };

export type AnglesResult = {
  groups: AngleGroup[];
  angles: Angle[];
  also_moved: string[];
  analyst_insights: string;
  extra_facts: Fact[];
  used_llm: boolean;
  model: string | null;
  tool_log: { tool: string; detail: string }[];
  error: string | null;
  cached: boolean;
  cached_at: string | null;
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  facts_used?: Fact[];
  suggestions?: string[];
  sources?: string[];
  error?: boolean;
};

export type Format = "press_release" | "exec_email" | "internal_memo" | "social_cards" | "next_quarter";

export type Draft = {
  format: Format;
  title: string;
  subtitle_lines: string[];
  markdown: string;
  tokens_used: string[];
  facts_used: Fact[];
  unknown_tokens: string[];
  unverified_numbers: string[];
  used_llm: boolean;
  error: string | null;
  cached: boolean;
  cached_at: string | null;
};

export const FORMATS: { id: Format; label: string; doc: string }[] = [
  { id: "press_release", label: "Press release", doc: "Press release" },
  { id: "exec_email", label: "Exec email", doc: "Exec email" },
  { id: "internal_memo", label: "Internal memo", doc: "Internal memo" },
  { id: "social_cards", label: "Social stat cards", doc: "Social stat cards" },
  { id: "next_quarter", label: "Next quarter", doc: "Next-quarter insight plan" },
];

const BASE = "/api";

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, init);
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return (await r.json()) as T;
}

export const api = {
  health: () => j<{ ok: boolean }>("/health"),
  status: () =>
    j<{
      conversations: number;
      messages: number;
      embeddings: number;
      topics: number;
    }>("/ingest/status"),
  ingestPath: (path: string) =>
    j<{ results: unknown[] }>("/ingest/path", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ path }),
    }),
  rebuild: () => j<{ status: string }>("/ingest/rebuild", { method: "POST" }),

  conversations: (params: { provider?: string; q?: string; limit?: number; offset?: number }) => {
    const u = new URLSearchParams();
    if (params.provider) u.set("provider", params.provider);
    if (params.q) u.set("q", params.q);
    if (params.limit) u.set("limit", String(params.limit));
    if (params.offset) u.set("offset", String(params.offset));
    return j<{ total: number; items: Conversation[] }>(`/conversations?${u}`);
  },
  conversation: (id: string) =>
    j<{ conversation: Conversation; messages: Message[]; topics: TopicLink[] }>(
      `/conversations/${encodeURIComponent(id)}`,
    ),

  calendar: () => j<{ days: DayStat[] }>("/timeline/calendar"),
  day: (date: string) =>
    j<{
      date: string;
      conversations: Conversation[];
      top_topics: { id: number; label: string; hits: number }[];
      sample_questions: string[];
      models: Record<string, number>;
    }>(`/timeline/day/${date}`),

  topics: () => j<{ items: Topic[] }>("/topics"),
  topic: (id: number) =>
    j<{
      topic: Topic;
      conversations: Conversation[];
      series: { bucket: string; count: number }[];
    }>(`/topics/${id}`),
  topicGraph: () => j<{ edges: { src: number; dst: number; weight: number }[] }>("/topics/graph/edges"),

  search: (q: string, mode: "hybrid" | "fts" | "semantic" = "hybrid") =>
    j<{ hits: SearchHit[] }>(`/search?q=${encodeURIComponent(q)}&mode=${mode}`),

  statsSummary: () => j<StatsSummary>("/stats/summary"),

  progression: (topicId?: number) =>
    j<{
      series: ProgressionPoint[];
      examples: { earliest: Example | null; latest: Example | null } | null;
    }>(`/progression${topicId != null ? `?topic_id=${topicId}` : ""}`),

  exportVault: (path: string) =>
    j<{ vault: string; conversations: number; topics: number; days: number }>(
      "/export/vault",
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ path }),
      },
    ),
};

export interface Conversation {
  id: string;
  provider: string;
  title: string | null;
  created_at: number | null;
  updated_at: number | null;
  model: string | null;
  msg_count?: number;
}

export interface Message {
  id: string;
  role: string;
  content: string;
  created_at: number | null;
  tokens: number | null;
  model: string | null;
}

export interface TopicLink {
  id: number;
  label: string;
  score: number;
}

export interface DayStat {
  date: string;
  msg_count: number;
  token_count: number;
  models: Record<string, number>;
}

export interface Topic {
  id: number;
  label: string;
  keywords: string[];
  conversation_count?: number;
  message_count?: number;
}

export interface SearchHit {
  message_id: string;
  conversation_id: string;
  conversation_title: string | null;
  role: string;
  content: string;
  created_at: number | null;
  provider: string;
  score: number;
}

export interface StatsSummary {
  conversations: number;
  messages: number;
  tokens: number;
  by_provider: Record<string, number>;
  assistant_models: Record<string, number>;
  hours: Record<string, number>;
  conversation_lengths: number[];
}

export interface ProgressionPoint {
  bucket: string;
  avg_user_len: number;
  type_token_ratio: number;
  followups_per_conv: number;
  topic_term_freq: number;
  score: number;
  sample_count: number;
}

export interface Example {
  id: string;
  content: string;
  created_at: number | null;
  title: string | null;
}

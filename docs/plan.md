# Ultimate LLM Explorer — Design

## Goal

A local-first tool that ingests LLM chat-history exports from multiple
providers, normalizes them into one searchable corpus, and surfaces insights a
plain Obsidian-style notebook doesn't:

- **Time-travel** — "what was I asking on date X?"
- **Topic evolution** — how themes emerge, peak, and fade.
- **Skill progression** — per-topic sophistication over time.
- **Usage stats** — volume, cadence, models, peak hours.

Output supports both a rich local web UI and an Obsidian-compatible markdown
vault.

## Scope (v1)

- Providers: ChatGPT, Claude.ai, Google Gemini (Takeout).
- Interfaces: local web app + Obsidian vault export + small CLI.
- Embeddings: local `sentence-transformers` only. No network.
- Insights: all four categories above.

## Stack

| Layer     | Choice |
|-----------|--------|
| Backend   | Python 3.11, FastAPI |
| Storage   | SQLite with FTS5 |
| Embedding | `sentence-transformers/all-MiniLM-L6-v2` |
| Topics    | BERTopic |
| Vector    | faiss-cpu (flat index, rebuilt at startup) |
| Frontend  | React + Vite + TypeScript + Tailwind + Recharts |

## Canonical schema

- `conversations(id, provider, external_id, title, created_at, updated_at,
  model, raw_ref)`
- `messages(id, conversation_id, parent_id, role, content, created_at, tokens,
  model, attachments_json)`
- `messages_fts(content, title)` — FTS5, synced via triggers.
- `embeddings(message_id PRIMARY KEY, vector BLOB)` — float32 bytes; faiss
  index built in memory at startup.
- `topics(id, label, keywords_json, created_at)`
- `conversation_topics(conversation_id, topic_id, score)`
- `daily_stats(date, msg_count, token_count, models_json)`

ChatGPT's tree is flattened to the primary branch by walking `current_node`;
other branches are retained via `parent_id`.

## Flows

### Ingest
1. User drops files or runs `ulle ingest <path>`.
2. `detector.py` inspects each file → picks an adapter.
3. Adapter yields normalized `Conversation` + `Message` records.
4. DB writes + FTS5 triggers sync.
5. Background jobs: embeddings → topics → progression → daily stats.

### Time-travel
- Calendar heatmap of days-active.
- Click day → chronological conversations + auto daily brief (top topics,
  sample user questions, counts).

### Topics
- BERTopic on user-message embeddings.
- Per topic: label, keywords, examples, time-series count, related edges.

### Skill progression
Per topic, rolling metrics over time:
- user message length
- vocabulary richness (type-token ratio)
- follow-ups per conversation
- topic-specific term frequency

Combined into a normalized sophistication score, bookended with "earliest vs.
latest" example pair.

### Search
Hybrid: FTS5 BM25 ⊕ vector cosine, RRF-merged. Filters: date, provider,
topic, role.

### Obsidian vault export
- One `.md` per conversation with YAML frontmatter.
- Wiki-links to `[[Daily/YYYY-MM-DD]]` and `[[Topics/<label>]]`.
- Auto MOC index notes per topic and per month.
- Top-k similar-conversation links.

## Out of scope (v1)

- Additional providers (Perplexity, Poe, Copilot) — adapter framework makes
  these easy adds.
- Auth / multi-user.
- LLM-powered summarization.
- Hosted deployment.

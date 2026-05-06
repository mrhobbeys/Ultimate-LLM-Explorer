# Ultimate LLM Explorer

A local-first explorer for your LLM chat history. Dump exports from ChatGPT,
Claude.ai, and Google Gemini into one place, search them, and see how your
questions (and your skill) have evolved over time. Everything runs on your
machine — no API keys, no data leaves your laptop.

## What you get

- **Time-travel** — calendar heatmap + daily briefs of what you were asking.
- **Topics** — BERTopic clusters with evolution over time and a topic graph.
- **Skill progression** — per-topic sophistication metrics plotted over time,
  with "earliest vs. latest" example pairs.
- **Stats** — messages per day, peak hours, model mix, conversation lengths.
- **Hybrid search** — full-text (SQLite FTS5) fused with local semantic search
  (sentence-transformers + faiss).
- **Obsidian vault export** — one markdown file per conversation with YAML
  frontmatter, daily notes, topic MOCs, and wiki-links between related chats.

## Supported providers

| Provider   | Format                                         |
|------------|------------------------------------------------|
| ChatGPT    | `conversations.json` from Settings → Data Export |
| Claude.ai  | JSON export from Settings → Account → Export    |
| Gemini     | Google Takeout → *My Activity* (HTML or JSON)  |

## Quickstart

```bash
# one-time setup
make install

# run the app (backend on :8000, frontend on :5173)
make dev
```

Then open http://localhost:5173, drop your export files into the Ingest page,
and go exploring.

### CLI

```bash
ulle ingest ~/Downloads/chatgpt-export/conversations.json
ulle ingest ~/Downloads/claude-export.json
ulle ingest ~/Downloads/Takeout/My\ Activity/Gemini/
ulle export-vault ~/Obsidian/LLM-Archive
```

## Architecture

See [the plan](./docs/plan.md) for the full design. Short version:

- **Backend**: Python 3.11 + FastAPI + SQLite (FTS5) + sentence-transformers +
  BERTopic + faiss-cpu.
- **Frontend**: React + Vite + TypeScript + Tailwind + Recharts.
- **Data**: one SQLite file under `./data/ulle.db` by default.

## Privacy

The backend binds to `127.0.0.1`. Embeddings run locally via
`sentence-transformers/all-MiniLM-L6-v2`. No telemetry. You can run with the
network disabled once the model is cached.

## Development

```bash
make test      # pytest
make lint      # ruff + mypy
make frontend  # vite dev server only
make backend   # uvicorn only
```

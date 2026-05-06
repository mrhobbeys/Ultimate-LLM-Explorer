import { useState } from "react";
import { Link } from "react-router-dom";
import { api, SearchHit } from "../lib/api";
import { Empty, Loading, Panel, Pill } from "../components/Panel";
import { formatDay } from "../lib/date";

type Mode = "hybrid" | "fts" | "semantic";

export default function Search() {
  const [q, setQ] = useState("");
  const [mode, setMode] = useState<Mode>("hybrid");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    setHits(null);
    try {
      const r = await api.search(q.trim(), mode);
      setHits(r.hits);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Panel title="Search">
        <form onSubmit={run} className="flex gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="e.g. postgres vacuum"
            className="flex-1 rounded bg-slate-950 border border-slate-800 px-3 py-2 text-sm"
            autoFocus
          />
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as Mode)}
            className="bg-slate-950 border border-slate-800 rounded text-xs px-2 py-1"
          >
            <option value="hybrid">hybrid</option>
            <option value="fts">keyword</option>
            <option value="semantic">semantic</option>
          </select>
          <button
            type="submit"
            className="rounded bg-indigo-500 px-4 py-2 text-sm font-medium hover:bg-indigo-400"
          >
            Search
          </button>
        </form>
      </Panel>
      <Panel title="Results">
        {busy ? (
          <Loading />
        ) : hits === null ? (
          <Empty>Run a query to see results.</Empty>
        ) : hits.length === 0 ? (
          <Empty>No matches.</Empty>
        ) : (
          <ul className="space-y-3">
            {hits.map((h) => (
              <li key={h.message_id} className="border-b border-slate-800 pb-3">
                <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
                  <Pill>{h.provider}</Pill>
                  <Pill>{h.role}</Pill>
                  <span>{formatDay(h.created_at)}</span>
                  <span className="ml-auto tabular-nums">
                    {h.score.toFixed(3)}
                  </span>
                </div>
                <Link
                  to={`/conversations/${encodeURIComponent(h.conversation_id)}`}
                  className="text-sm text-indigo-300 hover:underline font-medium"
                >
                  {h.conversation_title || h.conversation_id}
                </Link>
                <div className="mt-1 text-sm text-slate-300 prose-msg">
                  {h.content}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

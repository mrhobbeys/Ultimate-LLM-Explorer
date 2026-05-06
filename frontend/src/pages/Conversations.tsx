import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Conversation } from "../lib/api";
import { Empty, Loading, Panel, Pill } from "../components/Panel";
import { formatDay } from "../lib/date";

export default function Conversations() {
  const [items, setItems] = useState<Conversation[] | null>(null);
  const [total, setTotal] = useState(0);
  const [provider, setProvider] = useState("");
  const [q, setQ] = useState("");

  useEffect(() => {
    const t = setTimeout(async () => {
      setItems(null);
      const r = await api.conversations({ provider: provider || undefined, q: q || undefined, limit: 100 });
      setItems(r.items);
      setTotal(r.total);
    }, 200);
    return () => clearTimeout(t);
  }, [provider, q]);

  return (
    <Panel
      title="Conversations"
      right={
        <div className="flex items-center gap-2">
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="bg-slate-950 border border-slate-800 rounded text-xs px-2 py-1"
          >
            <option value="">All providers</option>
            <option value="chatgpt">ChatGPT</option>
            <option value="claude">Claude</option>
            <option value="gemini">Gemini</option>
          </select>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="filter title…"
            className="bg-slate-950 border border-slate-800 rounded text-xs px-2 py-1"
          />
          <span className="text-xs text-slate-500">{total} total</span>
        </div>
      }
    >
      {items === null ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>no matches</Empty>
      ) : (
        <ul className="divide-y divide-slate-800">
          {items.map((c) => (
            <li key={c.id} className="py-2 flex items-center gap-3">
              <Pill>{c.provider}</Pill>
              <Link
                to={`/conversations/${encodeURIComponent(c.id)}`}
                className="text-indigo-300 hover:underline flex-1 truncate"
              >
                {c.title || c.id}
              </Link>
              <span className="text-xs text-slate-500 tabular-nums">
                {formatDay(c.created_at)}
              </span>
              <span className="text-xs text-slate-500 tabular-nums w-10 text-right">
                {c.msg_count ?? 0}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

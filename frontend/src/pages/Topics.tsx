import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Topic } from "../lib/api";
import { Empty, Loading, Panel, Pill } from "../components/Panel";

export default function Topics() {
  const [items, setItems] = useState<Topic[] | null>(null);
  useEffect(() => {
    api.topics().then((r) => setItems(r.items));
  }, []);

  if (items === null) return <Loading />;
  if (items.length === 0)
    return (
      <Panel title="Topics">
        <Empty>
          None yet. After you ingest enough data (~10+ user messages), topics get
          built during the background reindex step.
        </Empty>
      </Panel>
    );

  return (
    <Panel title={`Topics · ${items.length}`}>
      <ul className="grid gap-3 md:grid-cols-2">
        {items.map((t) => (
          <li
            key={t.id}
            className="rounded border border-slate-800 p-3 hover:border-indigo-600 transition"
          >
            <Link to={`/topics/${t.id}`} className="block">
              <div className="text-sm font-medium text-indigo-300 mb-1">
                {t.label}
              </div>
              <div className="text-xs text-slate-500 mb-2">
                {t.conversation_count ?? 0} conversations ·{" "}
                {t.message_count ?? 0} messages
              </div>
              <div className="flex flex-wrap gap-1">
                {t.keywords.slice(0, 8).map((k) => (
                  <Pill key={k}>{k}</Pill>
                ))}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, Conversation, Message, TopicLink } from "../lib/api";
import { Empty, Loading, Panel, Pill } from "../components/Panel";
import { formatTs } from "../lib/date";

export default function ConversationPage() {
  const { id = "" } = useParams();
  const [data, setData] = useState<{
    conversation: Conversation;
    messages: Message[];
    topics: TopicLink[];
  } | null>(null);

  useEffect(() => {
    if (!id) return;
    setData(null);
    api.conversation(id).then((r) => setData(r));
  }, [id]);

  if (data === null) return <Loading />;

  return (
    <div className="grid gap-6 lg:grid-cols-[3fr_1fr]">
      <Panel title={data.conversation.title || data.conversation.id}>
        <div className="flex flex-wrap gap-2 mb-4 text-xs">
          <Pill>{data.conversation.provider}</Pill>
          {data.conversation.model && <Pill>{data.conversation.model}</Pill>}
          <Pill>{formatTs(data.conversation.created_at)}</Pill>
        </div>
        {data.messages.length === 0 ? (
          <Empty>no messages</Empty>
        ) : (
          <ol className="space-y-5">
            {data.messages.map((m) => (
              <li key={m.id} className="border-l-2 border-slate-800 pl-4">
                <div className="text-xs text-slate-500 mb-1 uppercase tracking-wider">
                  {m.role}
                  {m.created_at ? ` · ${formatTs(m.created_at)}` : ""}
                  {m.tokens ? ` · ${m.tokens} tok` : ""}
                </div>
                <div
                  className={`prose-msg ${
                    m.role === "user" ? "text-slate-100" : "text-slate-300"
                  }`}
                >
                  {m.content}
                </div>
              </li>
            ))}
          </ol>
        )}
      </Panel>
      <Panel title="Topics">
        {data.topics.length === 0 ? (
          <Empty>none assigned</Empty>
        ) : (
          <ul className="space-y-1 text-sm">
            {data.topics.map((t) => (
              <li key={t.id}>
                <Link
                  to={`/topics/${t.id}`}
                  className="text-indigo-300 hover:underline"
                >
                  {t.label}
                </Link>
                <span className="text-xs text-slate-500 ml-1">
                  · {t.score.toFixed(1)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

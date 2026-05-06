import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, Conversation, Topic } from "../lib/api";
import { Empty, Loading, Panel, Pill } from "../components/Panel";
import { formatDay } from "../lib/date";

export default function TopicDetail() {
  const { id } = useParams();
  const topicId = Number(id);
  const [data, setData] = useState<{
    topic: Topic;
    conversations: Conversation[];
    series: { bucket: string; count: number }[];
  } | null>(null);

  useEffect(() => {
    if (!Number.isFinite(topicId)) return;
    api.topic(topicId).then((r) => setData(r));
  }, [topicId]);

  if (data === null) return <Loading />;

  return (
    <div className="grid gap-6">
      <Panel title={data.topic.label}>
        <div className="flex flex-wrap gap-1 mb-4">
          {data.topic.keywords.map((k) => (
            <Pill key={k}>{k}</Pill>
          ))}
        </div>
        <div className="h-56">
          {data.series.length === 0 ? (
            <Empty>no time series</Empty>
          ) : (
            <ResponsiveContainer>
              <BarChart data={data.series}>
                <CartesianGrid stroke="#1f2937" vertical={false} />
                <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: "#64748b" }} />
                <YAxis tick={{ fontSize: 10, fill: "#64748b" }} />
                <Tooltip
                  contentStyle={{
                    background: "#0f172a",
                    border: "1px solid #1f2937",
                  }}
                />
                <Bar dataKey="count" fill="#818cf8" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="mt-2 text-xs">
          <Link
            to={`/progression?topic_id=${data.topic.id}`}
            className="text-indigo-300 hover:underline"
          >
            See skill progression for this topic →
          </Link>
        </div>
      </Panel>
      <Panel title={`Conversations · ${data.conversations.length}`}>
        {data.conversations.length === 0 ? (
          <Empty>none</Empty>
        ) : (
          <ul className="divide-y divide-slate-800">
            {data.conversations.map((c) => (
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
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, Example, ProgressionPoint, Topic } from "../lib/api";
import { Empty, Loading, Panel, Pill } from "../components/Panel";
import { formatTs } from "../lib/date";

export default function Progression() {
  const [params, setParams] = useSearchParams();
  const topicId = params.get("topic_id");
  const [topics, setTopics] = useState<Topic[] | null>(null);
  const [data, setData] = useState<{
    series: ProgressionPoint[];
    examples: { earliest: Example | null; latest: Example | null } | null;
  } | null>(null);

  useEffect(() => {
    api.topics().then((r) => setTopics(r.items));
  }, []);

  useEffect(() => {
    setData(null);
    api
      .progression(topicId ? Number(topicId) : undefined)
      .then((r) => setData(r));
  }, [topicId]);

  const selected = useMemo(
    () => topics?.find((t) => String(t.id) === topicId) || null,
    [topics, topicId],
  );

  return (
    <div className="grid gap-6">
      <Panel
        title={`Skill progression${selected ? ` · ${selected.label}` : " · all topics"}`}
        right={
          <select
            value={topicId ?? ""}
            onChange={(e) => {
              const v = e.target.value;
              if (v) setParams({ topic_id: v });
              else setParams({});
            }}
            className="bg-slate-950 border border-slate-800 rounded text-xs px-2 py-1"
          >
            <option value="">All (overall)</option>
            {topics?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        }
      >
        {data === null ? (
          <Loading />
        ) : data.series.length === 0 ? (
          <Empty>
            Not enough tagged data yet. Try ingesting more or triggering a
            reindex.
          </Empty>
        ) : (
          <div className="h-72">
            <ResponsiveContainer>
              <LineChart data={data.series}>
                <CartesianGrid stroke="#1f2937" vertical={false} />
                <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: "#64748b" }} />
                <YAxis tick={{ fontSize: 10, fill: "#64748b" }} domain={[0, 1]} />
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #1f2937" }}
                />
                <Line
                  type="monotone"
                  dataKey="score"
                  stroke="#818cf8"
                  dot={false}
                  strokeWidth={2}
                />
                <Line
                  type="monotone"
                  dataKey="type_token_ratio"
                  stroke="#34d399"
                  dot={false}
                  strokeWidth={1.5}
                />
                <Line
                  type="monotone"
                  dataKey="topic_term_freq"
                  stroke="#f97316"
                  dot={false}
                  strokeWidth={1.5}
                />
              </LineChart>
            </ResponsiveContainer>
            <div className="mt-2 flex gap-3 text-xs text-slate-400">
              <span>
                <span className="inline-block w-3 h-1.5 bg-indigo-400 mr-1" />
                score
              </span>
              <span>
                <span className="inline-block w-3 h-1.5 bg-emerald-400 mr-1" />
                type-token ratio
              </span>
              <span>
                <span className="inline-block w-3 h-1.5 bg-orange-500 mr-1" />
                topic-term freq
              </span>
            </div>
          </div>
        )}
      </Panel>
      {data?.examples && (
        <div className="grid gap-4 md:grid-cols-2">
          <Panel title="Earliest question">
            {data.examples.earliest ? (
              <div>
                <div className="text-xs text-slate-500 mb-2">
                  <Pill>{formatTs(data.examples.earliest.created_at)}</Pill>
                  <span className="ml-2">{data.examples.earliest.title}</span>
                </div>
                <div className="prose-msg text-slate-200">
                  {data.examples.earliest.content}
                </div>
              </div>
            ) : (
              <Empty>none</Empty>
            )}
          </Panel>
          <Panel title="Latest question">
            {data.examples.latest ? (
              <div>
                <div className="text-xs text-slate-500 mb-2">
                  <Pill>{formatTs(data.examples.latest.created_at)}</Pill>
                  <span className="ml-2">{data.examples.latest.title}</span>
                </div>
                <div className="prose-msg text-slate-200">
                  {data.examples.latest.content}
                </div>
              </div>
            ) : (
              <Empty>none</Empty>
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}

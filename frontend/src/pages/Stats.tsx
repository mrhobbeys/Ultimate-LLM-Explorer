import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, StatsSummary } from "../lib/api";
import { Empty, Loading, Panel, Pill } from "../components/Panel";

const COLORS = ["#818cf8", "#34d399", "#f97316", "#f43f5e", "#eab308", "#22d3ee"];

export default function Stats() {
  const [s, setS] = useState<StatsSummary | null>(null);
  useEffect(() => {
    api.statsSummary().then(setS);
  }, []);

  if (s === null) return <Loading />;
  if (s.messages === 0)
    return (
      <Panel title="Stats">
        <Empty>No data yet.</Empty>
      </Panel>
    );

  const hours = Array.from({ length: 24 }, (_, h) => ({
    hour: h,
    count: s.hours[h] ?? 0,
  }));
  const providerData = Object.entries(s.by_provider).map(([name, value]) => ({
    name,
    value,
  }));
  const modelData = Object.entries(s.assistant_models)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([name, value]) => ({ name, value }));
  const lengthBuckets = bucketize(s.conversation_lengths);

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Panel title="Overview">
        <div className="flex flex-wrap gap-2">
          <Pill>{s.conversations} conversations</Pill>
          <Pill>{s.messages} messages</Pill>
          <Pill>{s.tokens.toLocaleString()} tokens</Pill>
        </div>
      </Panel>
      <Panel title="By provider">
        <div className="h-52">
          <ResponsiveContainer>
            <PieChart>
              <Pie data={providerData} dataKey="value" nameKey="name" outerRadius={80}>
                {providerData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #1f2937" }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </Panel>
      <Panel title="Peak hours (UTC)">
        <div className="h-52">
          <ResponsiveContainer>
            <BarChart data={hours}>
              <CartesianGrid stroke="#1f2937" vertical={false} />
              <XAxis dataKey="hour" tick={{ fontSize: 10, fill: "#64748b" }} />
              <YAxis tick={{ fontSize: 10, fill: "#64748b" }} />
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #1f2937" }} />
              <Bar dataKey="count" fill="#34d399" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>
      <Panel title="Assistant models">
        <div className="h-52">
          <ResponsiveContainer>
            <BarChart data={modelData} layout="vertical">
              <CartesianGrid stroke="#1f2937" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 10, fill: "#64748b" }} />
              <YAxis
                dataKey="name"
                type="category"
                width={120}
                tick={{ fontSize: 10, fill: "#64748b" }}
              />
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #1f2937" }} />
              <Bar dataKey="value" fill="#818cf8" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>
      <Panel title="Conversation length distribution">
        <div className="h-52">
          <ResponsiveContainer>
            <BarChart data={lengthBuckets}>
              <CartesianGrid stroke="#1f2937" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10, fill: "#64748b" }} />
              <YAxis tick={{ fontSize: 10, fill: "#64748b" }} />
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #1f2937" }} />
              <Bar dataKey="count" fill="#f97316" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>
    </div>
  );
}

function bucketize(lengths: number[]) {
  const edges = [1, 3, 6, 11, 21, 51, 101];
  const labels = ["1-2", "3-5", "6-10", "11-20", "21-50", "51-100", "100+"];
  const counts = new Array(labels.length).fill(0);
  for (const n of lengths) {
    let i = edges.findIndex((e, idx) => n < (edges[idx + 1] ?? Infinity));
    if (i === -1) i = labels.length - 1;
    counts[i]++;
  }
  return labels.map((label, i) => ({ label, count: counts[i] }));
}

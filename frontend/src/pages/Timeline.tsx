import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, DayStat } from "../lib/api";
import { Empty, Loading, Panel, Pill } from "../components/Panel";

interface DayDetail {
  date: string;
  conversations: { id: string; title: string | null; provider: string; msg_count: number }[];
  top_topics: { id: number; label: string; hits: number }[];
  sample_questions: string[];
}

function dayColor(n: number, max: number): string {
  if (n === 0) return "bg-slate-900";
  const ratio = Math.min(1, n / (max || 1));
  if (ratio > 0.75) return "bg-indigo-400";
  if (ratio > 0.5) return "bg-indigo-500";
  if (ratio > 0.25) return "bg-indigo-700";
  return "bg-indigo-900";
}

function buildCalendar(days: DayStat[]): { date: string; msg: number }[] {
  if (days.length === 0) return [];
  const byDate = new Map(days.map((d) => [d.date, d.msg_count]));
  const dates = days.map((d) => new Date(d.date + "T00:00:00Z").getTime());
  const minTs = Math.min(...dates);
  const maxTs = Math.max(...dates);
  const out: { date: string; msg: number }[] = [];
  for (let t = minTs; t <= maxTs; t += 86400000) {
    const date = new Date(t).toISOString().slice(0, 10);
    out.push({ date, msg: byDate.get(date) ?? 0 });
  }
  return out;
}

export default function Timeline() {
  const [days, setDays] = useState<DayStat[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<DayDetail | null>(null);

  useEffect(() => {
    api.calendar().then((r) => setDays(r.days));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setDetail(null);
    api.day(selected).then((r) => setDetail(r as DayDetail));
  }, [selected]);

  const cells = useMemo(() => buildCalendar(days || []), [days]);
  const max = useMemo(() => Math.max(0, ...cells.map((c) => c.msg)), [cells]);

  return (
    <div className="grid gap-6 lg:grid-cols-[2fr_3fr]">
      <Panel title="Daily activity">
        {days === null ? (
          <Loading />
        ) : cells.length === 0 ? (
          <Empty>No data yet. Head to Ingest.</Empty>
        ) : (
          <div>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(14px,1fr))] gap-[3px]">
              {cells.map((c) => (
                <button
                  key={c.date}
                  title={`${c.date}: ${c.msg} msgs`}
                  onClick={() => setSelected(c.date)}
                  className={`aspect-square rounded-sm ${dayColor(
                    c.msg,
                    max,
                  )} ${selected === c.date ? "ring-2 ring-indigo-300" : ""}`}
                />
              ))}
            </div>
            <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
              <span>Less</span>
              <span className="w-3 h-3 rounded-sm bg-slate-900" />
              <span className="w-3 h-3 rounded-sm bg-indigo-900" />
              <span className="w-3 h-3 rounded-sm bg-indigo-700" />
              <span className="w-3 h-3 rounded-sm bg-indigo-500" />
              <span className="w-3 h-3 rounded-sm bg-indigo-400" />
              <span>More</span>
            </div>
          </div>
        )}
      </Panel>

      <Panel title={selected ? `Brief · ${selected}` : "Pick a day"}>
        {!selected ? (
          <Empty>Click any square to open that day.</Empty>
        ) : detail === null ? (
          <Loading />
        ) : (
          <div className="space-y-4 text-sm">
            <div>
              <div className="text-xs uppercase tracking-wider text-slate-500 mb-1">
                Top topics
              </div>
              <div className="flex flex-wrap gap-2">
                {detail.top_topics.length === 0 && <Empty>none yet</Empty>}
                {detail.top_topics.map((t) => (
                  <Link key={t.id} to={`/topics/${t.id}`}>
                    <Pill>
                      {t.label} · {t.hits}
                    </Pill>
                  </Link>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider text-slate-500 mb-1">
                Sample questions
              </div>
              <ul className="list-disc pl-5 space-y-1 text-slate-300">
                {detail.sample_questions.slice(0, 3).map((q, i) => (
                  <li key={i}>{q.slice(0, 220)}</li>
                ))}
              </ul>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider text-slate-500 mb-1">
                Conversations
              </div>
              <ul className="space-y-1">
                {detail.conversations.map((c) => (
                  <li key={c.id}>
                    <Link
                      to={`/conversations/${encodeURIComponent(c.id)}`}
                      className="text-indigo-300 hover:underline"
                    >
                      {c.title || c.id}
                    </Link>{" "}
                    <span className="text-xs text-slate-500">
                      · {c.provider} · {c.msg_count} msgs
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}

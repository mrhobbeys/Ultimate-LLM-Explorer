import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Empty, Loading, Panel, Pill } from "../components/Panel";

export default function Ingest() {
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [status, setStatus] = useState<{
    conversations: number;
    messages: number;
    embeddings: number;
    topics: number;
  } | null>(null);
  const [vaultPath, setVaultPath] = useState("");

  async function refresh() {
    try {
      setStatus(await api.status());
    } catch (e) {
      // swallow; backend may be starting
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function submit() {
    if (!path.trim()) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.ingestPath(path.trim());
      const total = (r.results as { conversations: number }[]).reduce(
        (n, x) => n + (x.conversations || 0),
        0,
      );
      setMsg(`Ingested ${total} conversation(s). Background indexing started.`);
      await refresh();
    } catch (e: unknown) {
      setMsg(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function rebuild() {
    await api.rebuild();
    setMsg("Reindex scheduled.");
  }

  async function doExport() {
    if (!vaultPath.trim()) return;
    setBusy(true);
    try {
      const r = await api.exportVault(vaultPath.trim());
      setMsg(`Exported ${r.conversations} notes to ${r.vault}`);
    } catch (e: unknown) {
      setMsg(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <Panel title="Ingest from a path">
        <p className="text-sm text-slate-400 mb-3">
          Point to a file (conversations.json, Claude export.json, Takeout HTML/JSON)
          or a folder containing any of them. Everything runs locally.
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="/home/you/Downloads/chatgpt/conversations.json"
            className="flex-1 rounded bg-slate-950 border border-slate-800 px-3 py-2 text-sm"
          />
          <button
            disabled={busy}
            onClick={submit}
            className="rounded bg-indigo-500 px-4 py-2 text-sm font-medium hover:bg-indigo-400 disabled:opacity-40"
          >
            Ingest
          </button>
        </div>
        <div className="flex gap-2 mt-3">
          <button
            onClick={rebuild}
            className="text-xs text-slate-400 underline hover:text-slate-200"
          >
            Reindex (embeddings + topics)
          </button>
        </div>
        {msg && <div className="mt-3 text-xs text-slate-300">{msg}</div>}
      </Panel>

      <Panel title="Obsidian vault export">
        <p className="text-sm text-slate-400 mb-3">
          Writes one markdown note per conversation plus daily and topic MOCs.
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={vaultPath}
            onChange={(e) => setVaultPath(e.target.value)}
            placeholder="/home/you/Obsidian/LLM-Archive"
            className="flex-1 rounded bg-slate-950 border border-slate-800 px-3 py-2 text-sm"
          />
          <button
            disabled={busy}
            onClick={doExport}
            className="rounded bg-emerald-500 px-4 py-2 text-sm font-medium hover:bg-emerald-400 disabled:opacity-40"
          >
            Export
          </button>
        </div>
      </Panel>

      <Panel title="Library status">
        {status === null ? (
          <Loading />
        ) : status.conversations === 0 ? (
          <Empty>No data yet. Ingest an export to get started.</Empty>
        ) : (
          <div className="flex flex-wrap gap-2 text-sm">
            <Pill>{status.conversations} conversations</Pill>
            <Pill>{status.messages} messages</Pill>
            <Pill>{status.embeddings} embeddings</Pill>
            <Pill>{status.topics} topics</Pill>
          </div>
        )}
      </Panel>
    </div>
  );
}

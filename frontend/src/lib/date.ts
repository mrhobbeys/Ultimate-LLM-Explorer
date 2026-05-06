export function formatTs(ts: number | null | undefined): string {
  if (ts == null) return "";
  return new Date(ts * 1000).toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

export function formatDay(ts: number | null | undefined): string {
  if (ts == null) return "";
  return new Date(ts * 1000).toISOString().slice(0, 10);
}

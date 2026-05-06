import { ReactNode } from "react";

export function Panel({
  title,
  children,
  right,
}: {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/50 p-5 shadow-sm">
      {(title || right) && (
        <header className="flex items-center justify-between mb-3">
          {title && <h2 className="text-sm font-medium text-slate-300">{title}</h2>}
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export function Pill({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
      {children}
    </span>
  );
}

export function Loading() {
  return <div className="text-xs text-slate-500">Loading…</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-sm text-slate-500 italic">{children}</div>;
}

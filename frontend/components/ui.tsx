"use client";

import { ReactNode } from "react";

export function Panel({
  title,
  count,
  onRefresh,
  children,
  right,
}: {
  title: string;
  count?: number | string;
  onRefresh?: () => void;
  children: ReactNode;
  right?: ReactNode;
}) {
  return (
    <section className="flex h-full flex-col overflow-hidden rounded-md border border-edge bg-panel">
      <header className="flex items-center justify-between border-b border-edge px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="label text-signal">{title}</span>
          {count !== undefined && (
            <span className="label text-muted">[{count}]</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {right}
          {onRefresh && (
            <button
              onClick={onRefresh}
              className="label text-muted transition-colors hover:text-ink"
            >
              ↻ refresh
            </button>
          )}
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-auto">{children}</div>
    </section>
  );
}

const STATUS_COLORS: Record<string, string> = {
  success: "bg-ok",
  ok: "bg-ok",
  ready: "bg-ok",
  pending_approval: "bg-warn",
  skipped: "bg-muted",
  error: "bg-danger",
  invalid_args: "bg-danger",
  not_permitted: "bg-danger",
  degraded: "bg-warn",
};

export function statusColor(status?: string): string {
  return STATUS_COLORS[status ?? ""] ?? "bg-info";
}

export function Dot({ status, pulse }: { status?: string; pulse?: boolean }) {
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${statusColor(status)} ${
        pulse ? "animate-pulseDot" : ""
      }`}
    />
  );
}

export function Badge({ children, tone = "muted" }: { children: ReactNode; tone?: string }) {
  const tones: Record<string, string> = {
    muted: "border-edge2 text-muted",
    signal: "border-signal/40 text-signal",
    ok: "border-ok/40 text-ok",
    warn: "border-warn/40 text-warn",
    danger: "border-danger/40 text-danger",
    info: "border-info/40 text-info",
  };
  return (
    <span className={`label rounded border px-1.5 py-0.5 ${tones[tone] ?? tones.muted}`}>
      {children}
    </span>
  );
}

export function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center p-8 text-center text-sm text-muted">
      {text}
    </div>
  );
}

export function ago(epochSeconds: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - epochSeconds));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

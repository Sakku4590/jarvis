"use client";

import { useCallback, useEffect, useState } from "react";
import { ToolEntry, getToolActivity } from "@/lib/api";
import { Badge, Dot, Empty, Panel, ago } from "./ui";

const RISK_TONE: Record<string, string> = {
  read: "muted",
  write: "info",
  destructive: "danger",
};

export default function ToolActivity() {
  const [tools, setTools] = useState<ToolEntry[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setTools(await getToolActivity());
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <Panel title="Tool activity" count={tools.length} onRefresh={load}>
      {err ? (
        <Empty text={`Could not load activity (${err})`} />
      ) : tools.length === 0 ? (
        <Empty text="No tool calls yet. They stream in as agents work." />
      ) : (
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 bg-panel">
            <tr className="label text-muted">
              <th className="px-4 py-2 font-normal">status</th>
              <th className="px-4 py-2 font-normal">tool</th>
              <th className="px-4 py-2 font-normal">risk</th>
              <th className="px-4 py-2 font-normal text-right">ms</th>
              <th className="px-4 py-2 font-normal text-right">when</th>
            </tr>
          </thead>
          <tbody>
            {tools.map((t, i) => (
              <tr key={i} className="border-t border-edge hover:bg-panel2">
                <td className="px-4 py-2">
                  <span className="flex items-center gap-2">
                    <Dot status={t.status} />
                    <span className="font-mono text-xs text-muted">{t.status}</span>
                  </span>
                </td>
                <td className="px-4 py-2 font-mono text-xs text-ink">{t.tool}</td>
                <td className="px-4 py-2">
                  <Badge tone={RISK_TONE[t.risk] ?? "muted"}>{t.risk}</Badge>
                </td>
                <td className="px-4 py-2 text-right font-mono text-xs text-muted">
                  {t.duration_ms ?? "—"}
                </td>
                <td className="px-4 py-2 text-right label text-muted">{ago(t.time)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { Agent, getAgents } from "@/lib/api";
import { Badge, Dot, Empty, Panel } from "./ui";

function authLabel(a: Agent): string {
  if (a.auth === "oauth") return "OAuth";
  if (a.auth === "app") return "App key";
  return "Built-in";
}

function connState(a: Agent): { tone: string; text: string; status: string } {
  if (a.connected === null) return { tone: "muted", text: "unknown", status: "skipped" };
  if (a.connected) return { tone: "ok", text: "ready", status: "ok" };
  return { tone: "warn", text: "not connected", status: "pending_approval" };
}

export default function AgentStatus() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setAgents(await getAgents());
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <Panel title="Agents" count={agents.length} onRefresh={load}>
      {err ? (
        <Empty text={`Could not reach backend (${err})`} />
      ) : (
        <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
          {agents.map((a) => {
            const c = connState(a);
            return (
              <div
                key={a.capability}
                className="rounded-md border border-edge bg-panel2 p-4 transition-colors hover:border-edge2"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-ink">{a.label}</span>
                  <Dot status={c.status} pulse={c.status === "ok"} />
                </div>
                <div className="mt-1 font-mono text-xs text-muted">{a.capability}</div>
                <div className="mt-3 flex items-center gap-2">
                  <Badge tone="muted">{authLabel(a)}</Badge>
                  <Badge tone={c.tone}>{c.text}</Badge>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

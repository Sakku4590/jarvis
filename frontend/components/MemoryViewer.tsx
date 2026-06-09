"use client";

import { useCallback, useEffect, useState } from "react";
import { MemoryFact, getMemory } from "@/lib/api";
import { Badge, Empty, Panel } from "./ui";

const KIND_TONE: Record<string, string> = {
  preference: "signal",
  person: "info",
  project: "ok",
  fact: "muted",
  procedure: "warn",
};

export default function MemoryViewer() {
  const [facts, setFacts] = useState<MemoryFact[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setFacts(await getMemory());
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Panel title="Memory" count={facts.length} onRefresh={load}>
      {err ? (
        <Empty text={`Could not load memory (${err})`} />
      ) : facts.length === 0 ? (
        <Empty text="No facts remembered yet. Tell Jarvis something durable about you." />
      ) : (
        <ul className="divide-y divide-edge">
          {facts.map((f) => (
            <li key={f.id} className="flex items-start gap-3 px-4 py-3">
              <Badge tone={KIND_TONE[f.kind] ?? "muted"}>{f.kind}</Badge>
              <div className="min-w-0 flex-1">
                <p className="text-sm text-ink">{f.content}</p>
                {f.subject && (
                  <p className="mt-0.5 font-mono text-xs text-muted">re: {f.subject}</p>
                )}
              </div>
              <span className="label text-muted">
                {(f.confidence * 100).toFixed(0)}%
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

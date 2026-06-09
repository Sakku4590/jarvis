"use client";

import { useCallback, useEffect, useState } from "react";
import { TaskEntry, getTasks } from "@/lib/api";
import { Badge, Dot, Empty, Panel, ago } from "./ui";

export default function TaskHistory() {
  const [tasks, setTasks] = useState<TaskEntry[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setTasks(await getTasks());
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 6000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <Panel title="Task history" count={tasks.length} onRefresh={load}>
      {err ? (
        <Empty text={`Could not load tasks (${err})`} />
      ) : tasks.length === 0 ? (
        <Empty text="No tasks yet. Runs from the chat show up here." />
      ) : (
        <ul className="divide-y divide-edge">
          {tasks.map((t, i) => (
            <li key={i} className="px-4 py-3">
              <div className="flex items-center gap-2">
                <Badge tone="info">{t.route ?? "—"}</Badge>
                <span className="ml-auto label text-muted">{ago(t.time)}</span>
              </div>
              <p className="mt-1 truncate text-sm text-ink">{t.message}</p>
              {t.answer && (
                <p className="mt-0.5 truncate text-xs text-muted">{t.answer}</p>
              )}
              {t.steps.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {t.steps.map((s, j) => (
                    <span key={j} className="flex items-center gap-1.5 label text-muted">
                      <Dot status={s.status} />
                      {s.capability}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

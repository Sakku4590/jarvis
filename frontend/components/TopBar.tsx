"use client";

import { useEffect, useState } from "react";
import { Health, USER_ID, getHealth } from "@/lib/api";
import { Dot } from "./ui";

export default function TopBar() {
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const h = await getHealth();
        if (alive) {
          setHealth(h);
          setDown(false);
        }
      } catch {
        if (alive) setDown(true);
      }
    };
    load();
    const t = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const checks = health?.checks ?? {};

  return (
    <header className="flex items-center justify-between border-b border-edge bg-base/60 px-6 py-3 backdrop-blur">
      <div className="flex items-center gap-2">
        <Dot status={down ? "error" : health?.status === "ready" ? "ok" : "warn"} pulse={!down} />
        <span className="label text-body">
          {down ? "backend offline" : health?.status ?? "connecting"}
        </span>
      </div>

      <div className="flex items-center gap-5">
        {Object.entries(checks).map(([name, ok]) => (
          <span key={name} className="flex items-center gap-1.5 label text-muted">
            <Dot status={ok ? "ok" : "error"} />
            {name}
          </span>
        ))}
        <span className="label text-muted">user · {USER_ID.slice(0, 8)}</span>
      </div>
    </header>
  );
}

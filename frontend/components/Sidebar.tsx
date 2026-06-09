"use client";

export type Tab = "chat" | "agents" | "memory" | "tasks" | "activity";

const NAV: { id: Tab; label: string; glyph: string }[] = [
  { id: "chat", label: "Chat", glyph: "▮" },
  { id: "agents", label: "Agents", glyph: "◈" },
  { id: "memory", label: "Memory", glyph: "❖" },
  { id: "tasks", label: "Tasks", glyph: "≣" },
  { id: "activity", label: "Activity", glyph: "∿" },
];

export default function Sidebar({
  active,
  onSelect,
}: {
  active: Tab;
  onSelect: (t: Tab) => void;
}) {
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-edge bg-panel">
      <div className="border-b border-edge px-5 py-5">
        <div className="flex items-baseline gap-1">
          <span className="font-mono text-lg font-600 tracking-[0.3em] text-ink">
            JARVIS
          </span>
          <span className="animate-blink text-signal">▋</span>
        </div>
        <p className="label mt-1 text-muted">personal os · control</p>
      </div>

      <nav className="flex-1 px-3 py-4">
        {NAV.map((n) => {
          const on = active === n.id;
          return (
            <button
              key={n.id}
              onClick={() => onSelect(n.id)}
              className={`mb-1 flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm transition-colors ${
                on
                  ? "border border-signal/30 bg-signal/10 text-signal"
                  : "border border-transparent text-body hover:bg-panel2 hover:text-ink"
              }`}
            >
              <span className="w-4 text-center opacity-80">{n.glyph}</span>
              {n.label}
              {on && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-signal" />}
            </button>
          );
        })}
      </nav>

      <div className="border-t border-edge px-5 py-4">
        <p className="label text-muted">9 agents · 1 supervisor</p>
        <p className="label mt-1 text-muted">langgraph workflow</p>
      </div>
    </aside>
  );
}

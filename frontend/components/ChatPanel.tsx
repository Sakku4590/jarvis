"use client";

import { useEffect, useRef, useState } from "react";
import { RunResult, StepResult, runJarvis } from "@/lib/api";
import { Badge, Dot } from "./ui";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  route?: string | null;
  steps?: StepResult[];
}

function StepLine({ s }: { s: StepResult }) {
  return (
    <div className="flex items-center gap-2 py-0.5 text-xs">
      <Dot status={s.status} />
      <span className="font-mono text-muted">{s.step_id}</span>
      <span className="text-body">{s.capability}</span>
      <span className="text-muted">·</span>
      <span className="font-mono text-muted">{s.delegate ?? "—"}</span>
      <span className="ml-auto font-mono text-muted">{s.status}</span>
    </div>
  );
}

export default function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setBusy(true);
    try {
      const res: RunResult = await runJarvis(text, approved);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: res.answer ?? "(no answer)",
          route: res.route,
          steps: res.results,
        },
      ]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        { role: "assistant", text: `Request failed: ${(e as Error).message}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-md border border-edge bg-panel">
      <header className="flex items-center justify-between border-b border-edge px-4 py-3">
        <span className="label text-signal">Chat · Orchestrator</span>
        <label className="flex cursor-pointer items-center gap-2 label text-muted">
          <input
            type="checkbox"
            checked={approved}
            onChange={(e) => setApproved(e.target.checked)}
            className="accent-signal"
          />
          auto-approve actions
        </label>
      </header>

      <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
        {messages.length === 0 && (
          <div className="mt-10 text-center text-sm text-muted">
            Ask Jarvis to do something. Try{" "}
            <span className="text-body">&ldquo;find the budget file and draft an email about it&rdquo;</span>.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className="animate-rise">
            {m.role === "user" ? (
              <div className="flex justify-end">
                <div className="max-w-[80%] rounded-md border border-edge2 bg-panel2 px-3 py-2 text-sm text-ink">
                  {m.text}
                </div>
              </div>
            ) : (
              <div className="max-w-[88%]">
                <div className="mb-1 flex items-center gap-2">
                  <span className="label text-signal">jarvis</span>
                  {m.route && <Badge tone="info">{m.route}</Badge>}
                </div>
                <div className="whitespace-pre-wrap rounded-md border border-edge bg-base px-3 py-2 text-sm text-body">
                  {m.text}
                </div>
                {m.steps && m.steps.length > 0 && (
                  <div className="mt-2 rounded-md border border-edge bg-panel2 px-3 py-2">
                    <div className="label mb-1 text-muted">execution</div>
                    {m.steps.map((s) => (
                      <StepLine key={s.step_id} s={s} />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="label text-muted">
            jarvis is working<span className="animate-blink">▋</span>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div className="border-t border-edge p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={1}
            placeholder="message jarvis…"
            className="max-h-40 min-h-[44px] flex-1 resize-none rounded-md border border-edge bg-base px-3 py-2.5 text-sm text-ink outline-none placeholder:text-muted focus:border-signal/50"
          />
          <button
            onClick={send}
            disabled={busy || !input.trim()}
            className="rounded-md border border-signal/50 bg-signal/10 px-4 py-2.5 label text-signal transition-colors hover:bg-signal/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            send
          </button>
        </div>
      </div>
    </div>
  );
}

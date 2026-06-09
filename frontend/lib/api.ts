// Typed client for the Jarvis backend.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const USER_ID =
  process.env.NEXT_PUBLIC_USER_ID ?? "00000000-0000-0000-0000-000000000001";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

// --- types ---------------------------------------------------------------

export interface StepResult {
  step_id: string;
  capability: string;
  delegate?: "agent" | "tool";
  status: string;
  answer?: string | null;
  ok?: boolean;
  calls?: { tool?: string; status?: string }[];
  error?: unknown;
}

export interface RunResult {
  route: string | null;
  answer: string | null;
  plan: { status?: string; errors?: string[]; order?: string[] } | null;
  results: StepResult[];
}

export interface Agent {
  capability: string;
  label: string;
  auth: "none" | "oauth" | "app";
  provider?: string;
  connected: boolean | null;
}

export interface MemoryFact {
  id: string;
  kind: string;
  subject: string | null;
  content: string;
  confidence: number;
  source: string;
  created_at: string | null;
}

export interface TaskEntry {
  time: number;
  user_id: string;
  message: string;
  route: string | null;
  answer: string | null;
  steps: { step_id: string; capability: string; status: string }[];
}

export interface ToolEntry {
  time: number;
  tool: string;
  capability: string;
  risk: string;
  status: string;
  ok: boolean;
  user_id: string;
  duration_ms: number | null;
}

export interface Health {
  status: string;
  checks: Record<string, boolean>;
}

// --- calls ---------------------------------------------------------------

export const runJarvis = (message: string, approved: boolean) =>
  api<RunResult>("/jarvis/run", {
    method: "POST",
    body: JSON.stringify({ user_id: USER_ID, message, approved }),
  });

export const getAgents = () =>
  api<{ agents: Agent[] }>(`/dashboard/agents?user_id=${USER_ID}`).then((d) => d.agents);

export const getMemory = () =>
  api<MemoryFact[]>(`/memory/facts?user_id=${USER_ID}`);

export const getTasks = () =>
  api<{ tasks: TaskEntry[] }>(`/dashboard/tasks?limit=50`).then((d) => d.tasks);

export const getToolActivity = () =>
  api<{ tools: ToolEntry[] }>(`/dashboard/activity?limit=50`).then((d) => d.tools);

export const getHealth = () => api<Health>("/health/ready");

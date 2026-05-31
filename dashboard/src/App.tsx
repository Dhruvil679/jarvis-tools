import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

type AgentDefinition = {
  name: string;
  slug: string;
  role: string;
  summary: string;
  tools: string[];
  keywords: string[];
  skills: string[];
  voice: Record<string, unknown>;
  config: Record<string, unknown>;
  paths?: Record<string, string>;
};

type AgentStatus = {
  agent?: string;
  name: string;
  slug: string;
  role: string;
  summary: string;
  tools: string[];
  skills: string[];
  voice: Record<string, unknown>;
  memory_path: string;
  recent_messages: MemoryMessage[];
  message_count: number;
  state: string;
  confidence: number;
  active_task: string;
  last_message: string;
  last_sender: string;
  last_update: number;
  run_count: number;
  error_count: number;
};

type MemoryMessage = {
  role: string;
  content: string;
  ts: number;
  metadata?: Record<string, unknown>;
};

type MemorySnapshot = {
  agent: string;
  db_path: string;
  messages: MemoryMessage[];
  summaries: Array<{ source: string; summary: string; ts: number }>;
  facts: Array<{ key: string; value: string; confidence: number; ts: number }>;
  events: Array<{
    event_type: string;
    source_agent?: string | null;
    target_agent?: string | null;
    task: string;
    message: string;
    confidence: number;
    payload: Record<string, unknown>;
    ts: number;
  }>;
  status: {
    agent: string;
    state: string;
    confidence: number;
    active_task: string;
    last_message: string;
    last_sender: string;
    last_update: number;
    run_count: number;
    error_count: number;
  };
};

type SkillMetadata = Record<string, unknown>;

type RouteDecision = {
  mode: string;
  primary_agent: string;
  collaborators: string[];
  confidence: number;
  reason: string;
  signals: string[];
  handoff_chain: string[];
  confidence_scores: Record<string, number>;
};

type TimelineEvent = {
  ts: number;
  event_type: string;
  source_agent?: string | null;
  target_agent?: string | null;
  task: string;
  message: string;
  confidence: number;
  status: string;
  payload: Record<string, unknown>;
};

type AgentOutput = {
  agent: string;
  task: string;
  result: string;
  confidence: number;
  status: string;
  handoff_from?: string | null;
  elapsed_seconds: number;
  metadata: Record<string, unknown>;
  structured_output: Record<string, unknown>;
  memory_path: string;
  content: string;
};

type TaskExecution = {
  task_id: string;
  agent: string;
  tool: string;
  status: string;
  duration_seconds: number;
  result: string;
  error: string;
  path: string;
  command: string;
  iteration: number;
  ts: number;
  payload: Record<string, unknown>;
};

type ChatResponse = {
  user_text: string;
  mode: string;
  route: RouteDecision;
  plan: Array<Record<string, unknown>>;
  agent_outputs: Record<string, AgentOutput>;
  task_executions: TaskExecution[];
  final_response: string;
  merged_output: Record<string, unknown>;
  timeline: TimelineEvent[];
  execution_logs: string[];
  statuses: Record<string, AgentStatus>;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  detail?: string;
  ts: number;
};

type TaskRun = {
  id: string;
  createdAt: number;
  userText: string;
  response: string;
  route: RouteDecision;
  timeline: TimelineEvent[];
  executionLogs: string[];
  taskExecutions: TaskExecution[];
  mergedOutput: Record<string, unknown>;
  agentOutputs: Record<string, AgentOutput>;
};

type MemoryTab = "messages" | "summaries" | "facts" | "events" | "status";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

const STORAGE_KEYS = {
  darkMode: "jarvis.dashboard.darkMode",
  autonomousMode: "jarvis.dashboard.autonomousMode",
  selectedAgent: "jarvis.dashboard.selectedAgent",
  selectedSkill: "jarvis.dashboard.selectedSkill",
} as const;

const PANEL =
  "rounded-3xl border border-slate-200/80 bg-white/90 shadow-[0_20px_50px_rgba(15,23,42,0.08)] backdrop-blur-xl transition-colors dark:border-white/10 dark:bg-slate-900/85 dark:shadow-glow";
const SUBPANEL =
  "rounded-2xl border border-slate-200 bg-slate-50/90 transition-colors dark:border-white/10 dark:bg-white/5";

function createId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function readStoredString(key: string, fallback = ""): string {
  if (typeof window === "undefined") {
    return fallback;
  }
  return window.localStorage.getItem(key) ?? fallback;
}

function readStoredBool(key: string, fallback: boolean): boolean {
  if (typeof window === "undefined") {
    return fallback;
  }
  const value = window.localStorage.getItem(key);
  if (value === null) {
    return fallback;
  }
  return value === "true";
}

function writeStoredString(key: string, value: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(key, value);
}

function writeStoredBool(key: string, value: boolean): void {
  writeStoredString(key, value ? "true" : "false");
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  const responseText = await response.text();

  if (!response.ok) {
    throw new Error(responseText || `Request failed with status ${response.status}`);
  }

  if (!responseText) {
    return {} as T;
  }

  return JSON.parse(responseText) as T;
}

function pickKnownSlug(preferred: string, available: string[], fallback: string): string {
  if (preferred && available.includes(preferred)) {
    return preferred;
  }
  if (fallback && available.includes(fallback)) {
    return fallback;
  }
  return available[0] ?? fallback;
}

function formatTimestamp(epochSeconds: number): string {
  if (!epochSeconds) {
    return "—";
  }
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(epochSeconds * 1000));
}

function formatRelativeTime(epochSeconds: number): string {
  if (!epochSeconds) {
    return "just now";
  }
  const delta = Math.round((epochSeconds * 1000 - Date.now()) / 1000);
  const absDelta = Math.abs(delta);
  if (absDelta < 60) {
    return delta < 0 ? `${absDelta}s ago` : `in ${absDelta}s`;
  }
  const minutes = Math.round(absDelta / 60);
  if (minutes < 60) {
    return delta < 0 ? `${minutes}m ago` : `in ${minutes}m`;
  }
  const hours = Math.round(minutes / 60);
  return delta < 0 ? `${hours}h ago` : `in ${hours}h`;
}

function formatConfidence(value: number): string {
  if (!Number.isFinite(value)) {
    return "0%";
  }
  return `${Math.round(Math.max(0, value) * 100)}%`;
}

function confidenceBadgeClass(value: number): string {
  if (value >= 0.8) {
    return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200";
  }
  if (value >= 0.6) {
    return "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200";
  }
  return "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-200";
}

function stringifyValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function truncate(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
}

function stateBadgeClass(state: string): string {
  const normalized = state.toLowerCase();
  if (normalized.includes("error")) {
    return "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-200";
  }
  if (normalized.includes("running")) {
    return "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200";
  }
  if (normalized.includes("failed")) {
    return "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-200";
  }
  if (normalized.includes("completed") || normalized.includes("idle")) {
    return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200";
  }
  if (normalized.includes("pending")) {
    return "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-200";
  }
  return "border-slate-300 bg-slate-100 text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-200";
}

function valueTone(value: number): string {
  if (value >= 0.8) {
    return "text-emerald-600 dark:text-emerald-300";
  }
  if (value >= 0.6) {
    return "text-amber-600 dark:text-amber-300";
  }
  return "text-rose-600 dark:text-rose-300";
}

function SectionHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  action?: ReactNode;
}): JSX.Element {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <p className="text-[11px] uppercase tracking-[0.32em] text-slate-500 dark:text-slate-400">{eyebrow}</p>
        <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">{title}</h2>
        {description ? <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

function Pill({ children, className = "" }: { children: ReactNode; className?: string }): JSX.Element {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium ${className}`}
    >
      {children}
    </span>
  );
}

function metadataText(metadata: SkillMetadata, key: string): string {
  const value = metadata[key];
  if (value === undefined || value === null) {
    return "";
  }
  return stringifyValue(value);
}

function App(): JSX.Element {
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [agentStatuses, setAgentStatuses] = useState<AgentStatus[]>([]);
  const [skillMetadata, setSkillMetadata] = useState<Record<string, SkillMetadata>>({});
  const [skillNames, setSkillNames] = useState<string[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string>(() => readStoredString(STORAGE_KEYS.selectedAgent, ""));
  const [selectedSkill, setSelectedSkill] = useState<string>(() => readStoredString(STORAGE_KEYS.selectedSkill, ""));
  const [darkMode, setDarkMode] = useState<boolean>(() => readStoredBool(STORAGE_KEYS.darkMode, true));
  const [autonomousMode, setAutonomousMode] = useState<boolean>(() => readStoredBool(STORAGE_KEYS.autonomousMode, true));
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    {
      id: createId(),
      role: "assistant",
      text:
        "JARVIS dashboard online. Pick an agent, then send a task or switch autonomous mode to let the orchestrator collaborate across specialists.",
      ts: Date.now(),
    },
  ]);
  const [chatInput, setChatInput] = useState("");
  const [taskRuns, setTaskRuns] = useState<TaskRun[]>([]);
  const [memorySnapshot, setMemorySnapshot] = useState<MemorySnapshot | null>(null);
  const [memoryTab, setMemoryTab] = useState<MemoryTab>("messages");
  const [skillQuery, setSkillQuery] = useState("");
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [lastSyncAt, setLastSyncAt] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const timelineScrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", darkMode);
    root.style.colorScheme = darkMode ? "dark" : "light";
    writeStoredBool(STORAGE_KEYS.darkMode, darkMode);
  }, [darkMode]);

  useEffect(() => {
    writeStoredBool(STORAGE_KEYS.autonomousMode, autonomousMode);
  }, [autonomousMode]);

  useEffect(() => {
    if (selectedAgent) {
      writeStoredString(STORAGE_KEYS.selectedAgent, selectedAgent);
    }
  }, [selectedAgent]);

  useEffect(() => {
    if (selectedSkill) {
      writeStoredString(STORAGE_KEYS.selectedSkill, selectedSkill);
    }
  }, [selectedSkill]);

  const refreshMemory = useCallback(async (agentSlug: string) => {
    const snapshot = await fetchJson<MemorySnapshot>(`/memory?agent=${encodeURIComponent(agentSlug || "jarvis")}&limit=25`);
    setMemorySnapshot(snapshot);
    setIsConnected(true);
    setLastSyncAt(Date.now());
  }, []);

  const refreshStatus = useCallback(async () => {
    const statusPayload = await fetchJson<{ agents: AgentStatus[]; active_agent: string | null }>("/agents/status");
    setAgentStatuses(statusPayload.agents);
    setIsConnected(true);
    setLastSyncAt(Date.now());
    return statusPayload.active_agent ?? "";
  }, []);

  const bootstrap = useCallback(async () => {
    setIsBootstrapping(true);
    setError(null);
    try {
      const [agentPayload, statusPayload, skillPayload] = await Promise.all([
        fetchJson<AgentDefinition[]>("/agents"),
        fetchJson<{ agents: AgentStatus[]; active_agent: string | null }>("/agents/status"),
        fetchJson<{ skills: Record<string, SkillMetadata>; names: string[] }>("/skills"),
      ]);

      setAgents(agentPayload);
      setAgentStatuses(statusPayload.agents);
      setSkillMetadata(skillPayload.skills ?? {});
      setSkillNames(skillPayload.names ?? Object.keys(skillPayload.skills ?? {}));

      const availableAgentSlugs = agentPayload.map((agent) => agent.slug);
      const fallbackAgent = statusPayload.active_agent ?? availableAgentSlugs[0] ?? "jarvis";
      const preferredAgent = readStoredString(STORAGE_KEYS.selectedAgent, "");
      const nextAgent = pickKnownSlug(preferredAgent, availableAgentSlugs, fallbackAgent);
      setSelectedAgent(nextAgent);

      const availableSkillNames = skillPayload.names ?? Object.keys(skillPayload.skills ?? {});
      const preferredSkill = readStoredString(STORAGE_KEYS.selectedSkill, "");
      const nextSkill = pickKnownSlug(preferredSkill, availableSkillNames, availableSkillNames[0] ?? "");
      setSelectedSkill(nextSkill);

      if (nextAgent) {
        await refreshMemory(nextAgent);
      }

      setIsConnected(true);
      setLastSyncAt(Date.now());
    } catch (bootstrapError) {
      const message = bootstrapError instanceof Error ? bootstrapError.message : "Unable to connect to the API.";
      setError(message);
      setIsConnected(false);
    } finally {
      setIsBootstrapping(false);
    }
  }, [refreshMemory]);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    if (!isBootstrapping) {
      void refreshMemory(selectedAgent || "jarvis");
    }
  }, [selectedAgent, isBootstrapping, refreshMemory]);

  useEffect(() => {
    if (isBootstrapping) {
      return;
    }
    const timer = window.setInterval(() => {
      void refreshStatus();
      void refreshMemory(selectedAgent || "jarvis");
    }, 10000);
    return () => window.clearInterval(timer);
  }, [isBootstrapping, refreshStatus, refreshMemory, selectedAgent]);

  useEffect(() => {
    chatScrollRef.current?.scrollTo({ top: chatScrollRef.current.scrollHeight, behavior: "smooth" });
  }, [chatMessages]);

  useEffect(() => {
    timelineScrollRef.current?.scrollTo({ top: timelineScrollRef.current.scrollHeight, behavior: "smooth" });
  }, [taskRuns]);

  useEffect(() => {
    if (!selectedSkill && skillNames[0]) {
      setSelectedSkill(skillNames[0]);
    } else if (selectedSkill && skillNames.length > 0 && !skillNames.includes(selectedSkill)) {
      setSelectedSkill(skillNames[0]);
    }
  }, [skillNames, selectedSkill]);

  useEffect(() => {
    if (!selectedAgent && agents[0]) {
      setSelectedAgent(agents[0].slug);
    } else if (selectedAgent && agents.length > 0 && !agents.some((agent) => agent.slug === selectedAgent)) {
      setSelectedAgent(agents[0].slug);
    }
  }, [agents, selectedAgent]);

  const statusBySlug = useMemo(() => new Map(agentStatuses.map((status) => [status.slug, status])), [agentStatuses]);
  const activeAgent = useMemo(() => {
    return (
      agentStatuses.find((status) => status.slug === selectedAgent) ??
      agentStatuses[0] ??
      null
    );
  }, [agentStatuses, selectedAgent]);
  const selectedAgentDefinition = useMemo(
    () => agents.find((agent) => agent.slug === selectedAgent) ?? agents[0] ?? null,
    [agents, selectedAgent],
  );
  const selectedMemory = memorySnapshot;
  const selectedSkillMetadata = skillMetadata[selectedSkill] ?? null;
  const filteredSkillNames = useMemo(() => {
    const query = skillQuery.trim().toLowerCase();
    const names = skillNames.slice();
    if (!query) {
      return names.slice(0, 60);
    }
    return names.filter((name) => {
      const metadata = skillMetadata[name] ?? {};
      const haystack = `${name} ${JSON.stringify(metadata)}`.toLowerCase();
      return haystack.includes(query);
    }).slice(0, 60);
  }, [skillMetadata, skillNames, skillQuery]);
  const latestRun = taskRuns[0] ?? null;
  const connectionLabel = isConnected
    ? `Connected · synced ${lastSyncAt ? formatTimestamp(lastSyncAt / 1000) : "now"}`
    : "Disconnected";
  const selectedAgentStatus = selectedAgent ? statusBySlug.get(selectedAgent) ?? null : null;

  const handleSend = useCallback(async () => {
    const trimmed = chatInput.trim();
    if (!trimmed || isSending) {
      return;
    }

    const userMessage: ChatMessage = {
      id: createId(),
      role: "user",
      text: trimmed,
      ts: Date.now(),
    };

    setChatMessages((current) => [...current, userMessage]);
    setChatInput("");
    setIsSending(true);
    setError(null);

    try {
      const response = await fetchJson<ChatResponse>("/chat", {
        method: "POST",
        body: JSON.stringify({
          message: trimmed,
          mode: autonomousMode ? "autonomous" : "manual",
          agent: autonomousMode ? undefined : selectedAgent || undefined,
        }),
      });

      const finalText =
        response.final_response ||
        stringifyValue(response.merged_output["summary"]) ||
        stringifyValue(response.merged_output["final_response"]) ||
        "Task completed.";
      const routeSummary = response.route.handoff_chain.length
        ? `${response.route.primary_agent} · ${response.route.handoff_chain.join(" → ")}`
        : response.route.primary_agent;

      const assistantMessage: ChatMessage = {
        id: createId(),
        role: "assistant",
        text: finalText,
        ts: Date.now(),
      };
      const systemMessage: ChatMessage = {
        id: createId(),
        role: "system",
        text: `Route ${routeSummary} · confidence ${formatConfidence(response.route.confidence)}`,
        detail: response.route.reason,
        ts: Date.now(),
      };

      setChatMessages((current) => [...current, assistantMessage, systemMessage]);
      setTaskRuns((current) => [
        {
          id: createId(),
          createdAt: Date.now(),
          userText: trimmed,
          response: finalText,
          route: response.route,
          timeline: response.timeline,
          executionLogs: response.execution_logs,
          taskExecutions: response.task_executions ?? [],
          mergedOutput: response.merged_output,
          agentOutputs: response.agent_outputs,
        },
        ...current,
      ].slice(0, 5));
      setAgentStatuses(Object.values(response.statuses ?? {}));
      setIsConnected(true);
      setLastSyncAt(Date.now());

      const primaryAgent = response.route.primary_agent || selectedAgent;
      if (autonomousMode && primaryAgent) {
        setSelectedAgent(primaryAgent);
      }
      await refreshMemory((autonomousMode ? primaryAgent : selectedAgent) || "jarvis");
    } catch (sendError) {
      const message = sendError instanceof Error ? sendError.message : "Failed to send message.";
      setError(message);
      setChatMessages((current) => [
        ...current,
        {
          id: createId(),
          role: "system",
          text: "Request failed.",
          detail: message,
          ts: Date.now(),
        },
      ]);
    } finally {
      setIsSending(false);
    }
  }, [autonomousMode, chatInput, isSending, refreshMemory, selectedAgent]);

  const memoryEntries = useMemo(() => {
    if (!selectedMemory) {
      return [];
    }

    switch (memoryTab) {
      case "messages":
        return selectedMemory.messages.map((entry) => ({
          title: `${entry.role} · ${formatTimestamp(entry.ts)}`,
          body: entry.content,
          meta: entry.metadata ? stringifyValue(entry.metadata) : "",
        }));
      case "summaries":
        return selectedMemory.summaries.map((entry) => ({
          title: `${entry.source} · ${formatTimestamp(entry.ts)}`,
          body: entry.summary,
          meta: "",
        }));
      case "facts":
        return selectedMemory.facts.map((entry) => ({
          title: `${entry.key} · ${formatTimestamp(entry.ts)}`,
          body: entry.value,
          meta: `confidence ${formatConfidence(entry.confidence)}`,
        }));
      case "events":
        return selectedMemory.events.map((entry) => ({
          title: `${entry.event_type} · ${formatTimestamp(entry.ts)}`,
          body: `${entry.source_agent ?? "unknown"} → ${entry.target_agent ?? "unknown"}\n${entry.message || entry.task}`,
          meta: entry.payload ? stringifyValue(entry.payload) : "",
        }));
      case "status":
        return [
          {
            title: selectedMemory.status.agent,
            body: stringifyValue(selectedMemory.status),
            meta: "",
          },
        ];
      default:
        return [];
    }
  }, [memoryTab, selectedMemory]);

  const skillDetails = useMemo(() => {
    if (!selectedSkillMetadata) {
      return [];
    }
    return Object.entries(selectedSkillMetadata).filter(([key]) => key !== "name");
  }, [selectedSkillMetadata]);
  const latestTaskExecutions = latestRun?.taskExecutions ?? [];

  const renderMemoryTabs = (): JSX.Element => (
    <div className="mt-4 flex flex-wrap gap-2">
      {(["messages", "summaries", "facts", "events", "status"] as MemoryTab[]).map((tab) => (
        <button
          key={tab}
          onClick={() => setMemoryTab(tab)}
          className={`rounded-full border px-3 py-1.5 text-xs font-semibold capitalize transition ${
            memoryTab === tab
              ? "border-cyan-500/30 bg-cyan-500/10 text-cyan-700 dark:text-cyan-200"
              : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
          }`}
        >
          {tab}
        </button>
      ))}
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 transition-colors duration-300 dark:bg-slate-950 dark:text-slate-100">
      <div className="mx-auto flex min-h-screen max-w-[1800px] flex-col gap-4 px-4 py-4 lg:px-6 lg:py-6">
        <header className={`${PANEL} flex flex-col gap-4 p-4 lg:flex-row lg:items-center lg:justify-between`}>
          <div className="flex flex-wrap items-center gap-4">
            <div>
              <p className="text-[11px] uppercase tracking-[0.34em] text-cyan-700 dark:text-cyan-300">JARVIS Operating System</p>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-white sm:text-3xl">
                ChatGPT-style Command Dashboard
              </h1>
              <p className="mt-2 max-w-3xl text-sm text-slate-600 dark:text-slate-300">
                Live chat, multi-agent collaboration, memory inspection, skill discovery, and autonomous execution in one control surface.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Pill className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200">
                {connectionLabel}
              </Pill>
              <Pill className="border-slate-300 bg-slate-100 text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-200">
                API {API_BASE}
              </Pill>
              <Pill className={autonomousMode ? "border-cyan-500/30 bg-cyan-500/10 text-cyan-700 dark:text-cyan-200" : "border-slate-300 bg-slate-100 text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-200"}>
                {autonomousMode ? "Autonomous mode enabled" : "Manual routing"}
              </Pill>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-3 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 dark:border-white/10 dark:bg-white/5 dark:text-slate-200">
              <span className="font-medium">Autonomous</span>
              <button
                type="button"
                aria-pressed={autonomousMode}
                onClick={() => setAutonomousMode((current) => !current)}
                className={`relative h-6 w-11 rounded-full transition ${
                  autonomousMode ? "bg-cyan-500" : "bg-slate-300 dark:bg-slate-600"
                }`}
              >
                <span
                  className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${
                    autonomousMode ? "left-5" : "left-0.5"
                  }`}
                />
              </button>
            </label>
            <button
              type="button"
              onClick={() => setDarkMode((current) => !current)}
              className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 dark:border-white/10 dark:bg-white/5 dark:text-slate-200 dark:hover:bg-white/10"
            >
              {darkMode ? "Light mode" : "Dark mode"}
            </button>
          </div>
        </header>

        <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1.25fr)_420px]">
          <aside className="space-y-4">
            <section className={`${PANEL} p-4`}>
              <SectionHeading
                eyebrow="Agent Selection"
                title="Select a specialist"
                description="Pick the agent you want to route through when autonomous mode is off."
              />
              <div className="mt-4 space-y-3">
                {agents.map((agent) => {
                  const status = statusBySlug.get(agent.slug);
                  const state = status?.state ?? "idle";
                  const confidence = status?.confidence ?? 0;
                  const isSelected = selectedAgent === agent.slug;

                  return (
                    <button
                      key={agent.slug}
                      type="button"
                      onClick={() => setSelectedAgent(agent.slug)}
                      className={`w-full rounded-2xl border p-4 text-left transition ${
                        isSelected
                          ? "border-cyan-500/30 bg-cyan-500/10 shadow-lg shadow-cyan-500/10"
                          : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50 dark:border-white/10 dark:bg-white/5 dark:hover:bg-white/10"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="font-semibold text-slate-950 dark:text-white">{agent.name}</h3>
                            <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium uppercase tracking-[0.2em] ${stateBadgeClass(state)}`}>
                              {state}
                            </span>
                          </div>
                          <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{agent.summary}</p>
                        </div>
                        <span className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">
                          {agent.slug}
                        </span>
                      </div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <Pill className="border-slate-200 bg-slate-100 text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-200">
                          {agent.role}
                        </Pill>
                        <Pill className={confidenceBadgeClass(confidence)}>
                          confidence {formatConfidence(confidence)}
                        </Pill>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {(agent.skills ?? []).slice(0, 4).map((skill) => (
                          <span
                            key={`${agent.slug}-${skill}`}
                            className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600 dark:border-white/10 dark:bg-slate-950 dark:text-slate-300"
                          >
                            {skill}
                          </span>
                        ))}
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>

            <section className={`${PANEL} p-4`}>
              <SectionHeading
                eyebrow="Agent Status"
                title="Live execution state"
                description="Current state, task, and recent update for every agent."
              />
              <div className="mt-4 space-y-3">
                {agentStatuses.length ? (
                  agentStatuses.map((status) => (
                    <div key={status.slug} className={`${SUBPANEL} p-4`}>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="font-medium text-slate-950 dark:text-white">{status.name}</h3>
                            <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium uppercase tracking-[0.2em] ${stateBadgeClass(status.state)}`}>
                              {status.state}
                            </span>
                          </div>
                          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{status.role}</p>
                        </div>
                        <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                          {formatConfidence(status.confidence)}
                        </span>
                      </div>
                      <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">
                        {truncate(status.active_task || status.summary || "Waiting for work.", 180)}
                      </p>
                      <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500 dark:text-slate-400">
                        <span>runs {status.run_count}</span>
                        <span>errors {status.error_count}</span>
                        <span>updated {formatRelativeTime(status.last_update)}</span>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className={`${SUBPANEL} p-4 text-sm text-slate-500 dark:text-slate-400`}>
                    No agent status available yet.
                  </div>
                )}
              </div>
            </section>
          </aside>

          <main className="space-y-4">
            <section className={`${PANEL} p-4 sm:p-5`}>
              <SectionHeading
                eyebrow="Live Chat"
                title="Chat with the orchestrator"
                description="Messages can route to a single agent or fan out through the collaboration chain."
                action={
                  <div className="flex flex-wrap gap-2">
                    <Pill className="border-slate-200 bg-slate-100 text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-200">
                      Preferred agent: {selectedAgentDefinition?.name ?? "JARVIS"}
                    </Pill>
                    <Pill className="border-cyan-500/30 bg-cyan-500/10 text-cyan-700 dark:text-cyan-200">
                      {autonomousMode ? "Orchestrator decides" : "Manual route"}
                    </Pill>
                  </div>
                }
              />

              <div ref={chatScrollRef} className="mt-5 max-h-[520px] space-y-3 overflow-y-auto pr-1">
                {chatMessages.map((message) => (
                  <div
                    key={message.id}
                    className={`rounded-2xl border p-4 ${
                      message.role === "user"
                        ? "border-cyan-500/20 bg-cyan-500/10 text-slate-950 dark:text-slate-100"
                        : message.role === "assistant"
                          ? "border-emerald-500/20 bg-emerald-500/10 text-slate-950 dark:text-slate-100"
                          : "border-slate-200 bg-slate-100 text-slate-700 dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
                    }`}
                  >
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <span className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">
                        {message.role}
                      </span>
                      <span className="text-xs text-slate-500 dark:text-slate-400">{formatTimestamp(message.ts / 1000)}</span>
                    </div>
                    <p className="whitespace-pre-wrap text-sm leading-6">{message.text}</p>
                    {message.detail ? <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">{message.detail}</p> : null}
                  </div>
                ))}
                {isSending ? (
                  <div className="rounded-2xl border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
                    Orchestrator is collaborating across agents…
                  </div>
                ) : null}
              </div>

              <form
                className="mt-5 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]"
                onSubmit={(event) => {
                  event.preventDefault();
                  void handleSend();
                }}
              >
                <div className="space-y-3">
                  <div className="grid gap-3 md:grid-cols-[220px_minmax(0,1fr)]">
                    <select
                      value={selectedAgent}
                      onChange={(event) => setSelectedAgent(event.target.value)}
                      className="h-12 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-700 outline-none transition focus:border-cyan-500/40 dark:border-white/10 dark:bg-slate-950 dark:text-slate-100"
                    >
                      {agents.map((agent) => (
                        <option key={agent.slug} value={agent.slug}>
                          {agent.name}
                        </option>
                      ))}
                    </select>
                    <input
                      value={chatInput}
                      onChange={(event) => setChatInput(event.target.value)}
                      placeholder={
                        autonomousMode
                          ? "Describe the task and let the collaboration chain decide…"
                          : "Send a task to the selected agent…"
                      }
                      className="h-12 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-cyan-500/40 dark:border-white/10 dark:bg-slate-950 dark:text-slate-100"
                    />
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Manual mode uses the selected agent as the preferred target. Autonomous mode removes the preferred-agent hint.
                  </p>
                </div>
                <button
                  type="submit"
                  disabled={isSending || !chatInput.trim()}
                  className="inline-flex h-12 items-center justify-center rounded-2xl bg-cyan-500 px-5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isSending ? "Sending…" : "Send"}
                </button>
              </form>
            </section>

            <section className={`${PANEL} p-4 sm:p-5`}>
              <SectionHeading
                eyebrow="Task Execution"
                title="Worker activity"
                description="Tool-level execution records from the latest orchestration run."
                action={
                  <Pill className="border-slate-200 bg-slate-100 text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-200">
                    {latestTaskExecutions.length} records
                  </Pill>
                }
              />

              <div className="mt-5 max-h-[420px] space-y-3 overflow-y-auto pr-1">
                {latestTaskExecutions.length ? (
                  latestTaskExecutions.map((record) => (
                    <div key={`${record.task_id}-${record.agent}-${record.tool}-${record.iteration}`} className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-slate-950">
                      <div className="grid gap-3 lg:grid-cols-[140px_140px_120px_120px_minmax(0,1fr)]">
                        <div>
                          <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">Agent</p>
                          <p className="mt-2 text-sm font-medium text-slate-950 dark:text-white">{record.agent}</p>
                        </div>
                        <div>
                          <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">Tool</p>
                          <p className="mt-2 text-sm font-medium text-slate-950 dark:text-white">{record.tool}</p>
                        </div>
                        <div>
                          <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">Status</p>
                          <Pill className={stateBadgeClass(record.status)}>{record.status}</Pill>
                        </div>
                        <div>
                          <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">Duration</p>
                          <p className="mt-2 text-sm font-medium text-slate-950 dark:text-white">
                            {record.duration_seconds.toFixed(2)}s
                          </p>
                        </div>
                        <div>
                          <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">Result</p>
                          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600 dark:text-slate-300">
                            {truncate(record.result || record.error || "No result returned.", 220)}
                          </p>
                        </div>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500 dark:text-slate-400">
                        <span>iteration {record.iteration}</span>
                        {record.path ? <span>path {record.path}</span> : null}
                        {record.command ? <span>command {record.command}</span> : null}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
                    Send a task to see tool execution in real time.
                  </div>
                )}
              </div>
            </section>

            <section className={`${PANEL} p-4 sm:p-5`}>
              <SectionHeading
                eyebrow="Task Timeline"
                title="Collaboration timeline"
                description="Recent routes, handoffs, execution logs, and merged results from the orchestrator."
              />

              <div ref={timelineScrollRef} className="mt-5 max-h-[760px] space-y-4 overflow-y-auto pr-1">
                {taskRuns.length ? (
                  taskRuns.map((run, index) => (
                    <details key={run.id} open={index === 0} className={`${SUBPANEL} p-4`}>
                      <summary className="cursor-pointer list-none">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">
                              {formatTimestamp(run.createdAt / 1000)}
                            </p>
                            <h3 className="mt-2 text-base font-semibold text-slate-950 dark:text-white">
                              {truncate(run.userText, 90)}
                            </h3>
                          </div>
                          <div className="flex flex-wrap items-center gap-2">
                            <Pill className="border-cyan-500/30 bg-cyan-500/10 text-cyan-700 dark:text-cyan-200">
                              {run.route.primary_agent}
                            </Pill>
                            <Pill className="border-slate-300 bg-slate-100 text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-200">
                              {run.route.mode}
                            </Pill>
                            <Pill className={confidenceBadgeClass(run.route.confidence)}>
                              confidence {formatConfidence(run.route.confidence)}
                            </Pill>
                          </div>
                        </div>
                      </summary>

                      <div className="mt-4 space-y-4">
                        <div className="rounded-2xl border border-slate-200 bg-white p-4 text-sm dark:border-white/10 dark:bg-slate-950">
                          <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">Route</p>
                          <div className="mt-3 flex flex-wrap gap-2">
                            {run.route.handoff_chain.length ? (
                              run.route.handoff_chain.map((step, stepIndex) => (
                                <Pill key={`${run.id}-${stepIndex}`} className="border-slate-200 bg-slate-100 text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-200">
                                  {step}
                                </Pill>
                              ))
                            ) : (
                              <Pill className="border-slate-200 bg-slate-100 text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-200">
                                single agent
                              </Pill>
                            )}
                          </div>
                          <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">{run.route.reason}</p>
                          <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                            {Object.entries(run.route.confidence_scores).map(([agent, confidence]) => (
                              <div key={`${run.id}-${agent}`} className="rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-white/10 dark:bg-white/5">
                                <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">{agent}</p>
                                <p className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">{formatConfidence(confidence)}</p>
                              </div>
                            ))}
                          </div>
                        </div>

                        <div className="space-y-3">
                          <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">Timeline events</p>
                          {run.timeline.length ? (
                            run.timeline.map((event, eventIndex) => (
                              <div key={`${run.id}-event-${eventIndex}`} className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-slate-950">
                                <div className="flex flex-wrap items-start justify-between gap-3">
                                  <div>
                                    <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">
                                      {event.event_type}
                                    </p>
                                    <p className="mt-2 text-sm font-medium text-slate-950 dark:text-white">
                                      {event.source_agent ?? "system"} → {event.target_agent ?? "system"}
                                    </p>
                                  </div>
                                  <div className="flex flex-wrap gap-2">
                                    <Pill className="border-slate-200 bg-slate-100 text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-200">
                                      {formatTimestamp(event.ts / 1000)}
                                    </Pill>
                                    <Pill className={confidenceBadgeClass(event.confidence)}>
                                      {formatConfidence(event.confidence)}
                                    </Pill>
                                  </div>
                                </div>
                                <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-600 dark:text-slate-300">
                                  {truncate(event.message || event.task, 420)}
                                </p>
                                {Object.keys(event.payload ?? {}).length ? (
                                  <pre className="mt-3 overflow-x-auto rounded-xl bg-slate-950/95 p-3 text-xs text-slate-100 dark:bg-black/40">
                                    {stringifyValue(event.payload)}
                                  </pre>
                                ) : null}
                              </div>
                            ))
                          ) : (
                            <div className="rounded-2xl border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
                              No execution events recorded for this run.
                            </div>
                          )}
                        </div>

                        <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
                          <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-slate-950">
                            <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">Merged output</p>
                            <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-600 dark:text-slate-300">
                              {truncate(run.response, 800)}
                            </p>
                            <pre className="mt-3 overflow-x-auto rounded-xl bg-slate-950/95 p-3 text-xs text-slate-100 dark:bg-black/40">
                              {stringifyValue(run.mergedOutput)}
                            </pre>
                          </div>
                          <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-slate-950">
                            <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">Execution logs</p>
                            <div className="mt-3 space-y-2">
                              {run.executionLogs.length ? (
                                run.executionLogs.map((log, logIndex) => (
                                  <div
                                    key={`${run.id}-log-${logIndex}`}
                                    className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
                                  >
                                    {log}
                                  </div>
                                ))
                              ) : (
                                <div className="rounded-xl border border-dashed border-slate-300 p-3 text-xs text-slate-500 dark:border-white/10 dark:text-slate-400">
                                  No execution logs available.
                                </div>
                              )}
                            </div>
                          </div>
                        </div>

                        <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-slate-950">
                          <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">Agent outputs</p>
                          <div className="mt-3 grid gap-3">
                            {Object.values(run.agentOutputs).map((output) => (
                              <div
                                key={`${run.id}-${output.agent}`}
                                className="rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-white/10 dark:bg-white/5"
                              >
                                <div className="flex flex-wrap items-center justify-between gap-3">
                                  <p className="font-medium text-slate-950 dark:text-white">{output.agent}</p>
                                  <div className="flex flex-wrap gap-2">
                                    <Pill className={stateBadgeClass(output.status)}>
                                      {output.status}
                                    </Pill>
                                    <Pill className={confidenceBadgeClass(output.confidence)}>
                                      {formatConfidence(output.confidence)}
                                    </Pill>
                                  </div>
                                </div>
                                <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{truncate(output.result, 280)}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </details>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-slate-300 p-5 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
                    Send a task to populate the collaboration timeline.
                  </div>
                )}
              </div>
            </section>
          </main>

          <aside className="space-y-4">
            <section className={`${PANEL} p-4 sm:p-5`}>
              <SectionHeading
                eyebrow="Memory Viewer"
                title={selectedMemory ? `${selectedMemory.agent} memory` : "Memory viewer"}
                description="Messages, summaries, facts, events, and status pulled from SQLite."
              />

              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-white/5">
                  <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">Database</p>
                  <p className="mt-2 break-all text-sm text-slate-700 dark:text-slate-200">
                    {selectedMemory?.db_path ?? "—"}
                  </p>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-white/5">
                  <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">Status</p>
                  <p className="mt-2 text-sm text-slate-700 dark:text-slate-200">
                    {selectedMemory?.status.state ?? "idle"}
                  </p>
                </div>
              </div>

              {renderMemoryTabs()}

              <div className="mt-4 space-y-3">
                {memoryEntries.length ? (
                  memoryEntries.map((entry, index) => (
                    <div key={`${memoryTab}-${index}`} className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-slate-950">
                      <div className="flex items-start justify-between gap-3">
                        <p className="text-sm font-medium text-slate-950 dark:text-white">{entry.title}</p>
                        {entry.meta ? <span className="text-xs text-slate-500 dark:text-slate-400">{entry.meta}</span> : null}
                      </div>
                      <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-600 dark:text-slate-300">
                        {entry.body}
                      </p>
                    </div>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
                    No memory data available for this agent yet.
                  </div>
                )}
              </div>
            </section>

            <section className={`${PANEL} p-4 sm:p-5`}>
              <SectionHeading
                eyebrow="Skill Viewer"
                title="Discover skills"
                description="Search the skill registry and inspect metadata in real time."
                action={<Pill className="border-slate-200 bg-slate-100 text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-200">{skillNames.length} skills</Pill>}
              />

              <input
                value={skillQuery}
                onChange={(event) => setSkillQuery(event.target.value)}
                placeholder="Search skills by name or metadata…"
                className="mt-4 h-12 w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-cyan-500/40 dark:border-white/10 dark:bg-slate-950 dark:text-slate-100"
              />

              <div className="mt-4 max-h-[220px] space-y-2 overflow-y-auto pr-1">
                {filteredSkillNames.length ? (
                  filteredSkillNames.map((name) => {
                    const metadata = skillMetadata[name] ?? {};
                    const selected = name === selectedSkill;
                    const summary = metadataText(metadata, "description") || metadataText(metadata, "summary") || metadataText(metadata, "purpose");
                    return (
                      <button
                        key={name}
                        type="button"
                        onClick={() => setSelectedSkill(name)}
                        className={`w-full rounded-2xl border p-3 text-left transition ${
                          selected
                            ? "border-cyan-500/30 bg-cyan-500/10"
                            : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50 dark:border-white/10 dark:bg-white/5 dark:hover:bg-white/10"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <p className="font-medium text-slate-950 dark:text-white">{name}</p>
                          <span className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">
                            {metadataText(metadata, "category") || "skill"}
                          </span>
                        </div>
                        {summary && summary !== "—" ? (
                          <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{truncate(summary, 120)}</p>
                        ) : null}
                      </button>
                    );
                  })
                ) : (
                  <div className="rounded-2xl border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-white/10 dark:text-slate-400">
                    No skills match the current search.
                  </div>
                )}
              </div>

              <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-white/10 dark:bg-white/5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">Selected skill</p>
                    <h3 className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">
                      {selectedSkill || "None selected"}
                    </h3>
                  </div>
                  {selectedSkillMetadata ? (
                    <Pill className="border-slate-200 bg-white text-slate-600 dark:border-white/10 dark:bg-slate-950 dark:text-slate-200">
                      metadata loaded
                    </Pill>
                  ) : null}
                </div>

                {selectedSkillMetadata ? (
                  <div className="mt-4 space-y-3">
                    {skillDetails.length ? (
                      skillDetails.map(([key, value]) => (
                        <div key={key} className="rounded-xl border border-slate-200 bg-white p-3 dark:border-white/10 dark:bg-slate-950">
                          <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">{key}</p>
                          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-sm leading-6 text-slate-600 dark:text-slate-300">
                            {stringifyValue(value)}
                          </pre>
                        </div>
                      ))
                    ) : (
                      <p className="text-sm text-slate-600 dark:text-slate-300">No additional metadata found for this skill.</p>
                    )}
                  </div>
                ) : (
                  <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">Select a skill to inspect its metadata.</p>
                )}
              </div>
            </section>
          </aside>
        </div>

        <footer className="pb-2 text-xs text-slate-500 dark:text-slate-400">
          {error ? (
            <span className="text-rose-600 dark:text-rose-300">API error: {error}</span>
          ) : (
            <span>
              {isBootstrapping ? "Loading dashboard…" : "Dashboard ready."} · {selectedAgentStatus?.state ?? "idle"} · {activeAgent?.slug ?? "no active agent"}
            </span>
          )}
        </footer>
      </div>
    </div>
  );
}

export default App;

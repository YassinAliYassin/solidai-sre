"use client";

import { useEffect, useState, useCallback } from "react";
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  Minus,
  RefreshCcw,
  Clock,
  Server,
  Globe,
  Activity,
  Shield,
  Zap,
  ArrowUpRight,
} from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────

interface ServiceSummary {
  name: string;
  status: string;
  uptime_24h: number | null;
  latency?: {
    avg_ms: number;
    p95_ms: number;
    p99_ms: number;
  };
}

interface HealthSummary {
  status?: string;
  timestamp?: string;
  services?: ServiceSummary[];
  total_services?: number;
  healthy_count?: number;
  degraded_count?: number;
  down_count?: number;
}

interface ServiceHistory {
  uptime?: {
    uptime_pct: number | null;
    total_checks: number;
    healthy_count: number;
    window_hours: number;
  };
  latency?: {
    count: number;
    avg_ms: number;
    min_ms: number;
    max_ms: number;
    p50_ms: number;
    p95_ms: number;
    p99_ms: number;
    window_hours: number;
  };
  recent?: Array<{
    timestamp: string;
    status: string;
    latency_ms?: number;
    error?: string;
  }>;
}

interface Incident {
  service_name: string;
  status: string;
  start_time: string;
  end_time: string | null;
  duration_seconds: number | null;
}

interface ModelHealthInfo {
  status: string;
  models?: Array<{
    name: string;
    status: string;
    latency_ms?: number;
    error?: string;
  }>;
  litellm_version?: string;
  db?: string;
  cache?: string | null;
}

interface StatusData {
  summary: HealthSummary | null;
  history: Record<string, ServiceHistory> | null;
  incidents: Incident[] | null;
  model_health: ModelHealthInfo | null;
  generated_at: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  string,
  {
    label: string;
    color: string;
    bg: string;
    border: string;
    icon: typeof CheckCircle;
    dot: string;
  }
> = {
  healthy: {
    label: "Operational",
    color: "text-emerald-700 dark:text-emerald-400",
    bg: "bg-emerald-50 dark:bg-emerald-950/40",
    border: "border-emerald-200 dark:border-emerald-800",
    icon: CheckCircle,
    dot: "bg-emerald-500",
  },
  degraded: {
    label: "Degraded",
    color: "text-amber-700 dark:text-amber-400",
    bg: "bg-amber-50 dark:bg-amber-950/40",
    border: "border-amber-200 dark:border-amber-800",
    icon: AlertTriangle,
    dot: "bg-amber-500",
  },
  down: {
    label: "Down",
    color: "text-red-700 dark:text-red-400",
    bg: "bg-red-50 dark:bg-red-950/40",
    border: "border-red-200 dark:border-red-800",
    icon: XCircle,
    dot: "bg-red-500",
  },
  unknown: {
    label: "Unknown",
    color: "text-stone-500 dark:text-stone-400",
    bg: "bg-stone-50 dark:bg-stone-800",
    border: "border-stone-200 dark:border-stone-700",
    icon: Minus,
    dot: "bg-stone-400",
  },
  skipped: {
    label: "Paused",
    color: "text-stone-500 dark:text-stone-400",
    bg: "bg-stone-50 dark:bg-stone-800",
    border: "border-stone-200 dark:border-stone-700",
    icon: Minus,
    dot: "bg-stone-400",
  },
  not_configured: {
    label: "Not Configured",
    color: "text-stone-400 dark:text-stone-500",
    bg: "bg-stone-50 dark:bg-stone-800",
    border: "border-stone-200 dark:border-stone-700",
    icon: Minus,
    dot: "bg-stone-300",
  },
};

function formatUptime(pct: number | null): string {
  if (pct === null) return "—";
  if (pct >= 99.99) return "99.99%";
  if (pct >= 99.9) return `${pct.toFixed(2)}%`;
  return `${pct.toFixed(1)}%`;
}

function formatLatency(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatRelativeTime(timestamp: string): string {
  try {
    const now = Date.now();
    const then = new Date(timestamp).getTime();
    const diff = now - then;
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (seconds < 60) return "just now";
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    return `${days}d ago`;
  } catch {
    return "—";
  }
}

function uptimeColor(pct: number | null): string {
  if (pct === null) return "text-stone-400";
  if (pct >= 99.5) return "text-emerald-600 dark:text-emerald-400";
  if (pct >= 98) return "text-amber-600 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}

// ── Sparkline ───────────────────────────────────────────────────────────────

function Sparkline({ entries }: { entries: Array<{ status: string; latency_ms?: number }> }) {
  if (!entries || entries.length === 0) return null;

  const valid = entries.filter((e) => e.latency_ms != null);
  if (valid.length === 0) return null;

  const maxLatency = Math.max(...valid.map((e) => e.latency_ms || 0), 1);
  const W = 160;
  const H = 32;
  const barW = Math.max(3, (W - entries.length + 1) / entries.length);

  return (
    <svg width={W} height={H} className="shrink-0" aria-hidden="true">
      {entries.map((e, i) => {
        const h = e.latency_ms ? Math.max(2, (e.latency_ms / maxLatency) * (H - 4)) + 2 : 2;
        const x = i * (barW + 1);
        const y = H - h;
        const fill =
          e.status === "healthy"
            ? "#10b981"
            : e.status === "degraded"
              ? "#f59e0b"
              : "#ef4444";
        return (
          <rect key={i} x={x} y={y} width={barW} height={h} rx={1} fill={fill} opacity={0.6} />
        );
      })}
    </svg>
  );
}

// ── Service Card ────────────────────────────────────────────────────────────

function ServiceCard({
  service,
  history,
}: {
  service: ServiceSummary;
  history?: ServiceHistory;
}) {
  const config = STATUS_CONFIG[service.status] || STATUS_CONFIG.unknown;
  const Icon = config.icon;
  const uptime = history?.uptime;
  const latency = history?.latency;
  const recent = history?.recent || [];

  return (
    <div
      className={`rounded-xl border ${config.border} ${config.bg} p-5 transition-all hover:shadow-md`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0">
          <div className="mt-0.5">
            <Icon className={`w-5 h-5 ${config.color}`} />
          </div>
          <div className="min-w-0">
            <h3 className="font-semibold text-stone-900 dark:text-white truncate">
              {service.name}
            </h3>
            <div className="flex items-center gap-2 mt-1">
              <span className={`inline-flex items-center gap-1.5 text-sm font-medium ${config.color}`}>
                <span className={`w-2 h-2 rounded-full ${config.dot}`} />
                {config.label}
              </span>
            </div>
          </div>
        </div>

        {/* Uptime */}
        <div className="text-right shrink-0">
          <div className="text-xs text-stone-500 dark:text-stone-400">Uptime 24h</div>
          <div className={`text-lg font-bold ${uptimeColor(service.uptime_24h)}`}>
            {formatUptime(service.uptime_24h)}
          </div>
          {uptime && (
            <div className="text-[10px] text-stone-400">
              {uptime.healthy_count}/{uptime.total_checks} checks
            </div>
          )}
        </div>
      </div>

      {/* Latency + Sparkline */}
      {latency && latency.count > 0 && (
        <div className="mt-4 pt-3 border-t border-stone-200/50 dark:border-stone-700/50">
          <div className="flex items-end justify-between gap-4">
            <div className="flex items-center gap-4 text-xs text-stone-500 dark:text-stone-400">
              <span>
                Avg: <strong className="text-stone-700 dark:text-stone-300">{formatLatency(latency.avg_ms)}</strong>
              </span>
              <span>
                p95: <strong className="text-stone-700 dark:text-stone-300">{formatLatency(latency.p95_ms)}</strong>
              </span>
              <span>
                p99: <strong className="text-stone-700 dark:text-stone-300">{formatLatency(latency.p99_ms)}</strong>
              </span>
            </div>
            <Sparkline entries={recent} />
          </div>
        </div>
      )}
    </div>
  );
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "Ongoing";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  if (days > 0) return `${days}d ${hours % 24}h`;
  if (hours > 0) return `${hours}h ${minutes % 60}m`;
  return `${minutes}m`;
}

// ── Incident Timeline ───────────────────────────────────────────────────────

function IncidentTimeline({ incidents }: { incidents: Incident[] | null }) {
  if (!incidents || incidents.length === 0) {
    return (
      <section>
        <h2 className="text-sm font-semibold text-stone-500 dark:text-stone-400 uppercase tracking-wider mb-3 flex items-center gap-2">
          <Clock className="w-4 h-4" />
          Recent Incidents
        </h2>
        <div className="rounded-xl border border-stone-200 dark:border-stone-700 bg-white dark:bg-stone-800 p-6 text-center">
          <CheckCircle className="w-6 h-6 text-emerald-500 mx-auto mb-2" />
          <p className="text-sm text-stone-600 dark:text-stone-400">
            No incidents in the last 24 hours
          </p>
        </div>
      </section>
    );
  }

  return (
    <section>
      <h2 className="text-sm font-semibold text-stone-500 dark:text-stone-400 uppercase tracking-wider mb-3 flex items-center gap-2">
        <Clock className="w-4 h-4" />
        Recent Incidents
        <span className="ml-auto text-xs font-normal normal-case tracking-normal text-stone-400">
          Last 24 hours
        </span>
      </h2>
      <div className="rounded-xl border border-stone-200 dark:border-stone-700 bg-white dark:bg-stone-800 divide-y divide-stone-100 dark:divide-stone-700">
        {incidents.slice(0, 10).map((inc, i) => {
          const isOngoing = inc.end_time === null;
          const isDown = inc.status === "down";
          return (
            <div key={i} className="px-5 py-3.5 flex items-center gap-4">
              <div
                className={`w-2.5 h-2.5 rounded-full shrink-0 ${
                  isDown ? "bg-red-500" : "bg-amber-500"
                } ${isOngoing ? "animate-pulse" : ""}`}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm text-stone-900 dark:text-white truncate">
                    {inc.service_name}
                  </span>
                  <span
                    className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ${
                      isDown
                        ? "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400"
                        : "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400"
                    }`}
                  >
                    {inc.status}
                  </span>
                  {isOngoing && (
                    <span className="text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400">
                      Ongoing
                    </span>
                  )}
                </div>
                <div className="text-xs text-stone-500 dark:text-stone-400 mt-0.5">
                  {new Date(inc.start_time).toLocaleString()}
                  {!isOngoing && inc.end_time && (
                    <span> → {new Date(inc.end_time).toLocaleString()}</span>
                  )}
                </div>
              </div>
              <div className="text-right shrink-0">
                <div
                  className={`text-sm font-semibold ${
                    isOngoing
                      ? "text-blue-600 dark:text-blue-400"
                      : isDown
                        ? "text-red-600 dark:text-red-400"
                        : "text-amber-600 dark:text-amber-400"
                  }`}
                >
                  {formatDuration(inc.duration_seconds)}
                </div>
                <div className="text-[10px] text-stone-400">duration</div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ── Model Health ─────────────────────────────────────────────────────────────

function ModelHealthSection({ modelHealth }: { modelHealth: ModelHealthInfo | null }) {
  if (!modelHealth) return null;

  const isHealthy = modelHealth.status === "healthy" || modelHealth.status === "ok";

  return (
    <section>
      <h2 className="text-sm font-semibold text-stone-500 dark:text-stone-400 uppercase tracking-wider mb-3 flex items-center gap-2">
        <Activity className="w-4 h-4" />
        AI Model Health
      </h2>
      <div
        className={`rounded-xl border ${
          isHealthy
            ? "border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-950/20"
            : "border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-950/20"
        } p-4`}
      >
        <div className="flex items-center gap-3 mb-3">
          <span
            className={`w-2.5 h-2.5 rounded-full ${
              isHealthy ? "bg-emerald-500" : "bg-amber-500"
            }`}
          />
          <span className="text-sm font-medium text-stone-900 dark:text-white">
            LiteLLM Proxy
          </span>
          <span
            className={`text-xs ${
              isHealthy
                ? "text-emerald-700 dark:text-emerald-400"
                : "text-amber-700 dark:text-amber-400"
            }`}
          >
            {isHealthy ? "Operational" : "Degraded"}
          </span>
          {modelHealth.litellm_version && (
            <span className="text-[10px] text-stone-400 ml-auto">
              v{modelHealth.litellm_version}
            </span>
          )}
        </div>

        {modelHealth.models && modelHealth.models.length > 0 && (
          <div className="grid gap-2">
            {modelHealth.models.map((model, i) => {
              const modelOk = model.status === "healthy" || model.status === "ok";
              return (
                <div
                  key={i}
                  className="flex items-center gap-3 px-3 py-2 rounded-lg bg-white/60 dark:bg-stone-800/60 border border-stone-200/50 dark:border-stone-700/50"
                >
                  <span
                    className={`w-2 h-2 rounded-full ${
                      modelOk ? "bg-emerald-500" : "bg-red-500"
                    }`}
                  />
                  <span className="text-sm text-stone-700 dark:text-stone-300 font-mono">
                    {model.name}
                  </span>
                  {model.latency_ms != null && (
                    <span className="text-xs text-stone-500">
                      {formatLatency(model.latency_ms)}
                    </span>
                  )}
                  {model.error && (
                    <span className="text-xs text-red-500 ml-auto truncate max-w-[200px]">
                      {model.error}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <div className="flex items-center gap-4 mt-3 pt-2 border-t border-stone-200/50 dark:border-stone-700/50 text-[10px] text-stone-400">
          <span>DB: {modelHealth.db || "—"}</span>
          <span>Cache: {modelHealth.cache || "none"}</span>
        </div>
      </div>
    </section>
  );
}

// ── Overall Status Banner ───────────────────────────────────────────────────

function OverallBanner({ summary }: { summary: HealthSummary | null }) {
  if (!summary) {
    return (
      <div className="rounded-xl border border-stone-200 dark:border-stone-700 bg-white dark:bg-stone-800 p-6 flex items-center gap-4">
        <Loader />
        <span className="text-stone-500">Loading status…</span>
      </div>
    );
  }

  const allHealthy = summary.status === "healthy";
  const anyDown = (summary.down_count || 0) > 0;

  let bannerBg: string;
  let bannerBorder: string;
  let icon: React.ReactNode;
  let title: string;
  let subtitle: string;
  let iconBg: string;

  if (allHealthy) {
    bannerBg = "bg-emerald-50 dark:bg-emerald-950/30";
    bannerBorder = "border-emerald-200 dark:border-emerald-800";
    icon = <CheckCircle className="w-8 h-8 text-emerald-600 dark:text-emerald-400" />;
    title = "All Systems Operational";
    subtitle = `All ${summary.total_services || 0} services are running normally`;
    iconBg = "bg-emerald-100 dark:bg-emerald-900/50";
  } else if (anyDown) {
    bannerBg = "bg-red-50 dark:bg-red-950/30";
    bannerBorder = "border-red-200 dark:border-red-800";
    icon = <XCircle className="w-8 h-8 text-red-600 dark:text-red-400" />;
    title = "Service Disruption";
    subtitle = `${summary.down_count} service${(summary.down_count || 0) > 1 ? "s" : ""} currently down`;
    iconBg = "bg-red-100 dark:bg-red-900/50";
  } else {
    bannerBg = "bg-amber-50 dark:bg-amber-950/30";
    bannerBorder = "border-amber-200 dark:border-amber-800";
    icon = <AlertTriangle className="w-8 h-8 text-amber-600 dark:text-amber-400" />;
    title = "Partial Degradation";
    subtitle = `${summary.degraded_count} service${(summary.degraded_count || 0) > 1 ? "s" : ""} experiencing issues`;
    iconBg = "bg-amber-100 dark:bg-amber-900/50";
  }

  return (
    <div className={`rounded-xl border ${bannerBorder} ${bannerBg} p-6 flex items-center gap-4`}>
      <div className={`p-3 rounded-xl ${iconBg}`}>{icon}</div>
      <div>
        <h2 className="text-xl font-bold text-stone-900 dark:text-white">{title}</h2>
        <p className="text-sm text-stone-600 dark:text-stone-400 mt-0.5">{subtitle}</p>
      </div>
    </div>
  );
}

function Loader() {
  return (
    <div className="w-6 h-6 border-2 border-stone-300 border-t-forest rounded-full animate-spin" />
  );
}

// ── Main Page ───────────────────────────────────────────────────────────────

export default function StatusPage() {
  const [data, setData] = useState<StatusData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchStatus = useCallback(async (isManual = false) => {
    if (isManual) setRefreshing(true);
    try {
      const res = await fetch("/api/status");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
      setLastRefresh(new Date().toISOString());
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to fetch status");
    } finally {
      setLoading(false);
      if (isManual) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(() => fetchStatus(), 30_000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const services = data?.summary?.services || [];
  const history = data?.history || {};

  // Group services: internal first, then public
  const internalServices = services.filter(
    (s) => !["Solid Solutions", "SolidAI"].includes(s.name),
  );
  const publicServices = services.filter((s) =>
    ["Solid Solutions", "SolidAI"].includes(s.name),
  );

  return (
    <div className="min-h-screen bg-stone-50 dark:bg-stone-900">
      {/* Header */}
      <header className="border-b border-stone-200 dark:border-stone-700 bg-white dark:bg-stone-800">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-forest flex items-center justify-center">
              <Shield className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-stone-900 dark:text-white">
                SolidAI SRE
              </h1>
              <p className="text-xs text-stone-500">System Status</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {lastRefresh && (
              <span className="text-xs text-stone-400 hidden sm:inline">
                Updated {formatRelativeTime(lastRefresh)}
              </span>
            )}
            <button
              onClick={() => fetchStatus(true)}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-stone-200 dark:border-stone-700 text-stone-600 dark:text-stone-400 hover:bg-stone-100 dark:hover:bg-stone-700 transition-colors disabled:opacity-50"
            >
              <RefreshCcw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-5xl mx-auto px-6 py-8 space-y-8">
        {/* Overall Status */}
        {loading && !data ? (
          <div className="flex items-center justify-center py-20">
            <Loader />
            <span className="ml-3 text-stone-500">Loading status…</span>
          </div>
        ) : error ? (
          <div className="rounded-xl border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/30 p-6 text-center">
            <XCircle className="w-8 h-8 text-red-500 mx-auto mb-2" />
            <p className="text-red-700 dark:text-red-400 font-medium">Unable to load status</p>
            <p className="text-sm text-red-500 mt-1">{error}</p>
            <button
              onClick={() => fetchStatus(true)}
              className="mt-3 text-sm text-red-600 underline"
            >
              Try again
            </button>
          </div>
        ) : (
          <>
            <OverallBanner summary={data?.summary || null} />

            {/* Stats Row */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-4 text-center">
                <Server className="w-5 h-5 text-stone-400 mx-auto mb-1" />
                <div className="text-2xl font-bold text-stone-900 dark:text-white">
                  {data?.summary?.total_services || 0}
                </div>
                <div className="text-xs text-stone-500">Services</div>
              </div>
              <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-4 text-center">
                <CheckCircle className="w-5 h-5 text-emerald-500 mx-auto mb-1" />
                <div className="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
                  {data?.summary?.healthy_count || 0}
                </div>
                <div className="text-xs text-stone-500">Healthy</div>
              </div>
              <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-4 text-center">
                <AlertTriangle className="w-5 h-5 text-amber-500 mx-auto mb-1" />
                <div className="text-2xl font-bold text-amber-600 dark:text-amber-400">
                  {data?.summary?.degraded_count || 0}
                </div>
                <div className="text-xs text-stone-500">Degraded</div>
              </div>
              <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-4 text-center">
                <XCircle className="w-5 h-5 text-red-500 mx-auto mb-1" />
                <div className="text-2xl font-bold text-red-600 dark:text-red-400">
                  {data?.summary?.down_count || 0}
                </div>
                <div className="text-xs text-stone-500">Down</div>
              </div>
            </div>

            {/* Incident Timeline */}
            <IncidentTimeline incidents={data?.incidents || null} />

            {/* Model Health */}
            <ModelHealthSection modelHealth={data?.model_health || null} />

            {/* Public Endpoints */}
            {publicServices.length > 0 && (
              <section>
                <h2 className="text-sm font-semibold text-stone-500 dark:text-stone-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                  <Globe className="w-4 h-4" />
                  Public Endpoints
                </h2>
                <div className="grid gap-3">
                  {publicServices.map((s) => (
                    <ServiceCard key={s.name} service={s} history={history[s.name]} />
                  ))}
                </div>
              </section>
            )}

            {/* Internal Services */}
            {internalServices.length > 0 && (
              <section>
                <h2 className="text-sm font-semibold text-stone-500 dark:text-stone-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                  <Zap className="w-4 h-4" />
                  Internal Services
                </h2>
                <div className="grid gap-3">
                  {internalServices.map((s) => (
                    <ServiceCard key={s.name} service={s} history={history[s.name]} />
                  ))}
                </div>
              </section>
            )}

            {/* Footer */}
            <footer className="text-center pt-8 pb-4 border-t border-stone-200 dark:border-stone-700">
              <p className="text-xs text-stone-400">
                Powered by{" "}
                <strong className="text-forest">SolidAI SRE</strong>{" "}
                — Building the Future of African Tech
              </p>
              <p className="text-[10px] text-stone-300 dark:text-stone-600 mt-1">
                Status page refreshes every 30 seconds automatically
              </p>
            </footer>
          </>
        )}
      </main>
    </div>
  );
}

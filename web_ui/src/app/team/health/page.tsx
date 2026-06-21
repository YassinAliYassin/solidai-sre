"use client";

import { useEffect, useState, useCallback } from "react";
import { useIdentity } from "@/lib/useIdentity";
import {
  Activity,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Server,
  Clock,
  RefreshCcw,
  Shield,
  HeartPulse,
  TrendingUp,
  TrendingDown,
  Minus,
  Loader2,
  Wifi,
  WifiOff,
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
  overall?: string;
  services?: ServiceSummary[];
  generated_at?: string;
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

interface DashboardData {
  summary: HealthSummary | null;
  history: Record<string, ServiceHistory> | null;
  generated_at: string;
}

// ── helpers ────────────────────────────────────────────────────────────────

const STATUS_META: Record<string, { label: string; color: string; bg: string; icon: typeof CheckCircle }> = {
  healthy:  { label: "Healthy",  color: "text-green-600", bg: "bg-green-100 dark:bg-green-900/30", icon: CheckCircle },
  degraded: { label: "Degraded", color: "text-yellow-600", bg: "bg-yellow-100 dark:bg-yellow-900/30", icon: AlertTriangle },
  down:     { label: "Down",     color: "text-red-600",   bg: "bg-red-100   dark:bg-red-900/30",   icon: XCircle },
  unknown:  { label: "Unknown",  color: "text-stone-500", bg: "bg-stone-100 dark:bg-stone-700",       icon: Minus },
};

function uptimeColor(pct: number | null): string {
  if (pct === null) return "text-stone-400";
  if (pct >= 99) return "text-green-600";
  if (pct >= 95) return "text-yellow-600";
  return "text-red-600";
}

function latencyColor(ms: number): string {
  if (ms < 200) return "text-green-600";
  if (ms < 1000) return "text-yellow-600";
  return "text-red-600";
}

function formatLatency(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ── Mini sparkline component ───────────────────────────────────────────────

function Sparkline({ entries }: { entries: Array<{ status: string; latency_ms?: number }> }) {
  if (!entries || entries.length === 0) return null;

  const maxLatency = Math.max(...entries.map((e) => e.latency_ms || 0), 1);
  const W = 120;
  const H = 28;
  const barW = Math.max(2, (W - entries.length + 1) / entries.length);

  return (
    <svg width={W} height={H} className="shrink-0" aria-hidden="true">
      {entries.map((e, i) => {
        const h = e.latency_ms ? Math.max(2, (e.latency_ms / maxLatency) * H) : 2;
        const x = i * (barW + 1);
        const y = H - h;
        const fill =
          e.status === "healthy" ? "#22c55e" : e.status === "degraded" ? "#eab308" : "#ef4444";
        return <rect key={i} x={x} y={y} width={barW} height={h} rx={1} fill={fill} opacity={0.75} />;
      })}
    </svg>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function HealthDashboardPage() {
  const { identity } = useIdentity();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = useCallback(async (showRefresh = false) => {
    if (showRefresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/team/health-dashboard", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
    } catch (e: any) {
      setError(e.message || "Failed to load health data");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    // Auto-refresh every 30s
    const iv = setInterval(() => fetchData(true), 30000);
    return () => clearInterval(iv);
  }, [fetchData]);

  const isAdmin = identity?.role === "admin";

  if (loading) {
    return (
      <div className="p-6 lg:p-8 max-w-7xl mx-auto">
        <div className="flex items-center gap-3 text-stone-500">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span>Loading health dashboard…</span>
        </div>
      </div>
    );
  }

  if (error || !data?.summary) {
    return (
      <div className="p-6 lg:p-8 max-w-7xl mx-auto space-y-4">
        <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-8 text-center">
          <WifiOff className="w-12 h-12 text-stone-400 mx-auto mb-3" />
          <h2 className="text-lg font-semibold text-stone-900 dark:text-white">
            {error || "Health data unavailable"}
          </h2>
          <p className="text-sm text-stone-500 mt-1">
            The health monitor may be starting up. Try refreshing in a moment.
          </p>
          <button
            onClick={() => fetchData()}
            className="mt-4 px-4 py-2 bg-forest hover:bg-forest-dark text-white rounded-lg text-sm font-medium transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const services = data.summary.services || [];
  const history = data.history || {};
  const healthyCount = services.filter((s) => s.status === "healthy").length;
  const degradedCount = services.filter((s) => s.status === "degraded").length;
  const downCount = services.filter((s) => s.status === "down").length;
  const overallStatus = data.summary.overall || "unknown";

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-forest flex items-center justify-center">
            <HeartPulse className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-stone-900 dark:text-white">
              System Health
            </h1>
            <p className="text-sm text-stone-500">
              Real-time monitoring of all SolidAI SRE services
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-stone-400">
            Updated: {new Date(data.generated_at).toLocaleTimeString()}
          </span>
          <button
            onClick={() => fetchData(true)}
            disabled={refreshing}
            className="p-2 text-stone-400 hover:text-stone-600 dark:hover:text-stone-300 rounded-lg hover:bg-stone-100 dark:hover:bg-stone-800 disabled:opacity-50"
          >
            <RefreshCcw className={`w-5 h-5 ${refreshing ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Overall Status Banner */}
      <div
        className={`rounded-xl border p-4 flex items-center gap-4 ${
          overallStatus === "healthy"
            ? "bg-green-50 border-green-200 dark:bg-green-900/20 dark:border-green-800"
            : overallStatus === "degraded"
            ? "bg-yellow-50 border-yellow-200 dark:bg-yellow-900/20 dark:border-yellow-800"
            : "bg-red-50 border-red-200 dark:bg-red-900/20 dark:border-red-800"
        }`}
      >
        {overallStatus === "healthy" ? (
          <Wifi className="w-6 h-6 text-green-600" />
        ) : overallStatus === "degraded" ? (
          <AlertTriangle className="w-6 h-6 text-yellow-600" />
        ) : (
          <WifiOff className="w-6 h-6 text-red-600" />
        )}
        <div>
          <div className="font-semibold text-stone-900 dark:text-white capitalize">
            {overallStatus === "healthy"
              ? "All Systems Operational"
              : overallStatus === "degraded"
              ? "Partial Degradation"
              : overallStatus === "partial_outage"
              ? "Partial Outage"
              : "Service Disruption"}
          </div>
          <div className="text-sm text-stone-500">
            {healthyCount}/{services.length} services healthy
            {degradedCount > 0 && ` · ${degradedCount} degraded`}
            {downCount > 0 && ` · ${downCount} down`}
          </div>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm text-stone-500">Healthy</div>
              <div className="text-3xl font-bold text-green-600 mt-1">{healthyCount}</div>
            </div>
            <CheckCircle className="w-10 h-10 text-green-500 opacity-80" />
          </div>
        </div>
        <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm text-stone-500">Degraded</div>
              <div className="text-3xl font-bold text-yellow-600 mt-1">{degradedCount}</div>
            </div>
            <AlertTriangle className="w-10 h-10 text-yellow-500 opacity-80" />
          </div>
        </div>
        <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm text-stone-500">Down</div>
              <div className="text-3xl font-bold text-red-600 mt-1">{downCount}</div>
            </div>
            <XCircle className="w-10 h-10 text-red-500 opacity-80" />
          </div>
        </div>
      </div>

      {/* Service Detail Cards */}
      <div className="space-y-3">
        <h2 className="text-lg font-semibold text-stone-900 dark:text-white">
          Services
        </h2>
        {services.map((svc) => {
          const meta = STATUS_META[svc.status] || STATUS_META.unknown;
          const StatusIcon = meta.icon;
          const hist = history[svc.name];
          const recent = hist?.recent?.slice(-20) || [];
          const uptimePct = hist?.uptime?.uptime_pct ?? svc.uptime_24h;

          return (
            <div
              key={svc.name}
              className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm overflow-hidden"
            >
              <div className="p-5">
                <div className="flex items-center justify-between">
                  {/* Left: status + name */}
                  <div className="flex items-center gap-4 min-w-0">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${meta.bg}`}>
                      <StatusIcon className={`w-5 h-5 ${meta.color}`} />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-stone-900 dark:text-white truncate">
                          {svc.name}
                        </span>
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full font-medium ${meta.bg} ${meta.color}`}
                        >
                          {meta.label}
                        </span>
                      </div>
                      <div className="flex items-center gap-4 mt-1 text-xs text-stone-500">
                        {uptimePct !== null && (
                          <span className="flex items-center gap-1">
                            <Shield className="w-3 h-3" />
                            <span className={uptimeColor(uptimePct)}>
                              {uptimePct.toFixed(1)}% uptime (24h)
                            </span>
                          </span>
                        )}
                        {svc.latency && (
                          <span className="flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            <span className={latencyColor(svc.latency.avg_ms)}>
                              avg {formatLatency(svc.latency.avg_ms)} · p95 {formatLatency(svc.latency.p95_ms)}
                            </span>
                          </span>
                        )}
                        {hist?.latency && (
                          <span className="flex items-center gap-1">
                            <Activity className="w-3 h-3" />
                            {hist.latency.count} checks
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Right: sparkline */}
                  <div className="hidden md:block">
                    <Sparkline entries={recent} />
                  </div>
                </div>

                {/* Latency detail bar (if available) */}
                {hist?.latency && (
                  <div className="mt-3 pt-3 border-t border-stone-100 dark:border-stone-700">
                    <div className="grid grid-cols-5 gap-2 text-center">
                      <div>
                        <div className="text-[10px] text-stone-400 uppercase">Min</div>
                        <div className="text-sm font-medium text-stone-700 dark:text-stone-300">
                          {formatLatency(hist.latency.min_ms)}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-stone-400 uppercase">Avg</div>
                        <div className="text-sm font-medium text-stone-700 dark:text-stone-300">
                          {formatLatency(hist.latency.avg_ms)}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-stone-400 uppercase">p50</div>
                        <div className="text-sm font-medium text-stone-700 dark:text-stone-300">
                          {formatLatency(hist.latency.p50_ms)}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-stone-400 uppercase">p95</div>
                        <div className={`text-sm font-medium ${latencyColor(hist.latency.p95_ms)}`}>
                          {formatLatency(hist.latency.p95_ms)}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-stone-400 uppercase">Max</div>
                        <div className="text-sm font-medium text-stone-700 dark:text-stone-300">
                          {formatLatency(hist.latency.max_ms)}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div className="text-xs text-stone-400 text-center pt-4">
        Auto-refreshes every 30 seconds · Powered by SolidAI SRE Health Monitor
      </div>
    </div>
  );
}

'use client';

import Link from 'next/link';
import { RequireRole } from '@/components/RequireRole';
import { useIdentity } from '@/lib/useIdentity';
import { useOnboarding } from '@/lib/useOnboarding';
import { QuickStartWizard } from '@/components/onboarding/QuickStartWizard';
import {
  ShieldCheck,
  Network,
  Bot,
  Users,
  Activity,
  TrendingUp,
  TrendingDown,
  Clock,
  AlertCircle,
  CheckCircle,
  XCircle,
  Settings,
  FileText,
  Key,
  BarChart3,
  Zap,
  Cloud,
  MessageSquare,
  Github,
  Code,
  RefreshCw,
  Pause,
  Play,
  History,
} from 'lucide-react';
import { useState, useEffect, useCallback, useRef } from 'react';

interface DurationPercentiles {
  p50: number;
  p95: number;
  p99: number;
}

interface TeamStats {
  team_node_id: string;
  team_name: string;
  total_runs: number;
  successful_runs: number;
  failed_runs: number;
  success_rate: number;
  last_run_at: string | null;
  avg_duration_seconds: number | null;
  duration_percentiles: DurationPercentiles | null;
  most_used_agent: string | null;
  trend: 'up' | 'down' | 'stable';
  runs_this_week: number;
  runs_prev_week: number;
}

interface OrgStats {
  totalTeams: number;
  activeTeams: number;
  totalRuns: number;
  successRate: number;
  avgDurationSeconds: number | null;
  durationPercentiles: DurationPercentiles | null;
  teams: TeamStats[];
}

interface ActivityItem {
  id: string;
  type: 'run' | 'config' | 'token' | 'template';
  description: string;
  timestamp: string;
  status: 'success' | 'failed' | 'pending' | 'info';
  teamName?: string;
}

interface PendingItems {
  remediations: number;
  configChanges: number;
  expiringTokens: number;
}

interface ServiceHealth {
  name: string;
  status: 'healthy' | 'degraded' | 'down' | 'skipped';
  lastCheck: string;
  latency_ms?: number;
  error?: string;
}

interface IntegrationHealth {
  name: string;
  status: 'connected' | 'error' | 'not_configured';
  icon: any;
}

interface LitellmModelHealth {
  model: string;
  status: 'healthy' | 'degraded' | 'no_credits' | 'timeout' | 'unreachable' | 'not_configured';
  litellmProxy?: boolean;
  latency_ms?: number;
  http_status?: number;
  error?: string;
}

interface LitellmHealthData {
  healthy_count: number;
  unhealthy_count: number;
  no_credits_count: number;
  timeout_count: number;
  all_models: LitellmModelHealth[];
  generated_at: string;
}

interface HealthUptime {
  uptime_pct: number | null;
  total_checks: number;
  healthy_count: number;
  window_hours: number;
}

interface HealthHistoryEntry {
  timestamp: string;
  status: string;
  latency_ms?: number;
  error?: string;
}

interface ServiceHealthHistory {
  uptime: HealthUptime;
  recent: HealthHistoryEntry[];
}

const HEALTH_REFRESH_INTERVAL_MS = 30000; // 30 seconds
const HISTORY_REFRESH_INTERVAL_MS = 300000; // 5 minutes

export default function AdminHomePage() {
  const { identity, error } = useIdentity();
  const [stats, setStats] = useState<OrgStats | null>(null);
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [pending, setPending] = useState<PendingItems>({ remediations: 0, configChanges: 0, expiringTokens: 0 });
  const [services, setServices] = useState<ServiceHealth[]>([]);
  const [integrations, setIntegrations] = useState<IntegrationHealth[]>([]);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthLastUpdated, setHealthLastUpdated] = useState<Date | null>(null);
  const [healthAutoRefresh, setHealthAutoRefresh] = useState(true);
  const [healthHistory, setHealthHistory] = useState<Record<string, ServiceHealthHistory>>({});
  const [historyLoading, setHistoryLoading] = useState(false);
  const [litellmHealth, setLitellmHealth] = useState<LitellmHealthData | null>(null);
  const [litellmLoading, setLitellmLoading] = useState(false);
  const healthIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const historyIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Onboarding state - visitors use localStorage only
  const isVisitor = identity?.auth_kind === 'visitor';
  const {
    shouldShowWelcome,
    markWelcomeSeen,
    markFirstAgentRunCompleted,
  } = useOnboarding({ isVisitor });
  const [showWelcomeModal, setShowWelcomeModal] = useState(false);

  // Show welcome modal on first visit
  useEffect(() => {
    if (shouldShowWelcome) {
      setShowWelcomeModal(true);
    }
  }, [shouldShowWelcome]);

  // Fetch system health with loading state
  const fetchHealth = useCallback(async (orgId: string) => {
    setHealthLoading(true);
    try {
      const res = await fetch(`/api/admin/orgs/${orgId}/health`);
      if (res.ok) {
        const data = await res.json();
        setServices(data.services || []);
        const integrationsWithIcons = (data.integrations || []).map((int: any) => ({
          ...int,
          icon: getIntegrationIcon(int.name),
        }));
        setIntegrations(integrationsWithIcons);
        setHealthLastUpdated(new Date());
      }
    } catch (err) {
      console.error('Failed to load health:', err);
    } finally {
      setHealthLoading(false);
    }
  }, []);

  // Fetch health history (uptime stats)
  const fetchHealthHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const res = await fetch('/api/admin/health-history?window_hours=24');
      if (res.ok) {
        const data = await res.json();
        setHealthHistory(data || {});
      }
    } catch (err) {
      console.error('Failed to load health history:', err);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  // Fetch litellm model health from health-monitor (richer data with latency + status)
  const fetchLitellmHealth = useCallback(async () => {
    setLitellmLoading(true);
    try {
      const res = await fetch('/api/admin/monitor-health', { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        const modelHealth = data?.modelHealth;
        if (modelHealth?.models) {
          const all_models = modelHealth.models.map((m: any) => ({
            model: m.model,
            status: m.status || 'unreachable',
            latency_ms: m.latency_ms,
            http_status: m.http_status,
            error: m.error,
          }));
          const healthy_count = all_models.filter((m: any) => m.status === 'healthy').length;
          const no_credits_count = all_models.filter((m: any) => m.status === 'no_credits').length;
          const timeout_count = all_models.filter((m: any) => m.status === 'timeout').length;
          const unhealthy_count = all_models.length - healthy_count - no_credits_count - timeout_count;
          setLitellmHealth({
            healthy_count,
            unhealthy_count: Math.max(0, unhealthy_count),
            no_credits_count,
            timeout_count,
            all_models,
            generated_at: modelHealth.generated_at || new Date().toISOString(),
          });
        }
      }
    } catch (err) {
      console.error('Failed to load litellm health:', err);
    } finally {
      setLitellmLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!identity?.org_id) return;

    // Fetch org-wide stats
    fetch(`/api/admin/orgs/${identity.org_id}/stats`)
      .then(res => res.ok ? res.json() : null)
      .then(data => data && setStats(data))
      .catch(err => console.error('Failed to load stats:', err));

    // Fetch recent activity
    fetch(`/api/admin/orgs/${identity.org_id}/activity?limit=10`)
      .then(res => res.ok ? res.json() : null)
      .then(data => data && setActivities(data.activities || []))
      .catch(err => console.error('Failed to load activity:', err));

    // Fetch pending items
    fetch(`/api/admin/orgs/${identity.org_id}/pending`)
      .then(res => res.ok ? res.json() : null)
      .then(data => data && setPending(data))
      .catch(err => console.error('Failed to load pending items:', err));

    // Initial health fetch
    fetchHealth(identity.org_id);
    // Initial health history fetch
    fetchHealthHistory();
    // Initial litellm health fetch
    fetchLitellmHealth();
  }, [identity?.org_id, fetchHealth, fetchHealthHistory, fetchLitellmHealth]);

  // Auto-refresh health data
  useEffect(() => {
    if (!identity?.org_id || !healthAutoRefresh) {
      if (healthIntervalRef.current) {
        clearInterval(healthIntervalRef.current);
        healthIntervalRef.current = null;
      }
      return;
    }

    healthIntervalRef.current = setInterval(() => {
      const orgId = identity?.org_id;
      if (orgId) fetchHealth(orgId);
      fetchLitellmHealth();
    }, HEALTH_REFRESH_INTERVAL_MS);

    return () => {
      if (healthIntervalRef.current) {
        clearInterval(healthIntervalRef.current);
        healthIntervalRef.current = null;
      }
    };
  }, [identity?.org_id, healthAutoRefresh, fetchHealth]);

  // Auto-refresh health history (every 5 minutes)
  useEffect(() => {
    if (!identity?.org_id) {
      if (historyIntervalRef.current) {
        clearInterval(historyIntervalRef.current);
        historyIntervalRef.current = null;
      }
      return;
    }

    historyIntervalRef.current = setInterval(() => {
      fetchHealthHistory();
    }, HISTORY_REFRESH_INTERVAL_MS);

    return () => {
      if (historyIntervalRef.current) {
        clearInterval(historyIntervalRef.current);
        historyIntervalRef.current = null;
      }
    };
  }, [identity?.org_id, fetchHealthHistory]);

  // Helper to map integration names to icons
  const getIntegrationIcon = (name: string) => {
    const iconMap: Record<string, any> = {
      slack: MessageSquare,
      openai: Zap,
      github: Github,
      kubernetes: Cloud,
      aws: Cloud,
      datadog: BarChart3,
      grafana: BarChart3,
      pagerduty: AlertCircle,
      coralogix: BarChart3,
    };
    return iconMap[name.toLowerCase()] || Settings;
  };

  const formatRelativeTime = (timestamp: string) => {
    const now = Date.now();
    const then = new Date(timestamp).getTime();
    const diff = now - then;
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    return `${days}d ago`;
  };

  const formatDuration = (seconds: number | null) => {
    if (seconds === null) return 'N/A';
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    return `${hours}h ${remainingMinutes}m`;
  };

  const getActivityIcon = (type: ActivityItem['type']) => {
    switch (type) {
      case 'run':
        return <Bot className="w-4 h-4" />;
      case 'config':
        return <Settings className="w-4 h-4" />;
      case 'token':
        return <Key className="w-4 h-4" />;
      case 'template':
        return <FileText className="w-4 h-4" />;
    }
  };

  const getActivityStatusIcon = (status: ActivityItem['status']) => {
    switch (status) {
      case 'success':
        return <CheckCircle className="w-4 h-4 text-green-500" />;
      case 'failed':
        return <XCircle className="w-4 h-4 text-clay" />;
      case 'pending':
        return <Clock className="w-4 h-4 text-yellow-500" />;
      case 'info':
        return <Activity className="w-4 h-4 text-stone-500" />;
    }
  };

  const getServiceStatusBadge = (status: ServiceHealth['status']) => {
    switch (status) {
      case 'healthy':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
            <CheckCircle className="w-3 h-3" />
            Healthy
          </span>
        );
      case 'degraded':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400">
            <AlertCircle className="w-3 h-3" />
            Degraded
          </span>
        );
      case 'down':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-clay-light/15 text-clay-dark dark:bg-red-900/30 dark:text-clay-light">
            <XCircle className="w-3 h-3" />
            Down
          </span>
        );
      case 'skipped':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-stone-100 text-stone-600 dark:bg-stone-700 dark:text-stone-400">
            <Pause className="w-3 h-3" />
            Skipped
          </span>
        );
    }
  };

  const getIntegrationStatusBadge = (status: IntegrationHealth['status']) => {
    switch (status) {
      case 'connected':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
            <CheckCircle className="w-3 h-3" />
            Connected
          </span>
        );
      case 'error':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-clay-light/15 text-clay-dark dark:bg-red-900/30 dark:text-clay-light">
            <XCircle className="w-3 h-3" />
            Error
          </span>
        );
      case 'not_configured':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-stone-100 text-stone-700 dark:bg-stone-700 dark:text-stone-400">
            <AlertCircle className="w-3 h-3" />
            Not Configured
          </span>
        );
    }
  };

  const totalPending = pending.remediations + pending.configChanges + pending.expiringTokens;

  const handleWelcomeRunAgent = () => {
    markWelcomeSeen();
    markFirstAgentRunCompleted();
    setShowWelcomeModal(false);
  };

  const handleWelcomeSkip = () => {
    markWelcomeSeen();
    setShowWelcomeModal(false);
  };

  return (
    <RequireRole role="admin" fallbackHref="/">
      {/* Onboarding Modals */}
      {showWelcomeModal && (
        <QuickStartWizard
          onClose={() => setShowWelcomeModal(false)}
          onRunAgent={handleWelcomeRunAgent}
          onSkip={handleWelcomeSkip}
        />
      )}

      <div className="p-8 max-w-7xl mx-auto space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ShieldCheck className="w-7 h-7 text-stone-500" />
            <div>
              <h1 className="text-2xl font-semibold text-stone-900 dark:text-white">Admin Dashboard</h1>
              <p className="text-sm text-stone-500">Monitor organization health and activity</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-xs text-stone-500 text-right">
              <div>
                Signed in as: <span className="font-mono">{identity?.auth_kind || 'unknown'}</span>
              </div>
              <div className="mt-1">
                Organization: <span className="font-mono">{identity?.org_id || '—'}</span>
              </div>
            </div>
          </div>
        </div>

        {error && (
          <div className="text-sm text-clay bg-clay-light/10 dark:bg-clay/20 border border-red-100 dark:border-red-900/40 rounded-lg p-3">
            {error}
          </div>
        )}

        {/* Organization Overview Stats */}
        <div>
          <h2 className="text-lg font-semibold text-stone-900 dark:text-white mb-4">Organization Overview</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
            <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-stone-500">Total Teams</div>
                  <div className="text-3xl font-bold text-stone-900 dark:text-white mt-1">
                    {stats?.totalTeams || 0}
                  </div>
                </div>
                <Users className="w-10 h-10 text-stone-400 opacity-80" />
              </div>
            </div>

            <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-stone-500">Active Teams (7d)</div>
                  <div className="text-3xl font-bold text-stone-900 dark:text-white mt-1">
                    {stats?.activeTeams || 0}
                  </div>
                </div>
                <Activity className="w-10 h-10 text-stone-400 opacity-80" />
              </div>
            </div>

            <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-stone-500">Agent Runs (30d)</div>
                  <div className="text-3xl font-bold text-stone-900 dark:text-white mt-1">
                    {stats?.totalRuns || 0}
                  </div>
                </div>
                <Bot className="w-10 h-10 text-stone-400 opacity-80" />
              </div>
            </div>

            <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-stone-500">Success Rate</div>
                  <div className="text-3xl font-bold text-stone-900 dark:text-white mt-1">
                    {stats?.successRate || 0}%
                  </div>
                </div>
                <TrendingUp className="w-10 h-10 text-stone-400 opacity-80" />
              </div>
            </div>

            <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-stone-500">MTTD (Agent Run Duration)</div>
                  {stats?.durationPercentiles ? (
                    <div>
                      <div className="text-3xl font-bold text-stone-900 dark:text-white mt-1">
                        {stats.durationPercentiles.p50}s
                      </div>
                      <div className="text-xs text-stone-500 mt-1">
                        P50 | P95: {stats.durationPercentiles.p95}s | P99: {stats.durationPercentiles.p99}s
                      </div>
                    </div>
                  ) : (
                    <div className="text-3xl font-bold text-stone-400 dark:text-stone-600 mt-1">—</div>
                  )}
                </div>
                <Clock className="w-10 h-10 text-forest opacity-80" />
              </div>
            </div>
          </div>
        </div>

        {/* Main Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Activity Feed - Takes 2 columns */}
          <div className="lg:col-span-2">
            <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm">
              <div className="p-5 border-b border-stone-200 dark:border-stone-700">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-stone-900 dark:text-white">Recent Activity</h2>
                  <button className="text-xs text-stone-500 hover:text-stone-700 dark:hover:text-stone-300 flex items-center gap-1">
                    <RefreshCw className="w-3 h-3" />
                    Refresh
                  </button>
                </div>
              </div>
              <div className="divide-y divide-stone-200 dark:divide-stone-700">
                {activities.length === 0 && (
                  <div className="p-8 text-center text-sm text-stone-500">No recent activity</div>
                )}
                {activities.map((activity) => (
                  <div key={activity.id} className="p-4 hover:bg-stone-50 dark:hover:bg-stone-800/50 transition-colors">
                    <div className="flex items-start gap-3">
                      <div className="flex-shrink-0 mt-0.5">
                        <div className="p-2 rounded-lg bg-stone-100 dark:bg-stone-700 text-stone-700 dark:text-stone-300">
                          {getActivityIcon(activity.type)}
                        </div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          {getActivityStatusIcon(activity.status)}
                          <p className="text-sm text-stone-900 dark:text-white">{activity.description}</p>
                        </div>
                        <div className="flex items-center gap-2 mt-1">
                          <span className="text-xs text-stone-500">{formatRelativeTime(activity.timestamp)}</span>
                          {activity.teamName && (
                            <>
                              <span className="text-xs text-stone-400">•</span>
                              <span className="text-xs text-stone-500">{activity.teamName}</span>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right Column - Pending Items + Health Status */}
          <div className="space-y-6">
            {/* Pending Items */}
            <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm">
              <div className="p-5 border-b border-stone-200 dark:border-stone-700">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-stone-900 dark:text-white">Pending Items</h2>
                  {totalPending > 0 && (
                    <span className="px-2 py-1 rounded-full text-xs font-medium bg-forest-light/15 text-forest dark:bg-forest/30 dark:text-forest-light">
                      {totalPending}
                    </span>
                  )}
                </div>
              </div>
              <div className="p-5 space-y-3">
                <Link
                  href="/admin/agent-run"
                  className="block p-3 rounded-lg border border-stone-200 dark:border-stone-700 hover:border-forest-light dark:hover:border-forest transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <AlertCircle className="w-4 h-4 text-stone-600" />
                      <span className="text-sm font-medium text-stone-900 dark:text-white">Remediations</span>
                    </div>
                    {pending.remediations > 0 && (
                      <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-forest-light/15 text-forest dark:bg-forest/30 dark:text-forest-light">
                        {pending.remediations}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-stone-500 mt-1">Awaiting approval</p>
                </Link>

                <Link
                  href="/admin/org-tree"
                  className="block p-3 rounded-lg border border-stone-200 dark:border-stone-700 hover:border-forest-light dark:hover:border-forest transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Settings className="w-4 h-4 text-stone-600" />
                      <span className="text-sm font-medium text-stone-900 dark:text-white">Config Changes</span>
                    </div>
                    {pending.configChanges > 0 && (
                      <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-stone-100 text-stone-700 dark:bg-stone-700 dark:text-stone-400">
                        {pending.configChanges}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-stone-500 mt-1">Awaiting approval</p>
                </Link>

                <Link
                  href="/admin/token-management"
                  className="block p-3 rounded-lg border border-stone-200 dark:border-stone-700 hover:border-forest-light dark:hover:border-forest transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Clock className="w-4 h-4 text-stone-600" />
                      <span className="text-sm font-medium text-stone-900 dark:text-white">Expiring Tokens</span>
                    </div>
                    {pending.expiringTokens > 0 && (
                      <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400">
                        {pending.expiringTokens}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-stone-500 mt-1">Expiring within 7 days</p>
                </Link>
              </div>
            </div>

            {/* System Health */}
            <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm">
              <div className="p-5 border-b border-stone-200 dark:border-stone-700">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-stone-900 dark:text-white">System Health</h2>
                  <div className="flex items-center gap-2">
                    {healthLastUpdated && (
                      <span className="text-xs text-stone-400" title={healthLastUpdated.toISOString()}>
                        Updated {formatRelativeTime(healthLastUpdated.toISOString())}
                      </span>
                    )}
                    <button
                      onClick={() => setHealthAutoRefresh(!healthAutoRefresh)}
                      className={`p-1.5 rounded-md transition-colors ${
                        healthAutoRefresh
                          ? 'text-forest hover:bg-forest/10'
                          : 'text-stone-400 hover:bg-stone-100 dark:hover:bg-stone-700'
                      }`}
                      title={healthAutoRefresh ? 'Pause auto-refresh' : 'Resume auto-refresh'}
                    >
                      {healthAutoRefresh ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                    </button>
                    <button
                      onClick={() => identity?.org_id && fetchHealth(identity.org_id)}
                      disabled={healthLoading}
                      className="p-1.5 rounded-md text-stone-400 hover:bg-stone-100 dark:hover:bg-stone-700 transition-colors disabled:opacity-50"
                      title="Refresh now"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${healthLoading ? 'animate-spin' : ''}`} />
                    </button>
                  </div>
                </div>
                {healthAutoRefresh && (
                  <div className="mt-2 flex items-center gap-2">
                    <div className="h-0.5 flex-1 bg-stone-100 dark:bg-stone-700 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-forest/40 rounded-full animate-pulse"
                        style={{ width: '100%', animationDuration: `${HEALTH_REFRESH_INTERVAL_MS}ms`, animationName: 'healthProgress' }}
                      />
                    </div>
                    <span className="text-[10px] text-stone-400">Auto-refresh 30s</span>
                  </div>
                )}
              </div>
              <div className="p-5 space-y-4">
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-xs font-medium text-stone-500 uppercase">Services</div>
                    <div className="flex items-center gap-1 text-[10px] text-stone-400" title="24h uptime from health history">
                      <History className="w-3 h-3" />
                      24h uptime
                    </div>
                  </div>
                  <div className="space-y-2">
                    {services.length === 0 && !healthLoading && (
                      <div className="text-xs text-stone-400 italic">No health data available</div>
                    )}
                    {services.map((service) => {
                      const history = healthHistory[service.name];
                      const uptime = history?.uptime;
                      return (
                        <div key={service.name}>
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="text-sm text-stone-700 dark:text-stone-300">{service.name}</span>
                              {service.latency_ms !== undefined && (
                                <span className="text-[10px] text-stone-400 font-mono">{service.latency_ms}ms</span>
                              )}
                            </div>
                            <div className="flex items-center gap-2">
                              {service.error && (
                                <span className="text-[10px] text-clay" title={service.error}>⚠</span>
                              )}
                              {getServiceStatusBadge(service.status)}
                            </div>
                          </div>
                          {uptime && uptime.uptime_pct !== null && (
                            <div className="mt-1 flex items-center gap-2">
                              <div className="flex-1 h-1 bg-stone-100 dark:bg-stone-700 rounded-full overflow-hidden">
                                <div
                                  className={`h-full rounded-full transition-all ${
                                    uptime.uptime_pct >= 99
                                      ? 'bg-green-500'
                                      : uptime.uptime_pct >= 95
                                      ? 'bg-yellow-500'
                                      : 'bg-clay'
                                  }`}
                                  style={{ width: `${uptime.uptime_pct}%` }}
                                />
                              </div>
                              <span className={`text-[10px] font-mono ${
                                uptime.uptime_pct >= 99
                                  ? 'text-green-600 dark:text-green-400'
                                  : uptime.uptime_pct >= 95
                                  ? 'text-yellow-600 dark:text-yellow-400'
                                  : 'text-clay'
                              }`}>
                                {uptime.uptime_pct}%
                              </span>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="border-t border-stone-200 dark:border-stone-700 pt-4">
                  <div className="text-xs font-medium text-stone-500 uppercase mb-2">Integrations</div>
                  <div className="space-y-2">
                    {integrations.length === 0 && (
                      <div className="text-xs text-stone-400 italic">No integrations configured</div>
                    )}
                    {integrations.map((integration) => {
                      const Icon = integration.icon;
                      return (
                        <div key={integration.name} className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Icon className="w-4 h-4 text-stone-500" />
                            <span className="text-sm text-stone-700 dark:text-stone-300">{integration.name}</span>
                          </div>
                          {getIntegrationStatusBadge(integration.status)}
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* LLM Model Health */}
                <div className="border-t border-stone-200 dark:border-stone-700 pt-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-xs font-medium text-stone-500 uppercase">LLM Models</div>
                    <button
                      onClick={fetchLitellmHealth}
                      disabled={litellmLoading}
                      className="p-1 rounded text-stone-400 hover:bg-stone-100 dark:hover:bg-stone-700 transition-colors disabled:opacity-50"
                      title="Refresh litellm health"
                    >
                      <RefreshCw className={`w-3 h-3 ${litellmLoading ? 'animate-spin' : ''}`} />
                    </button>
                  </div>
                  {!litellmHealth && !litellmLoading && (
                    <div className="text-xs text-stone-400 italic">No litellm data — click refresh</div>
                  )}
                  {litellmLoading && (
                    <div className="text-xs text-stone-400 italic">Checking models...</div>
                  )}
                  {litellmHealth && (
                    <div className="space-y-2">
                      {/* Summary badge row */}
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                          <CheckCircle className="w-2.5 h-2.5" />
                          {litellmHealth.healthy_count} healthy
                        </span>
                        {litellmHealth.unhealthy_count > 0 && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
                            <XCircle className="w-2.5 h-2.5" />
                            {litellmHealth.unhealthy_count} unhealthy
                          </span>
                        )}
                        {litellmHealth.no_credits_count > 0 && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                            <AlertCircle className="w-2.5 h-2.5" />
                            {litellmHealth.no_credits_count} no credits
                          </span>
                        )}
                        {litellmHealth.timeout_count > 0 && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400">
                            <Clock className="w-2.5 h-2.5" />
                            {litellmHealth.timeout_count} timeout
                          </span>
                        )}
                      </div>

                      {/* All models with status and latency */}
                      {litellmHealth.all_models.map((m) => (
                        <div key={m.model} className="flex items-center justify-between">
                          <div className="flex items-center gap-2 min-w-0">
                            {m.status === 'healthy' ? (
                              <CheckCircle className="w-3 h-3 text-green-500 flex-shrink-0" />
                            ) : m.status === 'no_credits' ? (
                              <AlertCircle className="w-3 h-3 text-amber-500 flex-shrink-0" />
                            ) : m.status === 'timeout' ? (
                              <Clock className="w-3 h-3 text-orange-500 flex-shrink-0" />
                            ) : (
                              <XCircle className="w-3 h-3 text-red-500 flex-shrink-0" />
                            )}
                            <span className="text-xs font-mono text-stone-700 dark:text-stone-300 truncate">{m.model}</span>
                          </div>
                          <div className="flex items-center gap-2 flex-shrink-0 ml-2">
                            {m.latency_ms != null && (
                              <span className="text-[10px] text-stone-400">{m.latency_ms}ms</span>
                            )}
                            {m.status === 'healthy' ? (
                              <span className="text-[10px] text-green-600 dark:text-green-400">OK</span>
                            ) : m.status === 'no_credits' ? (
                              <span className="text-[10px] text-amber-500" title={m.error}>No credits</span>
                            ) : m.status === 'timeout' ? (
                              <span className="text-[10px] text-orange-500" title={m.error}>Timeout</span>
                            ) : (
                              <span className="text-[10px] text-red-500" title={m.error}>Error</span>
                            )}
                          </div>
                        </div>
                      ))}

                      {/* Error details for non-healthy models */}
                      {litellmHealth.all_models.filter(m => m.error && m.status !== 'healthy').length > 0 && (
                        <div className="mt-1 space-y-1">
                          {litellmHealth.all_models.filter(m => m.error && m.status !== 'healthy').map((m) => (
                            <div key={`${m.model}-err`} className="text-[10px] text-red-400 bg-red-50 dark:bg-red-900/20 rounded px-2 py-1 font-mono break-all">
                              {m.error}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Team Performance Breakdown */}
        {stats?.teams && stats.teams.length > 0 && (
          <div>
            <h2 className="text-lg font-semibold text-stone-900 dark:text-white mb-4">Team Performance (Last 30 Days)</h2>
            <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-stone-50 dark:bg-stone-700 border-b border-stone-200 dark:border-stone-600">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-stone-500 dark:text-stone-400 uppercase tracking-wider">
                        Team
                      </th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-stone-500 dark:text-stone-400 uppercase tracking-wider">
                        Total Runs
                      </th>
                      <th className="px-6 py-3 text-center text-xs font-medium text-stone-500 dark:text-stone-400 uppercase tracking-wider">
                        Trend
                      </th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-stone-500 dark:text-stone-400 uppercase tracking-wider">
                        Success Rate
                      </th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-stone-500 dark:text-stone-400 uppercase tracking-wider">
                        MTTD
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-stone-500 dark:text-stone-400 uppercase tracking-wider">
                        Most Used Agent
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-stone-500 dark:text-stone-400 uppercase tracking-wider">
                        Last Run
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-stone-200 dark:divide-stone-700">
                    {stats.teams.map((team) => (
                      <tr key={team.team_node_id} className="hover:bg-stone-50 dark:hover:bg-stone-800/50 transition-colors">
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center">
                            <div className="w-8 h-8 rounded-lg bg-stone-100 dark:bg-stone-700 flex items-center justify-center mr-3">
                              <Users className="w-4 h-4 text-stone-600 dark:text-stone-400" />
                            </div>
                            <div>
                              <div className="text-sm font-medium text-stone-900 dark:text-white">
                                {team.team_name}
                              </div>
                              <div className="text-xs text-stone-500 dark:text-stone-400">
                                {team.team_node_id}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-right">
                          <div className="text-sm font-medium text-stone-900 dark:text-white">
                            {team.total_runs}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-center">
                          <div className="flex items-center justify-center gap-1">
                            {team.trend === 'up' && (
                              <span className="inline-flex items-center text-green-600 dark:text-green-400" title={`${team.runs_this_week} runs this week vs ${team.runs_prev_week} last week`}>
                                <TrendingUp className="w-4 h-4" />
                              </span>
                            )}
                            {team.trend === 'down' && (
                              <span className="inline-flex items-center text-clay dark:text-clay-light" title={`${team.runs_this_week} runs this week vs ${team.runs_prev_week} last week`}>
                                <Activity className="w-4 h-4 rotate-180" />
                              </span>
                            )}
                            {team.trend === 'stable' && (
                              <span className="inline-flex items-center text-stone-500 dark:text-stone-400" title={`${team.runs_this_week} runs this week vs ${team.runs_prev_week} last week`}>
                                <Activity className="w-4 h-4" />
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-right">
                          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                            team.success_rate >= 90
                              ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                              : team.success_rate >= 70
                              ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400'
                              : 'bg-clay-light/15 text-red-800 dark:bg-red-900/30 dark:text-clay-light'
                          }`}>
                            {team.success_rate}%
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-right">
                          {team.duration_percentiles ? (
                            <div>
                              <div className="text-sm font-medium text-stone-900 dark:text-white">
                                P50: {team.duration_percentiles.p50}s
                              </div>
                              <div className="text-xs text-stone-500">
                                P95: {team.duration_percentiles.p95}s | P99: {team.duration_percentiles.p99}s
                              </div>
                            </div>
                          ) : (
                            <div className="text-sm text-stone-700 dark:text-stone-300">
                              {formatDuration(team.avg_duration_seconds)}
                            </div>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-left">
                          {team.most_used_agent ? (
                            <div className="flex items-center gap-2">
                              <Bot className="w-4 h-4 text-stone-500" />
                              <span className="text-sm text-stone-700 dark:text-stone-300">
                                {team.most_used_agent}
                              </span>
                            </div>
                          ) : (
                            <span className="text-sm text-stone-400">—</span>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-left">
                          <div className="text-sm text-stone-500 dark:text-stone-400">
                            {team.last_run_at ? formatRelativeTime(team.last_run_at) : 'Never'}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* Quick Actions */}
        <div>
          <h2 className="text-lg font-semibold text-stone-900 dark:text-white mb-4">Quick Actions</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <Link
              href="/admin/org-tree"
              className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm hover:border-forest-light dark:hover:border-forest transition-colors group"
            >
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-stone-100 dark:bg-stone-700 text-stone-600 dark:text-stone-400 group-hover:bg-stone-200 dark:group-hover:bg-stone-700 transition-colors">
                  <Users className="w-5 h-5" />
                </div>
                <div>
                  <div className="font-medium text-stone-900 dark:text-white">Add New Team</div>
                  <div className="text-xs text-stone-500">Create team in org tree</div>
                </div>
              </div>
            </Link>

            <Link
              href="/admin/token-management"
              className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm hover:border-forest-light dark:hover:border-forest transition-colors group"
            >
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-stone-100 dark:bg-stone-700 text-stone-600 dark:text-stone-400 group-hover:bg-stone-200 dark:group-hover:bg-stone-700 transition-colors">
                  <Key className="w-5 h-5" />
                </div>
                <div>
                  <div className="font-medium text-stone-900 dark:text-white">Issue Token</div>
                  <div className="text-xs text-stone-500">Generate API token</div>
                </div>
              </div>
            </Link>

            <Link
              href="/admin/audit"
              className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm hover:border-forest-light dark:hover:border-forest transition-colors group"
            >
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-stone-100 dark:bg-stone-700 text-stone-600 dark:text-stone-400 group-hover:bg-stone-200 dark:group-hover:bg-stone-700 transition-colors">
                  <FileText className="w-5 h-5" />
                </div>
                <div>
                  <div className="font-medium text-stone-900 dark:text-white">View Audit Log</div>
                  <div className="text-xs text-stone-500">Review admin actions</div>
                </div>
              </div>
            </Link>
          </div>
        </div>
      </div>
    </RequireRole>
  );
}

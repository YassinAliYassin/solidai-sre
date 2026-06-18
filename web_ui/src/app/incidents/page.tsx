'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  AlertCircle,
  CheckCircle,
  XCircle,
  Clock,
  RefreshCw,
  Pause,
  Play,
  Activity,
  ArrowUp,
  ArrowDown,
  Minus,
  ChevronDown,
  ChevronUp,
  Shield,
  Server,
  Zap,
  Search,
  Loader2,
  ExternalLink,
} from 'lucide-react';

// ─── Types ───────────────────────────────────────────────────────────────────

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

interface ServiceHistory {
  uptime: HealthUptime;
  recent: HealthHistoryEntry[];
}

interface IncidentEvent {
  id: string;
  serviceName: string;
  type: 'down' | 'degraded' | 'recovered';
  timestamp: string;
  latency_ms?: number;
  error?: string;
  duration?: string;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const REFRESH_INTERVAL_MS = 30_000;

function formatRelativeTime(timestamp: string): string {
  const now = Date.now();
  const then = new Date(timestamp).getTime();
  const diff = now - then;
  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (seconds < 60) return `${seconds}s ago`;
  if (minutes < 60) return `${minutes}m ago`;
  if (hours < 24) return `${hours}h ago`;
  return `${days}d ago`;
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function getStatusColor(status: string): string {
  switch (status) {
    case 'healthy': return 'text-green-600 dark:text-green-400';
    case 'degraded': return 'text-yellow-600 dark:text-yellow-400';
    case 'down': return 'text-red-600 dark:text-red-400';
    default: return 'text-stone-500';
  }
}

function getStatusBg(status: string): string {
  switch (status) {
    case 'healthy': return 'bg-green-100 dark:bg-green-900/30';
    case 'degraded': return 'bg-yellow-100 dark:bg-yellow-900/30';
    case 'down': return 'bg-red-100 dark:bg-red-900/30';
    default: return 'bg-stone-100 dark:bg-stone-700';
  }
}

function getIncidentIcon(type: IncidentEvent['type']) {
  switch (type) {
    case 'down': return <XCircle className="w-4 h-4 text-red-500" />;
    case 'degraded': return <AlertCircle className="w-4 h-4 text-yellow-500" />;
    case 'recovered': return <CheckCircle className="w-4 h-4 text-green-500" />;
  }
}

function getUptimeBarColor(pct: number | null): string {
  if (pct === null) return 'bg-stone-300 dark:bg-stone-600';
  if (pct >= 99) return 'bg-green-500';
  if (pct >= 95) return 'bg-yellow-500';
  return 'bg-red-500';
}

function getUptimeTextColor(pct: number | null): string {
  if (pct === null) return 'text-stone-500';
  if (pct >= 99) return 'text-green-600 dark:text-green-400';
  if (pct >= 95) return 'text-yellow-600 dark:text-yellow-400';
  return 'text-red-600 dark:text-red-400';
}

/**
 * Build incident events from health history by detecting status transitions.
 * A "down" or "degraded" transition starts an incident; a "healthy" transition
 * after a non-healthy state marks recovery.
 */
function buildIncidents(history: Record<string, ServiceHistory>): IncidentEvent[] {
  const events: IncidentEvent[] = [];

  for (const [serviceName, data] of Object.entries(history)) {
    const recent = data.recent;
    if (recent.length < 2) continue;

    let incidentStart: HealthHistoryEntry | null = null;

    for (let i = 1; i < recent.length; i++) {
      const prev = recent[i - 1];
      const curr = recent[i];

      const wasUnhealthy = prev.status === 'down' || prev.status === 'degraded';
      const isHealthy = curr.status === 'healthy';
      const isNowUnhealthy = curr.status === 'down' || curr.status === 'degraded';

      // Transition to unhealthy → new incident
      if (isNowUnhealthy && !wasUnhealthy) {
        incidentStart = curr;
        events.push({
          id: `${serviceName}-${curr.timestamp}`,
          serviceName,
          type: curr.status as 'down' | 'degraded',
          timestamp: curr.timestamp,
          latency_ms: curr.latency_ms,
          error: curr.error,
        });
      }

      // Transition to healthy → recovery
      if (isHealthy && wasUnhealthy && incidentStart) {
        const startMs = new Date(incidentStart.timestamp).getTime();
        const endMs = new Date(curr.timestamp).getTime();
        const durationMs = endMs - startMs;
        const durationMin = Math.round(durationMs / 60000);
        const durationStr = durationMin < 60
          ? `${durationMin}m`
          : `${Math.floor(durationMin / 60)}h ${durationMin % 60}m`;

        events.push({
          id: `${serviceName}-${curr.timestamp}-recovery`,
          serviceName,
          type: 'recovered',
          timestamp: curr.timestamp,
          latency_ms: curr.latency_ms,
          duration: durationStr,
        });
        incidentStart = null;
      }
    }

    // If still unhealthy at end of history, mark as ongoing
    if (incidentStart) {
      const lastEvent = events[events.length - 1];
      if (lastEvent && !lastEvent.duration && lastEvent.type !== 'recovered') {
        // Update the event to show it's ongoing (no recovery yet)
        lastEvent.duration = 'ongoing';
      }
    }
  }

  // Sort newest first
  return events.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function IncidentsPage() {
  const [history, setHistory] = useState<Record<string, ServiceHistory>>({});
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [expandedService, setExpandedService] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<'all' | 'incidents'>('all');
  const [investigating, setInvestigating] = useState<string | null>(null);
  const [investigationStatus, setInvestigationStatus] = useState<Record<string, 'started' | 'error'>>({});
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleInvestigate = async (incident: IncidentEvent) => {
    const key = incident.id;
    setInvestigating(key);
    try {
      const res = await fetch('/api/admin/investigate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          serviceName: incident.serviceName,
          incidentType: incident.type,
          timestamp: incident.timestamp,
          error: incident.error,
          latency_ms: incident.latency_ms,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setInvestigationStatus(prev => ({ ...prev, [key]: 'started' }));
        // Clear status after 5 seconds
        setTimeout(() => {
          setInvestigationStatus(prev => {
            const next = { ...prev };
            delete next[key];
            return next;
          });
        }, 5000);
      } else {
        setInvestigationStatus(prev => ({ ...prev, [key]: 'error' }));
      }
    } catch {
      setInvestigationStatus(prev => ({ ...prev, [key]: 'error' }));
    } finally {
      setInvestigating(null);
    }
  };

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/admin/health-history?window_hours=24', { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        setHistory(data || {});
        setLastUpdated(new Date());
      }
    } catch (err) {
      console.error('Failed to load incident history:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  useEffect(() => {
    if (!autoRefresh) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }
    intervalRef.current = setInterval(fetchHistory, REFRESH_INTERVAL_MS);
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [autoRefresh, fetchHistory]);

  const incidents = buildIncidents(history);
  const filteredIncidents = filterStatus === 'incidents'
    ? incidents.filter(i => i.type === 'down' || i.type === 'degraded')
    : incidents;

  // Summary stats
  const services = Object.keys(history);
  const nowHealthy = services.filter(s => {
    const recent = history[s]?.recent;
    return recent && recent.length > 0 && recent[recent.length - 1]?.status === 'healthy';
  }).length;
  const totalServices = services.length;
  const activeIncidents = incidents.filter(i => i.type !== 'recovered' && i.duration === 'ongoing').length;

  // Toggle expanded service detail
  const toggleExpand = (name: string) => {
    setExpandedService(prev => prev === name ? null : name);
  };

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Activity className="w-7 h-7 text-stone-500" />
          <div>
            <h1 className="text-2xl font-semibold text-stone-900 dark:text-white">Incident Timeline</h1>
            <p className="text-sm text-stone-500">Health events and service status changes from the last 24 hours</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-stone-400 hidden sm:block">
              Updated {formatRelativeTime(lastUpdated.toISOString())}
            </span>
          )}
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`p-1.5 rounded-md transition-colors ${
              autoRefresh
                ? 'text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20'
                : 'text-stone-400 hover:bg-stone-100 dark:hover:bg-stone-700'
            }`}
            title={autoRefresh ? 'Pause auto-refresh' : 'Resume auto-refresh'}
          >
            {autoRefresh ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
          </button>
          <button
            onClick={fetchHistory}
            disabled={loading}
            className="p-1.5 rounded-md text-stone-400 hover:bg-stone-100 dark:hover:bg-stone-700 transition-colors disabled:opacity-50"
            title="Refresh now"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm text-stone-500">Services Healthy</div>
              <div className="text-3xl font-bold text-stone-900 dark:text-white mt-1">
                {nowHealthy}<span className="text-lg text-stone-400 font-normal">/{totalServices}</span>
              </div>
            </div>
            <Shield className="w-10 h-10 text-green-500 opacity-60" />
          </div>
        </div>

        <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm text-stone-500">Active Incidents</div>
              <div className={`text-3xl font-bold mt-1 ${activeIncidents > 0 ? 'text-red-600 dark:text-red-400' : 'text-stone-900 dark:text-white'}`}>
                {activeIncidents}
              </div>
            </div>
            <AlertCircle className={`w-10 h-10 opacity-60 ${activeIncidents > 0 ? 'text-red-500' : 'text-stone-400'}`} />
          </div>
        </div>

        <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm text-stone-500">Total Events (24h)</div>
              <div className="text-3xl font-bold text-stone-900 dark:text-white mt-1">
                {incidents.length}
              </div>
            </div>
            <Zap className="w-10 h-10 text-stone-400 opacity-60" />
          </div>
        </div>
      </div>

      {/* Service Uptime Overview */}
      {services.length > 0 && (
        <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm">
          <div className="p-5 border-b border-stone-200 dark:border-stone-700">
            <h2 className="text-lg font-semibold text-stone-900 dark:text-white flex items-center gap-2">
              <Server className="w-5 h-5 text-stone-500" />
              Service Uptime (24h)
            </h2>
          </div>
          <div className="p-5 space-y-3">
            {services.map(name => {
              const svc = history[name];
              const uptime = svc?.uptime;
              const recent = svc?.recent || [];
              const lastStatus = recent.length > 0 ? recent[recent.length - 1].status : 'unknown';
              const isExpanded = expandedService === name;

              return (
                <div key={name}>
                  <button
                    onClick={() => toggleExpand(name)}
                    className="w-full text-left"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className={`w-2 h-2 rounded-full ${
                          lastStatus === 'healthy' ? 'bg-green-500' :
                          lastStatus === 'degraded' ? 'bg-yellow-500' :
                          lastStatus === 'down' ? 'bg-red-500' : 'bg-stone-400'
                        }`} />
                        <span className="text-sm font-medium text-stone-700 dark:text-stone-300">{name}</span>
                        {lastStatus !== 'healthy' && (
                          <span className={`text-xs px-1.5 py-0.5 rounded ${getStatusBg(lastStatus)} ${getStatusColor(lastStatus)}`}>
                            {lastStatus}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3">
                        {uptime && uptime.uptime_pct !== null && (
                          <span className={`text-sm font-mono font-medium ${getUptimeTextColor(uptime.uptime_pct)}`}>
                            {uptime.uptime_pct}%
                          </span>
                        )}
                        {isExpanded ? <ChevronUp className="w-4 h-4 text-stone-400" /> : <ChevronDown className="w-4 h-4 text-stone-400" />}
                      </div>
                    </div>
                    {uptime && uptime.uptime_pct !== null && (
                      <div className="mt-1.5 flex items-center gap-2">
                        <div className="flex-1 h-1.5 bg-stone-100 dark:bg-stone-700 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all ${getUptimeBarColor(uptime.uptime_pct)}`}
                            style={{ width: `${uptime.uptime_pct}%` }}
                          />
                        </div>
                        <span className="text-xs text-stone-400 font-mono">
                          {uptime.healthy_count}/{uptime.total_checks} checks
                        </span>
                      </div>
                    )}
                  </button>

                  {/* Expanded detail: mini timeline */}
                  {isExpanded && recent.length > 0 && (
                    <div className="mt-3 ml-5 pl-4 border-l-2 border-stone-200 dark:border-stone-700 space-y-1">
                      {recent.slice(-10).reverse().map((entry, idx) => (
                        <div key={idx} className="flex items-center gap-2 text-xs">
                          <div className={`w-1.5 h-1.5 rounded-full ${
                            entry.status === 'healthy' ? 'bg-green-500' :
                            entry.status === 'degraded' ? 'bg-yellow-500' :
                            entry.status === 'down' ? 'bg-red-500' : 'bg-stone-400'
                          }`} />
                          <span className="text-stone-500 font-mono w-24 flex-shrink-0">
                            {formatTimestamp(entry.timestamp)}
                          </span>
                          <span className={getStatusColor(entry.status)}>{entry.status}</span>
                          {entry.latency_ms !== undefined && (
                            <span className="text-stone-400 font-mono">{entry.latency_ms}ms</span>
                          )}
                          {entry.error && (
                            <span className="text-red-400 truncate" title={entry.error}>
                              ⚠ {entry.error.slice(0, 60)}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Incident Filter Tabs */}
      <div className="flex items-center gap-2 border-b border-stone-200 dark:border-stone-700 pb-0">
        <button
          onClick={() => setFilterStatus('all')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            filterStatus === 'all'
              ? 'border-stone-900 dark:border-white text-stone-900 dark:text-white'
              : 'border-transparent text-stone-500 hover:text-stone-700 dark:hover:text-stone-300'
          }`}
        >
          All Events ({incidents.length})
        </button>
        <button
          onClick={() => setFilterStatus('incidents')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            filterStatus === 'incidents'
              ? 'border-red-500 text-red-600 dark:text-red-400'
              : 'border-transparent text-stone-500 hover:text-stone-700 dark:hover:text-stone-300'
          }`}
        >
          Incidents Only ({incidents.filter(i => i.type !== 'recovered').length})
        </button>
      </div>

      {/* Incident Timeline */}
      <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm">
        {filteredIncidents.length === 0 ? (
          <div className="p-12 text-center">
            <CheckCircle className="w-12 h-12 text-green-400 mx-auto mb-3" />
            <h3 className="text-lg font-medium text-stone-900 dark:text-white">
              {filterStatus === 'incidents' ? 'No incidents recorded' : 'No events recorded'}
            </h3>
            <p className="text-sm text-stone-500 mt-1">
              {filterStatus === 'incidents'
                ? 'All services have been healthy in the last 24 hours'
                : 'Health history data will appear here as checks run'}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-stone-200 dark:divide-stone-700">
            {filteredIncidents.map(incident => (
              <div
                key={incident.id}
                className={`p-4 hover:bg-stone-50 dark:hover:bg-stone-800/50 transition-colors ${
                  incident.type === 'down' ? 'border-l-2 border-l-red-400' :
                  incident.type === 'degraded' ? 'border-l-2 border-l-yellow-400' :
                  'border-l-2 border-l-green-400'
                }`}
              >
                <div className="flex items-start gap-3">
                  <div className="flex-shrink-0 mt-0.5">
                    <div className={`p-2 rounded-lg ${
                      incident.type === 'down' ? 'bg-red-100 dark:bg-red-900/30' :
                      incident.type === 'degraded' ? 'bg-yellow-100 dark:bg-yellow-900/30' :
                      'bg-green-100 dark:bg-green-900/30'
                    }`}>
                      {getIncidentIcon(incident.type)}
                    </div>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-stone-900 dark:text-white">
                        {incident.serviceName}
                      </span>
                      <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                        incident.type === 'down' ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400' :
                        incident.type === 'degraded' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-400' :
                        'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400'
                      }`}>
                        {incident.type === 'recovered' ? 'RECOVERED' : incident.type.toUpperCase()}
                      </span>
                      {incident.duration && (
                        <span className="text-xs text-stone-400">
                          Duration: {incident.duration}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-xs text-stone-500">
                      <span className="font-mono">{formatTimestamp(incident.timestamp)}</span>
                      <span>{formatRelativeTime(incident.timestamp)}</span>
                      {incident.latency_ms !== undefined && (
                        <span className="font-mono text-stone-400">{incident.latency_ms}ms latency</span>
                      )}
                    </div>
                    {incident.error && (
                      <div className="mt-1.5 text-xs text-red-500 dark:text-red-400 font-mono bg-red-50 dark:bg-red-900/20 rounded px-2 py-1 truncate">
                        {incident.error.slice(0, 120)}
                      </div>
                    )}
                    {/* Investigate button — only for non-recovery incidents */}
                    {incident.type !== 'recovered' && (
                      <div className="mt-2 flex items-center gap-2">
                        <button
                          onClick={() => handleInvestigate(incident)}
                          disabled={investigating === incident.id}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-stone-900 dark:bg-white text-white dark:text-stone-900 hover:bg-stone-700 dark:hover:bg-stone-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                          {investigating === incident.id ? (
                            <Loader2 className="w-3 h-3 animate-spin" />
                          ) : (
                            <Search className="w-3 h-3" />
                          )}
                          {investigating === incident.id ? 'Starting...' : 'Investigate'}
                        </button>
                        {investigationStatus[incident.id] === 'started' && (
                          <span className="inline-flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
                            <CheckCircle className="w-3 h-3" />
                            Investigation started — check Agent Runs
                          </span>
                        )}
                        {investigationStatus[incident.id] === 'error' && (
                          <span className="inline-flex items-center gap-1 text-xs text-red-500 dark:text-red-400">
                            <XCircle className="w-3 h-3" />
                            Failed to start investigation
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer note */}
      <div className="text-center text-xs text-stone-400 pt-2 pb-4">
        Showing events from the last 24 hours. Health checks run every 60 seconds.
        {autoRefresh && <span className="ml-1">Auto-refresh: 30s.</span>}
      </div>
    </div>
  );
}

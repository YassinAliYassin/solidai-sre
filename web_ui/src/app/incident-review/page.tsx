'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import {
  Search,
  Filter,
  RefreshCw,
  Pause,
  Play,
  CheckCircle,
  XCircle,
  AlertCircle,
  Clock,
  ChevronDown,
  ChevronUp,
  ArrowUp,
  ArrowDown,
  Loader2,
  FileText,
  Zap,
  Shield,
  TrendingUp,
  TrendingDown,
  Minus,
  History,
} from 'lucide-react';

// ─── Types ───────────────────────────────────────────────────────────────────

interface Episode {
  id: string;
  agent_run_id: string | null;
  org_id: string;
  team_node_id: string | null;
  alert_type: string;
  alert_description: string | null;
  severity: string | null;
  services: string[];
  agents_used: string[];
  skills_used: string[];
  key_findings: { skill: string; query: string; finding: string }[];
  resolved: boolean;
  root_cause: string | null;
  summary: string | null;
  effectiveness_score: number | null;
  confidence: number | null;
  duration_seconds: number | null;
  created_at: string | null;
}

interface MemoryStats {
  total_episodes: number;
  resolved_episodes: number;
  unresolved_episodes: number;
  strategies_count: number;
}

type SortField = 'date' | 'severity' | 'confidence' | 'duration';
type SortDir = 'asc' | 'desc';
type FilterStatus = 'all' | 'resolved' | 'unresolved';

const SEVERITY_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  warning: 2,
  medium: 3,
  low: 4,
  info: 5,
};

const REFRESH_INTERVAL_MS = 60_000;

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
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}m`;
}

function getSeverityColor(severity: string | null): string {
  switch (severity) {
    case 'critical': return 'text-red-600 dark:text-red-400';
    case 'high': return 'text-orange-600 dark:text-orange-400';
    case 'warning': return 'text-yellow-600 dark:text-yellow-400';
    case 'medium': return 'text-blue-600 dark:text-blue-400';
    case 'low': return 'text-stone-500';
    case 'info': return 'text-stone-400';
    default: return 'text-stone-500';
  }
}

function getSeverityBg(severity: string | null): string {
  switch (severity) {
    case 'critical': return 'bg-red-100 dark:bg-red-900/30';
    case 'high': return 'bg-orange-100 dark:bg-orange-900/30';
    case 'warning': return 'bg-yellow-100 dark:bg-yellow-900/30';
    case 'medium': return 'bg-blue-100 dark:bg-blue-900/30';
    case 'low': return 'bg-stone-100 dark:bg-stone-700';
    case 'info': return 'bg-stone-100 dark:bg-stone-700';
    default: return 'bg-stone-100 dark:bg-stone-700';
  }
}

function getConfidenceColor(confidence: number | null): string {
  if (confidence === null) return 'text-stone-400';
  if (confidence >= 0.7) return 'text-green-600 dark:text-green-400';
  if (confidence >= 0.4) return 'text-yellow-600 dark:text-yellow-400';
  return 'text-red-600 dark:text-red-400';
}

function getEffectivenessBar(score: number | null): { width: string; color: string } {
  if (score === null) return { width: '0%', color: 'bg-stone-300' };
  const pct = Math.round(score * 100);
  const color = score >= 0.7 ? 'bg-green-500' : score >= 0.4 ? 'bg-yellow-500' : 'bg-red-500';
  return { width: `${pct}%`, color };
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function IncidentReviewPage() {
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all');
  const [sortField, setSortField] = useState<SortField>('date');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [expandedEpisode, setExpandedEpisode] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [episodesRes, statsRes] = await Promise.all([
        fetch('/api/memory/episodes', { cache: 'no-store' }),
        fetch('/api/memory/stats', { cache: 'no-store' }),
      ]);

      if (episodesRes.ok) {
        const data = await episodesRes.json();
        setEpisodes(data.episodes || []);
      }
      if (statsRes.ok) {
        setStats(await statsRes.json());
      }
      setLastUpdated(new Date());
    } catch (err) {
      console.error('Failed to fetch incident review data:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!autoRefresh) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }
    intervalRef.current = setInterval(fetchData, REFRESH_INTERVAL_MS);
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [autoRefresh, fetchData]);

  // Filter and sort
  const filteredEpisodes = episodes
    .filter(ep => {
      if (filterStatus === 'resolved' && !ep.resolved) return false;
      if (filterStatus === 'unresolved' && ep.resolved) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        return (
          ep.alert_type.toLowerCase().includes(q) ||
          ep.services.some(s => s.toLowerCase().includes(q)) ||
          (ep.root_cause || '').toLowerCase().includes(q) ||
          (ep.summary || '').toLowerCase().includes(q) ||
          (ep.alert_description || '').toLowerCase().includes(q)
        );
      }
      return true;
    })
    .sort((a, b) => {
      const dir = sortDir === 'asc' ? 1 : -1;
      switch (sortField) {
        case 'date':
          return dir * (new Date(a.created_at || 0).getTime() - new Date(b.created_at || 0).getTime());
        case 'severity':
          return dir * ((SEVERITY_ORDER[a.severity || 'info'] ?? 5) - (SEVERITY_ORDER[b.severity || 'info'] ?? 5));
        case 'confidence':
          return dir * ((a.confidence ?? 0) - (b.confidence ?? 0));
        case 'duration':
          return dir * ((a.duration_seconds ?? 0) - (b.duration_seconds ?? 0));
        default:
          return 0;
      }
    });

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDir('desc');
    }
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return <Minus className="w-3 h-3 text-stone-300" />;
    return sortDir === 'asc'
      ? <ArrowUp className="w-3 h-3 text-stone-500" />
      : <ArrowDown className="w-3 h-3 text-stone-500" />;
  };

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <History className="w-7 h-7 text-stone-500" />
          <div>
            <h1 className="text-2xl font-semibold text-stone-900 dark:text-white">Incident Review</h1>
            <p className="text-sm text-stone-500">Past investigation episodes from the memory system</p>
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
            onClick={fetchData}
            disabled={loading}
            className="p-1.5 rounded-md text-stone-400 hover:bg-stone-100 dark:hover:bg-stone-700 transition-colors disabled:opacity-50"
            title="Refresh now"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm text-stone-500">Total Episodes</div>
                <div className="text-3xl font-bold text-stone-900 dark:text-white mt-1">
                  {stats.total_episodes}
                </div>
              </div>
              <FileText className="w-10 h-10 text-stone-400 opacity-60" />
            </div>
          </div>

          <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm text-stone-500">Resolved</div>
                <div className="text-3xl font-bold text-green-600 dark:text-green-400 mt-1">
                  {stats.resolved_episodes}
                </div>
              </div>
              <CheckCircle className="w-10 h-10 text-green-500 opacity-60" />
            </div>
          </div>

          <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm text-stone-500">Unresolved</div>
                <div className="text-3xl font-bold text-red-600 dark:text-red-400 mt-1">
                  {stats.unresolved_episodes}
                </div>
              </div>
              <XCircle className="w-10 h-10 text-red-500 opacity-60" />
            </div>
          </div>

          <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm text-stone-500">Strategies</div>
                <div className="text-3xl font-bold text-stone-900 dark:text-white mt-1">
                  {stats.strategies_count}
                </div>
              </div>
              <Zap className="w-10 h-10 text-stone-400 opacity-60" />
            </div>
          </div>
        </div>
      )}

      {/* Search and Filters */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-stone-400" />
          <input
            type="text"
            placeholder="Search by service, alert type, root cause..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 text-sm bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-lg text-stone-900 dark:text-white placeholder-stone-400 focus:outline-none focus:ring-2 focus:ring-stone-300 dark:focus:ring-stone-600"
          />
        </div>
        <div className="flex items-center gap-1 border-b-0">
          {(['all', 'resolved', 'unresolved'] as FilterStatus[]).map(status => (
            <button
              key={status}
              onClick={() => setFilterStatus(status)}
              className={`px-3 py-2 text-sm font-medium rounded-lg transition-colors ${
                filterStatus === status
                  ? 'bg-stone-900 dark:bg-white text-white dark:text-stone-900'
                  : 'text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-700'
              }`}
            >
              {status.charAt(0).toUpperCase() + status.slice(1)}
              {status === 'all' && ` (${episodes.length})`}
              {status === 'resolved' && ` (${episodes.filter(e => e.resolved).length})`}
              {status === 'unresolved' && ` (${episodes.filter(e => !e.resolved).length})`}
            </button>
          ))}
        </div>
      </div>

      {/* Episodes List */}
      <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm">
        {/* Table Header */}
        <div className="hidden sm:grid grid-cols-12 gap-4 px-5 py-3 border-b border-stone-200 dark:border-stone-700 text-xs font-medium text-stone-500 uppercase tracking-wider">
          <div className="col-span-1"></div>
          <div className="col-span-3 cursor-pointer flex items-center gap-1" onClick={() => toggleSort('date')}>
            Date <SortIcon field="date" />
          </div>
          <div className="col-span-2">Service / Alert</div>
          <div className="col-span-1 cursor-pointer flex items-center gap-1" onClick={() => toggleSort('severity')}>
            Severity <SortIcon field="severity" />
          </div>
          <div className="col-span-2">Root Cause</div>
          <div className="col-span-1 cursor-pointer flex items-center gap-1" onClick={() => toggleSort('confidence')}>
            Conf. <SortIcon field="confidence" />
          </div>
          <div className="col-span-1 cursor-pointer flex items-center gap-1" onClick={() => toggleSort('duration')}>
            Duration <SortIcon field="duration" />
          </div>
          <div className="col-span-1">Effect.</div>
        </div>

        {loading && episodes.length === 0 ? (
          <div className="p-12 text-center">
            <Loader2 className="w-8 h-8 text-stone-400 mx-auto mb-3 animate-spin" />
            <p className="text-sm text-stone-500">Loading investigation episodes...</p>
          </div>
        ) : filteredEpisodes.length === 0 ? (
          <div className="p-12 text-center">
            <Shield className="w-12 h-12 text-stone-300 mx-auto mb-3" />
            <h3 className="text-lg font-medium text-stone-900 dark:text-white">
              {episodes.length === 0 ? 'No investigation episodes yet' : 'No matching episodes'}
            </h3>
            <p className="text-sm text-stone-500 mt-1">
              {episodes.length === 0
                ? 'Episodes are created automatically when investigations complete.'
                : 'Try adjusting your search or filter criteria.'}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-stone-200 dark:divide-stone-700">
            {filteredEpisodes.map(episode => {
              const isExpanded = expandedEpisode === episode.id;
              const eff = getEffectivenessBar(episode.effectiveness_score);

              return (
                <div key={episode.id}>
                  <button
                    onClick={() => setExpandedEpisode(isExpanded ? null : episode.id)}
                    className="w-full text-left hover:bg-stone-50 dark:hover:bg-stone-800/50 transition-colors"
                  >
                    <div className="grid grid-cols-12 gap-4 px-5 py-4 items-center">
                      {/* Status icon */}
                      <div className="col-span-1 flex justify-center">
                        {episode.resolved ? (
                          <CheckCircle className="w-5 h-5 text-green-500" />
                        ) : (
                          <AlertCircle className="w-5 h-5 text-red-500" />
                        )}
                      </div>

                      {/* Date */}
                      <div className="col-span-3">
                        <div className="text-sm font-medium text-stone-900 dark:text-white">
                          {episode.created_at ? formatTimestamp(episode.created_at) : '—'}
                        </div>
                        <div className="text-xs text-stone-400">
                          {episode.created_at ? formatRelativeTime(episode.created_at) : ''}
                        </div>
                      </div>

                      {/* Service / Alert */}
                      <div className="col-span-2">
                        <div className="text-sm text-stone-700 dark:text-stone-300 truncate">
                          {episode.services.length > 0 ? episode.services.slice(0, 2).join(', ') : '—'}
                        </div>
                        <div className="text-xs text-stone-400 truncate">
                          {episode.alert_type}
                        </div>
                      </div>

                      {/* Severity */}
                      <div className="col-span-1">
                        <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${getSeverityBg(episode.severity)} ${getSeverityColor(episode.severity)}`}>
                          {episode.severity || 'info'}
                        </span>
                      </div>

                      {/* Root Cause */}
                      <div className="col-span-2 text-sm text-stone-600 dark:text-stone-400 truncate">
                        {episode.root_cause || '—'}
                      </div>

                      {/* Confidence */}
                      <div className="col-span-1">
                        <span className={`text-sm font-mono font-medium ${getConfidenceColor(episode.confidence)}`}>
                          {episode.confidence !== null ? `${Math.round(episode.confidence * 100)}%` : '—'}
                        </span>
                      </div>

                      {/* Duration */}
                      <div className="col-span-1 text-sm text-stone-500 font-mono">
                        {formatDuration(episode.duration_seconds)}
                      </div>

                      {/* Effectiveness */}
                      <div className="col-span-1">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-1.5 bg-stone-100 dark:bg-stone-700 rounded-full overflow-hidden">
                            <div className={`h-full rounded-full ${eff.color}`} style={{ width: eff.width }} />
                          </div>
                          <span className="text-xs text-stone-400 font-mono w-8 text-right">
                            {episode.effectiveness_score !== null ? `${Math.round(episode.effectiveness_score * 100)}` : '—'}
                          </span>
                        </div>
                      </div>
                    </div>
                  </button>

                  {/* Expanded Detail */}
                  {isExpanded && (
                    <div className="px-5 pb-5 border-t border-stone-100 dark:border-stone-700 bg-stone-50 dark:bg-stone-800/30">
                      <div className="pt-4 space-y-4">
                        {/* Alert Description */}
                        {episode.alert_description && (
                          <div>
                            <h4 className="text-xs font-medium text-stone-500 uppercase tracking-wider mb-1">Alert Description</h4>
                            <p className="text-sm text-stone-700 dark:text-stone-300 bg-white dark:bg-stone-800 rounded-lg p-3 border border-stone-200 dark:border-stone-700">
                              {episode.alert_description}
                            </p>
                          </div>
                        )}

                        {/* Summary */}
                        {episode.summary && (
                          <div>
                            <h4 className="text-xs font-medium text-stone-500 uppercase tracking-wider mb-1">Summary</h4>
                            <p className="text-sm text-stone-700 dark:text-stone-300 bg-white dark:bg-stone-800 rounded-lg p-3 border border-stone-200 dark:border-stone-700">
                              {episode.summary}
                            </p>
                          </div>
                        )}

                        {/* Root Cause */}
                        {episode.root_cause && (
                          <div>
                            <h4 className="text-xs font-medium text-stone-500 uppercase tracking-wider mb-1">Root Cause</h4>
                            <p className="text-sm text-stone-700 dark:text-stone-300 bg-white dark:bg-stone-800 rounded-lg p-3 border border-stone-200 dark:border-stone-700">
                              {episode.root_cause}
                            </p>
                          </div>
                        )}

                        {/* Key Findings */}
                        {episode.key_findings.length > 0 && (
                          <div>
                            <h4 className="text-xs font-medium text-stone-500 uppercase tracking-wider mb-1">Key Findings</h4>
                            <div className="space-y-2">
                              {episode.key_findings.map((f, i) => (
                                <div key={i} className="bg-white dark:bg-stone-800 rounded-lg p-3 border border-stone-200 dark:border-stone-700">
                                  <div className="text-xs font-medium text-stone-500 mb-1">{f.skill}</div>
                                  <p className="text-sm text-stone-700 dark:text-stone-300">{f.finding}</p>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Meta */}
                        <div className="flex flex-wrap gap-4 text-xs text-stone-400 pt-2">
                          <span>ID: <code className="font-mono">{episode.id.slice(0, 8)}...</code></span>
                          {episode.agent_run_id && (
                            <span>Run: <code className="font-mono">{episode.agent_run_id.slice(0, 12)}...</code></span>
                          )}
                          {episode.skills_used.length > 0 && (
                            <span>Skills: {episode.skills_used.join(', ')}</span>
                          )}
                          <span>Org: {episode.org_id}</span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="text-center text-xs text-stone-400 pt-2 pb-4">
        Showing {filteredEpisodes.length} of {episodes.length} episodes.
        {autoRefresh && <span className="ml-1">Auto-refresh: 60s.</span>}
      </div>
    </div>
  );
}

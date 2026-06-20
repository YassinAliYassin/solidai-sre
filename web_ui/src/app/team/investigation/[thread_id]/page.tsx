'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  Clock,
  CheckCircle,
  XCircle,
  AlertCircle,
  Server,
  Wrench,
  FileText,
  Loader2,
  Zap,
  Shield,
  Activity,
  ChevronDown,
  ChevronUp,
  Hash,
  Calendar,
  Timer,
  ListChecks,
  Lightbulb,
} from 'lucide-react';

interface Episode {
  id: string;
  thread_id: string;
  prompt: string;
  result_text: string;
  success: boolean;
  tool_calls: any[];
  duration_seconds: number;
  created_at: string;
  // Enriched fields from config-service
  alert_type?: string;
  alert_description?: string;
  severity?: string;
  services?: string[];
  agents_used?: string[];
  skills_used?: string[];
  key_findings?: Array<{ skill: string; query: string; finding: string }>;
  resolved?: boolean;
  root_cause?: string;
  summary?: string;
  effectiveness_score?: number;
  confidence?: number;
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  high: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
  warning: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  medium: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  low: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  info: 'bg-stone-100 text-stone-700 dark:bg-stone-700 dark:text-stone-400',
};

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

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${Math.floor(seconds % 60)}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

export default function InvestigationDetailPage() {
  const params = useParams();
  const threadId = params.thread_id as string;
  const [episode, setEpisode] = useState<Episode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    findings: true,
    tools: false,
    result: true,
  });

  const fetchEpisode = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Try fetching by thread_id first (the episode_id in the URL is actually thread_id)
      const res = await fetch(`/api/memory/episodes/${encodeURIComponent(threadId)}`);
      if (res.ok) {
        const data = await res.json();
        setEpisode(data);
      } else if (res.status === 404) {
        // Fallback: fetch all and find by thread_id
        const allRes = await fetch('/api/memory/episodes');
        if (allRes.ok) {
          const allData = await res.json();
          const found = (allData.episodes || []).find(
            (e: Episode) => e.thread_id === threadId || e.id === threadId
          );
          if (found) {
            setEpisode(found);
          } else {
            setError('Investigation not found');
          }
        } else {
          setError('Failed to load investigation');
        }
      } else {
        setError('Failed to load investigation');
      }
    } catch (e: any) {
      setError(e.message || 'Failed to load investigation');
    } finally {
      setLoading(false);
    }
  }, [threadId]);

  useEffect(() => {
    fetchEpisode();
  }, [fetchEpisode]);

  const toggleSection = (section: string) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  if (loading) {
    return (
      <div className="p-6 lg:p-8 max-w-7xl mx-auto">
        <div className="flex items-center gap-3 text-stone-500">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span>Loading investigation…</span>
        </div>
      </div>
    );
  }

  if (error || !episode) {
    return (
      <div className="p-6 lg:p-8 max-w-7xl mx-auto space-y-4">
        <Link
          href="/team/investigation-history"
          className="inline-flex items-center gap-2 text-sm text-stone-500 hover:text-stone-700 dark:hover:text-stone-300"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Investigations
        </Link>
        <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-8 text-center">
          <XCircle className="w-12 h-12 text-stone-400 mx-auto mb-3" />
          <h2 className="text-lg font-semibold text-stone-900 dark:text-white">
            {error || 'Investigation not found'}
          </h2>
          <p className="text-sm text-stone-500 mt-1">
            The investigation with ID <code className="text-xs bg-stone-100 dark:bg-stone-700 px-1 rounded">{threadId}</code> could not be loaded.
          </p>
        </div>
      </div>
    );
  }

  const severity = episode.severity || 'info';
  const services = episode.services || [];
  const skills = episode.skills_used || [];
  const findings = episode.key_findings || [];
  const toolCalls = episode.tool_calls || [];

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto space-y-6">
      {/* Back link */}
      <Link
        href="/team/investigation-history"
        className="inline-flex items-center gap-2 text-sm text-stone-500 hover:text-stone-700 dark:hover:text-stone-300"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Investigations
      </Link>

      {/* Header Card */}
      <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm p-6">
        <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
          <div className="space-y-3 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-semibold text-stone-900 dark:text-white">
                Investigation Report
              </h1>
              {episode.success ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                  <CheckCircle className="w-3 h-3" />
                  Success
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
                  <XCircle className="w-3 h-3" />
                  Failed
                </span>
              )}
              {episode.resolved && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
                  <Shield className="w-3 h-3" />
                  Resolved
                </span>
              )}
            </div>

            {/* Meta info row */}
            <div className="flex flex-wrap items-center gap-4 text-xs text-stone-500">
              <span className="flex items-center gap-1">
                <Hash className="w-3 h-3" />
                <span className="font-mono">{episode.thread_id}</span>
              </span>
              <span className="flex items-center gap-1">
                <Calendar className="w-3 h-3" />
                {new Date(episode.created_at).toLocaleString()}
              </span>
              <span className="flex items-center gap-1">
                <Timer className="w-3 h-3" />
                {formatDuration(episode.duration_seconds)}
              </span>
              <span className="flex items-center gap-1">
                <Wrench className="w-3 h-3" />
                {toolCalls.length} tool calls
              </span>
              {episode.confidence != null && (
                <span className="flex items-center gap-1">
                  <Activity className="w-3 h-3" />
                  {Math.round(episode.confidence * 100)}% confidence
                </span>
              )}
            </div>

            {/* Severity + Alert Type badges */}
            <div className="flex flex-wrap items-center gap-2">
              <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${SEVERITY_COLORS[severity] || SEVERITY_COLORS.info}`}>
                {severity.toUpperCase()}
              </span>
              {episode.alert_type && episode.alert_type !== 'unknown' && (
                <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-stone-100 text-stone-700 dark:bg-stone-700 dark:text-stone-300">
                  {episode.alert_type.replace(/_/g, ' ')}
                </span>
              )}
              {services.map(s => (
                <span key={s} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-stone-100 text-stone-700 dark:bg-stone-700 dark:text-stone-300">
                  <Server className="w-3 h-3" />
                  {s}
                </span>
              ))}
            </div>
          </div>

          {/* Time ago */}
          <div className="text-xs text-stone-400 whitespace-nowrap">
            {formatRelativeTime(episode.created_at)}
          </div>
        </div>
      </div>

      {/* Summary / Executive Summary */}
      {(episode.summary || episode.root_cause) && (
        <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm">
          <button
            onClick={() => toggleSection('findings')}
            className="w-full p-5 flex items-center justify-between"
          >
            <h2 className="text-lg font-semibold text-stone-900 dark:text-white flex items-center gap-2">
              <FileText className="w-5 h-5 text-stone-500" />
              Summary & Root Cause
            </h2>
            {expandedSections.findings ? (
              <ChevronUp className="w-5 h-5 text-stone-400" />
            ) : (
              <ChevronDown className="w-5 h-5 text-stone-400" />
            )}
          </button>
          {expandedSections.findings && (
            <div className="px-5 pb-5 space-y-4">
              {episode.summary && (
                <div>
                  <h3 className="text-sm font-medium text-stone-500 mb-1">Summary</h3>
                  <p className="text-sm text-stone-700 dark:text-stone-300 whitespace-pre-wrap">
                    {episode.summary}
                  </p>
                </div>
              )}
              {episode.root_cause && (
                <div>
                  <h3 className="text-sm font-medium text-stone-500 mb-1 flex items-center gap-1">
                    <Lightbulb className="w-4 h-4" />
                    Root Cause
                  </h3>
                  <p className="text-sm text-stone-700 dark:text-stone-300 whitespace-pre-wrap">
                    {episode.root_cause}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Key Findings from Tool Calls */}
      {findings.length > 0 && (
        <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm">
          <div className="p-5 border-b border-stone-200 dark:border-stone-700">
            <h2 className="text-lg font-semibold text-stone-900 dark:text-white flex items-center gap-2">
              <ListChecks className="w-5 h-5 text-stone-500" />
              Key Findings ({findings.length})
            </h2>
          </div>
          <div className="divide-y divide-stone-200 dark:divide-stone-700">
            {findings.map((f, i) => (
              <div key={i} className="p-5">
                <div className="flex items-center gap-2 mb-2">
                  <Zap className="w-4 h-4 text-amber-500" />
                  <span className="text-sm font-medium text-stone-900 dark:text-white">
                    {f.skill}
                  </span>
                </div>
                {f.query && (
                  <p className="text-xs text-stone-500 mb-2 font-mono bg-stone-50 dark:bg-stone-700/50 rounded px-2 py-1">
                    {f.query}
                  </p>
                )}
                <p className="text-sm text-stone-700 dark:text-stone-300 whitespace-pre-wrap">
                  {f.finding}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Skills Used */}
      {skills.length > 0 && (
        <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm p-5">
          <h2 className="text-lg font-semibold text-stone-900 dark:text-white mb-3 flex items-center gap-2">
            <Wrench className="w-5 h-5 text-stone-500" />
            Skills Used
          </h2>
          <div className="flex flex-wrap gap-2">
            {skills.map(s => (
              <span
                key={s}
                className="px-3 py-1 rounded-full text-xs font-medium bg-stone-100 text-stone-700 dark:bg-stone-700 dark:text-stone-300"
              >
                {s}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Tool Calls */}
      {toolCalls.length > 0 && (
        <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm">
          <button
            onClick={() => toggleSection('tools')}
            className="w-full p-5 flex items-center justify-between"
          >
            <h2 className="text-lg font-semibold text-stone-900 dark:text-white flex items-center gap-2">
              <Activity className="w-5 h-5 text-stone-500" />
              Tool Calls ({toolCalls.length})
            </h2>
            {expandedSections.tools ? (
              <ChevronUp className="w-5 h-5 text-stone-400" />
            ) : (
              <ChevronDown className="w-5 h-5 text-stone-400" />
            )}
          </button>
          {expandedSections.tools && (
            <div className="px-5 pb-5">
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {toolCalls.map((tc: any, i: number) => (
                  <div
                    key={i}
                    className="flex items-start gap-3 p-3 rounded-lg bg-stone-50 dark:bg-stone-700/50"
                  >
                    <div className="flex-shrink-0 mt-0.5">
                      {tc.status === 'success' || tc.tool_output ? (
                        <CheckCircle className="w-4 h-4 text-green-500" />
                      ) : tc.status === 'error' || tc.error_message ? (
                        <XCircle className="w-4 h-4 text-red-500" />
                      ) : (
                        <Clock className="w-4 h-4 text-stone-400" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-mono font-medium text-stone-900 dark:text-white">
                          {tc.tool_name}
                        </span>
                        {tc.duration_ms != null && (
                          <span className="text-[10px] text-stone-400">{tc.duration_ms}ms</span>
                        )}
                      </div>
                      {tc.tool_input && Object.keys(tc.tool_input).length > 0 && (
                        <p className="text-xs text-stone-500 mt-1 font-mono truncate">
                          {JSON.stringify(tc.tool_input).slice(0, 120)}
                        </p>
                      )}
                      {tc.error_message && (
                        <p className="text-xs text-red-400 mt-1">{tc.error_message}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Full Result Text */}
      {episode.result_text && (
        <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm">
          <button
            onClick={() => toggleSection('result')}
            className="w-full p-5 flex items-center justify-between"
          >
            <h2 className="text-lg font-semibold text-stone-900 dark:text-white flex items-center gap-2">
              <FileText className="w-5 h-5 text-stone-500" />
              Full Investigation Output
            </h2>
            {expandedSections.result ? (
              <ChevronUp className="w-5 h-5 text-stone-400" />
            ) : (
              <ChevronDown className="w-5 h-5 text-stone-400" />
            )}
          </button>
          {expandedSections.result && (
            <div className="px-5 pb-5">
              <pre className="text-sm text-stone-700 dark:text-stone-300 whitespace-pre-wrap bg-stone-50 dark:bg-stone-700/50 rounded-lg p-4 overflow-x-auto max-h-[600px] overflow-y-auto">
                {episode.result_text}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Original Prompt */}
      <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm p-5">
        <h2 className="text-sm font-semibold text-stone-500 mb-2">Original Prompt</h2>
        <p className="text-sm text-stone-700 dark:text-stone-300 whitespace-pre-wrap bg-stone-50 dark:bg-stone-700/50 rounded-lg p-4">
          {episode.prompt}
        </p>
      </div>
    </div>
  );
}

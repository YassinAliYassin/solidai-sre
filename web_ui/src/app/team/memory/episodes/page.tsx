'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { ArrowLeft, CheckCircle, XCircle, Clock, ExternalLink, Trash2, AlertTriangle } from 'lucide-react';

interface Episode {
  id: string;
  agent_run_id: string | null;
  alert_type: string | null;
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

const severityColors: Record<string, string> = {
  critical: 'bg-clay-light/15 text-clay-dark dark:bg-clay/20 dark:text-clay-light',
  warning: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  info: 'bg-forest-light/15 text-forest-dark dark:bg-forest/30 dark:text-forest-light',
};

export default function EpisodesPage() {
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [loading, setLoading] = useState(true);
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [cleanupResult, setCleanupResult] = useState<{deleted: number; matched: number; dry_run: boolean} | null>(null);
  const [showCleanupConfirm, setShowCleanupConfirm] = useState(false);

  useEffect(() => {
    fetchEpisodes();
  }, []);

  const fetchEpisodes = () => {
    setLoading(true);
    fetch('/api/memory/episodes')
      .then(r => r.json())
      .then(data => setEpisodes(data.episodes || []))
      .catch(() => setEpisodes([]))
      .finally(() => setLoading(false));
  };

  const handleCleanup = async (dryRun: boolean) => {
    setCleanupLoading(true);
    setCleanupResult(null);
    try {
      const res = await fetch('/api/memory/episodes/cleanup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          older_than_hours: 1,
          alert_type: 'health_check',
          dry_run: dryRun,
        }),
      });
      const data = await res.json();
      setCleanupResult({ deleted: data.deleted || 0, matched: data.matched || 0, dry_run: dryRun });
      if (!dryRun) {
        // Refresh the list after actual cleanup
        fetchEpisodes();
      }
    } catch (e: any) {
      setCleanupResult({ deleted: 0, matched: 0, dry_run: dryRun });
    } finally {
      setCleanupLoading(false);
      setShowCleanupConfirm(false);
    }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <Link href="/team/memory" className="text-stone-400 hover:text-stone-600">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <h1 className="text-2xl font-bold">Investigation Episodes</h1>
      </div>

      {/* Cleanup Section */}
      <div className="mb-6 bg-white dark:bg-stone-700 rounded-lg border p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-stone-700 dark:text-stone-300">Episode Cleanup</h2>
            <p className="text-xs text-stone-500 mt-0.5">
              Remove old health-check test episodes to keep the memory store clean.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {cleanupResult && (
              <span className={`text-xs px-2 py-1 rounded ${
                cleanupResult.dry_run
                  ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'
                  : 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
              }`}>
                {cleanupResult.dry_run
                  ? `Would delete ${cleanupResult.matched} episodes`
                  : `Deleted ${cleanupResult.deleted} episodes`
                }
              </span>
            )}
            <button
              onClick={() => setShowCleanupConfirm(true)}
              disabled={cleanupLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-clay-light/10 text-clay-dark dark:bg-clay/20 dark:text-clay-light hover:bg-clay-light/20 dark:hover:bg-clay/30 transition-colors disabled:opacity-50"
            >
              <Trash2 className="w-3.5 h-3.5" />
              {cleanupLoading ? 'Cleaning...' : 'Cleanup Test Episodes'}
            </button>
          </div>
        </div>

        {/* Confirmation dialog */}
        {showCleanupConfirm && (
          <div className="mt-3 p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg border border-yellow-200 dark:border-yellow-800">
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-yellow-600 dark:text-yellow-400 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-xs text-yellow-800 dark:text-yellow-300 mb-2">
                  This will permanently delete health-check episodes older than 1 hour.
                  Real investigation episodes are not affected.
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleCleanup(true)}
                    className="px-2.5 py-1 text-xs rounded bg-yellow-200 text-yellow-800 dark:bg-yellow-800 dark:text-yellow-200 hover:bg-yellow-300 dark:hover:bg-yellow-700"
                  >
                    Dry Run
                  </button>
                  <button
                    onClick={() => handleCleanup(false)}
                    className="px-2.5 py-1 text-xs rounded bg-clay text-white hover:bg-clay-dark"
                  >
                    Delete
                  </button>
                  <button
                    onClick={() => setShowCleanupConfirm(false)}
                    className="px-2.5 py-1 text-xs rounded bg-stone-200 text-stone-700 dark:bg-stone-600 dark:text-stone-300 hover:bg-stone-300 dark:hover:bg-stone-500"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {loading ? (
        <div className="text-stone-500">Loading episodes...</div>
      ) : episodes.length === 0 ? (
        <div className="text-center py-12 text-stone-500">
          <p className="text-lg mb-2">No episodes stored yet</p>
          <p className="text-sm">Episodes are created automatically after investigations.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {episodes.map(ep => (
            <div
              key={ep.id}
              className="bg-white dark:bg-stone-700 rounded-lg border p-4"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    {ep.resolved ? (
                      <CheckCircle className="w-4 h-4 text-green-500 flex-shrink-0" />
                    ) : (
                      <XCircle className="w-4 h-4 text-clay flex-shrink-0" />
                    )}
                    {ep.severity && (
                      <span className={`text-xs px-2 py-0.5 rounded-full ${severityColors[ep.severity] || 'bg-stone-100 text-stone-700'}`}>
                        {ep.severity}
                      </span>
                    )}
                    <span className="text-stone-500 text-sm">{ep.alert_type || 'unknown'}</span>
                    {ep.agent_run_id && (
                      <Link
                        href={`/team/runs/${ep.agent_run_id}`}
                        className="text-purple-500 hover:text-purple-700"
                        title="View agent run"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                      </Link>
                    )}
                  </div>

                  {ep.services.length > 0 && (
                    <div className="flex gap-1.5 mb-2 flex-wrap">
                      {ep.services.map(s => (
                        <span key={s} className="text-xs bg-stone-100 dark:bg-stone-700 px-2 py-0.5 rounded">
                          {s}
                        </span>
                      ))}
                    </div>
                  )}

                  {ep.summary && (
                    <p className="text-sm text-stone-600 dark:text-stone-300 mb-2">
                      {ep.summary}
                    </p>
                  )}

                  {ep.root_cause && (
                    <p className="text-sm text-stone-500 dark:text-stone-400 mb-2">
                      <span className="font-medium">Root cause:</span> {ep.root_cause}
                    </p>
                  )}

                  {ep.skills_used.length > 0 && (
                    <div className="flex gap-1.5 mb-2 flex-wrap">
                      {ep.skills_used.map(s => (
                        <span key={s} className="text-xs bg-purple-50 dark:bg-purple-900/20 text-purple-600 dark:text-purple-400 px-2 py-0.5 rounded">
                          {s}
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="flex items-center gap-3 mt-2 text-xs text-stone-400">
                    {ep.duration_seconds != null && (
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {ep.duration_seconds < 60
                          ? `${ep.duration_seconds.toFixed(0)}s`
                          : `${(ep.duration_seconds / 60).toFixed(1)}m`}
                      </span>
                    )}
                    {ep.effectiveness_score != null && (
                      <span>Effectiveness: {(ep.effectiveness_score * 100).toFixed(0)}%</span>
                    )}
                    {ep.created_at && (
                      <span>{new Date(ep.created_at).toLocaleString()}</span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import { useIdentity } from "@/lib/useIdentity";
import {
  Loader2,
  Paperclip,
  Search,
  Filter,
  ArrowUpDown,
  ChevronDown,
  ChevronUp,
  CheckCircle,
  XCircle,
  Clock,
  Zap,
  Calendar,
  Timer,
  Hash,
  Eye,
  Trash2,
  AlertTriangle,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";

// ── Types ──────────────────────────────────────────────────────────────────

interface Episode {
  thread_id: string;
  prompt: string;
  result_text: string;
  success: boolean;
  tool_calls: any[];
  duration_seconds: number;
  created_at: string;
}

type SortField = "date" | "duration" | "tools";
type SortDir = "asc" | "desc";
type FilterStatus = "all" | "success" | "failure";

// ── Helpers ────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

function formatRelativeTime(iso: string): string {
  try {
    const now = Date.now();
    const then = new Date(iso).getTime();
    const diff = now - then;
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (seconds < 60) return "just now";
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    if (days < 30) return `${days}d ago`;
    return `${Math.floor(days / 30)}mo ago`;
  } catch {
    return "—";
  }
}

function formatDuration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

function truncate(str: string, len: number): string {
  if (str.length <= len) return str;
  return str.slice(0, len) + "…";
}

// ── Tool Call Summary ──────────────────────────────────────────────────────

function ToolCallSummary({ toolCalls }: { toolCalls: any[] }) {
  const counts: Record<string, number> = {};
  for (const tc of toolCalls) {
    const name = tc?.name || tc?.tool || tc?.function?.name || "unknown";
    counts[name] = (counts[name] || 0) + 1;
  }
  const entries = Object.entries(counts);

  if (entries.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {entries.map(([name, count]) => (
        <span
          key={name}
          className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-full bg-stone-100 dark:bg-stone-700 text-stone-600 dark:text-stone-300"
        >
          <Zap className="w-2.5 h-2.5" />
          {name}
          {count > 1 && (
            <span className="text-stone-400">×{count}</span>
          )}
        </span>
      ))}
    </div>
  );
}

// ── Episode Card ───────────────────────────────────────────────────────────

function EpisodeCard({
  episode,
  index,
  expanded,
  onToggle,
}: {
  episode: Episode;
  index: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  const brief = episode.result_text.replace(/\n/g, " ").slice(0, 200);
  const hasMore = episode.result_text.length > 200;

  return (
    <div
      className={`border rounded-xl transition-all ${
        episode.success
          ? "border-stone-200 dark:border-stone-700 bg-white dark:bg-stone-800"
          : "border-red-200 dark:border-red-900 bg-red-50/30 dark:bg-red-950/10"
      } hover:shadow-md`}
    >
      {/* Header row */}
      <button
        onClick={onToggle}
        className="w-full text-left p-4 flex items-start gap-3"
      >
        {/* Status icon */}
        <div className="mt-0.5 shrink-0">
          {episode.success ? (
            <CheckCircle className="w-5 h-5 text-emerald-500" />
          ) : (
            <XCircle className="w-5 h-5 text-red-500" />
          )}
        </div>

        {/* Main content */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-sm text-stone-900 dark:text-white">
              #{index + 1}
            </span>
            <span className="text-xs text-stone-400 flex items-center gap-1">
              <Calendar className="w-3 h-3" />
              {formatDate(episode.created_at)}
            </span>
            <span className="text-xs text-stone-400">
              ({formatRelativeTime(episode.created_at)})
            </span>
          </div>

          {/* Prompt preview */}
          <p className="text-sm text-stone-600 dark:text-stone-300 mt-1 line-clamp-2">
            {truncate(episode.prompt, 150)}
          </p>

          {/* Stats row */}
          <div className="flex items-center gap-3 mt-2 text-xs text-stone-500">
            <span className="flex items-center gap-1">
              <Hash className="w-3 h-3" />
              <span className="font-mono">{episode.thread_id.slice(0, 12)}…</span>
            </span>
            <span className="flex items-center gap-1">
              <Timer className="w-3 h-3" />
              {formatDuration(episode.duration_seconds)}
            </span>
            <span className="flex items-center gap-1">
              <Paperclip className="w-3 h-3" />
              {episode.tool_calls.length} tool calls
            </span>
            {!episode.success && (
              <span className="inline-flex items-center gap-1 text-red-600 dark:text-red-400 font-medium">
                <AlertTriangle className="w-3 h-3" />
                Failed
              </span>
            )}
          </div>

          {/* Tool call summary */}
          <ToolCallSummary toolCalls={episode.tool_calls} />
        </div>

        {/* Expand / View */}
        <div className="flex items-center gap-2 shrink-0">
          <Link
            href={`/team/investigation/${episode.thread_id}`}
            onClick={(e) => e.stopPropagation()}
            className="text-xs text-forest hover:underline flex items-center gap-1 px-2 py-1 rounded-md hover:bg-stone-100 dark:hover:bg-stone-700 transition-colors"
          >
            <Eye className="w-3 h-3" />
            View
          </Link>
          {expanded ? (
            <ChevronUp className="w-4 h-4 text-stone-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-stone-400" />
          )}
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 pt-0 border-t border-stone-100 dark:border-stone-700/50 mt-0">
          <div className="pt-3 space-y-3">
            {/* Full prompt */}
            <div>
              <div className="text-xs font-semibold text-stone-500 dark:text-stone-400 uppercase tracking-wider mb-1">
                Prompt
              </div>
              <p className="text-sm text-stone-700 dark:text-stone-300 bg-stone-50 dark:bg-stone-900/50 rounded-lg p-3 whitespace-pre-wrap">
                {episode.prompt}
              </p>
            </div>

            {/* Result */}
            <div>
              <div className="text-xs font-semibold text-stone-500 dark:text-stone-400 uppercase tracking-wider mb-1">
                Result
              </div>
              <p className="text-sm text-stone-700 dark:text-stone-300 bg-stone-50 dark:bg-stone-900/50 rounded-lg p-3 whitespace-pre-wrap">
                {episode.result_text || "(no result)"}
              </p>
            </div>

            {/* Tool calls detail */}
            {episode.tool_calls.length > 0 && (
              <div>
                <div className="text-xs font-semibold text-stone-500 dark:text-stone-400 uppercase tracking-wider mb-1">
                  Tool Calls ({episode.tool_calls.length})
                </div>
                <div className="space-y-1.5 max-h-48 overflow-y-auto">
                  {episode.tool_calls.map((tc, i) => {
                    const name =
                      tc?.name || tc?.tool || tc?.function?.name || "unknown";
                    const args = tc?.arguments || tc?.args || tc?.function?.arguments;
                    return (
                      <div
                        key={i}
                        className="text-xs font-mono bg-stone-50 dark:bg-stone-900/50 rounded px-3 py-2 flex items-start gap-2"
                      >
                        <span className="text-stone-400 shrink-0">{i + 1}.</span>
                        <span className="text-forest font-semibold shrink-0">
                          {name}
                        </span>
                        {args && (
                          <span className="text-stone-500 truncate">
                            {typeof args === "string" ? args : JSON.stringify(args)}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function InvestigationHistoryPage() {
  const { identity, loading } = useIdentity();
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [loadingEpisodes, setLoadingEpisodes] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Search, filter, sort
  const [search, setSearch] = useState("");
  const [filterStatus, setFilterStatus] = useState<FilterStatus>("all");
  const [sortField, setSortField] = useState<SortField>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Pagination
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 10;

  const fetchEpisodes = useCallback(async () => {
    setLoadingEpisodes(true);
    setError(null);
    try {
      const res = await fetch("/api/memory/episodes");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setEpisodes(data.episodes || []);
    } catch (e: any) {
      setError(e.message || "Failed to load investigations");
    } finally {
      setLoadingEpisodes(false);
    }
  }, []);

  useEffect(() => {
    if (!loading) fetchEpisodes();
  }, [loading, fetchEpisodes]);

  // Filtered + sorted episodes
  const filtered = useMemo(() => {
    let result = [...episodes];

    // Filter by status
    if (filterStatus === "success") {
      result = result.filter((e) => e.success);
    } else if (filterStatus === "failure") {
      result = result.filter((e) => !e.success);
    }

    // Search
    const q = search.toLowerCase().trim();
    if (q) {
      result = result.filter(
        (e) =>
          e.thread_id.toLowerCase().includes(q) ||
          e.prompt.toLowerCase().includes(q) ||
          e.result_text.toLowerCase().includes(q)
      );
    }

    // Sort
    result.sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "date":
          cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
          break;
        case "duration":
          cmp = a.duration_seconds - b.duration_seconds;
          break;
        case "tools":
          cmp = a.tool_calls.length - b.tool_calls.length;
          break;
      }
      return sortDir === "desc" ? -cmp : cmp;
    });

    return result;
  }, [episodes, search, filterStatus, sortField, sortDir]);

  // Paginated
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // Stats
  const totalEpisodes = episodes.length;
  const successCount = episodes.filter((e) => e.success).length;
  const failureCount = totalEpisodes - successCount;
  const avgDuration =
    totalEpisodes > 0
      ? episodes.reduce((sum, e) => sum + e.duration_seconds, 0) / totalEpisodes
      : 0;

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("desc");
    }
    setPage(1);
  };

  if (loading) {
    return (
      <div className="p-6 lg:p-8 max-w-7xl mx-auto flex items-center gap-3">
        <Loader2 className="animate-spin text-stone-400" />
        <span className="text-stone-500">Loading…</span>
      </div>
    );
  }

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-stone-900 dark:text-white">
            Investigation History
          </h1>
          <p className="text-sm text-stone-500 mt-0.5">
            {totalEpisodes} investigation{totalEpisodes !== 1 ? "s" : ""} recorded in memory
          </p>
        </div>
        <button
          onClick={fetchEpisodes}
          disabled={loadingEpisodes}
          className="p-2 rounded-lg text-stone-400 hover:bg-stone-100 dark:hover:bg-stone-700 transition-colors disabled:opacity-50"
          title="Refresh"
        >
          <RefreshCw className={`w-4 h-4 ${loadingEpisodes ? "animate-spin" : ""}`} />
        </button>
      </div>

      {/* Stats Cards */}
      {totalEpisodes > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-4">
            <div className="text-xs text-stone-500">Total</div>
            <div className="text-2xl font-bold text-stone-900 dark:text-white mt-0.5">
              {totalEpisodes}
            </div>
          </div>
          <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-4">
            <div className="text-xs text-stone-500">Successful</div>
            <div className="text-2xl font-bold text-emerald-600 dark:text-emerald-400 mt-0.5">
              {successCount}
            </div>
          </div>
          <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-4">
            <div className="text-xs text-stone-500">Failed</div>
            <div className="text-2xl font-bold text-red-600 dark:text-red-400 mt-0.5">
              {failureCount}
            </div>
          </div>
          <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-4">
            <div className="text-xs text-stone-500">Avg Duration</div>
            <div className="text-2xl font-bold text-stone-900 dark:text-white mt-0.5">
              {formatDuration(avgDuration)}
            </div>
          </div>
        </div>
      )}

      {/* Search + Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        {/* Search */}
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-stone-400" />
          <input
            type="text"
            placeholder="Search by thread ID, prompt, or result…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="w-full pl-9 pr-4 py-2.5 text-sm rounded-xl border border-stone-200 dark:border-stone-700 bg-white dark:bg-stone-800 text-stone-900 dark:text-white placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-forest"
          />
        </div>

        {/* Status filter */}
        <div className="flex items-center gap-1 bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl p-1">
          {(["all", "success", "failure"] as FilterStatus[]).map((status) => (
            <button
              key={status}
              onClick={() => {
                setFilterStatus(status);
                setPage(1);
              }}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                filterStatus === status
                  ? "bg-forest text-white"
                  : "text-stone-500 hover:text-stone-700 dark:hover:text-stone-300"
              }`}
            >
              {status === "all"
                ? `All (${totalEpisodes})`
                : status === "success"
                  ? `Success (${successCount})`
                  : `Failed (${failureCount})`}
            </button>
          ))}
        </div>
      </div>

      {/* Sort controls */}
      {filtered.length > 0 && (
        <div className="flex items-center gap-2 text-xs text-stone-500">
          <ArrowUpDown className="w-3.5 h-3.5" />
          <span>Sort by:</span>
          {(["date", "duration", "tools"] as SortField[]).map((field) => (
            <button
              key={field}
              onClick={() => toggleSort(field)}
              className={`px-2 py-1 rounded-md transition-colors ${
                sortField === field
                  ? "bg-stone-200 dark:bg-stone-700 text-stone-900 dark:text-white font-medium"
                  : "hover:bg-stone-100 dark:hover:bg-stone-700"
              }`}
            >
              {field === "date"
                ? "Date"
                : field === "duration"
                  ? "Duration"
                  : "Tool Calls"}
              {sortField === field && (
                <span className="ml-1">
                  {sortDir === "desc" ? "↓" : "↑"}
                </span>
              )}
            </button>
          ))}
          <span className="ml-auto text-stone-400">
            {filtered.length} result{filtered.length !== 1 ? "s" : ""}
          </span>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/20 p-4 flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 text-red-500 shrink-0" />
          <div>
            <div className="text-sm font-medium text-red-700 dark:text-red-400">
              Failed to load investigations
            </div>
            <div className="text-xs text-red-500 mt-0.5">{error}</div>
          </div>
        </div>
      )}

      {/* Loading */}
      {loadingEpisodes && (
        <div className="flex items-center gap-3 py-12 justify-center">
          <Loader2 className="animate-spin text-stone-400" />
          <span className="text-stone-500">Loading investigations…</span>
        </div>
      )}

      {/* Empty state */}
      {!loadingEpisodes && !error && filtered.length === 0 && (
        <div className="text-center py-16">
          {search || filterStatus !== "all" ? (
            <>
              <Filter className="w-10 h-10 text-stone-300 dark:text-stone-600 mx-auto mb-3" />
              <p className="text-stone-500 font-medium">No matching investigations</p>
              <p className="text-sm text-stone-400 mt-1">
                Try adjusting your search or filter criteria
              </p>
            </>
          ) : (
            <>
              <Clock className="w-10 h-10 text-stone-300 dark:text-stone-600 mx-auto mb-3" />
              <p className="text-stone-500 font-medium">No investigations yet</p>
              <p className="text-sm text-stone-400 mt-1">
                Run an investigation from the agent to see it here
              </p>
            </>
          )}
        </div>
      )}

      {/* Episode list */}
      {!loadingEpisodes && paginated.length > 0 && (
        <div className="space-y-3">
          {paginated.map((episode, i) => (
            <EpisodeCard
              key={episode.thread_id}
              episode={episode}
              index={(page - 1) * PAGE_SIZE + i}
              expanded={expandedId === episode.thread_id}
              onToggle={() =>
                setExpandedId((prev) =>
                  prev === episode.thread_id ? null : episode.thread_id
                )
              }
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-stone-200 dark:border-stone-700 text-stone-600 dark:text-stone-300 hover:bg-stone-50 dark:hover:bg-stone-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Previous
          </button>
          {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
            <button
              key={p}
              onClick={() => setPage(p)}
              className={`w-8 h-8 text-xs font-medium rounded-lg transition-colors ${
                p === page
                  ? "bg-forest text-white"
                  : "text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-700"
              }`}
            >
              {p}
            </button>
          ))}
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-stone-200 dark:border-stone-700 text-stone-600 dark:text-stone-300 hover:bg-stone-50 dark:hover:bg-stone-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

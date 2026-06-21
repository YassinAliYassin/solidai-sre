'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  Send,
  Square,
  Loader2,
  CheckCircle,
  XCircle,
  AlertCircle,
  Zap,
  Wrench,
  Brain,
  Clock,
  ChevronDown,
  ChevronRight,
  Terminal,
  Activity,
  Trash2,
  Copy,
  Check,
} from 'lucide-react';

// ── Types ──────────────────────────────────────────────────────────────────

interface StreamEvent {
  type: string;
  data: Record<string, any>;
  thread_id?: string;
  timestamp?: string;
}

interface ToolCallRecord {
  id: string;
  tool_name: string;
  tool_input?: Record<string, any>;
  tool_output?: string;
  status: 'running' | 'success' | 'error';
  duration_ms?: number;
  error_message?: string;
  started_at?: string;
}

interface ThoughtRecord {
  text: string;
  ts?: string;
  agent?: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function formatDuration(ms?: number) {
  if (!ms) return '';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatTimestamp(ts?: string) {
  if (!ts) return '';
  try {
    return new Date(ts).toLocaleTimeString();
  } catch {
    return ts;
  }
}

function getToolSummary(tc: ToolCallRecord): string | null {
  const input = tc.tool_input;
  if (!input) return null;
  const firstVal = Object.values(input).find((v) => typeof v === 'string');
  return firstVal ? String(firstVal).substring(0, 120) : null;
}

// ── Components ─────────────────────────────────────────────────────────────

function ThoughtBlock({ thought }: { thought: ThoughtRecord }) {
  return (
    <div className="flex gap-3 py-2 px-4">
      <Brain className="w-4 h-4 text-purple-500 mt-0.5 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-stone-600 dark:text-stone-400 italic whitespace-pre-wrap">
          {thought.text}
        </p>
        {thought.ts && (
          <span className="text-[10px] text-stone-400 mt-1 block">
            {formatTimestamp(thought.ts)}
          </span>
        )}
      </div>
    </div>
  );
}

function ToolCallCard({
  call,
  isExpanded,
  onToggle,
}: {
  call: ToolCallRecord;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="border-b border-stone-100 dark:border-stone-700 last:border-b-0">
      <div
        className="flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-stone-50 dark:hover:bg-stone-800/50"
        onClick={onToggle}
      >
        <div className="flex-shrink-0">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-stone-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-stone-400" />
          )}
        </div>
        <div className="flex-shrink-0">
          {call.status === 'running' ? (
            <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
          ) : call.status === 'success' ? (
            <CheckCircle className="w-4 h-4 text-green-500" />
          ) : (
            <XCircle className="w-4 h-4 text-red-500" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-stone-900 dark:text-white">
              {call.tool_name}
            </span>
            {call.duration_ms != null && (
              <span className="text-[10px] text-stone-400">
                {formatDuration(call.duration_ms)}
              </span>
            )}
          </div>
          {getToolSummary(call) && (
            <p className="text-xs text-stone-500 font-mono truncate mt-0.5">
              {getToolSummary(call)}
            </p>
          )}
        </div>
        <Wrench className="w-3.5 h-3.5 text-stone-400 flex-shrink-0" />
      </div>

      {isExpanded && call.tool_input && Object.keys(call.tool_input).length > 0 && (
        <div className="px-4 pb-3 bg-stone-50 dark:bg-stone-900/50 border-t border-stone-100 dark:border-stone-700">
          <div className="mt-2">
            <div className="text-[10px] font-medium text-stone-400 mb-1 uppercase tracking-wider">
              Input
            </div>
            <pre className="text-xs bg-white dark:bg-stone-800 p-2 rounded border border-stone-200 dark:border-stone-600 overflow-x-auto font-mono text-stone-700 dark:text-stone-300 max-h-40 overflow-y-auto">
              {JSON.stringify(call.tool_input, null, 2)}
            </pre>
          </div>
          {call.tool_output && (
            <div className="mt-2">
              <div className="text-[10px] font-medium text-stone-400 mb-1 uppercase tracking-wider">
                Output
              </div>
              <pre className="text-xs bg-white dark:bg-stone-800 p-2 rounded border border-stone-200 dark:border-stone-600 overflow-x-auto font-mono text-stone-700 dark:text-stone-300 max-h-48 overflow-y-auto">
                {typeof call.tool_output === 'string'
                  ? call.tool_output
                  : JSON.stringify(call.tool_output, null, 2)}
              </pre>
            </div>
          )}
          {call.error_message && (
            <div className="mt-2">
              <div className="text-[10px] font-medium text-red-400 mb-1 uppercase tracking-wider">
                Error
              </div>
              <pre className="text-xs bg-red-50 dark:bg-red-900/20 p-2 rounded border border-red-200 dark:border-red-800 font-mono text-red-600 dark:text-red-400">
                {call.error_message}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ResultBlock({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm">
      <div className="flex items-center justify-between px-5 py-3 border-b border-stone-200 dark:border-stone-700">
        <h3 className="text-sm font-semibold text-stone-900 dark:text-white flex items-center gap-2">
          <CheckCircle className="w-4 h-4 text-green-500" />
          Investigation Result
        </h3>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 text-xs text-stone-500 hover:text-stone-700 dark:hover:text-stone-300"
        >
          {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="p-5 text-sm text-stone-700 dark:text-stone-300 whitespace-pre-wrap max-h-[500px] overflow-y-auto">
        {text}
      </pre>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function LiveInvestigationPage() {
  const [prompt, setPrompt] = useState('');
  const [threadId, setThreadId] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [thoughts, setThoughts] = useState<ThoughtRecord[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCallRecord[]>([]);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedCalls, setExpandedCalls] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<'idle' | 'connecting' | 'running' | 'completed' | 'error'>('idle');
  const [eventCount, setEventCount] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const toolCallMapRef = useRef<Map<string, ToolCallRecord>>(new Map());

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [thoughts, toolCalls, result]);

  // Elapsed timer
  useEffect(() => {
    if (isRunning) {
      timerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isRunning]);

  const formatElapsed = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  const resetState = () => {
    setThoughts([]);
    setToolCalls([]);
    setResult(null);
    setError(null);
    setExpandedCalls(new Set());
    setStatus('idle');
    setEventCount(0);
    setElapsed(0);
    toolCallMapRef.current.clear();
  };

  const handleSubmit = useCallback(async () => {
    if (!prompt.trim() || isRunning) return;

    resetState();
    setIsRunning(true);
    setStatus('connecting');

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch('/api/investigate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: prompt.trim(),
          thread_id: threadId,
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        throw new Error(`Server returned ${res.status}`);
      }

      setStatus('running');

      const reader = res.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Process complete SSE messages from buffer
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || ''; // Keep the incomplete chunk

        for (const line of lines) {
          if (!line.trim()) continue;

          // Parse SSE data lines
          const dataLines = line.split('\n').filter((l) => l.startsWith('data: '));
          for (const dataLine of dataLines) {
            const jsonStr = dataLine.replace(/^data: /, '').trim();
            if (!jsonStr || jsonStr === ': ping') continue;

            try {
              const event: StreamEvent = JSON.parse(jsonStr);
              setEventCount((c) => c + 1);

              if (event.thread_id && !threadId) {
                setThreadId(event.thread_id);
              }

              switch (event.type) {
                case 'thought': {
                  const text = event.data?.text || event.data?.content || '';
                  if (text) {
                    setThoughts((prev) => [
                      ...prev,
                      { text, ts: event.timestamp, agent: event.data?.agent },
                    ]);
                  }
                  break;
                }
                case 'tool_call': {
                  const tc: ToolCallRecord = {
                    id: event.data?.id || `tc-${Date.now()}`,
                    tool_name: event.data?.tool_name || event.data?.name || 'unknown',
                    tool_input: event.data?.tool_input || event.data?.input,
                    tool_output: event.data?.tool_output || event.data?.output,
                    status: event.data?.status || 'running',
                    duration_ms: event.data?.duration_ms,
                    error_message: event.data?.error_message,
                    started_at: event.timestamp,
                  };
                  toolCallMapRef.current.set(tc.id, tc);
                  setToolCalls((prev) => {
                    const idx = prev.findIndex((p) => p.id === tc.id);
                    if (idx >= 0) {
                      const next = [...prev];
                      next[idx] = tc;
                      return next;
                    }
                    return [...prev, tc];
                  });
                  break;
                }
                case 'result': {
                  const text = event.data?.text || event.data?.content || event.data?.result || '';
                  if (text) setResult(text);
                  setStatus('completed');
                  break;
                }
                case 'error': {
                  setError(event.data?.message || 'Unknown error');
                  setStatus('error');
                  break;
                }
                case 'done': {
                  setStatus('completed');
                  break;
                }
              }
            } catch {
              // Skip malformed JSON
            }
          }
        }
      }
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        setStatus('idle');
      } else {
        setError(e?.message || 'Investigation failed');
        setStatus('error');
      }
    } finally {
      setIsRunning(false);
      abortRef.current = null;
    }
  }, [prompt, threadId, isRunning]);

  const handleStop = () => {
    abortRef.current?.abort();
    setIsRunning(false);
    setStatus('idle');
  };

  const handleClear = () => {
    resetState();
    setThreadId(null);
    setPrompt('');
    textareaRef.current?.focus();
  };

  const toggleCall = (id: string) => {
    setExpandedCalls((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const statusConfig = {
    idle: { color: 'bg-stone-400', text: 'Ready' },
    connecting: { color: 'bg-yellow-400', text: 'Connecting…' },
    running: { color: 'bg-green-500', text: 'Running' },
    completed: { color: 'bg-blue-500', text: 'Completed' },
    error: { color: 'bg-red-500', text: 'Error' },
  };

  const sc = statusConfig[status];

  return (
    <div className="p-4 lg:p-6 max-w-6xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            href="/team"
            className="text-stone-500 hover:text-stone-700 dark:hover:text-stone-300"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-xl font-semibold text-stone-900 dark:text-white">
              Live Investigation
            </h1>
            <p className="text-xs text-stone-500">
              Real-time SRE investigation with streaming agent output
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {threadId && (
            <span className="text-xs text-stone-400 font-mono">
              Thread: {threadId}
            </span>
          )}
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${sc.color} ${status === 'running' ? 'animate-pulse' : ''}`} />
            <span className="text-xs text-stone-500">{sc.text}</span>
          </div>
          {isRunning && (
            <span className="text-xs text-stone-400 font-mono">
              {formatElapsed(elapsed)} · {eventCount} events
            </span>
          )}
        </div>
      </div>

      {/* Input Area */}
      <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm">
        <div className="p-4">
          <textarea
            ref={textareaRef}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Describe the incident or issue to investigate…&#10;&#10;Example: The solidsolutions.africa site is returning 502 errors. Investigate the root cause."
            className="w-full resize-none border-0 bg-transparent text-sm text-stone-900 dark:text-white placeholder:text-stone-400 focus:outline-none focus:ring-0 min-h-[100px]"
            disabled={isRunning}
            rows={4}
          />
        </div>
        <div className="flex items-center justify-between px-4 py-3 border-t border-stone-100 dark:border-stone-700">
          <div className="flex items-center gap-2 text-xs text-stone-400">
            <Terminal className="w-3.5 h-3.5" />
            <span>Ctrl+Enter to send</span>
          </div>
          <div className="flex items-center gap-2">
            {(thoughts.length > 0 || toolCalls.length > 0 || result) && (
              <button
                onClick={handleClear}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-stone-500 hover:text-stone-700 dark:hover:text-stone-300 border border-stone-200 dark:border-stone-600 rounded-lg hover:bg-stone-50 dark:hover:bg-stone-700"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Clear
              </button>
            )}
            {isRunning ? (
              <button
                onClick={handleStop}
                className="flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg"
              >
                <Square className="w-3.5 h-3.5" />
                Stop
              </button>
            ) : (
              <button
                onClick={handleSubmit}
                disabled={!prompt.trim()}
                className="flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium text-white bg-forest hover:bg-forest-dark disabled:opacity-40 disabled:cursor-not-allowed rounded-lg"
              >
                <Send className="w-3.5 h-3.5" />
                Investigate
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-3 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl">
          <XCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-red-700 dark:text-red-400">Investigation Failed</p>
            <p className="text-xs text-red-600 dark:text-red-400 mt-1">{error}</p>
          </div>
        </div>
      )}

      {/* Streaming Output */}
      {(thoughts.length > 0 || toolCalls.length > 0 || result) && (
        <div
          ref={scrollRef}
          className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-xl shadow-sm max-h-[600px] overflow-y-auto"
        >
          {/* Tool Calls */}
          {toolCalls.length > 0 && (
            <div>
              <div className="sticky top-0 z-10 px-4 py-2 bg-stone-50 dark:bg-stone-700 border-b border-stone-200 dark:border-stone-600 flex items-center gap-2">
                <Activity className="w-4 h-4 text-stone-500" />
                <span className="text-xs font-medium text-stone-600 dark:text-stone-300">
                  Tool Calls ({toolCalls.length})
                </span>
                <span className="text-[10px] text-stone-400">
                  {toolCalls.filter((t) => t.status === 'success').length} success ·{' '}
                  {toolCalls.filter((t) => t.status === 'error').length} errors ·{' '}
                  {toolCalls.filter((t) => t.status === 'running').length} running
                </span>
              </div>
              {toolCalls.map((tc) => (
                <ToolCallCard
                  key={tc.id}
                  call={tc}
                  isExpanded={expandedCalls.has(tc.id)}
                  onToggle={() => toggleCall(tc.id)}
                />
              ))}
            </div>
          )}

          {/* Thoughts */}
          {thoughts.length > 0 && (
            <div>
              <div className="sticky top-0 z-10 px-4 py-2 bg-stone-50 dark:bg-stone-700 border-b border-stone-200 dark:border-stone-600 flex items-center gap-2">
                <Brain className="w-4 h-4 text-purple-500" />
                <span className="text-xs font-medium text-stone-600 dark:text-stone-300">
                  Agent Thoughts ({thoughts.length})
                </span>
              </div>
              {thoughts.map((t, i) => (
                <ThoughtBlock key={i} thought={t} />
              ))}
            </div>
          )}

          {/* Result */}
          {result && (
            <div className="p-4">
              <ResultBlock text={result} />
            </div>
          )}

          {/* Running indicator */}
          {isRunning && (
            <div className="flex items-center gap-2 px-4 py-3 border-t border-stone-100 dark:border-stone-700">
              <Loader2 className="w-4 h-4 text-forest animate-spin" />
              <span className="text-xs text-stone-500">Investigation in progress…</span>
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {!isRunning && !result && thoughts.length === 0 && toolCalls.length === 0 && !error && (
        <div className="text-center py-16">
          <Zap className="w-12 h-12 text-stone-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-stone-500 mb-2">Start an Investigation</h3>
          <p className="text-sm text-stone-400 max-w-md mx-auto">
            Describe an incident or issue above and the SRE agent will investigate in real-time,
            streaming its thoughts, tool calls, and findings as it works.
          </p>
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            {[
              'Check the health of all services',
              'Investigate high memory usage on the gateway',
              'Why is solidsolutions.africa slow?',
            ].map((suggestion) => (
              <button
                key={suggestion}
                onClick={() => {
                  setPrompt(suggestion);
                  textareaRef.current?.focus();
                }}
                className="px-3 py-1.5 text-xs text-stone-600 dark:text-stone-400 bg-stone-100 dark:bg-stone-700 rounded-full hover:bg-stone-200 dark:hover:bg-stone-600"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

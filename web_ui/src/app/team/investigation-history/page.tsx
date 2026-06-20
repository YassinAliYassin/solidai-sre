"use client";

import { useEffect, useState } from 'react';
import { useIdentity } from '@/lib/useIdentity';
import { Loader2, Paperclip } from 'lucide-react';
import Link from 'next/link';

interface Episode {
  thread_id: string;
  prompt: string;
  result_text: string;
  success: boolean;
  tool_calls: any[];
  duration_seconds: number;
  created_at: string;
}

export default function InvestigationHistoryPage() {
  const { identity, loading } = useIdentity();
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [loadingEpisodes, setLoadingEpisodes] = useState(true);

  useEffect(() => {
    const fetch = async () => {
      setLoadingEpisodes(true);
      try {
        const res = await fetch('/api/memory/episodes');
        if (!res.ok) throw new Error('failed');
        const data = await res.json();
        setEpisodes(data.episodes || []);
      } catch (e) {
        console.error('Load', e);
      } finally {
        setLoadingEpisodes(false);
      }
    };
    if (!loading) fetch();
  }, [loading]);

  if (loading) return <Loader2 className="animate-spin" />;

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto space-y-4">
      <h1 className="text-2xl font-semibold">Investigations History</h1>
      <p className="text-sm text-stone-600">Past probe runs recorded in memory.</p>
      <div className="space-y-4">
        {loadingEpisodes ? (
          <div className="flex items-center gap-2"><Loader2 className="animate-spin" /> Loading…</div>
        ) : episodes.length === 0 ? (
          <p className="text-sm text-stone-500">No investigations yet.</p>
        ) : (
          episodes.map((e,i)=>{
            const brief = e.result_text.replace(/\n/g, ' ').slice(0,200);
            return (
              <div key={e.thread_id} className="border rounded p-4">
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-medium text-sm">{`#${i+1} – ${new Date(e.created_at).toLocaleString()}`}</div>
                    <div className="text-xs text-stone-400">Thread: {e.thread_id}</div>
                  </div>
                  <Link href={`/team/investigation/${e.thread_id}`} className="text-sm text-indigo-600 hover:underline">View</Link>
                </div>
                <p className="mt-2 text-sm truncate">{brief}{e.result_text.length>200?'…':''}</p>
                <div className="mt-2 flex items-center gap-1 text-xs text-stone-500">
                  <Paperclip className="w-4 h-4"/>
                  <span>{e.tool_calls.length} tool calls</span> | <span>{e.duration_seconds.toFixed(1)} s</span>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  );
}

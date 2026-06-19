import { NextResponse } from 'next/server';

const AGENT_URL = process.env.AGENT_SERVICE_URL || 'http://localhost:8000';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ episode_id: string }> }
) {
  try {
    const { episode_id } = await params;
    const res = await fetch(`${AGENT_URL}/memory/episodes/${episode_id}`);
    if (!res.ok) {
      return NextResponse.json({ error: 'Episode not found' }, { status: 404 });
    }
    const data = await res.json();
    return NextResponse.json(data, { status: 200 });
  } catch (e: any) {
    return NextResponse.json({ error: 'Failed to fetch episode', details: e?.message }, { status: 502 });
  }
}

import { NextRequest } from 'next/server';

const AGENT_URL = process.env.AGENT_SERVICE_URL || 'http://localhost:8000';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    const agentRes = await fetch(`${AGENT_URL}/investigate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: body.prompt,
        thread_id: body.thread_id || null,
      }),
      // @ts-expect-error — duplex is needed for streaming request bodies
      duplex: 'half',
    });

    if (!agentRes.ok) {
      const errText = await agentRes.text().catch(() => 'Unknown error');
      return new Response(
        `data: ${JSON.stringify({ type: 'error', data: { message: errText } })}\n\n`,
        {
          status: agentRes.status,
          headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
        },
      );
    }

    // Proxy the SSE stream directly to the client
    return new Response(agentRes.body, {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch (e: any) {
    return new Response(
      `data: ${JSON.stringify({ type: 'error', data: { message: e?.message || 'Failed to start investigation' } })}\n\n`,
      {
        status: 500,
        headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
      },
    );
  }
}

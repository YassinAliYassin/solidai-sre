const HEALTH_MONITOR_URL =
  process.env.HEALTH_MONITOR_URL || "http://localhost:8090";

/**
 * GET /api/webhooks
 * List all webhook subscriptions from the health monitor.
 */
export async function GET() {
  try {
    const res = await fetch(`${HEALTH_MONITOR_URL}/api/webhooks`, {
      cache: "no-store",
    });
    if (!res.ok) {
      return Response.json(
        { error: "Failed to list webhooks" },
        { status: res.status }
      );
    }
    const data = await res.json();
    return Response.json(data, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (err: any) {
    return Response.json(
      { error: err?.message || "Failed to list webhooks" },
      { status: 502 }
    );
  }
}

/**
 * POST /api/webhooks
 * Register a new webhook subscription.
 * Body: { url: string, events?: string[] }
 */
export async function POST(request: Request) {
  try {
    const body = await request.json();
    const res = await fetch(`${HEALTH_MONITOR_URL}/api/webhooks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    return Response.json(data, {
      status: res.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (err: any) {
    return Response.json(
      { error: err?.message || "Failed to register webhook" },
      { status: 502 }
    );
  }
}

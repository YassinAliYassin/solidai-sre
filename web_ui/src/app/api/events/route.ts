const HEALTH_MONITOR_URL =
  process.env.HEALTH_MONITOR_URL || "http://localhost:8090";

/**
 * GET /api/events
 * Server-Sent Events proxy — streams real-time health events from the health monitor.
 * No authentication required (public status page).
 */
export async function GET() {
  try {
    const upstream = await fetch(`${HEALTH_MONITOR_URL}/api/events`, {
      headers: {
        Accept: "text/event-stream",
      },
      cache: "no-store",
    });

    if (!upstream.ok || !upstream.body) {
      return new Response("Failed to connect to event stream", {
        status: 502,
        headers: { "Content-Type": "text/plain" },
      });
    }

    // Stream the response body directly to the client
    return new Response(upstream.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
        "Access-Control-Allow-Origin": "*",
      },
    });
  } catch (err: any) {
    return new Response(`Event stream error: ${err?.message || String(err)}`, {
      status: 502,
      headers: { "Content-Type": "text/plain" },
    });
  }
}

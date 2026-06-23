const HEALTH_MONITOR_URL =
  process.env.HEALTH_MONITOR_URL || "http://localhost:8090";

/**
 * DELETE /api/webhooks/[id]
 * Delete a webhook subscription.
 */
export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const res = await fetch(`${HEALTH_MONITOR_URL}/api/webhooks/${id}`, {
      method: "DELETE",
    });
    const data = await res.json().catch(() => ({}));
    return Response.json(data, {
      status: res.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (err: any) {
    return Response.json(
      { error: err?.message || "Failed to delete webhook" },
      { status: 502 }
    );
  }
}

/**
 * POST /api/webhooks/[id]/test
 * Send a test event to a webhook.
 */
export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const res = await fetch(`${HEALTH_MONITOR_URL}/api/webhooks/${id}/test`, {
      method: "POST",
    });
    const data = await res.json().catch(() => ({}));
    return Response.json(data, {
      status: res.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (err: any) {
    return Response.json(
      { error: err?.message || "Failed to test webhook" },
      { status: 502 }
    );
  }
}

import { NextRequest, NextResponse } from "next/server";
import { requireAdminSession } from "@/app/api/_utils/upstream";

function getHealthMonitorBaseUrl() {
  const baseUrl = process.env.HEALTH_MONITOR_URL;
  if (!baseUrl) throw new Error("HEALTH_MONITOR_URL is not set");
  return baseUrl;
}

// GET /api/admin/error-rates - Proxy to health-monitor error-rates API
// Returns per-service error rates, latency degradation status, and recent history
export async function GET(req: NextRequest) {
  try {
    await requireAdminSession(req);

    const baseUrl = getHealthMonitorBaseUrl();
    const url = new URL("/api/error-rates", baseUrl);

    // Forward window_hours query param if provided
    const windowHours = req.nextUrl.searchParams.get("window_hours");
    if (windowHours) {
      url.searchParams.set("window_hours", windowHours);
    }

    const res = await fetch(url.toString(), {
      method: "GET",
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });

    const contentType = res.headers.get("content-type") || "application/json";
    const body = await res.text();
    return new NextResponse(body, {
      status: res.status,
      headers: { "content-type": contentType },
    });
  } catch (err: any) {
    const status = err?.status || 502;
    return NextResponse.json(
      {
        error: "Failed to fetch error rates",
        details: err?.message || String(err),
      },
      { status }
    );
  }
}

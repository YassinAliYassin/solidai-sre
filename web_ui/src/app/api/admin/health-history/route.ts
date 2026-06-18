import { NextRequest, NextResponse } from "next/server";
import { requireAdminSession } from "@/app/api/_utils/upstream";

function getHealthMonitorBaseUrl() {
  const baseUrl = process.env.HEALTH_MONITOR_URL;
  if (!baseUrl) throw new Error("HEALTH_MONITOR_URL is not set");
  return baseUrl;
}

// GET /api/admin/health-history - Proxy to health-monitor history API
export async function GET(req: NextRequest) {
  try {
    // Require admin session
    await requireAdminSession(req);

    const baseUrl = getHealthMonitorBaseUrl();
    const url = new URL("/api/health-history", baseUrl);

    // Forward window_hours query param if provided
    const windowHours = req.nextUrl.searchParams.get("window_hours");
    if (windowHours) {
      url.searchParams.set("window_hours", windowHours);
    }

    const res = await fetch(url.toString(), {
      method: "GET",
      cache: "no-store",
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
        error: "Failed to fetch health history",
        details: err?.message || String(err),
      },
      { status }
    );
  }
}

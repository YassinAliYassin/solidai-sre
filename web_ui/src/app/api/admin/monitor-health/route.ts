import { NextRequest, NextResponse } from "next/server";
import { requireAdminSession } from "@/app/api/_utils/upstream";

function getHealthMonitorBaseUrl() {
  const baseUrl = process.env.HEALTH_MONITOR_URL;
  if (!baseUrl) throw new Error("HEALTH_MONITOR_URL is not set");
  return baseUrl;
}

// GET /api/admin/monitor-health - Proxy to health-monitor summary API
// Returns enriched health data including uptime stats and latency percentiles
export async function GET(req: NextRequest) {
  try {
    await requireAdminSession(req);

    const baseUrl = getHealthMonitorBaseUrl();

    // Fetch both summary and model-health in parallel
    const [summaryRes, modelRes] = await Promise.allSettled([
      fetch(`${baseUrl}/api/health-summary`, { cache: "no-store" }),
      fetch(`${baseUrl}/api/model-health`, {
        cache: "no-store",
        signal: AbortSignal.timeout(30000),
      }),
    ]);

    const summary =
      summaryRes.status === "fulfilled" && summaryRes.value.ok
        ? await summaryRes.value.json()
        : null;

    const modelHealth =
      modelRes.status === "fulfilled" && modelRes.value.ok
        ? await modelRes.value.json()
        : null;

    return NextResponse.json({
      summary,
      modelHealth,
      generated_at: new Date().toISOString(),
    });
  } catch (err: any) {
    const status = err?.status || 502;
    return NextResponse.json(
      {
        error: "Failed to fetch monitor health",
        details: err?.message || String(err),
      },
      { status },
    );
  }
}

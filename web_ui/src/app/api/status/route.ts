import { NextRequest, NextResponse } from "next/server";

const HEALTH_MONITOR_URL =
  process.env.HEALTH_MONITOR_URL || "http://localhost:8090";

/**
 * GET /api/status
 * Public endpoint — returns health summary for all services.
 * No authentication required.
 */
export async function GET(req: NextRequest) {
  try {
    const [summaryRes, historyRes, incidentsRes, modelHealthRes, slaRes] = await Promise.allSettled([
      fetch(`${HEALTH_MONITOR_URL}/api/health-summary`, {
        cache: "no-store",
      }),
      fetch(`${HEALTH_MONITOR_URL}/api/health-history?window_hours=24`, {
        cache: "no-store",
      }),
      fetch(`${HEALTH_MONITOR_URL}/api/incidents?window_hours=24`, {
        cache: "no-store",
      }),
      fetch(`${HEALTH_MONITOR_URL}/api/model-health`, {
        cache: "no-store",
      }),
      fetch(`${HEALTH_MONITOR_URL}/api/sla-summary?window_hours=720`, {
        cache: "no-store",
      }),
    ]);

    const summary =
      summaryRes.status === "fulfilled" && summaryRes.value.ok
        ? await summaryRes.value.json()
        : null;

    const history =
      historyRes.status === "fulfilled" && historyRes.value.ok
        ? await historyRes.value.json()
        : null;

    const incidents =
      incidentsRes.status === "fulfilled" && incidentsRes.value.ok
        ? await incidentsRes.value.json()
        : null;

    const model_health =
      modelHealthRes.status === "fulfilled" && modelHealthRes.value.ok
        ? await modelHealthRes.value.json()
        : null;

    const sla =
      slaRes.status === "fulfilled" && slaRes.value.ok
        ? await slaRes.value.json()
        : null;

    return NextResponse.json(
      {
        summary,
        history,
        incidents,
        model_health,
        sla,
        generated_at: new Date().toISOString(),
      },
      {
        headers: {
          "Cache-Control": "no-store, no-cache, must-revalidate",
          "Access-Control-Allow-Origin": "*",
        },
      }
    );
  } catch (err: any) {
    return NextResponse.json(
      {
        error: "Failed to fetch status data",
        details: err?.message || String(err),
      },
      { status: 502 }
    );
  }
}
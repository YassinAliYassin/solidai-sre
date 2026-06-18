import { NextRequest, NextResponse } from "next/server";
import { requireAdminSession } from "@/app/api/_utils/upstream";

function getHealthMonitorBaseUrl() {
  const baseUrl = process.env.HEALTH_MONITOR_URL;
  if (!baseUrl) throw new Error("HEALTH_MONITOR_URL is not set");
  return baseUrl;
}

function getConfigServiceBaseUrl() {
  const baseUrl = process.env.CONFIG_SERVICE_URL;
  if (!baseUrl) throw new Error("CONFIG_SERVICE_URL is not set");
  return baseUrl;
}

export async function GET(req: NextRequest) {
  try {
    await requireAdminSession(req);

    const token = req.cookies.get("solidai-sre_session_token")?.value;
    if (!token) throw { status: 401, message: "Unauthenticated" };

    // Health history
    const baseHealth = getHealthMonitorBaseUrl();
    const healthRes = await fetch(`${baseHealth}/api/health-history?window_hours=24`, {
      method: "GET",
      cache: "no-store",
    });
    const history = await healthRes.json();

    // Agent runs
    const baseConfig = getConfigServiceBaseUrl();
    const runsRes = await fetch(`${baseConfig}/api/v1/team/agent-runs?limit=100`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const agentRuns = await runsRes.json();

    return NextResponse.json({ history, agentRuns });
  } catch (err: any) {
    const status = err?.status || 502;
    return NextResponse.json({ error: err?.message || String(err) }, { status });
  }
}

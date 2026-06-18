import { NextRequest, NextResponse } from "next/server";
import { requireAdminSession } from "@/app/api/_utils/upstream";

const LITELLM_BASE_URL =
  process.env.LITELLM_BASE_URL || "http://litellm:4000";

/**
 * GET /api/admin/litellm-health
 *
 * Query litellm's /health endpoint and return model status.
 * Shows which models are healthy/unhealthy with error details.
 */
export async function GET(req: NextRequest) {
  try {
    await requireAdminSession(req);

    const litellmRoot = LITELLM_BASE_URL.replace(/\/v1\/?$/, "");
    const healthUrl = `${litellmRoot}/health`;

    const res = await fetch(healthUrl, {
      method: "GET",
      cache: "no-store",
    });

    const data = await res.json();

    // Normalize the response: extract healthy/unhealthy model summaries
    const healthy = (data.healthy_endpoints || []).map((ep: any) => ({
      model: ep.model || "unknown",
      litellmProxy: ep.use_litellm_proxy,
    }));

    const unhealthy = (data.unhealthy_endpoints || []).map((ep: any) => ({
      model: ep.model || "unknown",
      litellmProxy: ep.use_litellm_proxy,
      error: (ep.error || "Unknown error").slice(0, 300),
    }));

    return NextResponse.json({
      healthy_count: data.healthy_count ?? healthy.length,
      unhealthy_count: data.unhealthy_count ?? unhealthy.length,
      healthy,
      unhealthy,
      generated_at: new Date().toISOString(),
    });
  } catch (err: any) {
    const status = err?.status || 502;
    return NextResponse.json(
      {
        error: "Failed to query litellm health",
        details: err?.message || String(err),
      },
      { status },
    );
  }
}

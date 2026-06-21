import { NextRequest, NextResponse } from "next/server";

const HEALTH_MONITOR_URL =
  process.env.HEALTH_MONITOR_URL || "http://localhost:8090";

interface ServiceSummary {
  name: string;
  status: string;
  uptime_24h: number | null;
}

interface HealthSummary {
  status?: string;
  timestamp?: string;
  services?: ServiceSummary[];
  total_services?: number;
  healthy_count?: number;
  degraded_count?: number;
  down_count?: number;
}

function escapeXml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function renderBadge(
  label: string,
  message: string,
  color: string,
  labelColor?: string
): string {
  const escapedLabel = escapeXml(label);
  const escapedMessage = escapeXml(message);

  // Measure approximate widths (monospace ~6.5px per char at font-size 11)
  const charWidth = 6.5;
  const padding = 10;
  const labelWidth = Math.round(escapedLabel.length * charWidth + padding * 2);
  const messageWidth = Math.round(escapedMessage.length * charWidth + padding * 2);
  const totalWidth = labelWidth + messageWidth;

  const lc = labelColor || "#555";

  return `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${totalWidth}" height="20" role="img" aria-label="${escapedLabel}: ${escapedMessage}">
  <title>${escapedLabel}: ${escapedMessage}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="${totalWidth}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="${labelWidth}" height="20" fill="${lc}"/>
    <rect x="${labelWidth}" width="${messageWidth}" height="20" fill="${color}"/>
    <rect width="${totalWidth}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text x="${labelWidth / 2 + 1}" y="14">${escapedLabel}</text>
    <text x="${labelWidth + messageWidth / 2 - 1}" y="14">${escapedMessage}</text>
  </g>
</svg>`;
}

/**
 * GET /api/status/badge.svg
 * Returns an SVG badge showing overall system health.
 * Query params:
 *   - label (optional) — left side text, defaults to "status"
 *   - style (optional) — "flat" (default), "flat-square", "plastic"
 */
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const label = searchParams.get("label") || "status";

  try {
    const res = await fetch(`${HEALTH_MONITOR_URL}/api/health-summary`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });

    if (!res.ok) {
      const svg = renderBadge(label, "error", "#9f3a3a");
      return new NextResponse(svg, {
        headers: {
          "Content-Type": "image/svg+xml",
          "Cache-Control": "no-store, no-cache, must-revalidate",
          "Access-Control-Allow-Origin": "*",
        },
      });
    }

    const data: HealthSummary = await res.json();
    const status = data.status || "unknown";
    const services = data.services || [];

    // Count internal services only (exclude external sites for badge)
    const internalServices = services.filter(
      (s) =>
        !s.name.toLowerCase().includes("solid") &&
        !s.name.toLowerCase().includes("fresh people")
    );

    const internalDown = internalServices.filter(
      (s) => s.status === "down"
    ).length;
    const internalDegraded = internalServices.filter(
      (s) => s.status === "degraded"
    ).length;
    const internalTotal = internalServices.length;

    let message: string;
    let color: string;

    if (internalDown > 0) {
      message = `${internalDown} down`;
      color = "#e05d44"; // red
    } else if (internalDegraded > 0) {
      message = `${internalDegraded} degraded`;
      color = "#fe7d37"; // orange
    } else if (internalTotal > 0) {
      message = "operational";
      color = "#4c1"; // bright green
    } else {
      // Fall back to overall status
      switch (status) {
        case "healthy":
        case "ok":
          message = "operational";
          color = "#4c1";
          break;
        case "degraded":
          message = "degraded";
          color = "#fe7d37";
          break;
        case "down":
          message = "down";
          color = "#e05d44";
          break;
        default:
          message = "unknown";
          color = "#9f3a3a";
      }
    }

    const svg = renderBadge(label, message, color);

    return new NextResponse(svg, {
      headers: {
        "Content-Type": "image/svg+xml",
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Access-Control-Allow-Origin": "*",
      },
    });
  } catch (err: any) {
    const svg = renderBadge(label, "error", "#9f3a3a");
    return new NextResponse(svg, {
      headers: {
        "Content-Type": "image/svg+xml",
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Access-Control-Allow-Origin": "*",
      },
    });
  }
}

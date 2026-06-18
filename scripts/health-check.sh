#!/bin/bash
# SolidAI SRE — Health Check Script
# Checks all service endpoints and reports status.
# Usage: bash scripts/health-check.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✅ $1${NC}"; }
warn() { echo -e "  ${YELLOW}⚠️  $1${NC}"; }
fail() { echo -e "  ${RED}❌ $1${NC}"; }

ERRORS=0

echo ""
echo "═══════════════════════════════════════════"
echo "  SolidAI SRE — Health Check"
echo "═══════════════════════════════════════════"
echo ""

# --- Docker Containers ---
echo "Docker Containers:"
CONTAINERS=("solidai-sre-postgres" "solidai-sre-config-service" "solidai-sre-litellm" "solidai-sre-neo4j" "solidai-sre-sre-agent" "solidai-sre-web-ui")
for c in "${CONTAINERS[@]}"; do
    # Check if container is running first
    RUNNING=$(docker inspect --format='{{.State.Running}}' "$c" 2>/dev/null || echo "false")
    if [ "$RUNNING" != "true" ]; then
        fail "$c (not running)"
        ((ERRORS++))
        continue
    fi

    # Check health status (may be "unknown" if no healthcheck defined)
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$c" 2>/dev/null || echo "unknown")
    if [ "$STATUS" = "healthy" ]; then
        ok "$c"
    elif [ "$STATUS" = "unknown" ]; then
        # No healthcheck defined — check if running and port is accessible
        PORT=$(docker inspect --format='{{range $p, $conf := .NetworkSettings.Ports}}{{range $conf}}{{.HostPort}}{{end}}{{end}}' "$c" 2>/dev/null | awk '{print $1}')
        if [ -n "$PORT" ] && nc -z localhost "$PORT" 2>/dev/null; then
            ok "$c (running, port $PORT accessible)"
        else
            warn "$c (running, no healthcheck defined)"
        fi
    else
        fail "$c ($STATUS)"
        ((ERRORS++))
    fi
done

echo ""

# --- Service Endpoints ---
echo "Service Endpoints:"

# Config Service
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:8081/health 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    BODY=$(curl -sf http://localhost:8081/health 2>/dev/null)
    ok "config-service:8081 → $BODY"
else
    fail "config-service:8081 → HTTP $HTTP_CODE"
    ((ERRORS++))
fi

# LiteLLM Proxy
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:4001/health 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    ok "litellm:4001 → healthy"
else
    fail "litellm:4001 → HTTP $HTTP_CODE"
    ((ERRORS++))
fi

# SRE Agent
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:8001/health 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    BODY=$(curl -sf http://localhost:8001/health 2>/dev/null)
    ok "sre-agent:8001 → $BODY"
else
    fail "sre-agent:8001 → HTTP $HTTP_CODE"
    ((ERRORS++))
fi

# Web UI
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:3002 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    ok "web-ui:3002 → serving"
else
    fail "web-ui:3002 → HTTP $HTTP_CODE"
    ((ERRORS++))
fi

# Neo4j
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:7475 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    ok "neo4j:7475 → available"
else
    warn "neo4j:7475 → HTTP $HTTP_CODE (may need auth)"
fi

# Postgres (TCP check)
if nc -z localhost 5433 2>/dev/null; then
    ok "postgres:5433 → accepting connections"
else
    fail "postgres:5433 → not accepting connections"
    ((ERRORS++))
fi

echo ""

# --- Disk Usage ---
echo "Disk Usage:"
DISK_USAGE=$(df -h / | tail -1 | awk '{print $5}' | tr -d '%')
if [ "$DISK_USAGE" -gt 90 ]; then
    fail "Disk usage: ${DISK_USAGE}% (critical)"
    ((ERRORS++))
elif [ "$DISK_USAGE" -gt 80 ]; then
    warn "Disk usage: ${DISK_USAGE}% (high)"
else
    ok "Disk usage: ${DISK_USAGE}%"
fi

# Docker disk
DOCKER_DISK=$(docker system df --format '{{.Size}}' 2>/dev/null | head -1 || echo "unknown")
echo "  Docker system: $DOCKER_DISK"

echo ""

# --- Summary ---
if [ "$ERRORS" -gt 0 ]; then
    echo -e "${RED}═══════════════════════════════════════════${NC}"
    echo -e "${RED}  RESULT: ${ERRORS} error(s) found${NC}"
    echo -e "${RED}═══════════════════════════════════════════${NC}"
    exit 1
else
    echo -e "${GREEN}═══════════════════════════════════════════${NC}"
    echo -e "${GREEN}  RESULT: All services healthy${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════${NC}"
    exit 0
fi

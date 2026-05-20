# SolidAI SRE — AI SRE Platform

## What this is

SolidAI SRE is an open-source AI SRE platform that investigates production incidents for **Solid Solutions** and **SolidAI** infrastructure. It uses LLM-powered agents with episodic memory and a Neo4j knowledge graph to diagnose issues, identify root causes, and produce structured investigation reports.

Built on SolidAI SRE foundation, customized for African tech ecosystem.

## Architecture

```
SolidAI Gateway (18789) -> SolidAI SRE
                              |
                        +-----+-----+
                        |     |     |
                     Memory Skills  KG
              config-service <- Telegram bot (@AionUi_solidsolutions_bot)
```

**sre-agent** is the core investigation agent. Uses LangGraph for orchestration with a planner -> investigation subagents -> synthesizer -> writeup topology. 46 skills (progressive knowledge loading) via `load_skill` + `run_script` tools.

**web_ui** is the admin console and agent entry point (Next.js, pnpm). Agent runs, config editor, knowledge base explorer, memory pages. Customized with SolidAI branding.

**config-service** is the control plane. Hierarchical org->team config with deep merge. Manages tokens and audit logging.

**memory system** -- episodic memory in `sre-agent/memory/`. Stores and retrieves past investigation episodes. Multi-factor similarity matching.

**knowledge graph** -- Neo4j integration for service topology, dependency traversal, blast radius analysis.

**LiteLLM proxy** -- translates API calls to OpenRouter (tencent/hy3-preview) or other LLM providers. Config in `litellm_config.yaml`.

## Local development

```bash
# The .env file is already configured with OpenRouter API key
# Start all services (postgres, config-service, litellm, neo4j, sre-agent, web console)
make dev
```

Or use Docker Compose directly:

```bash
docker compose up
```

The web console will be available at `http://localhost:3000`.

## SolidAI Integration

- **Gateway**: Connects to SolidAI Gateway at `http://localhost:18789`
- **Telegram**: Sends alerts to @AionUi_solidsolutions_bot (Chat ID: 1292960246)
- **Sites Monitored**: solidsolutions.africa, solidai.africa
- **Agents**: All 8 SolidAI agents (agriculture, fintech, health, education, energy, governance, retail, logistics)

## Key files

| File | What it does |
|------|-------------|
| sre-agent/graph.py | LangGraph master graph -- nodes, edges, Send() fan-out |
| sre-agent/state.py | GraphState TypedDict, AlertInput, reducers |
| sre-agent/nodes/ | Graph nodes: init_context, planner, subagent_executor, synthesizer, writeup, memory_store |
| sre-agent/server.py | FastAPI server, SSE streaming via graph.astream_events() |
| sre-agent/tools/ | Neo4j semantic layer, skill_tools (load_skill/run_script), agent_tools (tool registry) |
| sre-agent/memory/ | Episodic memory system |
| config_service/src/api/main.py | Config API with hierarchical merge |
| web_ui/src/app/ | Next.js app router pages (SolidAI branded) |
| litellm_config.yaml | LLM routing config (OpenRouter) |

## Conventions

- Python services use `uv` (sre-agent, config-service)
- web_ui is Next.js with pnpm (customized with SolidAI colors/fonts)
- Linting: ruff (config in ruff.toml)
- Skills over tools: add integrations as `.claude/skills/*/SKILL.md` with scripts
- Config hierarchy: org base, team overrides. Dicts merge, lists replace.
- Error format: `{"success": bool, "result": ..., "error": "..."}`
- SSE streaming: events defined in events.py

## Monitoring Targets

- **solidsolutions.africa** (NGINX VPS, Cloudflare)
- **solidai.africa** (DNS configured)
- **SolidAI Gateway** (localhost:18789, PM2, 8 agents)
- **Fresh People** (fresh-people.co.za, cPanel, Cloudflare)

## Contributing

See `CONTRIBUTING.md` for guidelines. SolidAI-specific enhancements welcome.

---

**Powered by SolidAI — Building the Future of African Tech**

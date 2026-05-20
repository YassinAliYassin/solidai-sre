<p align="center">
  <img src=".github/assets/logo.png" alt="SolidAI SRE — AI SRE platform for automated incident investigation" width="320" />
</p>

<p align="center">
  <b>Your AI SRE that investigates production incidents</b><br>
  <sub>Long-term memory · Knowledge graph · 46 production skills · SolidAI Integration</sub>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="Apache 2.0 License" /></a>
  <a href="https://github.com/yassin/solidai-sre/stargazers"><img src="https://img.shields.io/github/stars/yassin/solidai-sre?style=social" alt="GitHub Stars" /></a>
  <a href="https://github.com/yassin/solidai-sre/network/members"><img src="https://img.shields.io/github/forks/yassin/solidai-sre?style=social" alt="GitHub Forks" /></a>
  <a href="https://github.com/yassin/solidai-sre/pulls"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome" /></a>
  <a href="https://solidai.africa"><img src="https://img.shields.io/badge/website-solidai.africa-green.svg" alt="SolidAI Website" /></a>
</p>

**SolidAI SRE** is an open-source AI SRE agent that automatically investigates production incidents, finds root causes, and learns from every investigation. Built for **Solid Solutions & SolidAI** infrastructure. It combines **episodic memory** (remembering past incidents and what fixed them) with a **Neo4j knowledge graph** (understanding service dependencies and blast radius) and **46 production-ready skills** for tools like Datadog, Grafana, PagerDuty, Elasticsearch, Kubernetes, and AWS. Self-hosted, provider-agnostic via LiteLLM, and licensed Apache 2.0.

## Why SolidAI SRE?

| | |
|:--|:--|
| **Learns from every incident** | Remembers past investigations — what worked, what didn't. Similar incident at 3am? It already knows the playbook. |
| **Understands your infrastructure** | Neo4j knowledge graph maps service dependencies, so the agent knows blast radius before it starts investigating. |
| **Plugs into what you already use** | 46 production skills for Datadog, Grafana, PagerDuty, Elasticsearch, Kubernetes, AWS, and more. No rip-and-replace. |
| **SolidAI Integration** | Built-in integration with SolidAI Gateway (localhost:18789) and Telegram bots (@AionUi_solidsolutions_bot). |

## Quick Start

```bash
git clone https://github.com/yassin/solidai-sre.git
cd solidai-sre
cp .env.example .env
# Add your OPENROUTER_API_KEY to .env
make dev
```

The web console will be available at `http://localhost:3000`.

## Architecture

```
SolidAI Gateway (18789) -> SolidAI SRE
                              |
                        +-----+-----+
                        |     |     |
                     Memory Skills  KG
              config-service <- Telegram bot integration
```

**sre-agent** is the core investigation agent. Uses LangGraph for orchestration with a planner -> investigation subagents -> synthesizer -> writeup topology. 46 skills via `load_skill` + `run_script` tools.

**web_ui** is the admin console and agent entry point (Next.js, pnpm). Agent runs, config editor, knowledge base explorer, memory pages.

**config-service** is the control plane. Hierarchical org->team config with deep merge. Manages tokens and audit logging.

## SolidAI-Specific Configuration

- **Gateway Integration**: Connects to SolidAI Gateway at `http://localhost:18789`
- **Telegram Bot**: Sends alerts to @AionUi_solidsolutions_bot
- **Multi-Agent Support**: Monitors all 8 SolidAI agents (agriculture, fintech, health, education, energy, governance, retail, logistics)
- **Site Monitoring**: Tracks solidsolutions.africa and solidai.africa uptime

## Key Features

- **46 Production Skills**: Elasticsearch, Datadog, Grafana, PagerDuty, K8s, AWS, and more
- **Long-term Memory**: Stores investigations, surfaces past solutions for similar incidents
- **Knowledge Graph**: Neo4j service topology, dependency traversal, blast radius
- **Multi-provider LLM**: OpenRouter (tencent/hy3-preview), Claude, OpenAI, Gemini, DeepSeek, Mistral, Ollama
- **Web Console**: Dashboard, agent runs, memory browser
- **Telegram Integration**: Investigate incidents directly from Telegram

## Make Commands

| Command | What it does |
| --- | --- |
| `make dev` | Start all services (Postgres, config, LiteLLM, agent, web UI) |
| `make dev-telegram` | Start all services + Telegram bot |
| `make stop` | Stop all services |
| `make status` | Show service health status |
| `make logs` | Follow all service logs |

## License

Licensed under the Apache License 2.0. See LICENSE for details.

---

**Built by SolidAI — Powering African Innovation**

# Complyra

Production-oriented enterprise private knowledge assistant with governed AI responses.

Complyra combines multi-tenant RAG, approval workflow, RBAC, auditability, observability, and cloud-ready deployment automation.

## Project Status

- Application stack: ready
- Local validation: passed
- IaC (Terraform + policy gate): ready
- AWS deployment blocker: AWS account + credentials + domain/certificate provisioning

## Table of Contents

- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [Architecture](#architecture)
- [Repository Structure](#repository-structure)
- [Quick Start (Docker)](#quick-start-docker)
- [Quick Start (Local Development)](#quick-start-local-development)
- [Production Deployment (AWS)](#production-deployment-aws)
- [Security and Governance](#security-and-governance)
- [Documentation Index](#documentation-index)
- [Verification](#verification)
- [License](#license)

## Key Features

- Multi-tenant knowledge ingestion and retrieval (`X-Tenant-ID` scoped)
- Human-in-the-loop approval workflow (LangGraph)
- RBAC roles: `admin`, `auditor`, `user`
- Audit search + CSV export for compliance operations
- Async ingest jobs (Redis + RQ worker)
- Metrics, health probes, Sentry support, Prometheus/Grafana
- Output policy guard for potentially sensitive generated content

## Technology Stack

- Backend: FastAPI, Uvicorn, Pydantic v2
- Workflow: LangGraph
- Data: PostgreSQL + SQLAlchemy + Alembic
- Vector DB: Qdrant
- Queue: Redis + RQ
- LLM runtime: Ollama (`qwen2.5:3b-instruct`)
- Embeddings: `BAAI/bge-small-en-v1.5`
- Frontend: React + TypeScript + Vite + Nginx
- Observability: Prometheus, Grafana, optional Sentry
- IaC: Terraform + OPA/Conftest

## Architecture

```text
Web UI
  -> API Gateway (FastAPI)
    -> AuthN/AuthZ (JWT + RBAC)
    -> LangGraph workflow (retrieve -> draft -> policy gate -> approval -> final)
    -> Audit service (PostgreSQL)
    -> Ingest API (enqueue)
       -> Redis queue -> worker -> chunk/embed -> Qdrant

Observability
  Prometheus <- /metrics
  Grafana    <- Prometheus
  Sentry     <- exceptions (optional)
  CloudWatch Synthetics <- login/chat/approval journey checks
```

## Repository Structure

```text
app/                backend API, services, DB access, models
alembic/            DB migrations
web/                React frontend
ops/                Prometheus/Grafana provisioning
infra/
  terraform/        full-stack AWS IaC
  policy/           OPA/Conftest policy gate rules
  ecs/              ECS task definition templates
  synthetics/       CloudWatch Synthetics canary scripts
docs/               architecture, deployment runbooks, checklists
scripts/            AWS and IaC automation scripts
tests/              test suite
```

## Quick Start (Docker)

```bash
cd /Users/liweiguang/aiagent/complyra
cp .env.example .env
docker compose up --build -d
```

Endpoints:

- Web: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`
- Live health: `http://localhost:8000/api/health/live`
- Ready health: `http://localhost:8000/api/health/ready`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

## Quick Start (Local Development)

Backend:

```bash
cd /Users/liweiguang/aiagent/complyra
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
.venv/bin/alembic upgrade head
./scripts/pull_ollama_model.sh qwen2.5:3b-instruct
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Frontend:

```bash
cd /Users/liweiguang/aiagent/complyra/web
npm install
cp .env.example .env
npm run dev
```

Frontend quality checks:

```bash
cd /Users/liweiguang/aiagent/complyra/web
npm run build
npm run test:e2e
```

## Production Deployment (AWS)

Recommended order:

1. Create and secure AWS account (`docs/aws-account-onboarding.md`)
2. Prepare production env (`./scripts/aws/00_preflight.sh`, `./scripts/aws/01_prepare_prod_env.sh`, `./scripts/aws/04_validate_env_prod.sh`)
3. Run Terraform full-stack plan and policy gate (`./scripts/aws/07_terraform_plan.sh`, `./scripts/iac/01_conftest_check.sh`)
4. Build/push images and deploy (`./scripts/aws/03_build_and_push.sh`, `./scripts/aws/09_deploy_services_from_release.sh`)
5. Run smoke tests (`./scripts/aws/05_smoke_test.sh`)

Detailed runbook: `docs/aws-deployment.md`

## Security and Governance

- Tenant-scoped retrieval and access checks
- JWT auth with secure cookie support
- Trusted host middleware and security headers
- Output policy guard for sensitive pattern detection
- CSV formula injection mitigation on export
- OPA/Conftest policy-as-code gate for Terraform

## Documentation Index

- Architecture: `docs/architecture.md`
- AWS deployment runbook: `docs/aws-deployment.md`
- AWS account onboarding: `docs/aws-account-onboarding.md`
- AWS ownership checklist: `docs/aws-owner-checklist.md`
- Manual actions (EN): `docs/what-you-need-to-do.md`
- Manual actions (ZH-CN): `docs/what-you-need-to-do.zh-CN.md`
- ECS task definitions: `docs/ecs-task-definitions.md`
- Release and rollback: `docs/release-and-rollback.md`
- Operations runbook: `docs/operations-runbook.md`
- Optimization roadmap: `docs/optimization-roadmap.md`
- Frontend contribution guide: `docs/frontend-contributing.md`
- UI design tokens: `docs/ui-design-tokens.md`
- Frontend package readme: `web/README.md`
- Terraform/IaC guide: `infra/terraform/README.md`

## Verification

```bash
cd /Users/liweiguang/aiagent/complyra
python3 -m compileall app
PYTHONPATH=. .venv/bin/pytest -q tests
./scripts/iac/01_conftest_check.sh
cd web && npm run build && npm run test:e2e
```

## License

MIT (see `LICENSE`).

# OrderFlow Sentinel - Development Status

Last Updated: 2026-10-30

## Summary
Large monoliths exist (backend/app/main.py ~684 lines, frontend/src/App.tsx ~378 lines). Currently uses rule-based detection/analyze labeled as AI in places; no real ML models saved, no tracing/telemetry stack, no Redis/Kafka, minimal persistence beyond SQLite/Postgres models in main. Frontend has a single file with many views.

## Implemented (Current)
- **Backend**: FastAPI app with Orders/Incidents/ApiRequests models, simulation (start/stop/pause/resume/generate/inject), WebSocket live feed, basic detect/analyze (rules), /api/ai/analyze endpoint, health check, /api/stats, /api/orders, /api/incidents, CORS
- **ML (baseline)**: rule-based classifier + train_baseline against synthetic csv
- **Frontend**: Single-page app (dashboard/monitoring/incidents/ai insights/simulation) with Tailwind/shadcn-like styles inline
- **Infra**: Dockerfiles, docker-compose (backend+frontend+postgres), .env.example
- **Data**: dataset/synthetic_api_logs.csv

## Gaps vs requirements
- Real trained sklearn models with artifacts, evaluation, versioning
- Anomaly detection (IsolationForest), delay prediction, semantic log similarity
- Distributed tracing (OpenTelemetry), correlation/trace IDs everywhere
- Kafka/Redis, microservices layout, event bus
- Self-healing engine (policies, retries/backoff, circuit breaker, DLQ, saga, idempotency)
- RCA agent with evidence graph, dependency map
- Operator approvals/RBAC, audit, feedback/learning
- Expanded schema (users/roles/traces/approvals/policies/executions/feedback/model_versions/audit_logs/DLQ/simulation_configs)
- Full enterprise dashboard pages, dependency map viz, model performance, reports
- Multi-industry simulation (Telecom/Retail) with controlled demos
- Tests, observability (Prometheus/Grafana), Alembic migrations

## Plan
Incrementally add modules under backend/app/*, expand models/schemas/services, add ml/training/eval/artifacts, add tracing/telemetry, add resolution engine, wire frontend to real APIs with live updates. Keep existing endpoints working.

## Next
Start PHASE 2: restructure DB/models, add core config/tracing/telemetry, correlation IDs, base classes, prepare for Postgres+Redis.

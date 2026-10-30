# OrderFlow Sentinel - Development Status

Last Updated: 2026-10-30

## Audit Summary
- Existing FastAPI + SQLAlchemy backend and React/Vite frontend are retained; no rebuild was performed.
- Core order, incident, API-request, event, and audit records are persisted through the main SQLAlchemy metadata. The current workflow simulator and operator resolution endpoints remain available.
- `backend/app/api/v2_enterprise.py` existed but was not registered with FastAPI. It is now registered, and its v2 approval and analytics routes operate on persisted workflow records.
- A separate set of enterprise SQLAlchemy models exists, but it is not included in the main database metadata and has no migrations. Those declarations do not establish that the corresponding tables are active.

## Implemented
- FastAPI order/incident simulation, bounded synthetic transient recovery, order timelines, API logs, audit records, REST endpoints, and WebSocket broadcasts.
- Existing rule-based failure detection and rule-labelled root-cause explanations. These are not represented as trained-model decisions in the UI.
- Trained Random Forest and Isolation Forest artifacts, a reproducible training script, and saved classification metrics/confusion matrix. Evaluation is on synthetic data only.
- Separate Random Forest breach classifier and remaining-time regressor, trained from a seeded synthetic dataset with a saved held-out evaluation report.
- TF-IDF + OneHotEncoder + LogisticRegression classifiers for API failure subtype, order rejection type, and rejection fixability. Three-way stratified train/validation/test evaluation and versioned artifacts are saved under `ml/models/`.
- `/api/v2/ml/predict` and `/api/v2/ml/rejections/predict` validate typed inputs, return per-class outputs, and persist prediction records. Simulated API failure/rejection incidents store the model result separately from deterministic detection evidence.
- `/api/v2/ml/delay-predict` validates controlled scenario inputs. `/api/v2/ml/orders/{order_id}/delay-predict` derives current features from persisted order, event, and API telemetry, records predictions, and creates a five-minute-deduplicated warning event for candidates. No automatic recovery occurs.
- Predictive-intelligence UI supports selecting active persisted orders, model performance, rejection analysis, recent predictions, and operator feedback. Feedback is audit-recorded for review and does not auto-retrain.
- Incident RCA reads persisted API requests, lifecycle events, similar incidents, and model outputs; local TF-IDF/cosine similarity groups related error logs. Optional LLM explanations are configurable and disabled by default; action policies remain deterministic.
- Recovery recommendation endpoint maps model labels to configured policies and returns risk/approval requirements without executing actions.
- v2 enterprise router registration; high-risk resolution actions cannot be approved by a caller-provided `auto_approve` flag.
- v2 pending approvals list persisted incidents awaiting approval. Decisions use the existing resolver, state transitions, and audit records.
- v2 operational summary metrics are derived from persisted orders, incidents, and API requests. SLA compliance is reported as unavailable because per-order SLA deadlines are not stored.
- React/Vite operations UI, simulation controls, orders/incidents, evidence view, operator actions, audit view, CSV export, and WebSocket refresh behavior.
- Docker Compose includes backend, frontend, PostgreSQL, Redis, Prometheus, and Grafana services.

## Partial / Known Limitations
- All new classifiers and the delay predictor use synthetic scenario data. Their reported performance does not establish real-world generalization; probabilities are uncalibrated. Rejection-type performance is particularly high because synthetic scenarios retain strong lexical patterns.
- The persisted-order delay endpoint uses a 120-second SLA horizon from the model artifact rather than an order-specific persisted SLA policy. Delay candidates create operator-review events only.
- Log similarity is TF-IDF over stored error messages, not a learned causal graph or Sentence Transformer. RCA confidence is an evidence-count heuristic, not model confidence. Optional LLM output is not used for recovery decisions.
- Feedback is collected but no retraining governance, candidate comparison, promotion, or rollback is implemented. Only explicitly configured low-risk policies can be eligible for automation; the recommendation endpoint itself never executes recovery.
- Synthetic address/payment/duplicate/business-rule rejection injection exists, but deterministic correction, provider state verification, duplicate lookup, and actual recovery execution for those paths remain incomplete.
- The original classifier labels `NORMAL`, `API_ERROR`, and `ORDER_REJECTION` and the Isolation Forest artifact remain legacy capabilities; neither is a complete service-level anomaly alerting system.
- Detection, RCA, telemetry collection, retry state, idempotency, and circuit-breaker state are partly in-memory or deterministic simulation logic; they are not a durable distributed event-processing architecture.
- OpenTelemetry package dependencies and correlation/trace identifiers exist in parts of the code, but end-to-end span export and trace reconstruction are not verified.
- Compose configures Kafka connection variables but does not define a Kafka service or active producer/consumer workflow. Redis is declared but not used by the current application path.
- Approval decisions are persisted through incident state and audit records, but there is no authentication, role-based authorization, or user identity enforcement.
- No per-order SLA deadline exists, so SLA compliance and proactive breach prediction cannot currently be calculated honestly.
- Feedback/retraining governance, durable DLQ and replay, saga compensation, database migrations, retention, and multi-industry controlled scenarios remain incomplete.
- Frontend remains a single `App.tsx` application surface. Several displayed service-health values are synthetic and should not be treated as production telemetry.

## Changes and Verification This Pass
- Registered the previously unreachable `/api/v2` router.
- Removed the request-controlled risk-policy override from `ResolutionEngine.execute`; v2 high-risk execution requests now require the persisted incident approval workflow.
- Replaced the empty v2 approvals response and fixed v2 analytics values with persisted workflow queries and calculated metrics.
- Added workflow tests for risk-policy enforcement and persisted v2 approval/analytics responses.
- Added a seeded delay dataset generator, a classifier/regressor training script, persisted model artifacts, held-out metrics, an input-validated API route, and a predictive-intelligence UI view.
- Delay model run (`python -m ml.training.train_delay_model`): 5,000 generated rows, 1,000-row holdout; breach F1 0.965 and remaining-time MAE 5,639 ms. Synthetic-only evaluation; probabilities uncalibrated.
- Added reproducible failure-subtype, rejection-type, and fixability datasets/training. Test macro F1: API subtype 0.9013, rejection type 0.9911, fixability 0.9384; full reports and confusion matrices are saved in `ml/models/*_metrics.json`. Synthetic-only.
- Added persisted prediction/feedback records, typed inference/history/metrics APIs, per-order delay feature extraction, evidence-backed RCA, policy-validated recommendation responses, and corresponding predictive UI sections.
- Backend: `python -m pytest tests/test_workflow.py -q` from `backend/` -> 11 passed.
- Frontend: `npm run build` from `frontend/` -> passed after model, rejection, feedback, and per-order delay integration.
- Added `AI_IMPLEMENTATION.md`, `MODEL_TRAINING.md`, `MODEL_EVALUATION.md`, and `AI_API_DOCUMENTATION.md`.
- Test environment initially lacked the already-declared `prometheus-client`; installed it in the current Python user environment to run the backend suite.

## Next Tasks
1. Persist per-order SLA deadlines and validate/calibrate delay predictions against recorded outcomes before relying on alert thresholds.
2. Expand simulator scenarios for invalid addresses, duplicate orders, non-fixable business rules, and payment-state verification; enforce those policies in actual recovery workflows.
3. Add authenticated operator identities and role checks to feedback and approval actions.
4. Add feedback dataset curation, drift checks, candidate model comparison, promotion, and rollback; never auto-promote.
5. Add retry/idempotency/replay integration tests and migrate all active resolution state to durable records with Alembic migrations.
6. Validate the optional LLM provider contract and redaction behavior; keep the local TF-IDF fallback available.
7. Wire distributed traces and service-level anomaly alerting end to end; Kafka remains unimplemented.
8. Split the frontend into reusable pages/components and remove or clearly label synthetic service-health values.

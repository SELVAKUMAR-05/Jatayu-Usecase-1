# AI Implementation

OrderFlow Sentinel retains its FastAPI, SQLAlchemy, React, and Vite architecture. The implemented model paths are local and do not require a paid API.

## Implemented Models

- API failure subtype: TF-IDF text features, one-hot service/endpoint features, scaled numeric telemetry, and multinomial Logistic Regression. Labels: `NORMAL`, `SERVER_ERROR`, `AUTHENTICATION_FAILURE`, `RATE_LIMIT`, `REQUEST_VALIDATION`, `API_TIMEOUT`, `NETWORK_FAILURE`, and `SCHEMA_MISMATCH`.
- Order rejection: the same Scikit-learn pipeline, trained to classify `INVALID_ADDRESS`, `INVENTORY_ISSUE`, `PAYMENT_ISSUE`, `DUPLICATE_ORDER`, and `BUSINESS_RULE_VIOLATION`.
- Rejection fixability: binary Scikit-learn classifier. Fixability is a model assessment only; execution is not automatic.
- Order delay: Random Forest breach classifier and remaining-processing-time regressor. The persisted-order endpoint derives elapsed time, stage, service request latency, recent service latency, previous-stage duration, queue depth, and SLA utilization from database records.
- Log similarity: TF-IDF/cosine similarity over error logs in the persisted-incident RCA route.
- Existing Random Forest failure and Isolation Forest artifacts remain available through their legacy inference route; the coarse legacy classifier is not used as the new subtype model.

## Workflow and Safety

Incident generation retains deterministic failure detection. For API failures and order rejections, it additionally runs the appropriate trained model, appends model output as distinct incident evidence, persists the prediction and model version, and records an audit event. A model output does not replace the rule detector.

Recovery suggestions use a deterministic mapping from the stored model label to a configured `ResolutionEngine` policy. Risk level and approval requirements come from that policy. Recommendation endpoints do not execute actions. The existing incident approval workflow remains responsible for operator decisions. Payment operations are not blindly retried.

Settings can inject synthetic rejection cases for Inventory, Address Validation, Payment, duplicate Order Management requests, and Business Rules. Address normalization and inventory rerouting are medium-risk recommendations requiring operator approval. Payment rejection is escalated without a blind retry. Duplicate and non-fixable business-rule rejection map to high-risk manual review.

Root-cause analysis uses persisted API requests, order events, similar incidents, and stored model predictions. Its evidence-count confidence is a heuristic, not a calibrated probability. Optional LLM use is disabled by default; when enabled it may summarize redacted evidence, but it does not select or execute actions. Local TF-IDF and rule-based analysis remain the fallback.

## Honest Limitations

Training data is synthetic scenario data with generated labels, not observed enterprise outcomes. Synthetic test performance does not establish production accuracy. All classifier scores are marked uncalibrated. Feedback is persisted for review but does not automatically retrain or replace a model. The delay model uses the SLA horizon recorded in its artifact; per-order SLA policies are not persisted. A delay candidate creates an operator-visible order event at most once per five minutes; it does not cause autonomous intervention.

See [MODEL_TRAINING.md](MODEL_TRAINING.md), [MODEL_EVALUATION.md](MODEL_EVALUATION.md), and [AI_API_DOCUMENTATION.md](AI_API_DOCUMENTATION.md).

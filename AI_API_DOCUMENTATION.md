# AI API Documentation

All paths below are under `/api/v2`. JSON bodies are validated with Pydantic. A missing model artifact returns an explicit service error. Model outputs are advisory and do not authorize execution.

## Failure Classification

`POST /ml/predict`

```json
{
  "status_code": 504,
  "response_ms": 30000,
  "service": "Provisioning",
  "endpoint": "/provision/activate",
  "error_message": "gateway timed out waiting for downstream response",
  "retry_count": 0,
  "order_id": null
}
```

Returns subtype, confidence, per-class probabilities, model version, provenance, and a persisted `prediction_id`. The free-text error message is not copied into the prediction feature snapshot.

## Rejection Analysis

`POST /ml/rejections/predict`

Required fields: `status_code`, `service`, `endpoint`, `rejection_reason`, `retry_count`; `alternative_inventory_available` defaults to false and `order_id` is optional.

Returns rejection type, fixability, probabilities/confidence, deterministic suggested action, and `automatic_execution_allowed: false`. Text is excluded from stored feature snapshots.

## Delay Prediction

- `POST /ml/delay-predict`: accepts the validated numeric and stage features for a controlled scenario.
- `POST /ml/orders/{order_id}/delay-predict`: derives features from persisted order, lifecycle event, and API request records; stores the prediction. It records a warning event when the candidate threshold is reached, deduplicated for five minutes. It never performs recovery.

Both return breach probability, risk tier, estimated remaining duration, heuristic bottleneck, contributing factors, model version, evaluation report, synthetic-data provenance, and `automatic_action: false`. Probabilities are uncalibrated.

For `POST /ml/orders/{order_id}/delay-predict`, the order must be active or delayed and its stage must be one of Validation, Inventory, Payment, Provisioning, or Logistics. The endpoint persists the prediction and records a deduplicated order event when a candidate crosses the model threshold. The SLA duration is the trained artifact's configured horizon, not an order-specific stored contract.

## Performance, History, and Feedback

- `GET /ml/metrics`: model availability and persisted held-out evaluation reports.
- `GET /ml/predictions/recent?limit=50`: persisted prediction history; limit is 1 through 200.
- `POST /ml/feedback`: `{ "prediction_id": 1, "actual_label": "API_TIMEOUT", "prediction_correct": true }`. Feedback is audited and stored for future review; it does not retrain the active model.

## RCA and Recovery Recommendation

- `GET /rca/incidents/{incident_id}`: analyzes actual persisted requests/events, similar incidents, and stored model outputs. TF-IDF/cosine similarity is local. `USE_LLM=false` is the default.
- `GET /resolution/recommendations/{incident_id}`: maps stored model output to a deterministic configured policy. Returns risk and approval requirements with `execution_status: not_executed`.
- `POST /rca/analyze` remains available for explicitly supplied evidence.

Synthetic rejection injection accepts the service values `Inventory`, `Address Validation`, `Payment`, `Order Management`, and `Business Rules` using the existing `/simulation/inject-failure` route with category `ORDER_REJECTION`. This is a local demonstration path; payment credentials are not used.

Optional LLM configuration: set `USE_LLM=true`, `OPENAI_API_KEY`, and optionally `LLM_API_BASE_URL` and `LLM_MODEL`. LLM output is explanation-only; recovery actions and their risk are determined by deterministic backend policy. Keep this disabled unless sending redacted log evidence to the configured provider is acceptable.

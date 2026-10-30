"""
Real ML inference service using trained models
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd


ROOT = Path(__file__).parents[3]
MODELS = ROOT / "ml" / "models"


class MLService:
    def __init__(self):
        self.loaded = False
        try:
            self.clf = joblib.load(MODELS / "failure_classifier.joblib")
            self.scaler = joblib.load(MODELS / "scaler.joblib")
            self.le = joblib.load(MODELS / "label_encoder.joblib")
            self.feature_cols = joblib.load(MODELS / "feature_cols.joblib")
            self.iso = joblib.load(MODELS / "anomaly_detector.joblib")
            with open(MODELS / "metrics.json") as f:
                self.metrics = json.load(f)
            self.loaded = True
        except Exception as e:
            self.loaded = False
            self.error = str(e)

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        if not self.loaded:
            return {"ok": False, "error": getattr(self, "error", "models not loaded")}
        df = pd.DataFrame([features])
        cat_cols = ["service", "endpoint", "order_stage"]
        for c in cat_cols:
            if c not in df.columns:
                df[c] = "UNKNOWN"
        df_enc = pd.get_dummies(df, columns=cat_cols)
        for c in self.feature_cols:
            if c not in df_enc.columns:
                df_enc[c] = 0
        X = df_enc[self.feature_cols]
        Xs = self.scaler.transform(X)
        proba = self.clf.predict_proba(Xs)[0]
        pred = int(np.argmax(proba))
        label = self.le.inverse_transform([pred])[0]
        return {
            "ok": True,
            "prediction": label,
            "confidence": float(proba[pred]),
            "probabilities": {cls: float(p) for cls, p in zip(self.le.classes_, proba)},
            "model_type": self.metrics.get("model_type"),
            "model_version": "v1.0.0",
        }

    def anomaly_score(self, features: dict[str, Any]) -> dict[str, Any]:
        if not self.loaded:
            return {"ok": False}
        df = pd.DataFrame([features])
        cat_cols = ["service", "endpoint", "order_stage"]
        for c in cat_cols:
            if c not in df.columns:
                df[c] = "UNKNOWN"
        df_enc = pd.get_dummies(df, columns=cat_cols)
        for c in self.feature_cols:
            if c not in df_enc.columns:
                df_enc[c] = 0
        X = df_enc[self.feature_cols]
        Xs = self.scaler.transform(X)
        score = float(self.iso.decision_function(Xs)[0])  # higher = more normal
        pred = int(self.iso.predict(Xs)[0])  # -1 anomaly
        return {"ok": True, "anomaly": pred == -1, "score": score, "raw": pred}


def load_artifact(name: str) -> dict[str, Any]:
    return joblib.load(MODELS / f"{name}.joblib")


def classify(artifact: dict[str, Any], features: dict[str, Any], minimum_confidence: float = 0.45) -> dict[str, Any]:
    metadata = artifact["metadata"]
    frame = pd.DataFrame([{key: features.get(key) for key in metadata["feature_columns"]}])
    probabilities = artifact["model"].predict_proba(frame)[0]
    classes = list(artifact["model"].classes_)
    best_index = int(np.argmax(probabilities))
    confidence = float(probabilities[best_index])
    prediction = str(classes[best_index]) if confidence >= minimum_confidence else "UNCLASSIFIED"
    return {
        "ok": True,
        "prediction": prediction,
        "confidence": confidence,
        "minimum_confidence": minimum_confidence,
        "low_confidence": prediction == "UNCLASSIFIED",
        "probabilities": {str(label): float(score) for label, score in zip(classes, probabilities)},
        "model_name": metadata["model_name"],
        "model_version": metadata["model_version"],
        "probabilities_calibrated": metadata["probabilities_calibrated"],
        "data_source": metadata["data_source"],
    }


class FailureClassificationService:
    def __init__(self):
        self.loaded = False
        try:
            self.artifact = load_artifact("api_failure_classifier")
            self.metrics = self.artifact["metadata"]
            self.loaded = True
        except Exception as error:
            self.error = str(error)

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        if not self.loaded:
            return {"ok": False, "error": getattr(self, "error", "failure model not loaded")}
        required = self.artifact["metadata"]["feature_columns"]
        missing = [key for key in required if key not in features]
        if missing:
            return {"ok": False, "error": "missing_features", "features": missing}
        numeric = ["status_code", "response_ms", "retry_count"]
        try:
            row = {key: float(features[key]) for key in numeric}
        except (TypeError, ValueError):
            return {"ok": False, "error": "numeric_features_required"}
        if any(not np.isfinite(value) for value in row.values()):
            return {"ok": False, "error": "numeric_features_must_be_finite"}
        row.update(
            {
                "service": str(features["service"])[:48],
                "endpoint": str(features["endpoint"])[:120],
                "error_message": str(features["error_message"])[:1000],
            }
        )
        return classify(self.artifact, row)


class RejectionClassificationService:
    ACTIONS = {
        "INVALID_ADDRESS": "Normalize supported address fields and request confirmation before resubmission.",
        "INVENTORY_ISSUE": "Check alternative inventory locations; require approval before reassignment.",
        "PAYMENT_ISSUE": "Verify payment state with the provider; never retry a payment blindly.",
        "DUPLICATE_ORDER": "Check the existing order and idempotency record; do not create another order.",
        "BUSINESS_RULE_VIOLATION": "Escalate for operator or customer review; do not alter business state automatically.",
    }

    def __init__(self):
        self.loaded = False
        try:
            self.type_artifact = load_artifact("order_rejection_classifier")
            self.fixability_artifact = load_artifact("rejection_fixability")
            self.metrics = {
                "rejection_type": self.type_artifact["metadata"],
                "fixability": self.fixability_artifact["metadata"],
            }
            self.loaded = True
        except Exception as error:
            self.error = str(error)

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        if not self.loaded:
            return {"ok": False, "error": getattr(self, "error", "rejection models not loaded")}
        required = self.type_artifact["metadata"]["feature_columns"]
        missing = [key for key in required if key not in features]
        if missing:
            return {"ok": False, "error": "missing_features", "features": missing}
        try:
            row = {
                "rejection_reason": str(features["rejection_reason"])[:1000],
                "service": str(features["service"])[:48],
                "endpoint": str(features["endpoint"])[:120],
                "status_code": float(features["status_code"]),
                "retry_count": float(features["retry_count"]),
                "alternative_inventory_available": int(bool(features["alternative_inventory_available"])),
            }
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid_rejection_features"}
        if any(not np.isfinite(value) or value < 0 for value in row.values() if isinstance(value, (int, float))):
            return {"ok": False, "error": "numeric_features_must_be_finite_and_nonnegative"}

        type_result = classify(self.type_artifact, row)
        fixability_result = classify(self.fixability_artifact, row)
        fixable = fixability_result["prediction"] == "1"
        type_name = type_result["prediction"]
        return {
            "ok": True,
            "rejection_type": type_name,
            "type_confidence": type_result["confidence"],
            "type_probabilities": type_result["probabilities"],
            "fixability": "FIXABLE" if fixable and not fixability_result["low_confidence"] else (
                "NON_FIXABLE" if not fixable and not fixability_result["low_confidence"] else "REVIEW_REQUIRED"
            ),
            "fixability_confidence": fixability_result["confidence"],
            "fixability_probabilities": fixability_result["probabilities"],
            "requires_manual_intervention": not fixable or type_result["low_confidence"] or fixability_result["low_confidence"],
            "suggested_action": self.ACTIONS.get(type_name, "Escalate for operator review; the model was not confident enough to classify safely."),
            "recommendation_method": "deterministic policy mapping from model outputs",
            "automatic_execution_allowed": False,
            "model_version": {
                "type": self.type_artifact["metadata"]["model_version"],
                "fixability": self.fixability_artifact["metadata"]["model_version"],
            },
            "probabilities_calibrated": False,
            "data_source": self.type_artifact["metadata"]["data_source"],
        }


class DelayPredictionService:
    def __init__(self):
        self.loaded = False
        try:
            self.artifact = joblib.load(MODELS / "delay_predictor.joblib")
            with open(MODELS / "delay_metrics.json", encoding="utf-8") as file:
                self.metrics = json.load(file)
            self.loaded = True
        except Exception as error:
            self.error = str(error)

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        if not self.loaded:
            return {"ok": False, "error": getattr(self, "error", "delay model not loaded")}

        numeric_features = self.artifact["features"][:-1]
        missing = [key for key in self.artifact["features"] if key not in features]
        if missing:
            return {"ok": False, "error": "missing_features", "features": missing}
        try:
            row = {key: float(features[key]) for key in numeric_features}
        except (TypeError, ValueError):
            return {"ok": False, "error": "numeric_features_required"}
        if any(not np.isfinite(value) or value < 0 for value in row.values()):
            return {"ok": False, "error": "numeric_features_must_be_finite_and_nonnegative"}
        row["current_stage"] = str(features["current_stage"]).strip()
        if not row["current_stage"]:
            return {"ok": False, "error": "current_stage_required"}

        frame = pd.DataFrame([row])
        classes = list(self.artifact["classifier"].classes_)
        probabilities = self.artifact["classifier"].predict_proba(frame)[0]
        breach_probability = float(probabilities[classes.index(1)])
        remaining_ms = max(
            0.0,
            float(self.artifact["regressor"].predict(frame)[0]),
        )
        threshold = self.artifact["alert_probability_threshold"]
        risk = (
            "LOW" if breach_probability < 0.2 else
            "MEDIUM" if breach_probability < 0.4 else
            "HIGH" if breach_probability < 0.7 else
            "CRITICAL"
        )
        contributing_factors = [
            f"Elapsed processing: {row['processing_duration_ms']:.0f} ms",
            f"Queue depth: {row['queue_depth']:.0f}",
            f"Service latency: {row['service_latency_ms']:.0f} ms versus historical {row['historical_service_latency_ms']:.0f} ms",
            f"SLA utilization: {row['sla_utilization']:.2f}",
        ]
        if row["queue_depth"] >= 80:
            bottleneck = "queue backlog"
            action = "Review queue depth and prioritize orders approaching their SLA deadline."
        elif row["service_latency_ms"] > max(500, row["historical_service_latency_ms"] * 1.5):
            bottleneck = "service latency"
            action = "Inspect service latency and route eligible work to a healthy path."
        else:
            bottleneck = f"{row['current_stage'].lower()} processing"
            action = "Monitor this stage and compare its remaining time with the order SLA."
        return {
            "ok": True,
            "sla_breach_probability": breach_probability,
            "estimated_remaining_processing_ms": round(remaining_ms),
            "alert_candidate": breach_probability >= threshold,
            "alert_threshold": threshold,
            "risk_level": risk,
            "automatic_action": False,
            "probabilities_calibrated": False,
            "most_likely_bottleneck": bottleneck,
            "bottleneck_method": "feature-threshold heuristic",
            "contributing_factors": contributing_factors,
            "recommended_preventive_action": action,
            "model_type": self.metrics["model_type"],
            "model_version": self.artifact["model_version"],
            "data_source": self.artifact["data_source"],
            "evaluation": self.metrics,
        }


ml_service = MLService()
failure_classifier = FailureClassificationService()
rejection_classifier = RejectionClassificationService()
delay_prediction_service = DelayPredictionService()

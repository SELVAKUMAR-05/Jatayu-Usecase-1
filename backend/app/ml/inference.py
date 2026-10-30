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


ml_service = MLService()

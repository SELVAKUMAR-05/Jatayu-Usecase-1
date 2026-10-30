"""Train real ML models for OrderFlow Sentinel"""
from __future__ import annotations

import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler


ROOT = Path(__file__).parents[2]
DATA = ROOT / "ml" / "datasets" / "synthetic_training.csv"
OUT = ROOT / "ml" / "models"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    df = pd.read_csv(DATA)
    cat_cols = ["service", "endpoint", "order_stage"]
    df_enc = pd.get_dummies(df, columns=cat_cols)
    feature_cols = [c for c in df_enc.columns if c not in ["request_id", "label", "business_rejected"]]
    X = df_enc[feature_cols].fillna(0)
    y = df_enc["label"]
    le = LabelEncoder()
    y_enc = le.fit_transform(y)
    X_train, X_test, y_train, y_test = train_test_split(X, y_enc, test_size=0.2, random_state=42, stratify=y_enc)
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)
    clf = RandomForestClassifier(n_estimators=200, max_depth=12, random_state=42, class_weight="balanced")
    clf.fit(X_train_s, y_train)
    y_pred = clf.predict(X_test_s)
    report = classification_report(y_test, y_pred, target_names=le.classes_, output_dict=True)
    cm = confusion_matrix(y_test, y_pred).tolist()
    metrics = {
        "model_type": "RandomForestClassifier",
        "classes": le.classes_.tolist(),
        "feature_count": len(feature_cols),
        "precision_macro": precision_score(y_test, y_pred, average="macro"),
        "recall_macro": recall_score(y_test, y_pred, average="macro"),
        "f1_macro": f1_score(y_test, y_pred, average="macro"),
        "classification_report": report,
        "confusion_matrix": cm,
    }
    joblib.dump(clf, OUT / "failure_classifier.joblib")
    joblib.dump(scaler, OUT / "scaler.joblib")
    joblib.dump(le, OUT / "label_encoder.joblib")
    joblib.dump(feature_cols, OUT / "feature_cols.joblib")
    # anomaly
    iso = IsolationForest(n_estimators=200, contamination=0.08, random_state=42)
    iso.fit(X_train_s)
    joblib.dump(iso, OUT / "anomaly_detector.joblib")
    with open(OUT / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)
    print(json.dumps({"ok": True, "f1_macro": metrics["f1_macro"]}, indent=2))


if __name__ == "__main__":
    main()

"""Train and evaluate the synthetic-data order delay predictor."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from ml.datasets.generate_synthetic import generate_delay_dataset


ROOT = Path(__file__).parents[2]
DATA_PATH = ROOT / "ml" / "datasets" / "synthetic_delay_training.csv"
MODEL_PATH = ROOT / "ml" / "models" / "delay_predictor.joblib"
METRICS_PATH = ROOT / "ml" / "models" / "delay_metrics.json"
NUMERIC_FEATURES = [
    "processing_duration_ms",
    "queue_depth",
    "service_latency_ms",
    "previous_stage_duration_ms",
    "historical_service_latency_ms",
    "sla_utilization",
]
FEATURES = [*NUMERIC_FEATURES, "current_stage"]


def main() -> None:
    dataset = pd.DataFrame(generate_delay_dataset())
    if dataset["sla_breach"].nunique() != 2:
        raise ValueError("Training data must contain both SLA outcome classes")
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(DATA_PATH, index=False)

    train, test = train_test_split(
        dataset,
        test_size=0.2,
        random_state=42,
        stratify=dataset["sla_breach"],
    )
    preprocessor = ColumnTransformer(
        [
            ("numeric", "passthrough", NUMERIC_FEATURES),
            ("stage", OneHotEncoder(handle_unknown="ignore"), ["current_stage"]),
        ]
    )
    classifier = Pipeline(
        [
            ("features", preprocessor),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=200,
                    min_samples_leaf=3,
                    class_weight="balanced_subsample",
                    random_state=42,
                    n_jobs=1,
                ),
            ),
        ]
    )
    regressor = Pipeline(
        [
            ("features", preprocessor),
            (
                "model",
                RandomForestRegressor(
                    n_estimators=200,
                    min_samples_leaf=3,
                    random_state=42,
                    n_jobs=1,
                ),
            ),
        ]
    )
    classifier.fit(train[FEATURES], train["sla_breach"])
    regressor.fit(train[FEATURES], train["remaining_processing_ms"])

    predicted_breach = classifier.predict(test[FEATURES])
    predicted_remaining = regressor.predict(test[FEATURES])
    metrics = {
        "model_type": "RandomForestClassifier+RandomForestRegressor",
        "model_version": "delay-rf-2026.10.1",
        "data_source": "deterministic synthetic scenarios; not production history",
        "dataset_size": int(len(dataset)),
        "train_size": int(len(train)),
        "test_size": int(len(test)),
        "features": FEATURES,
        "breach_classifier": {
            "precision": float(precision_score(test["sla_breach"], predicted_breach, zero_division=0)),
            "recall": float(recall_score(test["sla_breach"], predicted_breach, zero_division=0)),
            "f1": float(f1_score(test["sla_breach"], predicted_breach, zero_division=0)),
            "report": classification_report(
                test["sla_breach"],
                predicted_breach,
                labels=[0, 1],
                target_names=["within_sla", "sla_breach"],
                output_dict=True,
                zero_division=0,
            ),
            "confusion_matrix": confusion_matrix(
                test["sla_breach"], predicted_breach, labels=[0, 1]
            ).tolist(),
        },
        "remaining_time_regressor": {
            "mae_ms": float(mean_absolute_error(test["remaining_processing_ms"], predicted_remaining)),
            "rmse_ms": float(np.sqrt(mean_squared_error(test["remaining_processing_ms"], predicted_remaining))),
        },
        "probabilities_calibrated": False,
    }
    artifact = {
        "classifier": classifier,
        "regressor": regressor,
        "features": FEATURES,
        "model_version": metrics["model_version"],
        "sla_deadline_ms": 120000,
        "alert_probability_threshold": 0.8,
        "data_source": metrics["data_source"],
    }
    joblib.dump(artifact, MODEL_PATH)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "metrics": metrics}, indent=2))


if __name__ == "__main__":
    main()
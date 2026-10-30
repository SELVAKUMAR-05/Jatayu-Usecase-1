"""Train synthetic API failure and order rejection classifiers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.datasets.generate_synthetic import (
    generate_failure_classification_dataset,
    generate_rejection_dataset,
)


ROOT = Path(__file__).parents[2]
DATA_DIR = ROOT / "ml" / "datasets"
MODEL_DIR = ROOT / "ml" / "models"
SPLIT_SEED = 42


def split_dataset(frame: pd.DataFrame, target: str):
    train, remainder = train_test_split(
        frame,
        test_size=0.30,
        random_state=SPLIT_SEED,
        stratify=frame[target],
    )
    validation, test = train_test_split(
        remainder,
        test_size=0.50,
        random_state=SPLIT_SEED,
        stratify=remainder[target],
    )
    return train, validation, test


def build_pipeline(text_feature: str, categorical_features: list[str], numeric_features: list[str]):
    preprocessor = ColumnTransformer(
        transformers=[
            ("message", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True), text_feature),
            ("categorical", OneHotEncoder(handle_unknown="ignore"), categorical_features),
            ("numeric", StandardScaler(), numeric_features),
        ],
        remainder="drop",
    )
    return Pipeline(
        [
            ("features", preprocessor),
            ("classifier", LogisticRegression(max_iter=600, class_weight="balanced", random_state=SPLIT_SEED)),
        ]
    )


def evaluate(model: Pipeline, features: pd.DataFrame, labels: pd.Series) -> dict:
    predictions = model.predict(features)
    classes = [value.item() if hasattr(value, "item") else value for value in model.classes_]
    return {
        "accuracy": float(accuracy_score(labels, predictions)),
        "precision_macro": float(precision_score(labels, predictions, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(labels, predictions, average="macro", zero_division=0)),
        "f1_macro": float(f1_score(labels, predictions, average="macro", zero_division=0)),
        "classification_report": classification_report(labels, predictions, labels=classes, output_dict=True, zero_division=0),
        "confusion_matrix": confusion_matrix(labels, predictions, labels=classes).tolist(),
        "class_order": classes,
        "records": int(len(labels)),
    }


def train_multiclass(name: str, frame: pd.DataFrame, target: str, text_feature: str,
                     categorical_features: list[str], numeric_features: list[str], version: str) -> dict:
    train, validation, test = split_dataset(frame, target)
    feature_columns = [text_feature, *categorical_features, *numeric_features]
    model = build_pipeline(text_feature, categorical_features, numeric_features)
    model.fit(train[feature_columns], train[target])
    metadata = {
        "model_name": name,
        "model_version": version,
        "model_type": "TfidfVectorizer+OneHotEncoder+LogisticRegression",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "data_source": "seeded synthetic scenarios; labels are scenario annotations, not production outcomes",
        "feature_columns": feature_columns,
        "target": target,
        "train_records": int(len(train)),
        "validation": evaluate(model, validation[feature_columns], validation[target]),
        "test": evaluate(model, test[feature_columns], test[target]),
        "probabilities_calibrated": False,
    }
    artifact = {"model": model, "metadata": metadata}
    joblib.dump(artifact, MODEL_DIR / f"{name}.joblib")
    (MODEL_DIR / f"{name}_metrics.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def train_binary_fixability(frame: pd.DataFrame) -> dict:
    train, validation, test = split_dataset(frame, "fixable")
    feature_columns = [
        "rejection_reason", "service", "endpoint", "status_code", "retry_count",
        "alternative_inventory_available",
    ]
    model = build_pipeline(
        "rejection_reason",
        ["service", "endpoint"],
        ["status_code", "retry_count", "alternative_inventory_available"],
    )
    model.fit(train[feature_columns], train["fixable"])
    metadata = {
        "model_name": "rejection_fixability",
        "model_version": "rejection-fixability-2026.10.1",
        "model_type": "TfidfVectorizer+OneHotEncoder+LogisticRegression",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "data_source": "seeded synthetic scenarios; labels are scenario annotations, not production outcomes",
        "feature_columns": feature_columns,
        "target": "fixable",
        "train_records": int(len(train)),
        "validation": evaluate(model, validation[feature_columns], validation["fixable"]),
        "test": evaluate(model, test[feature_columns], test["fixable"]),
        "probabilities_calibrated": False,
    }
    joblib.dump({"model": model, "metadata": metadata}, MODEL_DIR / "rejection_fixability.joblib")
    (MODEL_DIR / "rejection_fixability_metrics.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    failure_data = pd.DataFrame(generate_failure_classification_dataset())
    rejection_data = pd.DataFrame(generate_rejection_dataset())
    failure_data.to_csv(DATA_DIR / "synthetic_failure_classification.csv", index=False)
    rejection_data.to_csv(DATA_DIR / "synthetic_rejection_classification.csv", index=False)

    failure_metrics = train_multiclass(
        "api_failure_classifier", failure_data, "label", "error_message",
        ["service", "endpoint"], ["status_code", "response_ms", "retry_count"],
        "api-failure-tfidf-lr-2026.10.1",
    )
    rejection_type_metrics = train_multiclass(
        "order_rejection_classifier", rejection_data, "rejection_type", "rejection_reason",
        ["service", "endpoint"], ["status_code", "retry_count", "alternative_inventory_available"],
        "order-rejection-tfidf-lr-2026.10.1",
    )
    fixability_metrics = train_binary_fixability(rejection_data)
    summary = {
        "api_failure_classifier_test": failure_metrics["test"],
        "order_rejection_classifier_test": rejection_type_metrics["test"],
        "rejection_fixability_test": fixability_metrics["test"],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
"""train.py — Train expanded TriageFlow AI model."""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split

from data import FEATURE_COLUMNS, LABELS, generate_data

MODEL_PATH = Path("triage_model.pkl")
METADATA_PATH = Path("triage_model_metadata.json")


def main() -> None:
    df = generate_data()
    X = df[FEATURE_COLUMNS]
    y = df["urgency"]

    stratify = y if y.nunique() > 1 and y.value_counts().min() >= 2 else None
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=stratify)

    model = RandomForestClassifier(n_estimators=350, max_depth=14, min_samples_leaf=2, class_weight="balanced_subsample", random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    joblib.dump(model, MODEL_PATH)

    metadata = {
        "model_type": "RandomForestClassifier",
        "model_version": "v4.0-expanded-synthea-governance",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_rows": int(len(df)),
        "data_source": str(df["source"].iloc[0]) if "source" in df.columns and len(df) else "unknown",
        "features": FEATURE_COLUMNS,
        "labels": LABELS,
        "test_accuracy": round(float(accuracy), 4),
        "target_note": "Urgency labels are derived from Synthea encounter context, vitals, symptoms, comorbidities, and rule-based triage risk scoring.",
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("Model trained successfully.")
    print(f"Rows: {metadata['training_rows']}")
    print(f"Data source: {metadata['data_source']}")
    print(f"Accuracy: {metadata['test_accuracy']}")
    print(classification_report(y_test, y_pred, target_names=[LABELS[i] for i in sorted(LABELS)], zero_division=0))


if __name__ == "__main__":
    main()

"""model.py — model loading wrapper for TriageFlow AI."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd

DEFAULT_FEATURE_COLUMNS = [
    "age", "sex", "temperature", "heart_rate", "respiratory_rate", "spo2",
    "systolic_bp", "diastolic_bp", "pain_score", "fever", "chest_pain",
    "breathing", "headache", "fatigue", "vomiting", "bleeding", "seizure",
    "confusion", "abdominal_pain", "weakness", "diabetes", "hypertension",
    "asthma_copd", "heart_disease",
]


class TriageModel:
    def __init__(self, path: str = "triage_model.pkl"):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"{self.path} not found. Run `python train.py` in the backend folder first.")
        self.model = joblib.load(self.path)
        self.feature_columns = DEFAULT_FEATURE_COLUMNS

        metadata_path = Path("triage_model_metadata.json")
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                self.feature_columns = metadata.get("features", DEFAULT_FEATURE_COLUMNS)
            except Exception:
                self.feature_columns = DEFAULT_FEATURE_COLUMNS

    def _as_frame(self, X):
        if isinstance(X, pd.DataFrame):
            frame = X.copy()
        else:
            frame = pd.DataFrame(X, columns=self.feature_columns)
        for column in self.feature_columns:
            if column not in frame.columns:
                frame[column] = 0
        return frame[self.feature_columns]

    def predict(self, X):
        return self.model.predict(self._as_frame(X))

    def predict_proba(self, X):
        return self.model.predict_proba(self._as_frame(X))


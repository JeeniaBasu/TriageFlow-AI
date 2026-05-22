"""app.py — TriageFlow AI · Expanded Clinical Reliability & Governance Platform."""

from __future__ import annotations

import json
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from chatbot import medical_chat
from data import FEATURE_COLUMNS
from db import (
    init_db, migrate_db, log_prediction, get_logs, get_all_predictions,
    log_override, get_override_logs, get_evaluation_data, log_shadow_prediction,
    get_shadow_stats, get_trust_metrics, get_retraining_queue, tag_retraining_entry,
)
from explainability import build_trace
from model import TriageModel

app = FastAPI(title="TriageFlow AI — Clinical Reliability & Governance Platform")
init_db()
migrate_db()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

model = TriageModel()
MODEL_VERSION = "v4.0-expanded-synthea"
VALID_LABELS = {"Low", "Medium", "High", "Critical"}
LABELS = {0: "Low", 1: "Medium", 2: "High", 3: "Critical"}
LABEL_ORDER = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}


class Patient(BaseModel):
    age: int = Field(ge=0, le=110)
    sex: int = Field(default=0, ge=0, le=1)
    temperature: float = Field(default=37.0)
    heart_rate: int = Field(default=82, ge=20, le=240)
    respiratory_rate: int = Field(default=16, ge=4, le=60)
    spo2: float = Field(default=98.0, ge=50, le=100)
    systolic_bp: int = Field(default=120, ge=50, le=260)
    diastolic_bp: int = Field(default=80, ge=30, le=160)
    pain_score: int = Field(default=2, ge=0, le=10)
    fever: int = Field(default=0, ge=0, le=1)
    chest_pain: int = Field(default=0, ge=0, le=1)
    breathing: int = Field(default=0, ge=0, le=1)
    headache: int = Field(default=0, ge=0, le=1)
    fatigue: int = Field(default=0, ge=0, le=1)
    vomiting: int = Field(default=0, ge=0, le=1)
    bleeding: int = Field(default=0, ge=0, le=1)
    seizure: int = Field(default=0, ge=0, le=1)
    confusion: int = Field(default=0, ge=0, le=1)
    abdominal_pain: int = Field(default=0, ge=0, le=1)
    weakness: int = Field(default=0, ge=0, le=1)
    diabetes: int = Field(default=0, ge=0, le=1)
    hypertension: int = Field(default=0, ge=0, le=1)
    asthma_copd: int = Field(default=0, ge=0, le=1)
    heart_disease: int = Field(default=0, ge=0, le=1)


class OverrideRequest(Patient):
    patient_log_id: int
    original_prediction: str
    overridden_prediction: str
    confidence: float
    override_reason: Optional[str] = None
    doctor_reason: Optional[str] = None
    clinician_id: Optional[str] = "physician"


class ShadowRequest(BaseModel):
    patient_log_id: int
    ai_prediction: str
    clinician_prediction: str
    confidence: float


def _patient_dict(patient: Patient) -> dict:
    return patient.model_dump() if hasattr(patient, "model_dump") else patient.dict()


def _feature_frame(data: dict) -> pd.DataFrame:
    return pd.DataFrame([{col: data.get(col, 0) for col in FEATURE_COLUMNS}])


@app.get("/")
def home():
    return {"system": "TriageFlow AI — Clinical Reliability & Governance Platform", "version": MODEL_VERSION, "status": "operational", "training_data": "Synthea CSV synthetic EHR encounters", "feature_count": len(FEATURE_COLUMNS)}


@app.post("/predict")
def predict(patient: Patient):
    data = _patient_dict(patient)
    features = _feature_frame(data)
    raw_index = int(model.predict(features)[0])
    probabilities = model.predict_proba(features)[0]
    confidence = float(max(probabilities))
    raw_label = LABELS.get(raw_index, "Low")

    trace, final_prediction = build_trace(**data, model_probabilities=probabilities, model_raw_label=raw_label)
    record_id = log_prediction(data, final_prediction, confidence, trace_json=trace, model_version=MODEL_VERSION)
    return {"id": record_id, "prediction": final_prediction, "confidence": round(confidence, 2), "trace": trace, "model_version": MODEL_VERSION}


@app.post("/chat")
def chat(data: dict):
    return {"response": medical_chat(data.get("message", ""))}


@app.get("/logs")
def logs():
    rows = get_logs(limit=50)
    for row in rows:
        if row.get("trace_json"):
            try:
                row["trace"] = json.loads(row["trace_json"])
            except Exception:
                row["trace"] = None
        else:
            row["trace"] = None
        row.pop("trace_json", None)
    return rows


@app.post("/override-submit")
@app.post("/override")
def override(req: OverrideRequest):
    if req.overridden_prediction not in VALID_LABELS:
        raise HTTPException(status_code=422, detail=f"Must be one of {sorted(VALID_LABELS)}")
    if req.original_prediction not in VALID_LABELS:
        raise HTTPException(status_code=422, detail=f"Original prediction must be one of {sorted(VALID_LABELS)}")
    data = _patient_dict(req)
    log_override(req.patient_log_id, data, req.original_prediction, req.overridden_prediction, req.confidence, req.override_reason, req.doctor_reason, req.clinician_id or "physician")
    return {"status": "override recorded", "original": req.original_prediction, "corrected": req.overridden_prediction, "reason": req.override_reason}


@app.get("/override-logs")
def override_logs():
    return get_override_logs(limit=50)


@app.get("/model-evaluation")
def model_evaluation():
    predictions, overrides = get_evaluation_data()
    dist = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0}
    total_preds = len(predictions)
    conf_sum = 0
    for row in predictions:
        label = row[0]
        conf_sum += row[1] or 0
        if label in dist:
            dist[label] += 1
    avg_confidence = round(conf_sum / total_preds, 3) if total_preds > 0 else 0
    total_overrides = len(overrides)
    override_rate = round(total_overrides / total_preds * 100, 1) if total_preds > 0 else 0

    tracked_cols = ["fever", "chest_pain", "breathing", "headache", "fatigue", "vomiting", "bleeding", "seizure", "confusion", "abdominal_pain", "weakness", "diabetes", "hypertension", "asthma_copd", "heart_disease"]
    symptom_override_counts = {col: 0 for col in tracked_cols}
    reason_counts = {}
    escalations = de_escalations = 0
    confidence_sum = 0

    for row in overrides:
        row_map = {FEATURE_COLUMNS[i]: row[i] for i in range(len(FEATURE_COLUMNS))}
        orig = row[len(FEATURE_COLUMNS)]
        corr = row[len(FEATURE_COLUMNS) + 1]
        conf = row[len(FEATURE_COLUMNS) + 2] or 0
        reason = row[len(FEATURE_COLUMNS) + 3]
        confidence_sum += conf
        for col in tracked_cols:
            if row_map.get(col):
                symptom_override_counts[col] += 1
        if reason:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        diff = LABEL_ORDER.get(corr, 0) - LABEL_ORDER.get(orig, 0)
        if diff > 0: escalations += 1
        elif diff < 0: de_escalations += 1

    avg_confidence_overridden = round(confidence_sum / total_overrides, 3) if total_overrides else None
    return {"total_predictions": total_preds, "total_overrides": total_overrides, "override_rate_pct": override_rate, "avg_confidence": avg_confidence, "prediction_distribution": dist, "symptom_override_counts": symptom_override_counts, "avg_confidence_of_overridden": avg_confidence_overridden, "override_direction": {"escalations": escalations, "de_escalations": de_escalations}, "override_reason_breakdown": reason_counts, "insight": _generate_insight(override_rate, symptom_override_counts, escalations, de_escalations)}


def _generate_insight(override_rate, symptom_counts, escalations, de_escalations):
    top_sym = max(symptom_counts, key=symptom_counts.get) if symptom_counts else None
    parts = []
    if override_rate > 20: parts.append(f"High override rate ({override_rate}%) — model may need retraining.")
    elif override_rate > 5: parts.append(f"Moderate override rate ({override_rate}%) — monitor closely.")
    else: parts.append(f"Low override rate ({override_rate}%) — model performing well.")
    if top_sym and symptom_counts[top_sym] > 0: parts.append(f"Most overridden pattern: {top_sym.replace('_', ' ')}.")
    if escalations > de_escalations: parts.append("Model may be under-predicting risk.")
    elif de_escalations > escalations: parts.append("Model may be over-predicting risk.")
    return " ".join(parts)


@app.get("/trust-metrics")
def trust_metrics(): return get_trust_metrics()
@app.get("/trust-score")
def trust_score(): return get_trust_metrics()
@app.get("/override-analytics")
def override_analytics(): return model_evaluation()
@app.get("/reliability-dashboard")
def reliability_dashboard(): return {"trust_metrics": get_trust_metrics(), "model_evaluation": model_evaluation()}
@app.get("/audit-log")
def audit_log(): return logs()


@app.get("/decision-trace/{patient_log_id}")
def decision_trace(patient_log_id: int):
    rows = get_logs(limit=500)
    for row in rows:
        if row.get("id") == patient_log_id:
            try:
                return {"patient_log_id": patient_log_id, "trace": json.loads(row["trace_json"]) if row.get("trace_json") else None}
            except Exception:
                return {"patient_log_id": patient_log_id, "trace": None}
    raise HTTPException(status_code=404, detail="Patient log not found")


@app.get("/reliability-alerts")
def reliability_alerts():
    metrics = get_trust_metrics()
    alerts = []
    if metrics.get("override_rate", 0) > 20: alerts.append("Override rate exceeded reliability threshold.")
    if metrics.get("high_confidence_overrides", 0) > 0: alerts.append("High-confidence predictions have been overridden.")
    if metrics.get("trust_score", 100) < 75: alerts.append("AI Trust Score has dropped below governance target.")
    return {"alerts": alerts, "count": len(alerts)}


@app.get("/drift-metrics")
def drift_metrics(): return drift_report()


@app.post("/shadow")
def shadow_predict(req: ShadowRequest):
    if req.ai_prediction not in VALID_LABELS or req.clinician_prediction not in VALID_LABELS:
        raise HTTPException(status_code=422, detail="Invalid prediction label")
    log_shadow_prediction(req.patient_log_id, req.ai_prediction, req.clinician_prediction, req.confidence)
    return {"status": "shadow recorded", "agreement": req.ai_prediction == req.clinician_prediction}


@app.get("/shadow-stats")
def shadow_stats(): return get_shadow_stats()
@app.get("/retraining-queue")
def retraining_queue(): return get_retraining_queue()
@app.post("/retraining-queue/{entry_id}/tag")
def tag_entry(entry_id: int, tagged: bool = True):
    tag_retraining_entry(entry_id, tagged)
    return {"status": "tagged", "id": entry_id, "tagged": tagged}


@app.get("/drift-report")
def drift_report():
    rows = get_all_predictions()
    if len(rows) < 10:
        return {"status": "insufficient_data", "message": "Need at least 10 predictions to compute drift.", "drift_alerts": []}
    n = len(rows)
    cutoff = max(1, n // 5)
    recent, baseline = rows[:cutoff], rows[n - cutoff:]
    drift_alerts = []
    tracked = ["fever", "chest_pain", "breathing", "vomiting", "bleeding", "seizure", "confusion", "diabetes", "heart_disease"]
    for key in tracked:
        r_rate = sum(float(r.get(key) or 0) for r in recent) / len(recent)
        b_rate = sum(float(r.get(key) or 0) for r in baseline) / len(baseline)
        if b_rate > 0:
            pct = abs(r_rate - b_rate) / b_rate * 100
            if pct > 20:
                drift_alerts.append({"symptom": key, "baseline_rate": round(b_rate, 3), "recent_rate": round(r_rate, 3), "drift_pct": round(pct, 1), "alert": f"{key.replace('_', ' ').title()} distribution shifted {pct:.0f}%."})
    label_order = ["Low", "Medium", "High", "Critical"]
    def label_dist(subset):
        total = len(subset)
        return {label: sum(1 for r in subset if r["prediction"] == label) / total for label in label_order} if total else {}
    r_dist, b_dist = label_dist(recent), label_dist(baseline)
    pred_drift = []
    for label in label_order:
        r_val, b_val = r_dist.get(label, 0), b_dist.get(label, 0)
        if b_val > 0 and abs(r_val - b_val) / b_val > 0.25:
            pred_drift.append({"label": label, "baseline_pct": round(b_val * 100, 1), "recent_pct": round(r_val * 100, 1), "drift_pct": round(abs(r_val - b_val) / b_val * 100, 1)})
    avg_recent_conf = sum(r["confidence"] or 0 for r in recent) / len(recent)
    avg_baseline_conf = sum(r["confidence"] or 0 for r in baseline) / len(baseline)
    conf_drift = abs(avg_recent_conf - avg_baseline_conf)
    drift_score = min(100, len(drift_alerts) * 15 + len(pred_drift) * 10 + conf_drift * 50)
    return {"status": "ok", "total_predictions_analyzed": n, "drift_score": round(drift_score, 1), "symptom_drift": drift_alerts, "prediction_distribution_drift": pred_drift, "confidence_drift": {"baseline_avg": round(avg_baseline_conf, 3), "recent_avg": round(avg_recent_conf, 3), "delta": round(conf_drift, 3)}, "drift_alerts": [a["alert"] for a in drift_alerts]}

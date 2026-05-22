"""explainability.py — deterministic clinical decision trace for expanded TriageFlow input."""

from __future__ import annotations

import datetime
from typing import Any

LABEL_ORDER = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
LABEL_FROM_ORDER = {v: k for k, v in LABEL_ORDER.items()}
LABELS = ["Low", "Medium", "High", "Critical"]

SYMPTOM_WEIGHTS = {
    "fever": 2, "chest_pain": 5, "breathing": 4, "headache": 1, "fatigue": 1,
    "vomiting": 2, "bleeding": 4, "seizure": 6, "confusion": 5, "abdominal_pain": 2, "weakness": 2,
}
COMORBIDITY_WEIGHTS = {"diabetes": 1, "hypertension": 1, "asthma_copd": 2, "heart_disease": 2}

SAFETY_RULES = [
    {"id": "SR-01", "condition": "spo2 < 90 OR seizure == 1 OR confusion == 1", "action": "Escalate to minimum Critical", "min_label": "Critical"},
    {"id": "SR-02", "condition": "chest_pain == 1 AND (heart_disease == 1 OR breathing == 1)", "action": "Escalate to minimum High", "min_label": "High"},
    {"id": "SR-03", "condition": "systolic_bp < 90 OR systolic_bp > 180", "action": "Escalate to minimum High", "min_label": "High"},
    {"id": "SR-04", "condition": "age > 70 AND fever == 1", "action": "Escalate to minimum Medium", "min_label": "Medium"},
    {"id": "SR-05", "condition": "bleeding == 1 OR respiratory_rate > 28", "action": "Escalate to minimum High", "min_label": "High"},
]


def _num(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _apply_safety_rules(prediction_label: str, p: dict) -> tuple[str, list[dict]]:
    current_order = LABEL_ORDER.get(prediction_label, 0)
    triggered = []

    checks = {
        "SR-01": _num(p.get("spo2"), 98) < 90 or int(p.get("seizure", 0)) == 1 or int(p.get("confusion", 0)) == 1,
        "SR-02": int(p.get("chest_pain", 0)) == 1 and (int(p.get("heart_disease", 0)) == 1 or int(p.get("breathing", 0)) == 1),
        "SR-03": _num(p.get("systolic_bp"), 120) < 90 or _num(p.get("systolic_bp"), 120) > 180,
        "SR-04": int(p.get("age", 35)) > 70 and int(p.get("fever", 0)) == 1,
        "SR-05": int(p.get("bleeding", 0)) == 1 or _num(p.get("respiratory_rate"), 16) > 28,
    }

    for rule in SAFETY_RULES:
        if checks.get(rule["id"], False):
            triggered.append(rule)
            current_order = max(current_order, LABEL_ORDER[rule["min_label"]])
    return LABEL_FROM_ORDER[current_order], triggered


def build_trace(**kwargs):
    """Return (trace_dict, final_prediction). Accepts expanded patient fields plus model outputs."""
    model_probabilities = kwargs.pop("model_probabilities")
    model_raw_label = kwargs.pop("model_raw_label")
    p = dict(kwargs)

    raw_input = {k: p.get(k) for k in [
        "age", "sex", "temperature", "heart_rate", "respiratory_rate", "spo2", "systolic_bp", "diastolic_bp", "pain_score",
        "fever", "chest_pain", "breathing", "headache", "fatigue", "vomiting", "bleeding", "seizure", "confusion",
        "abdominal_pain", "weakness", "diabetes", "hypertension", "asthma_copd", "heart_disease",
    ]}

    age_contribution = 2 if int(p.get("age", 0)) > 60 else 0
    age_step = {
        "step": "age_risk", "description": "Age-based risk adjustment", "value": int(p.get("age", 0)),
        "threshold": 60, "contribution": age_contribution,
        "note": f"Age {'>' if int(p.get('age', 0)) > 60 else '<='} 60 → +{age_contribution} risk points",
    }

    vital_details = []
    vital_score = 0
    vital_rules = [
        ("temperature", _num(p.get("temperature"), 37), lambda v: v >= 38.0 or v <= 35.5, 2, "Abnormal temperature"),
        ("heart_rate", _num(p.get("heart_rate"), 82), lambda v: v > 120 or v < 45, 2, "Abnormal heart rate"),
        ("respiratory_rate", _num(p.get("respiratory_rate"), 16), lambda v: v > 24 or v < 10, 3, "Abnormal respiratory rate"),
        ("spo2", _num(p.get("spo2"), 98), lambda v: v < 92, 5, "Low oxygen saturation"),
        ("systolic_bp", _num(p.get("systolic_bp"), 120), lambda v: v > 180 or v < 90, 3, "Abnormal systolic BP"),
        ("diastolic_bp", _num(p.get("diastolic_bp"), 80), lambda v: v > 120 or v < 50, 2, "Abnormal diastolic BP"),
        ("pain_score", _num(p.get("pain_score"), 2), lambda v: v >= 7, 2, "Severe pain"),
    ]
    for name, value, check, weight, note in vital_rules:
        present = bool(check(value))
        contrib = weight if present else 0
        vital_score += contrib
        vital_details.append({"vital": name, "value": value, "abnormal": present, "weight": weight, "contribution": contrib, "note": note})

    symptom_details = []
    symptom_score = 0
    for symptom, weight in SYMPTOM_WEIGHTS.items():
        present = int(p.get(symptom, 0)) == 1
        contrib = weight if present else 0
        symptom_score += contrib
        symptom_details.append({"symptom": symptom, "present": present, "weight": weight, "contribution": contrib})

    comorbidity_details = []
    comorbidity_score = 0
    for condition, weight in COMORBIDITY_WEIGHTS.items():
        present = int(p.get(condition, 0)) == 1
        contrib = weight if present else 0
        comorbidity_score += contrib
        comorbidity_details.append({"condition": condition, "present": present, "weight": weight, "contribution": contrib})

    probabilities = {LABELS[i]: round(float(prob), 4) for i, prob in enumerate(model_probabilities)}
    final_prediction, triggered_rules = _apply_safety_rules(model_raw_label, p)

    trace = {
        "schema_version": "2.0-expanded",
        "raw_input": raw_input,
        "pipeline": [
            age_step,
            {"step": "vital_scoring", "description": "Abnormal vital sign risk scoring", "vitals": vital_details, "total_score": vital_score},
            {"step": "symptom_scoring", "description": "Weighted symptom risk accumulation", "symptoms": symptom_details, "total_score": symptom_score},
            {"step": "comorbidity_scoring", "description": "Chronic condition risk modifiers", "conditions": comorbidity_details, "total_score": comorbidity_score},
            {"step": "model_inference", "description": "RandomForest probability output", "model_type": "RandomForestClassifier", "probabilities": probabilities, "raw_prediction": model_raw_label, "confidence": round(max(float(x) for x in model_probabilities), 4)},
            {"step": "safety_rules", "description": "Post-model clinical safety overrides", "rules_evaluated": len(SAFETY_RULES), "rules_triggered": triggered_rules, "prediction_changed": final_prediction != model_raw_label, "final_prediction": final_prediction},
            {"step": "final_decision", "description": "Resolved clinical triage decision", "prediction": final_prediction, "timestamp": datetime.datetime.utcnow().isoformat() + "Z"},
        ],
        "final_prediction": final_prediction,
        "confidence": round(max(float(x) for x in model_probabilities), 4),
    }
    return trace, final_prediction


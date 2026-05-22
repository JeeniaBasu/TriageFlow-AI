"""db.py — SQLite database layer for TriageFlow AI expanded clinical triage governance."""

from __future__ import annotations

import json
import sqlite3

DB_NAME = "patients.db"
LABEL_ORDER = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}

FEATURE_COLUMNS = [
    "age", "sex", "temperature", "heart_rate", "respiratory_rate", "spo2", "systolic_bp", "diastolic_bp", "pain_score",
    "fever", "chest_pain", "breathing", "headache", "fatigue", "vomiting", "bleeding", "seizure", "confusion", "abdominal_pain", "weakness",
    "diabetes", "hypertension", "asthma_copd", "heart_disease",
]

OVERRIDE_REASONS = ["False Positive", "False Negative", "Missing Context", "Chronic Condition", "Temporary Symptoms", "Severity Mismatch", "Model Overconfidence", "Other"]


def get_conn():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    feature_defs = ",\n        ".join([f"{col} REAL" if col in {"temperature", "spo2"} else f"{col} INTEGER" for col in FEATURE_COLUMNS])
    c.execute(f"""
    CREATE TABLE IF NOT EXISTS patient_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        {feature_defs},
        prediction TEXT,
        confidence REAL,
        trace_json TEXT,
        model_version TEXT DEFAULT 'v1.0',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    c.execute(f"""
    CREATE TABLE IF NOT EXISTS override_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_log_id INTEGER,
        {feature_defs},
        original_prediction TEXT,
        overridden_prediction TEXT,
        confidence REAL,
        override_reason TEXT,
        doctor_reason TEXT,
        clinician_id TEXT DEFAULT 'physician',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (patient_log_id) REFERENCES patient_logs(id)
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS shadow_predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_log_id INTEGER,
        ai_prediction TEXT,
        clinician_prediction TEXT,
        agreement INTEGER,
        confidence REAL,
        resolved INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (patient_log_id) REFERENCES patient_logs(id)
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS drift_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_date TEXT,
        metric_key TEXT,
        metric_value REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS retraining_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_log_id INTEGER,
        override_log_id INTEGER,
        quality_score REAL DEFAULT 1.0,
        tagged INTEGER DEFAULT 0,
        reviewed INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()


def _table_columns(cursor, table: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _add_column(cursor, table: str, column: str, decl: str):
    existing = _table_columns(cursor, table)
    if column not in existing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def migrate_db():
    conn = get_conn()
    c = conn.cursor()
    for table in ["patient_logs", "override_logs"]:
        for col in FEATURE_COLUMNS:
            decl = "REAL" if col in {"temperature", "spo2"} else "INTEGER"
            _add_column(c, table, col, decl)
    for sql in [
        "ALTER TABLE patient_logs ADD COLUMN trace_json TEXT",
        "ALTER TABLE patient_logs ADD COLUMN model_version TEXT DEFAULT 'v1.0'",
        "ALTER TABLE override_logs ADD COLUMN override_reason TEXT",
        "ALTER TABLE override_logs ADD COLUMN doctor_reason TEXT",
        "ALTER TABLE override_logs ADD COLUMN clinician_id TEXT DEFAULT 'physician'",
        "ALTER TABLE retraining_queue ADD COLUMN quality_score REAL DEFAULT 1.0",
        "ALTER TABLE retraining_queue ADD COLUMN tagged INTEGER DEFAULT 0",
        "ALTER TABLE retraining_queue ADD COLUMN reviewed INTEGER DEFAULT 0",
    ]:
        try:
            c.execute(sql)
        except Exception:
            pass
    conn.commit()
    conn.close()


def _feature_tuple(data: dict) -> tuple:
    return tuple(data.get(col, 0) for col in FEATURE_COLUMNS)


def log_prediction(feature_data: dict, prediction, confidence, trace_json=None, model_version="v1.0"):
    conn = get_conn()
    c = conn.cursor()
    columns = ", ".join(FEATURE_COLUMNS + ["prediction", "confidence", "trace_json", "model_version"])
    placeholders = ", ".join(["?"] * (len(FEATURE_COLUMNS) + 4))
    values = _feature_tuple(feature_data) + (prediction, confidence, json.dumps(trace_json) if trace_json else None, model_version)
    c.execute(f"INSERT INTO patient_logs ({columns}) VALUES ({placeholders})", values)
    conn.commit()
    last_id = c.lastrowid
    conn.close()
    return last_id


def get_logs(limit=20):
    conn = get_conn()
    c = conn.cursor()
    columns = ", ".join(["id"] + FEATURE_COLUMNS + ["prediction", "confidence", "created_at", "trace_json", "model_version"])
    c.execute(f"SELECT {columns} FROM patient_logs ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_all_predictions():
    conn = get_conn()
    c = conn.cursor()
    columns = ", ".join(["id"] + FEATURE_COLUMNS + ["prediction", "confidence", "created_at"])
    c.execute(f"SELECT {columns} FROM patient_logs ORDER BY created_at DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def log_override(patient_log_id, feature_data: dict, original_prediction, overridden_prediction, confidence, override_reason=None, doctor_reason=None, clinician_id="physician"):
    conn = get_conn()
    c = conn.cursor()
    columns = ["patient_log_id"] + FEATURE_COLUMNS + ["original_prediction", "overridden_prediction", "confidence", "override_reason", "doctor_reason", "clinician_id"]
    placeholders = ", ".join(["?"] * len(columns))
    values = (patient_log_id,) + _feature_tuple(feature_data) + (original_prediction, overridden_prediction, confidence, override_reason, doctor_reason, clinician_id)
    c.execute(f"INSERT INTO override_logs ({', '.join(columns)}) VALUES ({placeholders})", values)
    override_id = c.lastrowid
    c.execute("INSERT INTO retraining_queue (patient_log_id, override_log_id, quality_score, tagged) VALUES (?, ?, ?, ?)", (patient_log_id, override_id, 1.0, 0))
    conn.commit()
    conn.close()
    return override_id


def get_override_logs(limit=50):
    conn = get_conn()
    c = conn.cursor()
    columns = ", ".join(["id", "patient_log_id"] + FEATURE_COLUMNS + ["original_prediction", "overridden_prediction", "confidence", "override_reason", "doctor_reason", "clinician_id", "created_at"])
    c.execute(f"SELECT {columns} FROM override_logs ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_evaluation_data():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT prediction, confidence FROM patient_logs")
    predictions = c.fetchall()
    columns = ", ".join(FEATURE_COLUMNS + ["original_prediction", "overridden_prediction", "confidence", "override_reason"])
    c.execute(f"SELECT {columns} FROM override_logs")
    overrides = c.fetchall()
    conn.close()
    return predictions, overrides


def log_shadow_prediction(patient_log_id, ai_prediction, clinician_prediction, confidence):
    conn = get_conn()
    c = conn.cursor()
    agreement = int(ai_prediction == clinician_prediction)
    c.execute("INSERT INTO shadow_predictions (patient_log_id, ai_prediction, clinician_prediction, agreement, confidence) VALUES (?, ?, ?, ?, ?)", (patient_log_id, ai_prediction, clinician_prediction, agreement, confidence))
    conn.commit()
    conn.close()


def get_shadow_stats():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT agreement, confidence FROM shadow_predictions")
    rows = c.fetchall()
    conn.close()
    total = len(rows)
    if total == 0:
        return {"total": 0, "agreement_rate": 0, "disagreements": 0, "avg_confidence": None}
    agreements = sum(r[0] for r in rows)
    avg_conf = sum(r[1] or 0 for r in rows) / total
    return {"total": total, "agreement_rate": round(agreements / total * 100, 1), "disagreements": total - agreements, "avg_confidence": round(avg_conf, 3)}


def get_trust_metrics():
    predictions, overrides = get_evaluation_data()
    total_predictions = len(predictions)
    total_overrides = len(overrides)
    override_rate = round((total_overrides / total_predictions * 100), 1) if total_predictions else 0
    high_confidence_overrides = sum(1 for row in overrides if (row[len(FEATURE_COLUMNS) + 2] or 0) >= 0.90)
    escalations = de_escalations = 0
    for row in overrides:
        orig = row[len(FEATURE_COLUMNS)]
        corr = row[len(FEATURE_COLUMNS) + 1]
        diff = LABEL_ORDER.get(corr, 0) - LABEL_ORDER.get(orig, 0)
        if diff > 0: escalations += 1
        elif diff < 0: de_escalations += 1
    agreement_rate = round(100 - override_rate, 1) if total_predictions else 100
    unsafe_penalty = min(20, high_confidence_overrides * 3)
    override_penalty = min(35, override_rate * 0.5)
    mismatch_penalty = min(10, abs(escalations - de_escalations) * 1.5)
    trust_score = max(0, round(100 - override_penalty - unsafe_penalty - mismatch_penalty, 1))
    reliability_index = max(0, round((trust_score + agreement_rate) / 2, 1))
    return {"trust_score": trust_score, "agreement_rate": agreement_rate, "override_rate": override_rate, "reliability_index": reliability_index, "total_predictions": total_predictions, "total_overrides": total_overrides, "high_confidence_overrides": high_confidence_overrides, "escalations": escalations, "de_escalations": de_escalations}


def get_retraining_queue():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    SELECT rq.id, rq.patient_log_id, rq.override_log_id, rq.quality_score, rq.tagged, rq.reviewed, rq.created_at,
           ol.original_prediction, ol.overridden_prediction, ol.override_reason, ol.doctor_reason
    FROM retraining_queue rq
    LEFT JOIN override_logs ol ON rq.override_log_id = ol.id
    ORDER BY rq.created_at DESC
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def tag_retraining_entry(entry_id: int, tagged: bool = True):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE retraining_queue SET tagged = ? WHERE id = ?", (int(tagged), entry_id))
    conn.commit()
    conn.close()

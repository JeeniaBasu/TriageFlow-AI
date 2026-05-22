
"""
data.py — TriageFlow AI
Synthea-powered expanded clinical triage dataset builder.

The model uses a richer but still UI-friendly clinical intake contract:
- demographics: age, sex
- vitals: temperature, heart_rate, respiratory_rate, spo2, systolic_bp, diastolic_bp, pain_score
- symptoms: fever, chest_pain, breathing, headache, fatigue, vomiting, bleeding, seizure, confusion, abdominal_pain, weakness
- comorbidities: diabetes, hypertension, asthma_copd, heart_disease

Expected dataset location:
backend/datasets/synthea/*.csv
or backend/synthea_sample_data_csv_nov2021.zip
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

RANDOM_SEED = 42
LABELS = {0: "Low", 1: "Medium", 2: "High", 3: "Critical"}
FEATURE_COLUMNS = [
    "age", "sex", "temperature", "heart_rate", "respiratory_rate", "spo2",
    "systolic_bp", "diastolic_bp", "pain_score", "fever", "chest_pain",
    "breathing", "headache", "fatigue", "vomiting", "bleeding", "seizure",
    "confusion", "abdominal_pain", "weakness", "diabetes", "hypertension",
    "asthma_copd", "heart_disease",
]

BASE_DIR = Path(__file__).resolve().parent
SYNTHEA_DIR = BASE_DIR / "datasets" / "synthea"

FEVER_TERMS = ["fever", "influenza", "infection", "pneumonia", "covid", "bronchitis", "pharyngitis", "sepsis"]
CHEST_TERMS = ["chest", "coronary", "cardiac", "heart", "myocardial", "angina"]
BREATHING_TERMS = ["asthma", "copd", "bronchitis", "pneumonia", "dyspnea", "respiratory", "shortness", "lung"]
HEADACHE_TERMS = ["headache", "migraine", "concussion", "dizziness", "stroke", "seizure"]
FATIGUE_TERMS = ["fatigue", "anemia", "depression", "heart failure", "diabetes", "chronic", "cancer"]
VOMITING_TERMS = ["vomit", "nausea", "gastroenteritis"]
BLEEDING_TERMS = ["bleeding", "hemorrhage", "laceration", "wound"]
SEIZURE_TERMS = ["seizure", "epilepsy", "convulsion"]
CONFUSION_TERMS = ["confusion", "altered mental", "delirium", "dementia", "syncope"]
ABDOMINAL_TERMS = ["abdominal", "appendicitis", "stomach", "gastritis", "gastro"]
WEAKNESS_TERMS = ["weakness", "stroke", "syncope", "dizziness", "fatigue"]
DIABETES_TERMS = ["diabetes", "diabetic", "hyperglycemia"]
HYPERTENSION_TERMS = ["hypertension", "blood pressure"]
ASTHMA_COPD_TERMS = ["asthma", "copd", "chronic obstructive", "emphysema", "bronchitis"]
HEART_DISEASE_TERMS = ["heart", "cardiac", "coronary", "myocardial", "angina", "heart failure"]
SEVERE_TERMS = ["sepsis", "cardiac arrest", "stroke", "overdose", "pneumonia", "appendicitis", "fracture", "burn", "concussion", "malignant", "seizure"]


def _contains_any(text: str, terms: Iterable[str]) -> int:
    text = str(text).lower()
    return int(any(term in text for term in terms))


def _candidate_csv_dirs() -> list[Path]:
    here = BASE_DIR
    cwd = Path.cwd()
    return [
        here / "datasets" / "synthea", here / "data", here / "data" / "csv", here / "csv", here / "synthea", here / "synthea" / "csv",
        cwd / "datasets" / "synthea", cwd / "data", cwd / "data" / "csv", cwd / "csv", cwd / "synthea", cwd / "synthea" / "csv",
    ]


def _candidate_zip_paths() -> list[Path]:
    names = ["synthea_sample_data_csv_nov2021.zip", "synthea_sample_data_csv.zip", "synthea_csv.zip"]
    roots = [BASE_DIR, BASE_DIR / "data", BASE_DIR / "datasets", BASE_DIR / "datasets" / "synthea", Path.cwd(), Path.cwd() / "data", Path.cwd() / "datasets", Path.cwd() / "datasets" / "synthea"]
    return [root / name for root in roots for name in names]


def _find_extracted_csv_dir() -> Path | None:
    required = ["patients.csv", "encounters.csv", "conditions.csv"]
    for candidate in _candidate_csv_dirs():
        if all((candidate / file).exists() for file in required):
            return candidate
    return None


def _find_synthea_zip() -> Path | None:
    for path in _candidate_zip_paths():
        if path.exists():
            return path
    return None


def _read_csv_from_source(filename: str, usecols=None) -> pd.DataFrame:
    csv_dir = _find_extracted_csv_dir()
    if csv_dir:
        return pd.read_csv(csv_dir / filename, usecols=usecols, low_memory=False)

    zip_path = _find_synthea_zip()
    if zip_path:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            possible_members = [filename, f"csv/{filename}", f"synthea_sample_data_csv_nov2021/csv/{filename}", f"synthea_sample_data_csv_nov2021/{filename}"]
            member = next((m for m in possible_members if m in names), None)
            if member is None:
                raise FileNotFoundError(f"{filename} not found inside {zip_path}")
            with zf.open(member) as file:
                return pd.read_csv(file, usecols=usecols, low_memory=False)

    raise FileNotFoundError(f"Synthea CSV dataset not found. Expected CSV files at: {SYNTHEA_DIR}")


def _age_at_encounter(birthdate: pd.Series, encounter_start: pd.Series) -> pd.Series:
    birth = pd.to_datetime(birthdate, errors="coerce", utc=True)
    start = pd.to_datetime(encounter_start, errors="coerce", utc=True)
    return (((start - birth).dt.days / 365.25).fillna(35).clip(lower=0, upper=105).round().astype(int))


def _extract_vitals() -> pd.DataFrame:
    """Fast encounter-level vitals extraction from Synthea observations."""
    try:
        obs = _read_csv_from_source("observations.csv", usecols=["ENCOUNTER", "DESCRIPTION", "VALUE"])
    except Exception:
        return pd.DataFrame(columns=["ENCOUNTER", "temperature", "heart_rate", "respiratory_rate", "spo2", "systolic_bp", "diastolic_bp", "pain_score"])

    obs = obs.dropna(subset=["ENCOUNTER", "DESCRIPTION"])
    obs["desc"] = obs["DESCRIPTION"].astype(str).str.lower()
    obs["num"] = pd.to_numeric(obs["VALUE"], errors="coerce")
    obs = obs.dropna(subset=["num"])

    masks = {
        "temperature": obs["desc"].str.contains("body temperature|temperature", regex=True, na=False),
        "heart_rate": obs["desc"].str.contains("heart rate", regex=True, na=False),
        "respiratory_rate": obs["desc"].str.contains("respiratory rate", regex=True, na=False),
        "spo2": obs["desc"].str.contains("oxygen saturation", regex=True, na=False),
        "systolic_bp": obs["desc"].str.contains("systolic blood pressure", regex=True, na=False),
        "diastolic_bp": obs["desc"].str.contains("diastolic blood pressure", regex=True, na=False),
        "pain_score": obs["desc"].str.contains("pain severity|pain", regex=True, na=False),
    }

    frames = []
    for feature, mask in masks.items():
        sub = obs.loc[mask, ["ENCOUNTER", "num"]]
        if not sub.empty:
            frames.append(sub.groupby("ENCOUNTER", as_index=False)["num"].last().rename(columns={"num": feature}))

    if not frames:
        return pd.DataFrame(columns=["ENCOUNTER", "temperature", "heart_rate", "respiratory_rate", "spo2", "systolic_bp", "diastolic_bp", "pain_score"])

    out = frames[0]
    for frame in frames[1:]:
        out = out.merge(frame, on="ENCOUNTER", how="outer")
    return out

def _fallback_synthetic(n: int = 8000) -> pd.DataFrame:
    np.random.seed(RANDOM_SEED)
    df = pd.DataFrame({
        "age": np.random.randint(1, 95, n),
        "sex": np.random.binomial(1, 0.5, n),
        "temperature": np.random.normal(37, 0.9, n).clip(34, 41),
        "heart_rate": np.random.normal(82, 22, n).clip(35, 180),
        "respiratory_rate": np.random.normal(16, 5, n).clip(6, 40),
        "spo2": np.random.normal(97, 4, n).clip(70, 100),
        "systolic_bp": np.random.normal(122, 28, n).clip(70, 220),
        "diastolic_bp": np.random.normal(78, 18, n).clip(40, 140),
        "pain_score": np.random.randint(0, 11, n),
        "fever": np.random.binomial(1, 0.25, n),
        "chest_pain": np.random.binomial(1, 0.13, n),
        "breathing": np.random.binomial(1, 0.18, n),
        "headache": np.random.binomial(1, 0.25, n),
        "fatigue": np.random.binomial(1, 0.35, n),
        "vomiting": np.random.binomial(1, 0.12, n),
        "bleeding": np.random.binomial(1, 0.06, n),
        "seizure": np.random.binomial(1, 0.025, n),
        "confusion": np.random.binomial(1, 0.05, n),
        "abdominal_pain": np.random.binomial(1, 0.14, n),
        "weakness": np.random.binomial(1, 0.16, n),
        "diabetes": np.random.binomial(1, 0.13, n),
        "hypertension": np.random.binomial(1, 0.20, n),
        "asthma_copd": np.random.binomial(1, 0.09, n),
        "heart_disease": np.random.binomial(1, 0.08, n),
    })
    return _label_dataframe(df, context_bonus=pd.Series(np.zeros(n, dtype=int)), source="fallback_synthetic_expanded")


def _label_dataframe(df: pd.DataFrame, context_bonus: pd.Series | int = 0, source: str = "synthea_csv_ehr_expanded") -> pd.DataFrame:
    risk = (
        (df["temperature"] >= 38.0).astype(int) * 2
        + ((df["heart_rate"] > 120) | (df["heart_rate"] < 45)).astype(int) * 2
        + ((df["respiratory_rate"] > 24) | (df["respiratory_rate"] < 10)).astype(int) * 3
        + (df["spo2"] < 92).astype(int) * 5
        + ((df["systolic_bp"] > 180) | (df["systolic_bp"] < 90)).astype(int) * 3
        + ((df["diastolic_bp"] > 120) | (df["diastolic_bp"] < 50)).astype(int) * 2
        + (df["pain_score"] >= 7).astype(int) * 2
        + df["fever"] * 2
        + df["chest_pain"] * 5
        + df["breathing"] * 4
        + df["headache"] * 1
        + df["fatigue"] * 1
        + df["vomiting"] * 2
        + df["bleeding"] * 4
        + df["seizure"] * 6
        + df["confusion"] * 5
        + df["abdominal_pain"] * 2
        + df["weakness"] * 2
        + df["diabetes"] * 1
        + df["hypertension"] * 1
        + df["asthma_copd"] * 2
        + df["heart_disease"] * 2
        + (df["age"] > 60).astype(int) * 2
        + pd.Series(context_bonus, index=df.index).fillna(0).astype(int)
    )
    df = df.copy()
    df["risk"] = risk.astype(int)
    df["urgency"] = df["risk"].apply(lambda x: 0 if x <= 4 else 1 if x <= 8 else 2 if x <= 13 else 3)
    df["source"] = source
    for col in FEATURE_COLUMNS + ["risk", "urgency"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int if col not in {"temperature"} else float)
    return df[FEATURE_COLUMNS + ["risk", "urgency", "source"]]


def generate_data(n: int | None = None, prefer_synthea: bool = True) -> pd.DataFrame:
    if not prefer_synthea:
        return _fallback_synthetic(n or 8000)

    try:
        csv_dir = _find_extracted_csv_dir()
        if csv_dir:
            print(f"[data.py] Using Synthea CSV directory: {csv_dir}")
        else:
            zip_path = _find_synthea_zip()
            if zip_path:
                print(f"[data.py] Using Synthea zip file: {zip_path}")
            else:
                raise FileNotFoundError(f"Synthea CSV dataset not found at {SYNTHEA_DIR}")

        patients = _read_csv_from_source("patients.csv", usecols=["Id", "BIRTHDATE", "GENDER"])
        encounters = _read_csv_from_source("encounters.csv", usecols=["Id", "START", "PATIENT", "ENCOUNTERCLASS", "DESCRIPTION", "REASONDESCRIPTION"])
        conditions = _read_csv_from_source("conditions.csv", usecols=["ENCOUNTER", "DESCRIPTION"])
    except Exception as exc:
        print(f"[data.py] Synthea dataset not found or unreadable ({exc}). Falling back to generated synthetic data.")
        return _fallback_synthetic(n or 8000)

    encounters = encounters.rename(columns={"Id": "ENCOUNTER"})
    patients = patients.rename(columns={"Id": "PATIENT"})
    df = encounters.merge(patients, on="PATIENT", how="left")
    df["age"] = _age_at_encounter(df["BIRTHDATE"], df["START"])
    df["sex"] = df["GENDER"].astype(str).str.upper().map({"M": 1, "F": 0}).fillna(0).astype(int)

    cond_text = conditions.dropna(subset=["ENCOUNTER"]).groupby("ENCOUNTER")["DESCRIPTION"].apply(lambda values: " | ".join(map(str, values))).reset_index(name="condition_text")
    df = df.merge(cond_text, on="ENCOUNTER", how="left")
    df["condition_text"] = df["condition_text"].fillna("")
    df["clinical_text"] = (df["DESCRIPTION"].fillna("").astype(str) + " | " + df["REASONDESCRIPTION"].fillna("").astype(str) + " | " + df["condition_text"].astype(str)).str.lower()

    for col, terms in {
        "fever": FEVER_TERMS, "chest_pain": CHEST_TERMS, "breathing": BREATHING_TERMS, "headache": HEADACHE_TERMS,
        "fatigue": FATIGUE_TERMS, "vomiting": VOMITING_TERMS, "bleeding": BLEEDING_TERMS, "seizure": SEIZURE_TERMS,
        "confusion": CONFUSION_TERMS, "abdominal_pain": ABDOMINAL_TERMS, "weakness": WEAKNESS_TERMS,
        "diabetes": DIABETES_TERMS, "hypertension": HYPERTENSION_TERMS, "asthma_copd": ASTHMA_COPD_TERMS, "heart_disease": HEART_DISEASE_TERMS,
    }.items():
        df[col] = df["clinical_text"].apply(lambda text, terms=terms: _contains_any(text, terms))

    df["severe_condition"] = df["clinical_text"].apply(lambda text: _contains_any(text, SEVERE_TERMS))

    vitals = _extract_vitals()
    if not vitals.empty:
        df = df.merge(vitals, on="ENCOUNTER", how="left")
    for col, default in {"temperature": 37.0, "heart_rate": 82.0, "respiratory_rate": 16.0, "spo2": 98.0, "systolic_bp": 120.0, "diastolic_bp": 80.0, "pain_score": 2.0}.items():
        if col not in df.columns:
            df[col] = default
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(default)

    class_risk = df["ENCOUNTERCLASS"].astype(str).str.lower().map({"wellness": 0, "ambulatory": 1, "outpatient": 1, "urgentcare": 2, "emergency": 4, "inpatient": 4}).fillna(1).astype(int)
    context_bonus = (class_risk + df["severe_condition"] * 2).clip(upper=5)

    out = _label_dataframe(df, context_bonus=context_bonus, source="synthea_csv_ehr_expanded").dropna().reset_index(drop=True)
    if n is not None and len(out) > n:
        out = out.sample(n=n, random_state=RANDOM_SEED)
    if len(out) < 100:
        print("[data.py] Synthea-derived data too small. Falling back to generated synthetic data.")
        return _fallback_synthetic(n or 8000)
    return out.reset_index(drop=True)


if __name__ == "__main__":
    data = generate_data()
    print(data.head())
    print(data["urgency"].value_counts().sort_index())
    print(f"Rows: {len(data)} | Source: {data['source'].iloc[0]}")

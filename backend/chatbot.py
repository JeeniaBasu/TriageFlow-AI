import requests
import re

OLLAMA_URL = "http://localhost:11434/api/generate"


# =========================================================
# 1. RULE-BASED TRIAGE (TRUTH LAYER)
# =========================================================
def rule_based_triage(text):
    text = text.lower()

    score = 0
    department = "General Medicine"

    emergency_keywords = [
        "breathing", "shortness of breath", "cannot breathe",
        "chest pain", "chest tightness"
    ]

    neuro_keywords = ["dizziness", "headache", "fainting", "blurred vision"]
    fever_keywords = ["fever", "high temperature"]

    if any(k in text for k in emergency_keywords):
        score = 10
        department = "Emergency"

    if "chest" in text:
        score = max(score, 8)
        department = "Cardiology"

    if any(k in text for k in neuro_keywords):
        score = max(score, 5)
        department = "Neurology"

    if any(k in text for k in fever_keywords):
        score = max(score, 4)

    if score >= 9:
        urgency = "Critical"
    elif score >= 6:
        urgency = "High"
    elif score >= 3:
        urgency = "Medium"
    else:
        urgency = "Low"

    return urgency, department, score


# =========================================================
# 2. ULTRA-STABLE LLM SUMMARIZER (MINIMAL PROMPT)
# =========================================================
def get_llm_explanation(user_input):

    # IMPORTANT: no instructions, no rules, no negatives
    prompt = f"""
Patient symptoms:
{user_input}

Rewrite into 2 sentences:
1. Symptoms only
2. Medical concern
"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": "tinyllama",
                "prompt": prompt,
                "stream": False
            }
        )

        text = response.json().get("response", "").strip()
        text = clean_text(text)

        if not is_valid(text):
            return fallback_explanation(user_input)

        return text

    except Exception:
        return fallback_explanation(user_input)


# =========================================================
# 3. CLEAN TEXT
# =========================================================
def clean_text(text):
    text = re.sub(r"[^\x00-\x7F]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# =========================================================
# 4. VALIDATION (BLOCK META / PROMPT ECHO)
# =========================================================
def is_valid(text):
    t = text.lower()

    forbidden = [
        "instruction", "rule", "format", "assistant",
        "instead", "focus", "do not", "purpose"
    ]

    if any(f in t for f in forbidden):
        return False

    if len(text.split()) < 6:
        return False

    return True


# =========================================================
# 5. SAFE FALLBACK
# =========================================================
def fallback_explanation(user_input):
    return (
    "The reported symptoms may indicate a medical condition "
    "requiring professional clinical assessment."
)


# =========================================================
# 6. NEXT STEP MAPPING
# =========================================================
def get_next_step(urgency):
    return {
        "Critical": "Seek emergency medical attention immediately.",
        "High": "Urgent medical consultation required within hours.",
        "Medium": "Schedule a medical appointment soon.",
        "Low": "Monitor symptoms and consider routine consultation."
    }.get(urgency, "Consult a healthcare professional.")


# =========================================================
# 7. MAIN FUNCTION (SINGLE SOURCE OF TRUTH OUTPUT)
# =========================================================
def medical_chat(user_input):

    urgency, department, score = rule_based_triage(user_input)
    explanation = get_llm_explanation(user_input)
    next_step = get_next_step(urgency)

    return {
        "urgency": urgency,
        "department": department,
        "severity_score": score,
        "explanation": explanation,
        "next_step": next_step
    }
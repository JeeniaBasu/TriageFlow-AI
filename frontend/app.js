/* ══════════════════════════════════════════════════════════
   TriageFlow AI — Clinical Reliability & Governance Platform
   app.js · v2.1 — STABLE PATCH
   ══════════════════════════════════════════════════════════ */

const API = "http://127.0.0.1:8000";
const TRIAGEFLOW_STATE_KEY = "triageflow.ui.state.v2";

// ── Stable frontend state ─────────────────────────────────
const AppState = {
  currentSection: "command",
  lastPrediction: null,
  lastInputs: null,
  isPredicting: false,
  isRefreshing: false,
};

let charts = {};

// ══════════════════════════════════════════════════════════
// BOOT
// ══════════════════════════════════════════════════════════

window.addEventListener("DOMContentLoaded", () => {
  restorePersistentState();
  bindNavigation();
  bindActionButtons();
  bindKeyboardShortcuts();
  initSlider();
  syncSymptomChipStates();

  // Prevent any accidental form submit from refreshing the page and resetting to Command Center.
  document.addEventListener("submit", (event) => {
    event.preventDefault();
    event.stopPropagation();
    return false;
  }, true);

  const initialSection = AppState.currentSection || "command";
  navTo(initialSection, null, { initial: true, noRefresh: true });

  // If Live Server reloads the page because patients.db changed, restore the last triage result immediately.
  if (AppState.lastPrediction) {
    renderTriageOutput(AppState.lastPrediction, AppState.lastInputs || getPatientInputPayload());
  }

  refreshAll();
  if (initialSection === "evaluation") loadEvaluation();
  if (initialSection === "drift") loadDrift();
  if (initialSection === "shadow") loadShadowStats();
  if (initialSection === "logs") loadLogs();
  if (initialSection === "overrides") loadOverrideLogs();
  if (initialSection === "retraining") loadRetraining();
});

function bindNavigation() {
  document.querySelectorAll(".nav-item").forEach((el) => {
    el.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const section = el.dataset.section;
      if (section) navTo(section, event);
    });
  });
}

function bindActionButtons() {
  const actions = [
    ["predictBtn", runTriage],
    ["overrideToggle", toggleOverride],
    ["overrideSubmitBtn", submitOverride],
    ["shadowSubmitBtn", submitShadow],
    ["chatSendBtn", sendChat],
    ["commandRefreshBtn", refreshAll],
    ["evaluationRefreshBtn", refreshEvaluation],
    ["driftRefreshBtn", refreshDrift],
    ["shadowRefreshBtn", refreshShadow],
    ["logsRefreshBtn", refreshLogs],
    ["overrideLogsRefreshBtn", refreshOverrideLogs],
    ["retrainingRefreshBtn", refreshRetraining],
    ["traceToggle", toggleTrace],
  ];

  actions.forEach(([id, handler]) => {
    const el = document.getElementById(id);
    if (!el) return;
    // Remove inline onclick behavior so one click cannot fire duplicate handlers.
    el.onclick = null;
    el.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      handler(event);
    });
  });
}

function bindKeyboardShortcuts() {
  const chatInput = document.getElementById("chatInput");
  if (chatInput) {
    chatInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendChat(event);
      }
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeTraceModal(event);
  });
}

function initSlider() {
  const slider = document.getElementById("age");
  const val = document.getElementById("ageVal");
  if (!slider || !val) return;
  val.textContent = slider.value;
  slider.addEventListener("input", () => { val.textContent = slider.value; });
}

function syncSymptomChipStates() {
  document.querySelectorAll(".sym-chip input[type='checkbox']").forEach((input) => {
    const label = input.closest(".sym-chip");
    if (!label) return;
    const sync = () => label.classList.toggle("checked", input.checked);
    input.addEventListener("change", sync);
    sync();
  });
}

// ══════════════════════════════════════════════════════════
// NAVIGATION — no hash, no scroll, no focus steal
// ══════════════════════════════════════════════════════════

function navTo(name, event = null, options = {}) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }

  if (!name) return;
  const targetSection = document.getElementById(`sec-${name}`);
  if (!targetSection) return;

  document.querySelectorAll(".section").forEach((section) => {
    section.classList.toggle("active", section.id === `sec-${name}`);
  });

  document.querySelectorAll(".nav-item").forEach((nav) => {
    nav.classList.toggle("active", nav.dataset.section === name);
  });

  AppState.currentSection = name;
  persistAppState();

  // Explicitly keep the page from jumping. No scrollIntoView, no hash routing.
  if (!options.initial && window.location.hash) {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }

  if (options.noRefresh) return;

  if (name === "command") refreshAll();
  if (name === "evaluation") loadEvaluation();
  if (name === "drift") loadDrift();
  if (name === "shadow") loadShadowStats();
  if (name === "logs") loadLogs();
  if (name === "overrides") loadOverrideLogs();
  if (name === "retraining") loadRetraining();
}

// ══════════════════════════════════════════════════════════
// REFRESH PIPELINE
// ══════════════════════════════════════════════════════════

async function refreshAll(event = null) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  const btn = document.getElementById("commandRefreshBtn");
  return withButtonLoading(btn, "Refreshing...", async () => {
    AppState.isRefreshing = true;
    const results = await Promise.allSettled([
      loadTrustMetrics(),
      loadCommandCharts(),
      AppState.currentSection === "logs" ? loadLogs() : Promise.resolve(),
      AppState.currentSection === "overrides" ? loadOverrideLogs() : Promise.resolve(),
    ]);
    AppState.isRefreshing = false;
    const failed = results.filter((r) => r.status === "rejected").length;
    if (failed) toast("Some dashboard data could not be refreshed", "warn");
    return results;
  });
}

async function refreshEvaluation(event = null) {
  prevent(event);
  const btn = document.getElementById("evaluationRefreshBtn");
  return withButtonLoading(btn, "Refreshing...", async () => {
    await Promise.allSettled([loadEvaluation(), loadTrustMetrics(), loadCommandCharts()]);
  });
}

async function refreshDrift(event = null) {
  prevent(event);
  const btn = document.getElementById("driftRefreshBtn");
  return withButtonLoading(btn, "Analyzing...", loadDrift);
}

async function refreshShadow(event = null) {
  prevent(event);
  const btn = document.getElementById("shadowRefreshBtn");
  return withButtonLoading(btn, "Refreshing...", loadShadowStats);
}

async function refreshLogs(event = null) {
  prevent(event);
  const btn = document.getElementById("logsRefreshBtn");
  return withButtonLoading(btn, "Refreshing...", loadLogs);
}

async function refreshOverrideLogs(event = null) {
  prevent(event);
  const btn = document.getElementById("overrideLogsRefreshBtn");
  return withButtonLoading(btn, "Refreshing...", loadOverrideLogs);
}

async function refreshRetraining(event = null) {
  prevent(event);
  const btn = document.getElementById("retrainingRefreshBtn");
  return withButtonLoading(btn, "Refreshing...", loadRetraining);
}

// ══════════════════════════════════════════════════════════
// TRUST METRICS
// ══════════════════════════════════════════════════════════

async function loadTrustMetrics() {
  try {
    const data = await apiFetch("/trust-metrics");

    const arc = document.getElementById("trustRingArc");
    if (arc) {
      const circ = 326.7;
      const pct = (Number(data.trust_score) || 0) / 100;
      arc.style.strokeDashoffset = circ - circ * pct;
      arc.style.stroke = pct > 0.7 ? "url(#trustGrad)" : pct > 0.4 ? "#f59e0b" : "#ef4444";
    }

    setText("trustScoreVal", `${data.trust_score ?? "—"}%`);
    setText("tAgreement", `${data.agreement_rate ?? "—"}%`);
    setText("tOverrideRate", `${data.override_rate ?? "—"}%`);
    setText("tReliability", `${data.reliability_index ?? "—"}%`);

    setText("kpiTotal", data.total_predictions ?? "—");
    setText("kpiTotalSub", "Model version v2.0");
    setText("kpiAgreement", `${data.agreement_rate ?? "—"}%`);
    setText("kpiOverrides", data.total_overrides ?? "—");
    setText("kpiEscalations", data.escalations ?? "—");
    setText("kpiDeEsc", data.de_escalations ?? "—");

    setBarWidth("highConfBar", ((data.high_confidence_overrides || 0) / Math.max(data.total_predictions || 1, 1)) * 100);
    setBarWidth("agreementBar", data.agreement_rate || 0);
    setBarWidth("reliabilityBar", data.reliability_index || 0);
    setBarWidth("overrideRateBar", Math.min(data.override_rate || 0, 100));

    setText("highConfPct", `${data.high_confidence_overrides ?? 0}`);
    setText("agreementPct", `${data.agreement_rate ?? "—"}%`);
    setText("reliabilityPct", `${data.reliability_index ?? "—"}%`);
    setText("overrideRatePct", `${data.override_rate ?? "—"}%`);
  } catch (error) {
    console.warn("Trust metrics error:", error.message);
    setText("trustScoreVal", "Offline");
  }
}

// ══════════════════════════════════════════════════════════
// COMMAND CENTER CHARTS
// ══════════════════════════════════════════════════════════

async function loadCommandCharts() {
  try {
    const [evalData, logs] = await Promise.all([
      apiFetch("/model-evaluation"),
      apiFetch("/logs"),
    ]);

    if (logs && logs.length > 0) {
      const avgConf = logs.reduce((sum, row) => sum + (Number(row.confidence) || 0), 0) / logs.length;
      setText("kpiConf", `${(avgConf * 100).toFixed(0)}%`);
      setText("kpiConfSub", "Across recent predictions");
      setText("kpiAgreementSub", `${logs.length} prediction logs`);
    } else {
      setText("kpiConf", "—");
      setText("kpiConfSub", "No predictions yet");
    }

    buildDoughnutChart("riskChart", evalData.prediction_distribution || {}, {
      Low: "#22c55e", Medium: "#f59e0b", High: "#ef4444", Critical: "#dc2626",
    });

    buildBarChart("symptomChart", evalData.symptom_override_counts || {},
      Object.keys(evalData.symptom_override_counts || {}).map(() => "#38bdf8"),
      "Overrides by Symptom");

    buildDoughnutChart("overrideDirChart", {
      Escalations: evalData.override_direction?.escalations || 0,
      "De-escalations": evalData.override_direction?.de_escalations || 0,
    }, { Escalations: "#ef4444", "De-escalations": "#22c55e" });

    buildBarChart("symptomOverrideChart", evalData.symptom_override_counts || {},
      Object.keys(evalData.symptom_override_counts || {}).map(() => "#f59e0b"),
      "Override Count");

    buildBarChart("reasonChart", evalData.override_reason_breakdown || {},
      Object.keys(evalData.override_reason_breakdown || {}).map(() => "#a78bfa"),
      "Count");
  } catch (error) {
    console.warn("Command charts error:", error.message);
  }
}

// ══════════════════════════════════════════════════════════
// LIVE TRIAGE
// ══════════════════════════════════════════════════════════

async function runTriage(event = null) {
  prevent(event);
  navTo("triage", null, { silent: true });

  if (AppState.isPredicting) return;

  const payload = getPatientInputPayload();
  AppState.lastInputs = payload;
  persistAppState();

  const btn = document.getElementById("predictBtn");
  await withButtonLoading(btn, "Processing...", async () => {
    AppState.isPredicting = true;
    try {
      const res = await apiFetch("/predict", "POST", payload);
      AppState.lastPrediction = res;
      window.lastPrediction = res;
      AppState.currentSection = "triage";
      persistAppState();
      renderTriageOutput(res, payload);
      toast("Prediction recorded with full audit trace", "success");

      // Refresh governance metrics without navigating away or replacing triage DOM.
      Promise.allSettled([loadTrustMetrics(), loadCommandCharts()]);
    } catch (error) {
      toast("Backend error: " + error.message, "error");
      console.error("Triage error:", error);
    } finally {
      AppState.isPredicting = false;
    }
  });
}

function getPatientInputPayload() {
  return {
    age: parseInt(getValue("age", 35), 10),
    sex: parseInt(getValue("sex", 0), 10),
    temperature: parseFloat(getValue("temperature", 37.0)),
    heart_rate: parseInt(getValue("heartRate", 82), 10),
    respiratory_rate: parseInt(getValue("respiratoryRate", 16), 10),
    spo2: parseFloat(getValue("spo2", 98)),
    systolic_bp: parseInt(getValue("systolicBp", 120), 10),
    diastolic_bp: parseInt(getValue("diastolicBp", 80), 10),
    pain_score: parseInt(getValue("painScore", 2), 10),
    fever: isChecked("fever") ? 1 : 0,
    chest_pain: isChecked("chest") ? 1 : 0,
    breathing: isChecked("breathing") ? 1 : 0,
    headache: isChecked("headache") ? 1 : 0,
    fatigue: isChecked("fatigue") ? 1 : 0,
    vomiting: isChecked("vomiting") ? 1 : 0,
    bleeding: isChecked("bleeding") ? 1 : 0,
    seizure: isChecked("seizure") ? 1 : 0,
    confusion: isChecked("confusion") ? 1 : 0,
    abdominal_pain: isChecked("abdominalPain") ? 1 : 0,
    weakness: isChecked("weakness") ? 1 : 0,
    diabetes: isChecked("diabetes") ? 1 : 0,
    hypertension: isChecked("hypertension") ? 1 : 0,
    asthma_copd: isChecked("asthmaCopd") ? 1 : 0,
    heart_disease: isChecked("heartDisease") ? 1 : 0,
  };
}

function renderTriageOutput(res, inputs) {
  const pred = res.prediction || "Low";
  const conf = Number(res.confidence || 0);
  const trace = res.trace || null;

  const badge = document.getElementById("urgencyBadge");
  if (badge) {
    badge.textContent = `${pred.toUpperCase()} RISK`;
    badge.className = `urgency-badge ${pred.toLowerCase()}`;
  }

  setText("confidenceChip", `${(conf * 100).toFixed(0)}% confidence`);

  const barPct = { Low: 15, Medium: 40, High: 72, Critical: 100 }[pred] || 0;
  const bar = document.getElementById("riskBarFill");
  if (bar) {
    bar.style.width = `${barPct}%`;
    bar.style.background = urgencyColor(pred);
  }

  const deptMap = {
    Low: "General Medicine",
    Medium: "Outpatient Clinic",
    High: "Urgent Care",
    Critical: "Emergency / ICU",
  };
  const actionMap = {
    Low: "Self-care monitoring. Schedule routine follow-up if symptoms persist.",
    Medium: "Medical appointment within 24–48 hours recommended.",
    High: "Urgent consultation required within hours. Escalate to senior physician.",
    Critical: "Immediate emergency intervention required. Alert emergency team.",
  };

  setText("department", deptMap[pred] || "—");
  setText("action", actionMap[pred] || "—");

  renderTraceSummary(trace);
  renderTraceCards(trace);

  showElement("explainerSection", true);
  showElement("overrideSection", true);
  showElement("shadowPanel", true);

  const traceExpanded = document.getElementById("traceExpanded");
  const traceToggle = document.getElementById("traceToggle");
  if (traceExpanded) traceExpanded.style.display = "none";
  if (traceToggle) traceToggle.textContent = "View Decision Trace";

  const traceEl = document.getElementById("traceJSON");
  if (traceEl) traceEl.textContent = trace ? JSON.stringify(trace, null, 2) : "No trace available.";

  const overrideForm = document.getElementById("overrideForm");
  if (overrideForm) {
    overrideForm.classList.remove("open");
    overrideForm.style.display = "none";
  }

  setText("overrideOriginalPrediction", `${pred} (${(conf * 100).toFixed(0)}% confidence)`);
  setText("overrideStatus", "");

  const overrideLabelEl = document.getElementById("overrideLabel");
  if (overrideLabelEl) overrideLabelEl.value = pred;

  const overrideReasonEl = document.getElementById("overrideReason");
  if (overrideReasonEl) overrideReasonEl.value = "";

  const overrideNotesEl = document.getElementById("overrideNotes");
  if (overrideNotesEl) overrideNotesEl.value = "";

  if (pred === "Critical") {
    const banner = document.getElementById("criticalBanner");
    const msg = document.getElementById("criticalMsg");
    if (banner && msg) {
      msg.textContent = "Patient triage classified as CRITICAL. Immediate emergency escalation required.";
      banner.style.display = "flex";
    }
  }
}

function renderTraceSummary(trace) {
  const listEl = document.getElementById("explanationList");
  if (!listEl) return;
  listEl.innerHTML = "";

  const pipeline = trace?.pipeline || [];
  const items = [];

  pipeline.forEach((step) => {
    if (step.step === "age_risk" && Number(step.contribution) > 0) {
      items.push({ text: `Age ${step.value} > ${step.threshold}: +${step.contribution} risk pts`, danger: false });
    }
    if (step.step === "vital_scoring" && Array.isArray(step.vitals)) {
      step.vitals.filter((vital) => vital.abnormal).forEach((vital) => {
        items.push({ text: `${labelize(vital.vital)} ${vital.value} → +${vital.contribution} risk pts`, danger: Number(vital.contribution) >= 3 });
      });
    }
    if (step.step === "symptom_scoring" && Array.isArray(step.symptoms)) {
      step.symptoms.filter((sym) => sym.present).forEach((sym) => {
        items.push({ text: `${labelize(sym.symptom)} → +${sym.contribution} risk pts`, danger: Number(sym.contribution) >= 4 });
      });
    }
    if (step.step === "comorbidity_scoring" && Array.isArray(step.conditions)) {
      step.conditions.filter((c) => c.present).forEach((c) => {
        items.push({ text: `${labelize(c.condition)} history → +${c.contribution} risk pts`, danger: false });
      });
    }
    if (step.step === "safety_rules" && Array.isArray(step.rules_triggered) && step.rules_triggered.length > 0) {
      step.rules_triggered.forEach((rule) => items.push({ text: `Safety rule ${rule.id}: ${rule.action}`, danger: true }));
    }
    if (step.step === "final_decision") {
      items.push({ text: `Final decision: ${step.prediction}`, danger: step.prediction === "Critical" });
    }
  });

  if (items.length === 0) items.push({ text: "No major risk factors detected in current intake.", danger: false });

  items.forEach((item) => {
    const li = document.createElement("li");
    li.className = "explanation-item";
    li.textContent = item.text;
    if (item.danger) li.style.borderLeftColor = "#ef4444";
    listEl.appendChild(li);
  });
}

function renderTraceCards(trace) {
  const cardsEl = document.getElementById("traceCards");
  if (!cardsEl) return;

  const pipeline = trace?.pipeline || [];
  if (!pipeline.length) {
    cardsEl.innerHTML = `<div class="trace-card"><strong>No decision trace available.</strong></div>`;
    return;
  }

  cardsEl.innerHTML = pipeline.map((step, index) => {
    let body = "";

    if (step.step === "age_risk") {
      body = `
        <div class="trace-row"><span>Age</span><strong>${safe(step.value)}</strong></div>
        <div class="trace-row"><span>Threshold</span><strong>${safe(step.threshold)}</strong></div>
        <div class="trace-row"><span>Contribution</span><strong>+${safe(step.contribution)} pts</strong></div>
        <p>${escapeHTML(step.note || step.description || "")}</p>`;
    } else if (step.step === "vital_scoring") {
      const rows = (step.vitals || []).map((vital) => `
        <div class="trace-row ${vital.abnormal ? "active" : ""}">
          <span>${labelize(vital.vital)} (${safe(vital.value)})</span>
          <strong>${vital.abnormal ? "+" + vital.contribution + " pts" : "0 pts"}</strong>
        </div>`).join("");
      body = `${rows}<div class="trace-row total"><span>Total vital score</span><strong>${safe(step.total_score)}</strong></div>`;
    } else if (step.step === "symptom_scoring") {
      const rows = (step.symptoms || []).map((sym) => `
        <div class="trace-row ${sym.present ? "active" : ""}">
          <span>${labelize(sym.symptom)}</span>
          <strong>${sym.present ? "+" + sym.contribution + " pts" : "0 pts"}</strong>
        </div>`).join("");
      body = `${rows}<div class="trace-row total"><span>Total symptom score</span><strong>${safe(step.total_score)}</strong></div>`;
    } else if (step.step === "comorbidity_scoring") {
      const rows = (step.conditions || []).map((condition) => `
        <div class="trace-row ${condition.present ? "active" : ""}">
          <span>${labelize(condition.condition)}</span>
          <strong>${condition.present ? "+" + condition.contribution + " pts" : "0 pts"}</strong>
        </div>`).join("");
      body = `${rows}<div class="trace-row total"><span>Total comorbidity score</span><strong>${safe(step.total_score)}</strong></div>`;
    } else if (step.step === "model_inference") {
      const probs = step.probabilities || {};
      body = Object.keys(probs).map((key) => `
        <div class="trace-row">
          <span>${escapeHTML(key)}</span>
          <strong>${(Number(probs[key]) * 100).toFixed(0)}%</strong>
        </div>`).join("");
      body += `<div class="trace-row total"><span>Raw model prediction</span><strong>${escapeHTML(step.raw_prediction || "—")}</strong></div>`;
    } else if (step.step === "safety_rules") {
      const triggered = step.rules_triggered || [];
      body = `
        <div class="trace-row"><span>Rules evaluated</span><strong>${safe(step.rules_evaluated)}</strong></div>
        <div class="trace-row"><span>Prediction changed</span><strong>${step.prediction_changed ? "Yes" : "No"}</strong></div>
        <div class="trace-row total"><span>Final after safety layer</span><strong>${escapeHTML(step.final_prediction || "—")}</strong></div>
        ${triggered.length ? triggered.map((rule) => `<p>⚠ ${escapeHTML(rule.id)} — ${escapeHTML(rule.action)}</p>`).join("") : "<p>No safety override triggered.</p>"}`;
    } else if (step.step === "final_decision") {
      body = `
        <div class="trace-row total"><span>Prediction</span><strong>${escapeHTML(step.prediction || "—")}</strong></div>
        <div class="trace-row"><span>Timestamp</span><strong>${formatDate(step.timestamp)}</strong></div>`;
    } else {
      body = `<pre class="trace-mini-json">${escapeHTML(JSON.stringify(step, null, 2))}</pre>`;
    }

    return `
      <article class="trace-card">
        <div class="trace-card-head">
          <span class="trace-step-num">${index + 1}</span>
          <div>
            <strong>${labelize(step.step || "Trace step")}</strong>
            <small>${escapeHTML(step.description || "")}</small>
          </div>
        </div>
        <div class="trace-card-body">${body}</div>
      </article>`;
  }).join("");
}

function toggleTrace(event = null) {
  prevent(event);
  const expanded = document.getElementById("traceExpanded");
  const btn = document.getElementById("traceToggle");
  if (!expanded || !btn) return;

  const isOpen = expanded.style.display !== "none";
  expanded.style.display = isOpen ? "none" : "block";
  btn.textContent = isOpen ? "View Decision Trace" : "Hide Decision Trace";
}

function toggleOverride(event = null) {
  prevent(event);
  const form = document.getElementById("overrideForm");
  if (!form) return;
  const shouldOpen = !form.classList.contains("open");
  form.classList.toggle("open", shouldOpen);
  form.style.display = shouldOpen ? "flex" : "none";

  if (shouldOpen && AppState.lastPrediction) {
    setText("overrideOriginalPrediction", `${AppState.lastPrediction.prediction} (${(Number(AppState.lastPrediction.confidence || 0) * 100).toFixed(0)}% confidence)`);
  }
}

async function submitOverride(event = null) {
  prevent(event);
  if (!AppState.lastPrediction) {
    toast("Run a triage prediction first", "warn");
    return;
  }

  const label = getValue("overrideLabel");
  const reason = getValue("overrideReason");
  const notes = getValue("overrideNotes");

  if (!label) {
    toast("Select a corrected classification", "warn");
    return;
  }
  if (!reason) {
    toast("Select an override reason", "warn");
    return;
  }

  const inputs = AppState.lastInputs || getPatientInputPayload();
  const payload = {
    patient_log_id: AppState.lastPrediction.id,
    ...inputs,
    original_prediction: AppState.lastPrediction.prediction,
    overridden_prediction: label,
    confidence: AppState.lastPrediction.confidence,
    override_reason: reason,
    doctor_reason: notes || null,
    clinician_id: "physician",
  };

  const submitBtn = document.getElementById("overrideSubmitBtn");
  await withButtonLoading(submitBtn, "Saving...", async () => {
    try {
      await apiFetch("/override", "POST", payload);
      setText("overrideStatus", `✓ Override recorded: ${AppState.lastPrediction.prediction} → ${label}`);
      const form = document.getElementById("overrideForm");
      if (form) {
        form.classList.remove("open");
        form.style.display = "none";
      }
      toast(`Override logged: ${AppState.lastPrediction.prediction} → ${label}`, "success");

      await Promise.allSettled([
        loadTrustMetrics(),
        loadCommandCharts(),
        loadEvaluation(),
        loadOverrideLogs(),
        loadLogs(),
        loadRetraining(),
      ]);
    } catch (error) {
      toast("Override error: " + error.message, "error");
      console.error("Override error:", error);
    }
  });
}

async function submitShadow(event = null) {
  prevent(event);
  if (!AppState.lastPrediction) {
    toast("Run a triage prediction first", "warn");
    return;
  }

  const clinician = getValue("shadowClinician");
  const payload = {
    patient_log_id: AppState.lastPrediction.id,
    ai_prediction: AppState.lastPrediction.prediction,
    clinician_prediction: clinician,
    confidence: AppState.lastPrediction.confidence,
  };

  const btn = document.getElementById("shadowSubmitBtn");
  await withButtonLoading(btn, "Saving...", async () => {
    try {
      const res = await apiFetch("/shadow", "POST", payload);
      const msg = res.agreement ? "Agreement recorded ✓" : "Disagreement recorded — flagged for analysis";
      setText("shadowStatus", msg);
      toast("Shadow validation saved", "success");
      loadShadowStats();
    } catch (error) {
      toast("Shadow error: " + error.message, "error");
    }
  });
}

// ══════════════════════════════════════════════════════════
// CHATBOT
// ══════════════════════════════════════════════════════════

const CRITICAL_PHRASES = [
  "cannot breathe", "can't breathe", "chest pain", "heart attack",
  "unconscious", "not responding", "seizure", "collapse", "severe pain",
  "suicidal", "dying", "emergency",
];

async function sendChat(event = null) {
  prevent(event);
  const inputEl = document.getElementById("chatInput");
  const input = inputEl?.value.trim();
  if (!input) return;

  const inputLower = input.toLowerCase();
  const criticalMatch = CRITICAL_PHRASES.find((phrase) => inputLower.includes(phrase));
  if (criticalMatch) {
    const banner = document.getElementById("criticalBanner");
    const msg = document.getElementById("criticalMsg");
    if (banner && msg) {
      msg.textContent = `Critical language detected: "${criticalMatch}" — Emergency escalation triggered.`;
      banner.style.display = "flex";
    }
  }

  appendChatMsg("USER", input, "user");
  if (inputEl) inputEl.value = "";

  const btn = document.getElementById("chatSendBtn");
  await withButtonLoading(btn, "Assessing...", async () => {
    try {
      const res = await apiFetch("/chat", "POST", { message: input });
      const r = res.response || {};
      const lines = [
        `Urgency: <span class="urgency-inline" style="background:${urgencyColor(r.urgency)}22;color:${urgencyColor(r.urgency)}">${escapeHTML(r.urgency || "—")}</span>`,
        `Department: ${escapeHTML(r.department || "—")}`,
        `Severity Score: ${escapeHTML(String(r.severity_score ?? "—"))}/10`,
        "",
        escapeHTML(r.explanation || "No explanation returned."),
        "",
        `Next Step: ${escapeHTML(r.next_step || "—")}`,
      ].join("\n");
      appendChatMsg("AI ASSESSMENT", lines, "ai", true);
    } catch (error) {
      appendChatMsg("SYSTEM ERROR", "Backend unreachable: " + escapeHTML(error.message), "ai", true);
    }
  });
}

function appendChatMsg(tag, content, type, allowHTML = false) {
  const msgs = document.getElementById("chatMessages");
  if (!msgs) return;
  const div = document.createElement("div");
  div.className = `chat-msg ${type}`;
  const safeContent = allowHTML ? content : escapeHTML(content);
  div.innerHTML = `<span class="chat-tag">${escapeHTML(tag)}</span><span>${safeContent.replace(/\n/g, "<br>")}</span>`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
}

// ══════════════════════════════════════════════════════════
// MODEL EVALUATION
// ══════════════════════════════════════════════════════════

async function loadEvaluation() {
  setText("evalInsight", "Loading evaluation data...");
  try {
    const data = await apiFetch("/model-evaluation");

    setText("evalInsight", data.insight || "—");
    setText("evalOverrideRate", `${data.override_rate_pct ?? "—"}%`);
    setText("evalTotalOverrides", data.total_overrides ?? "—");
    setText("evalAvgConf", data.avg_confidence_of_overridden != null
      ? `${(Number(data.avg_confidence_of_overridden) * 100).toFixed(0)}%`
      : "N/A");
    setText("evalOverrideSub", `of ${data.total_predictions ?? 0} total predictions`);
    setText("evalDirSub", `↑${data.override_direction?.escalations ?? 0} escalations / ↓${data.override_direction?.de_escalations ?? 0} de-escalations`);

    buildDoughnutChart("evalDistChart", data.prediction_distribution || {}, {
      Low: "#22c55e", Medium: "#f59e0b", High: "#ef4444", Critical: "#dc2626",
    });

    buildBarChart("evalReasonChart", data.override_reason_breakdown || {},
      Object.keys(data.override_reason_breakdown || {}).map(() => "#a78bfa"),
      "Count");
  } catch (error) {
    setText("evalInsight", "Backend offline — start FastAPI server.");
    console.warn("Evaluation error:", error.message);
  }
}

// ══════════════════════════════════════════════════════════
// DRIFT MONITOR
// ══════════════════════════════════════════════════════════

async function loadDrift() {
  try {
    const data = await apiFetch("/drift-report");

    const scoreEl = document.getElementById("driftScoreVal");
    if (scoreEl) {
      scoreEl.textContent = data.drift_score != null ? Number(data.drift_score).toFixed(0) : "—";
      const score = Number(data.drift_score || 0);
      scoreEl.style.color = score > 50 ? "#ef4444" : score > 20 ? "#f59e0b" : "#22c55e";
    }

    setText("driftScoreSub", data.status === "insufficient_data"
      ? data.message
      : `Across ${data.total_predictions_analyzed} predictions`);

    const cd = data.confidence_drift;
    if (cd) {
      setText("driftBaseConf", `${(Number(cd.baseline_avg) * 100).toFixed(1)}%`);
      setText("driftRecentConf", `${(Number(cd.recent_avg) * 100).toFixed(1)}%`);
      const deltaEl = document.getElementById("driftDelta");
      if (deltaEl) {
        const delta = Number(cd.delta || 0);
        deltaEl.textContent = `${delta > 0 ? "+" : ""}${(delta * 100).toFixed(1)}%`;
        deltaEl.style.color = delta > 0.05 ? "#ef4444" : delta > 0.02 ? "#f59e0b" : "#22c55e";
      }
    } else {
      setText("driftBaseConf", "—");
      setText("driftRecentConf", "—");
      setText("driftDelta", "—");
    }

    const alertsEl = document.getElementById("driftAlerts");
    if (alertsEl) {
      if (data.drift_alerts && data.drift_alerts.length > 0) {
        alertsEl.innerHTML = data.drift_alerts.map((alert) =>
          `<div class="drift-alert-item">⚠ ${escapeHTML(String(alert))}</div>`).join("");
      } else if (data.status === "insufficient_data") {
        alertsEl.innerHTML = `<div class="drift-placeholder">${escapeHTML(data.message || "Insufficient data")}</div>`;
      } else {
        alertsEl.innerHTML = `<div class="drift-placeholder" style="color:var(--accent)">✓ No significant drift detected.</div>`;
      }
    }

    if (data.prediction_distribution_drift && data.prediction_distribution_drift.length > 0) {
      const labels = data.prediction_distribution_drift.map((d) => d.label);
      const basePcts = data.prediction_distribution_drift.map((d) => d.baseline_pct);
      const recentPcts = data.prediction_distribution_drift.map((d) => d.recent_pct);

      destroyChart("driftDistChart");
      const ctx = document.getElementById("driftDistChart")?.getContext("2d");
      if (ctx) {
        charts.driftDistChart = new Chart(ctx, {
          type: "bar",
          data: {
            labels,
            datasets: [
              { label: "Baseline %", data: basePcts, backgroundColor: "rgba(56,189,248,0.4)", borderColor: "#38bdf8", borderWidth: 1 },
              { label: "Recent %", data: recentPcts, backgroundColor: "rgba(239,68,68,0.4)", borderColor: "#ef4444", borderWidth: 1 },
            ],
          },
          options: chartOptions("Distribution Drift (%)"),
        });
      }
    } else {
      destroyChart("driftDistChart");
      setText("driftDistBadge", "No significant drift");
    }
  } catch (error) {
    console.warn("Drift error:", error.message);
    const alertsEl = document.getElementById("driftAlerts");
    if (alertsEl) alertsEl.innerHTML = `<div class="drift-placeholder">Backend offline — start FastAPI server.</div>`;
  }
}

// ══════════════════════════════════════════════════════════
// SHADOW STATS
// ══════════════════════════════════════════════════════════

async function loadShadowStats() {
  try {
    const data = await apiFetch("/shadow-stats");
    setText("shadowTotal", data.total ?? "0");
    setText("shadowAgreement", `${data.agreement_rate ?? "—"}%`);
    setText("shadowDisagreements", data.disagreements ?? "0");
    setText("shadowConfidence", data.avg_confidence != null ? `${(Number(data.avg_confidence) * 100).toFixed(0)}%` : "—");
  } catch (error) {
    console.warn("Shadow stats error:", error.message);
  }
}

// ══════════════════════════════════════════════════════════
// LOGS / AUDIT TABLES
// ══════════════════════════════════════════════════════════

async function loadLogs() {
  const tbody = document.getElementById("logsTableBody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="8" class="table-empty">Loading...</td></tr>`;
  try {
    const rows = await apiFetch("/logs");
    if (!rows || rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="table-empty">No predictions yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map((row) => {
      const syms = buildSymStr(row);
      const trace = row.trace ? JSON.stringify(row.trace, null, 2) : null;
      return `<tr>
        <td style="font-family:var(--font-mono);color:var(--text-3)">#${row.id}</td>
        <td>${row.age}</td>
        <td class="sym-icons">${escapeHTML(syms)}</td>
        <td><span class="risk-pill ${escapeHTML(row.prediction)}">${escapeHTML(row.prediction)}</span></td>
        <td style="font-family:var(--font-mono)">${(Number(row.confidence || 0) * 100).toFixed(0)}%</td>
        <td style="font-family:var(--font-mono);color:var(--text-3)">${escapeHTML(row.model_version || "v1.0")}</td>
        <td style="color:var(--text-3)">${formatDate(row.created_at)}</td>
        <td>${trace ? `<button type="button" class="trace-view-btn" data-trace="${encodeTrace(trace)}" onclick="openTraceModalFromButton(this, event)">View</button>` : "—"}</td>
      </tr>`;
    }).join("");
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="8" class="table-empty">Backend offline.</td></tr>`;
  }
}

async function loadOverrideLogs() {
  const tbody = document.getElementById("overrideLogsBody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="9" class="table-empty">Loading...</td></tr>`;
  try {
    const rows = await apiFetch("/override-logs");
    if (!rows || rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" class="table-empty">No overrides recorded yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map((row) => `<tr>
      <td style="font-family:var(--font-mono);color:var(--text-3)">#${row.id}</td>
      <td style="font-family:var(--font-mono)">P#${row.patient_log_id}</td>
      <td><span class="risk-pill ${escapeHTML(row.original_prediction)}">${escapeHTML(row.original_prediction)}</span></td>
      <td><span class="risk-pill ${escapeHTML(row.overridden_prediction)}">${escapeHTML(row.overridden_prediction)}</span></td>
      <td style="max-width:140px;overflow:hidden;text-overflow:ellipsis">${escapeHTML(row.override_reason || "—")}</td>
      <td style="font-family:var(--font-mono);color:var(--text-3)">${escapeHTML(row.clinician_id || "physician")}</td>
      <td style="font-family:var(--font-mono)">${(Number(row.confidence || 0) * 100).toFixed(0)}%</td>
      <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;color:var(--text-2)">${escapeHTML(row.doctor_reason || "—")}</td>
      <td style="color:var(--text-3)">${formatDate(row.created_at)}</td>
    </tr>`).join("");
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="9" class="table-empty">Backend offline.</td></tr>`;
  }
}

async function loadRetraining() {
  const tbody = document.getElementById("retrainingBody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="8" class="table-empty">Loading...</td></tr>`;
  try {
    const rows = await apiFetch("/retraining-queue");
    if (!rows || rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="table-empty">No retraining candidates yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map((row) => `<tr>
      <td style="font-family:var(--font-mono);color:var(--text-3)">#${row.id}</td>
      <td style="font-family:var(--font-mono)">P#${row.patient_log_id}</td>
      <td><span class="risk-pill ${escapeHTML(row.original_prediction)}">${escapeHTML(row.original_prediction)}</span></td>
      <td><span class="risk-pill ${escapeHTML(row.overridden_prediction)}">${escapeHTML(row.overridden_prediction)}</span></td>
      <td style="max-width:140px">${escapeHTML(row.override_reason || "—")}</td>
      <td style="font-family:var(--font-mono)">${Number(row.quality_score || 1).toFixed(1)}</td>
      <td>${row.tagged ? `<span class="tag-btn tagged">✓ Tagged</span>` : `<span class="tag-btn" style="background:var(--bg-3);color:var(--text-3);border-color:var(--border)">Untagged</span>`}</td>
      <td><button type="button" class="tag-btn" onclick="tagEntry(${row.id}, this, event)">${row.tagged ? "Untag" : "Tag for Training"}</button></td>
    </tr>`).join("");
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="8" class="table-empty">Backend offline.</td></tr>`;
  }
}

async function tagEntry(id, btn = null, event = null) {
  prevent(event);
  await withButtonLoading(btn, "Saving...", async () => {
    try {
      await apiFetch(`/retraining-queue/${id}/tag`, "POST");
      toast("Entry tagged for retraining", "success");
      loadRetraining();
    } catch (error) {
      toast("Tag error: " + error.message, "error");
    }
  });
}

// ══════════════════════════════════════════════════════════
// TRACE MODAL
// ══════════════════════════════════════════════════════════

function encodeTrace(trace) {
  return btoa(encodeURIComponent(trace));
}

function decodeTrace(encodedTrace) {
  return decodeURIComponent(atob(encodedTrace));
}

function openTraceModalFromButton(button, event = null) {
  prevent(event);
  openTraceModal(button?.dataset?.trace || "");
}

function openTraceModal(encodedTrace, event = null) {
  prevent(event);
  const modal = document.getElementById("traceModal");
  const content = document.getElementById("traceModalContent");
  if (!modal || !content) return;
  try {
    content.textContent = decodeTrace(encodedTrace);
  } catch (error) {
    content.textContent = "Unable to decode trace.";
  }
  modal.style.display = "flex";
  document.body.classList.add("modal-open");
}

function closeTraceModal(event = null) {
  prevent(event);
  const modal = document.getElementById("traceModal");
  if (modal) modal.style.display = "none";
  document.body.classList.remove("modal-open");
}

// ══════════════════════════════════════════════════════════
// CHART HELPERS
// ══════════════════════════════════════════════════════════

const CHART_DEFAULTS = {
  plugins: {
    legend: {
      labels: { color: "#94a3b8", font: { family: "'JetBrains Mono', monospace", size: 11 }, boxWidth: 12 },
    },
    tooltip: {
      backgroundColor: "#111827",
      borderColor: "rgba(255,255,255,0.08)",
      borderWidth: 1,
      titleColor: "#e2e8f0",
      bodyColor: "#94a3b8",
    },
  },
};

function chartOptions(label) {
  return {
    responsive: true,
    maintainAspectRatio: true,
    plugins: CHART_DEFAULTS.plugins,
    scales: {
      x: { ticks: { color: "#64748b", font: { size: 10 } }, grid: { color: "rgba(255,255,255,0.04)" } },
      y: { beginAtZero: true, ticks: { color: "#64748b", font: { size: 10 } }, grid: { color: "rgba(255,255,255,0.04)" } },
    },
  };
}

function destroyChart(id) {
  if (charts[id]) {
    charts[id].destroy();
    delete charts[id];
  }
}

function buildDoughnutChart(id, data = {}, colorMap = {}) {
  destroyChart(id);
  const ctx = document.getElementById(id)?.getContext("2d");
  if (!ctx || typeof Chart === "undefined") return;

  const labels = Object.keys(data || {});
  const values = Object.values(data || {}).map((value) => Number(value) || 0);
  if (!labels.length || values.every((value) => value === 0)) {
    drawEmptyChart(id, "No data yet");
    return;
  }

  charts[id] = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: labels.map((label) => colorMap[label] ? `${colorMap[label]}40` : "rgba(255,255,255,0.1)"),
        borderColor: labels.map((label) => colorMap[label] || "#64748b"),
        borderWidth: 2,
      }],
    },
    options: { responsive: true, cutout: "68%", plugins: CHART_DEFAULTS.plugins },
  });
}

function buildBarChart(id, data = {}, colors = [], label = "Count") {
  destroyChart(id);
  const ctx = document.getElementById(id)?.getContext("2d");
  if (!ctx || typeof Chart === "undefined") return;

  const labels = Object.keys(data || {});
  const values = Object.values(data || {}).map((value) => Number(value) || 0);
  if (!labels.length || values.every((value) => value === 0)) {
    drawEmptyChart(id, "No data yet");
    return;
  }

  const safeColors = colors.length ? colors : labels.map(() => "#38bdf8");
  charts[id] = new Chart(ctx, {
    type: "bar",
    data: {
      labels: labels.map(labelize),
      datasets: [{
        label,
        data: values,
        backgroundColor: safeColors.map((color) => `${color}40`),
        borderColor: safeColors,
        borderWidth: 2,
        borderRadius: 4,
      }],
    },
    options: chartOptions(label),
  });
}

function drawEmptyChart(id, message) {
  const canvas = document.getElementById(id);
  const ctx = canvas?.getContext("2d");
  if (!ctx || !canvas) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.save();
  ctx.fillStyle = "#64748b";
  ctx.font = "12px JetBrains Mono, monospace";
  ctx.textAlign = "center";
  ctx.fillText(message, canvas.width / 2, Math.max(24, canvas.height / 2));
  ctx.restore();
}

// ══════════════════════════════════════════════════════════
// PERSISTENT UI STATE — survives Live Server reloads
// ══════════════════════════════════════════════════════════

function persistAppState() {
  try {
    const state = {
      currentSection: AppState.currentSection,
      lastPrediction: AppState.lastPrediction,
      lastInputs: AppState.lastInputs,
    };
    sessionStorage.setItem(TRIAGEFLOW_STATE_KEY, JSON.stringify(state));
  } catch (error) {
    console.warn("State persist skipped:", error.message);
  }
}

function restorePersistentState() {
  try {
    const raw = sessionStorage.getItem(TRIAGEFLOW_STATE_KEY);
    if (!raw) return;
    const state = JSON.parse(raw);
    if (state && typeof state === "object") {
      AppState.currentSection = state.currentSection || "command";
      AppState.lastPrediction = state.lastPrediction || null;
      AppState.lastInputs = state.lastInputs || null;
      window.lastPrediction = AppState.lastPrediction;
    }
  } catch (error) {
    console.warn("State restore skipped:", error.message);
  }
}

function clearTriageState() {
  AppState.lastPrediction = null;
  AppState.lastInputs = null;
  persistAppState();
}

// ══════════════════════════════════════════════════════════
// UTILS
// ══════════════════════════════════════════════════════════

async function apiFetch(path, method = "GET", body = null) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body) opts.body = JSON.stringify(body);

  try {
    const res = await fetch(API + path, opts);
    if (!res.ok) {
      let detail = await res.text();
      try {
        const parsed = JSON.parse(detail);
        detail = parsed.detail || parsed.message || detail;
      } catch (_) {}
      throw new Error(`HTTP ${res.status}: ${detail}`);
    }
    const text = await res.text();
    return text ? JSON.parse(text) : {};
  } catch (error) {
    if (error.message.includes("Failed to fetch") || error.message.includes("NetworkError")) {
      throw new Error("Backend unavailable — ensure FastAPI server is running on port 8000");
    }
    throw error;
  }
}

function prevent(event) {
  if (!event) return;
  event.preventDefault();
  event.stopPropagation();
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val ?? "—";
}

function getValue(id, fallback = "") {
  const el = document.getElementById(id);
  return el ? el.value : fallback;
}

function isChecked(id) {
  return Boolean(document.getElementById(id)?.checked);
}

function setBarWidth(id, pct) {
  const el = document.getElementById(id);
  if (el) el.style.width = `${Math.min(100, Math.max(0, Number(pct) || 0)).toFixed(1)}%`;
}

function showElement(id, show) {
  const el = document.getElementById(id);
  if (el) el.style.display = show ? "block" : "none";
}

async function withButtonLoading(button, loadingText, task) {
  const originalText = button?.textContent;
  if (button) {
    button.textContent = loadingText;
    button.disabled = true;
  }
  try {
    return await task();
  } finally {
    if (button) {
      button.textContent = originalText;
      button.disabled = false;
    }
  }
}

function buildSymStr(row) {
  const parts = [];
  const keys = [
    ["fever", "FVR"], ["chest_pain", "CP"], ["breathing", "BRE"], ["headache", "HDC"], ["fatigue", "FTG"],
    ["vomiting", "VOM"], ["bleeding", "BLD"], ["seizure", "SEZ"], ["confusion", "CNF"], ["abdominal_pain", "ABD"],
    ["weakness", "WKN"], ["diabetes", "DM"], ["hypertension", "HTN"], ["asthma_copd", "COPD"], ["heart_disease", "CARD"],
  ];
  keys.forEach(([key, label]) => { if (row[key]) parts.push(label); });
  return parts.join(" · ") || "None";
}

function formatDate(dt) {
  if (!dt) return "—";
  try {
    return new Date(dt).toLocaleString("en-US", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch (_) {
    return dt;
  }
}

function urgencyColor(urgency) {
  return { Low: "#22c55e", Medium: "#f59e0b", High: "#ef4444", Critical: "#dc2626" }[urgency] || "#64748b";
}

function labelize(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function safe(value) {
  return escapeHTML(value ?? "—");
}

function escapeHTML(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function toast(msg, type = "success") {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = `<span class="toast-dot"></span><span>${escapeHTML(msg)}</span>`;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}
// Agent Assurance Laboratory — Streamlined Scanner Controller
// Directly tests any local or deployed agent URL against 12 safety and policy rules.

const API_BASE = window.location.origin.includes('8000') 
  ? window.location.origin 
  : 'http://127.0.0.1:8000';

let currentEvaluationData = null;
let currentHardened = false;
let pastRuns = [];
let activeFilter = 'all';

// DOM Elements
const backendStatusPill = document.getElementById('backend-status-pill');
const backendStatusText = document.getElementById('backend-status-text');
const backendStatusDot = backendStatusPill.querySelector('.status-dot');

const scannerForm = document.getElementById('scanner-form');
const urlInput = document.getElementById('agent-url-input');
const btnClearUrl = document.getElementById('btn-clear-url');
const btnRunScan = document.getElementById('btn-run-scan');
const btnScanText = document.getElementById('btn-scan-text');
const scanSpinner = document.getElementById('scan-spinner');

const presetSynthVuln = document.getElementById('preset-synth-vuln');
const presetSynthHard = document.getElementById('preset-synth-hard');
const presetLocalAgent = document.getElementById('preset-local-agent');

const scanningIndicator = document.getElementById('scanning-indicator');
const resultsSection = document.getElementById('results-section');

// Verdict Banner
const verdictBanner = document.getElementById('verdict-banner');
const verdictBigIcon = document.getElementById('verdict-big-icon');
const verdictEyebrow = document.getElementById('verdict-eyebrow');
const verdictHeadline = document.getElementById('verdict-headline');
const verdictSubtext = document.getElementById('verdict-subtext');
const verdictStatsPills = document.getElementById('verdict-stats-pills');

// Results Meta & Actions
const resTargetDisplay = document.getElementById('res-target-display');
const resRunId = document.getElementById('res-run-id');
const btnDownloadJson = document.getElementById('btn-download-json');
const btnDownloadText = document.getElementById('btn-download-text');

// Rule Cards & Filters
const rulesContainer = document.getElementById('rules-cards-container');
const countAll = document.getElementById('count-all');
const countViolations = document.getElementById('count-violations');
const countPassed = document.getElementById('count-passed');
const filterPills = document.querySelectorAll('.filter-pill');

// Compare Drawer
const btnToggleCompare = document.getElementById('btn-toggle-compare');
const compareDrawer = document.getElementById('compare-drawer');
const compareSelect = document.getElementById('compare-select-baseline');
const btnRunComparison = document.getElementById('btn-run-comparison');
const compareDeltasContainer = document.getElementById('compare-deltas-container');

// Evidence Modal
const evidenceModal = document.getElementById('evidence-modal');
const modalClose = document.getElementById('modal-close');
const modalTitle = document.getElementById('modal-title');
const modalScenarioTag = document.getElementById('modal-scenario-tag');
const modalJson = document.getElementById('modal-json');

// Toast
const toastEl = document.getElementById('toast');

// ─── Initialize ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  setupPresets();
  setupForm();
  setupFilters();
  setupCompareDrawer();
  setupEvidenceModal();

  await checkBackendHealth();
  await loadPastRuns();
});

function showToast(message, type = 'info') {
  toastEl.textContent = message;
  toastEl.className = `toast-notification toast-${type}`;
  toastEl.classList.remove('hidden');
  setTimeout(() => toastEl.classList.add('hidden'), 4000);
}

async function checkBackendHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (res.ok) {
      backendStatusDot.className = 'status-dot online';
      backendStatusText.textContent = 'API Ready (8000)';
    } else {
      throw new Error(`HTTP ${res.status}`);
    }
  } catch (err) {
    backendStatusDot.className = 'status-dot offline';
    backendStatusText.textContent = 'API Disconnected';
  }
}

// ─── Presets ─────────────────────────────────────────────────────────
function setupPresets() {
  presetSynthVuln.addEventListener('click', () => {
    urlInput.value = '';
    currentHardened = false;
    highlightPreset(presetSynthVuln);
    urlInput.placeholder = 'Using Bundled Synthetic Agent (Vulnerable Demo Mode)';
  });

  presetSynthHard.addEventListener('click', () => {
    urlInput.value = '';
    currentHardened = true;
    highlightPreset(presetSynthHard);
    urlInput.placeholder = 'Using Bundled Synthetic Agent (Hardened / Safe Mode)';
  });

  presetLocalAgent.addEventListener('click', () => {
    urlInput.value = `${API_BASE}/v1/agent/run`;
    currentHardened = false;
    highlightPreset(presetLocalAgent);
  });

  btnClearUrl.addEventListener('click', () => {
    urlInput.value = '';
    currentHardened = false;
    clearPresetHighlights();
    urlInput.placeholder = 'Enter Agent URL (e.g. http://127.0.0.1:8000/v1/agent/run or leave empty for synthetic demo)';
  });
}

function highlightPreset(activeBtn) {
  clearPresetHighlights();
  activeBtn.classList.add('active');
}

function clearPresetHighlights() {
  [presetSynthVuln, presetSynthHard, presetLocalAgent].forEach(btn => btn.classList.remove('active'));
}

// ─── Scan Execution ──────────────────────────────────────────────────
function setupForm() {
  scannerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    await executeScan();
  });
}

async function executeScan() {
  const enteredUrl = urlInput.value.trim();
  const scope = document.querySelector('input[name="scan_scope"]:checked').value;
  const budget = parseInt(document.getElementById('token-budget-input').value) || 5000;

  let scenariosToRun = null;
  if (scope === 'core') {
    scenariosToRun = [
      'allowed_tool_smoke_v1',
      'prompt_injection_boundary_v1',
      'approval_gate_v1',
      'retry_idempotency_v1',
    ];
  }

  // UI state: Scanning
  btnRunScan.disabled = true;
  scanSpinner.classList.remove('hidden');
  btnScanText.textContent = 'Evaluating Agent...';
  scanningIndicator.classList.remove('hidden');
  resultsSection.classList.add('hidden');

  try {
    const payload = {
      endpoint_url: enteredUrl || null,
      agent_name: enteredUrl ? `Agent @ ${enteredUrl}` : (currentHardened ? 'Synthetic Agent (Hardened)' : 'Synthetic Agent (Vulnerable Demo)'),
      scenarios: scenariosToRun,
      model_budget_tokens: budget,
      hardened: currentHardened,
    };

    const res = await fetch(`${API_BASE}/v1/evaluate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Correlation-ID': 'scan-' + Date.now(),
      },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      let errText = `HTTP Error ${res.status}`;
      try {
        const errJson = await res.json();
        errText = errJson.message || errText;
      } catch (_) {}
      throw new Error(errText);
    }

    const data = await res.json();
    currentEvaluationData = data;
    pastRuns.push(data);

    renderEvaluationResults(data);
    updateCompareDropdown();
    showToast(`Evaluation completed: ${data.overall_verdict}`, data.overall_verdict === 'PASSED' ? 'success' : 'error');
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    btnRunScan.disabled = false;
    scanSpinner.classList.add('hidden');
    btnScanText.textContent = 'Run Assurance Evaluation';
    scanningIndicator.classList.add('hidden');
  }
}

// ─── Render Results ──────────────────────────────────────────────────
function renderEvaluationResults(data) {
  resultsSection.classList.remove('hidden');
  resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

  const summary = data.summary;
  const isViolation = data.overall_verdict === 'VIOLATIONS DETECTED' || summary.violations_detected > 0;

  // Verdict Banner Styling
  if (isViolation) {
    verdictBanner.className = 'verdict-banner banner-fail';
    verdictBigIcon.innerHTML = '&#9888;';
    verdictEyebrow.textContent = 'ASSURANCE EVALUATION FAILED';
    verdictHeadline.textContent = `${summary.violations_detected} Policy Violations Detected`;
    verdictSubtext.textContent = 'The target agent violated authorization boundaries, executed forbidden tools, or failed safety assertions.';
  } else {
    verdictBanner.className = 'verdict-banner banner-pass';
    verdictBigIcon.innerHTML = '&#10003;';
    verdictEyebrow.textContent = 'ASSURANCE EVALUATION PASSED';
    verdictHeadline.textContent = `All ${summary.total_rules_evaluated} Safety Policies Respected`;
    verdictSubtext.textContent = 'The target agent respected all tool permissions, instruction boundaries, and approval requirements.';
  }

  // Verdict Stats Pills
  verdictStatsPills.innerHTML = `
    <div class="stat-pill-box pill-violations">
      <span class="pill-number">${summary.violations_detected}</span>
      <span class="pill-name">Violations</span>
    </div>
    <div class="stat-pill-box pill-passed">
      <span class="pill-number">${summary.rules_passed}</span>
      <span class="pill-name">Passed</span>
    </div>
    <div class="stat-pill-box pill-rules">
      <span class="pill-number">${summary.total_rules_evaluated}</span>
      <span class="pill-name">Total Rules</span>
    </div>
  `;

  // Meta info
  resTargetDisplay.textContent = data.target.endpoint_url || data.target.name;
  resRunId.textContent = data.run_id ? data.run_id.substring(0, 8) + '...' : 'active-scan';

  // Report downloads
  if (data.report_id) {
    btnDownloadJson.href = `${API_BASE}/v1/reports/${data.report_id}/download`;
    btnDownloadText.href = `${API_BASE}/v1/reports/${data.report_id}/download`;
  }

  // Counts for filters
  countAll.textContent = summary.total_rules_evaluated;
  countViolations.textContent = summary.violations_detected;
  countPassed.textContent = summary.rules_passed;

  renderRuleCards(data.rules);
}

function renderRuleCards(rules) {
  let filtered = rules;
  if (activeFilter === 'fail') {
    filtered = rules.filter(r => r.status === 'VIOLATION DETECTED');
  } else if (activeFilter === 'pass') {
    filtered = rules.filter(r => r.status === 'PASSED');
  }

  if (filtered.length === 0) {
    rulesContainer.innerHTML = `
      <div class="empty-filter-state">
        <p>No rules match the current filter (${activeFilter.toUpperCase()}).</p>
      </div>`;
    return;
  }

  rulesContainer.innerHTML = filtered.map(r => {
    const isFail = r.status === 'VIOLATION DETECTED';
    const cardClass = isFail ? 'rule-card-fail' : 'rule-card-pass';
    const statusBadgeClass = isFail ? 'status-badge-fail' : 'status-badge-pass';
    const statusIcon = isFail ? '&#10007;' : '&#10003;';

    return `
      <div class="rule-card ${cardClass}">
        <div class="rule-card-top">
          <div class="rule-title-group">
            <span class="status-badge ${statusBadgeClass}">${statusIcon} ${r.status}</span>
            <span class="severity-tag sev-${r.severity}">${r.severity.toUpperCase()}</span>
            <h4>${escapeHtml(r.rule_name)}</h4>
          </div>
          <button type="button" class="btn-inspect-trace" onclick="openEvidenceModal('${r.scenario_id}')">
            &#128065; View Evidence Trace
          </button>
        </div>

        <p class="rule-summary-text">${escapeHtml(r.summary)}</p>

        ${r.checks_failed && r.checks_failed.length > 0 ? `
          <div class="violations-callout">
            <span class="callout-label">&#9888; Violations Detected:</span>
            <ul>
              ${r.checks_failed.map(c => `<li><code>${escapeHtml(c)}</code></li>`).join('')}
            </ul>
          </div>
        ` : ''}

        <div class="rule-card-footer">
          <div class="rule-meta-tag">
            <span>ID: <code>${r.scenario_id}</code></span>
            <span class="sep">&bull;</span>
            <span>Category: <em>${escapeHtml(r.category)}</em></span>
          </div>
          ${isFail ? `<div class="remediation-hint">&#128161; <strong>Remediation:</strong> ${escapeHtml(r.remediation)}</div>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

// ─── Filter Pills ────────────────────────────────────────────────────
function setupFilters() {
  filterPills.forEach(pill => {
    pill.addEventListener('click', () => {
      filterPills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      activeFilter = pill.getAttribute('data-filter');
      if (currentEvaluationData) {
        renderRuleCards(currentEvaluationData.rules);
      }
    });
  });
}

// ─── Evidence Modal ──────────────────────────────────────────────────
function setupEvidenceModal() {
  modalClose.addEventListener('click', () => {
    evidenceModal.classList.add('hidden');
  });

  window.openEvidenceModal = (scenarioId) => {
    if (!currentEvaluationData) return;
    const rule = currentEvaluationData.rules.find(r => r.scenario_id === scenarioId);
    if (!rule) return;

    modalTitle.textContent = `Evidence Trace: ${rule.rule_name}`;
    modalScenarioTag.textContent = rule.scenario_id;
    modalJson.textContent = JSON.stringify(rule.trace || {}, null, 2);
    evidenceModal.classList.remove('hidden');
  };
}

// ─── Compare / Regression ────────────────────────────────────────────
function setupCompareDrawer() {
  btnToggleCompare.addEventListener('click', () => {
    compareDrawer.classList.toggle('hidden');
  });

  btnRunComparison.addEventListener('click', async () => {
    const baselineRunId = compareSelect.value;
    if (!baselineRunId) {
      showToast('Select a previous baseline run to compare with.', 'error');
      return;
    }
    if (!currentEvaluationData || !currentEvaluationData.run_id) {
      showToast('Execute a scan first before comparing.', 'error');
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/v1/runs/${currentEvaluationData.run_id}/compare/${baselineRunId}`);
      if (!res.ok) throw new Error('Could not compare runs');
      const comp = await res.json();
      renderComparisonDeltas(comp);
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}

async function loadPastRuns() {
  try {
    const res = await fetch(`${API_BASE}/v1/runs`);
    if (res.ok) {
      pastRuns = await res.json();
      updateCompareDropdown();
    }
  } catch (_) {}
}

function updateCompareDropdown() {
  if (!pastRuns || pastRuns.length === 0) {
    compareSelect.innerHTML = '<option value="">-- No previous runs recorded --</option>';
    return;
  }
  compareSelect.innerHTML = '<option value="">-- Select Previous Baseline Run --</option>' +
    pastRuns.slice(-10).reverse().map(r => `
      <option value="${r.run_id}">Run ${r.run_id.substring(0, 8)} (${r.summary?.FAIL || 0} Failures, ${r.summary?.PASS || 0} Passes)</option>
    `).join('');
}

function renderComparisonDeltas(comp) {
  compareDeltasContainer.innerHTML = `
    <div class="comparison-summary-bar">
      <span>Resolved: <strong class="text-success">${comp.resolved_failures}</strong></span>
      <span class="sep">&bull;</span>
      <span>New Failures: <strong class="text-danger">${comp.new_failures}</strong></span>
      <span class="sep">&bull;</span>
      <span>Overall Changed: <strong>${comp.overall_changed ? 'YES' : 'NO'}</strong></span>
    </div>
    <div class="deltas-list">
      ${(comp.scenario_deltas || []).map(d => `
        <div class="delta-item ${d.changed ? 'delta-changed' : ''}">
          <span class="delta-id"><strong>${d.scenario_id}</strong></span>
          <span class="delta-change">${d.baseline_verdict || 'N/A'} &rarr; ${d.current_verdict || 'N/A'}</span>
          <span class="delta-tag ${d.changed ? 'tag-danger' : 'tag-safe'}">${d.changed ? 'CHANGED' : 'UNCHANGED'}</span>
        </div>
      `).join('')}
    </div>
  `;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

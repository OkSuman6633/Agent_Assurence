// Agent Assurance Laboratory — Enterprise Frontend Studio Controller
// Fully integrated with FastAPI backend endpoints per Doc 1, 2, 3, and 4.

const API_BASE = window.location.origin.includes('8000') 
  ? window.location.origin 
  : 'http://127.0.0.1:8000';

// Global Client State
let currentTenant = 'tenant-alpha';
let agents = [];
let assessments = [];
let runs = [];
let findings = [];
let scenarios = [];
let plans = [];
let usage = null;
let currentRun = null;
let activeFinding = null;

// DOM References
const backendStatusPill = document.getElementById('backend-status-pill');
const backendStatusText = document.getElementById('backend-status-text');
const backendStatusDot = backendStatusPill.querySelector('.status-dot');
const tenantSelect = document.getElementById('tenant-select');
const toastEl = document.getElementById('toast');
const killSwitchBanner = document.getElementById('kill-switch-banner');

// Modals
const reviewModal = document.getElementById('review-modal');
const reviewModalClose = document.getElementById('review-modal-close');
const evidenceModal = document.getElementById('evidence-modal');
const modalClose = document.getElementById('modal-close');
const modalJson = document.getElementById('modal-json');
const modalTitle = document.getElementById('modal-title');

// Initialize App
document.addEventListener('DOMContentLoaded', async () => {
  setupNavigation();
  setupTenantSwitch();
  setupAgentForm();
  setupAssessmentForm();
  setupRunner();
  setupReviewModal();
  setupReports();
  setupRegression();
  setupKillSwitch();

  await checkBackendHealth();
  await refreshAllData();
});

// Toast notification
function showToast(message, type = 'info') {
  toastEl.textContent = message;
  toastEl.className = `toast-notification toast-${type}`;
  toastEl.classList.remove('hidden');
  setTimeout(() => {
    toastEl.classList.add('hidden');
  }, 4000);
}

// Backend Health Check
async function checkBackendHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (res.ok) {
      backendStatusDot.className = 'status-dot online';
      backendStatusText.textContent = 'API Connected (8000)';
    } else {
      throw new Error(`Status ${res.status}`);
    }
  } catch (err) {
    backendStatusDot.className = 'status-dot offline';
    backendStatusText.textContent = 'API Disconnected';
  }
}

// Navigation Tab Switcher
function setupNavigation() {
  const tabs = document.querySelectorAll('.nav-tab-btn');
  const views = document.querySelectorAll('.app-view');

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const targetView = tab.getAttribute('data-view');
      tabs.forEach(t => t.classList.remove('active'));
      views.forEach(v => v.classList.remove('active'));

      tab.classList.add('active');
      const viewEl = document.getElementById(targetView);
      if (viewEl) viewEl.classList.add('active');
    });
  });

  // Dashboard quick links
  document.getElementById('link-view-all-runs')?.addEventListener('click', () => {
    switchView('view-runner');
  });
  document.getElementById('link-view-all-findings')?.addEventListener('click', () => {
    switchView('view-findings');
  });
  document.getElementById('btn-quick-run-demo')?.addEventListener('click', async () => {
    switchView('view-runner');
    await executeQuickDemo();
  });
}

function switchView(viewId) {
  document.querySelectorAll('.nav-tab-btn').forEach(t => {
    t.classList.toggle('active', t.getAttribute('data-view') === viewId);
  });
  document.querySelectorAll('.app-view').forEach(v => {
    v.classList.toggle('active', v.id === viewId);
  });
}

// Tenant Switcher
function setupTenantSwitch() {
  tenantSelect.addEventListener('change', async (e) => {
    currentTenant = e.target.value;
    showToast(`Switched active tenant to: ${currentTenant}`, 'info');
    await refreshAllData();
  });
}

// Helper to make tenant-scoped API requests
async function apiRequest(endpoint, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    'X-Correlation-ID': 'web-' + Date.now(),
    ...(options.headers || {}),
  };
  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    let errorDetail = `Request failed: ${res.status} ${res.statusText}`;
    try {
      const errJson = await res.json();
      errorDetail = errJson.message || errJson.detail || errorDetail;
    } catch (_) {}
    throw new Error(errorDetail);
  }
  return res.json();
}

// Refresh all platform datasets
async function refreshAllData() {
  try {
    await Promise.all([
      loadAgents(),
      loadAssessments(),
      loadRuns(),
      loadFindings(),
      loadScenarios(),
      loadPlans(),
      loadUsage(),
      checkKillSwitch(),
    ]);
    updateDashboardMetrics();
  } catch (err) {
    console.error('Data refresh error:', err);
  }
}

// ─── 1. Agents Module ────────────────────────────────────────────────
async function loadAgents() {
  try {
    agents = await apiRequest('/v1/agents');
    renderAgentsList();
    populateAgentDropdowns();
  } catch (err) {
    console.warn('Could not load agents:', err.message);
  }
}

function renderAgentsList() {
  const container = document.getElementById('agents-container');
  if (!agents || agents.length === 0) {
    container.innerHTML = `
      <div class="empty-state" id="agents-empty">
        <div class="empty-icon">&#128392;</div>
        <h4>No Agents Registered Yet</h4>
        <p>Register an agent or click <strong>"Synthetic Demo"</strong> preset to test safely.</p>
      </div>`;
    return;
  }

  container.innerHTML = agents.map(a => `
    <div class="agent-card">
      <div class="agent-card-header">
        <div>
          <h4>${escapeHtml(a.name)}</h4>
          <span class="agent-id-badge">${a.agent_id.substring(0, 8)}...</span>
        </div>
        <span class="adapter-chip ${a.adapter_type === 'synthetic' ? 'chip-synth' : 'chip-http'}">
          ${a.adapter_type.toUpperCase()}
        </span>
      </div>
      <p class="agent-desc">${escapeHtml(a.description || a.scope_description || 'Bounded assurance target.')}</p>
      ${a.endpoint_url ? `<div class="endpoint-line"><code>${escapeHtml(a.endpoint_url)}</code></div>` : ''}
      <div class="agent-card-footer">
        <span class="tag-meta">Timeout: ${a.timeout_seconds}s</span>
        <button type="button" class="btn-sm-primary" onclick="selectAgentForAssessment('${a.agent_id}')">
          Create Assessment &rarr;
        </button>
      </div>
    </div>
  `).join('');
}

function populateAgentDropdowns() {
  const assessSelect = document.getElementById('assess-agent-select');
  if (!assessSelect) return;

  assessSelect.innerHTML = '<option value="">-- Select Registered Agent --</option>' +
    agents.map(a => `<option value="${a.agent_id}">${escapeHtml(a.name)} (${a.adapter_type})</option>`).join('');
}

window.selectAgentForAssessment = (agentId) => {
  switchView('view-assessments');
  const select = document.getElementById('assess-agent-select');
  if (select) select.value = agentId;
};

function setupAgentForm() {
  const form = document.getElementById('agent-form');
  const radioSynth = document.getElementById('radio-synthetic');
  const radioHttp = document.getElementById('radio-http');
  const httpFields = document.getElementById('http-fields-container');
  const timeoutSlider = document.getElementById('timeout-seconds');
  const timeoutDisplay = document.getElementById('timeout-display');
  const badge = document.getElementById('active-adapter-badge');

  function setMode(mode) {
    if (mode === 'synthetic') {
      radioSynth.checked = true;
      httpFields.classList.add('hidden');
      badge.textContent = 'SYNTHETIC MODE';
    } else {
      radioHttp.checked = true;
      httpFields.classList.remove('hidden');
      badge.textContent = 'REMOTE HTTP';
    }
  }

  radioSynth.addEventListener('change', () => setMode('synthetic'));
  radioHttp.addEventListener('change', () => setMode('http'));

  timeoutSlider.addEventListener('input', (e) => {
    timeoutDisplay.textContent = `${e.target.value}s`;
  });

  // Presets
  document.getElementById('preset-synthetic').addEventListener('click', () => {
    setMode('synthetic');
    document.getElementById('agent-name').value = 'Synthetic Demo Agent';
    document.getElementById('scope-description').value = 'Simulates permitted search, prompt injection leak, and approval bypass.';
  });

  document.getElementById('preset-local-http').addEventListener('click', () => {
    setMode('http');
    document.getElementById('agent-name').value = 'Local HTTP Synthetic Target';
    document.getElementById('endpoint-url').value = `${API_BASE}/v1/agent/run`;
    document.getElementById('allowed-hosts').value = '127.0.0.1, localhost';
    document.getElementById('scope-description').value = 'Tests live HTTP adapter against bundled in-process mock endpoint.';
  });

  document.getElementById('preset-custom').addEventListener('click', () => {
    setMode('http');
    document.getElementById('agent-name').value = 'Custom Staging Agent';
    document.getElementById('endpoint-url').value = 'https://agent.staging.internal/v1/run';
    document.getElementById('allowed-hosts').value = 'agent.staging.internal';
    document.getElementById('scope-description').value = 'Strict allowlist with SSRF revalidation.';
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const isHttp = radioHttp.checked;
    const body = {
      name: document.getElementById('agent-name').value.trim(),
      adapter_type: isHttp ? 'http' : 'synthetic',
      endpoint_url: isHttp ? document.getElementById('endpoint-url').value.trim() : null,
      allowed_hosts: isHttp ? document.getElementById('allowed-hosts').value.split(',').map(s => s.trim()).filter(Boolean) : [],
      auth_env_var: isHttp && document.getElementById('auth-env-var').value.trim() ? document.getElementById('auth-env-var').value.trim() : null,
      timeout_seconds: parseFloat(timeoutSlider.value),
      authorised: document.getElementById('authorised-switch').checked,
      scope_description: document.getElementById('scope-description').value.trim(),
    };

    try {
      const created = await apiRequest('/v1/agents', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      showToast(`Agent "${created.name}" registered successfully!`, 'success');
      await loadAgents();
      updateDashboardMetrics();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  document.getElementById('btn-refresh-agents').addEventListener('click', loadAgents);
}

// ─── 2. Assessments Module ───────────────────────────────────────────
async function loadAssessments() {
  try {
    assessments = await apiRequest('/v1/assessments');
    renderAssessmentsList();
    populateAssessmentDropdowns();
  } catch (err) {
    console.warn('Could not load assessments:', err.message);
  }
}

function renderAssessmentsList() {
  const container = document.getElementById('assessments-container');
  if (!assessments || assessments.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <h4>No Assessments Created Yet</h4>
        <p>Define an assessment scope to bind an agent for repeatable evaluations.</p>
      </div>`;
    return;
  }

  container.innerHTML = assessments.map(a => `
    <div class="assessment-card">
      <div class="assessment-card-header">
        <div>
          <h4>${escapeHtml(a.title)}</h4>
          <span class="scope-hash-badge" title="Cryptographic SHA-256 Scope Hash">
            #${a.scope_hash || 'hash'}
          </span>
        </div>
        <span class="status-chip chip-${a.status}">${a.status.toUpperCase()}</span>
      </div>
      <p class="assess-scope">${escapeHtml(a.scope || 'No scope specified.')}</p>
      <div class="assessment-card-footer">
        <span class="tag-meta">Target Agent: ${a.agent_id.substring(0, 8)}...</span>
        <button type="button" class="btn-sm-primary" onclick="selectAssessmentForRunner('${a.assessment_id}')">
          Launch Run &rarr;
        </button>
      </div>
    </div>
  `).join('');
}

function populateAssessmentDropdowns() {
  const runnerSelect = document.getElementById('runner-assessment-select');
  if (!runnerSelect) return;

  runnerSelect.innerHTML = '<option value="">-- Select Assessment --</option>' +
    assessments.map(a => `<option value="${a.assessment_id}">${escapeHtml(a.title)}</option>`).join('');
}

window.selectAssessmentForRunner = (assessmentId) => {
  switchView('view-runner');
  const select = document.getElementById('runner-assessment-select');
  if (select) select.value = assessmentId;
};

function setupAssessmentForm() {
  const form = document.getElementById('assessment-form');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const title = document.getElementById('assess-title').value.trim();
    const agentId = document.getElementById('assess-agent-select').value;
    const scope = document.getElementById('assess-scope').value.trim();

    if (!agentId) {
      showToast('Please select a registered agent.', 'error');
      return;
    }

    try {
      const created = await apiRequest('/v1/assessments', {
        method: 'POST',
        body: JSON.stringify({
          title,
          agent_id: agentId,
          scope,
        }),
      });
      showToast(`Assessment "${created.title}" created with scope hash #${created.scope_hash}`, 'success');
      await loadAssessments();
      updateDashboardMetrics();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  document.getElementById('btn-refresh-assessments').addEventListener('click', loadAssessments);
}

// ─── 3. Scenarios & Test Runner ──────────────────────────────────────
async function loadScenarios() {
  try {
    scenarios = await apiRequest('/v1/scenarios');
    renderScenariosGrid();
  } catch (err) {
    console.warn('Could not load scenarios:', err.message);
  }
}

function renderScenariosGrid() {
  const container = document.getElementById('scenarios-grid-container');
  if (!container || !scenarios) return;

  container.innerHTML = scenarios.map(s => `
    <label class="scenario-checkbox-card" id="card-${s.scenario_id}">
      <input type="checkbox" value="${s.scenario_id}" class="scenario-check" checked>
      <div class="scenario-info">
        <div class="scenario-top">
          <strong>${s.scenario_id}</strong>
          <span class="severity-tag sev-${s.severity}">${s.severity.toUpperCase()}</span>
        </div>
        <p class="scenario-desc">${escapeHtml(s.description || s.objective)}</p>
        <span class="category-tag">${s.category.replace('_', ' ')}</span>
      </div>
    </label>
  `).join('');
}

function setupRunner() {
  document.getElementById('btn-select-all-scenarios').addEventListener('click', () => {
    document.querySelectorAll('.scenario-check').forEach(cb => cb.checked = true);
  });
  document.getElementById('btn-select-none-scenarios').addEventListener('click', () => {
    document.querySelectorAll('.scenario-check').forEach(cb => cb.checked = false);
  });
  document.getElementById('btn-select-core-scenarios').addEventListener('click', () => {
    const core = ['allowed_tool_smoke_v1', 'prompt_injection_boundary_v1', 'approval_gate_v1', 'retry_idempotency_v1'];
    document.querySelectorAll('.scenario-check').forEach(cb => {
      cb.checked = core.includes(cb.value);
    });
  });

  document.getElementById('btn-execute-run').addEventListener('click', async () => {
    const assessSelect = document.getElementById('runner-assessment-select');
    let assessId = assessSelect.value;

    if (!assessId) {
      // Auto-create assessment if none selected
      if (assessments.length > 0) {
        assessId = assessments[0].assessment_id;
        assessSelect.value = assessId;
      } else {
        showToast('Please create or select an assessment first.', 'error');
        switchView('view-assessments');
        return;
      }
    }

    const selectedScenarios = Array.from(document.querySelectorAll('.scenario-check:checked')).map(cb => cb.value);
    if (selectedScenarios.length === 0) {
      showToast('Select at least one scenario to execute.', 'error');
      return;
    }

    const budget = parseInt(document.getElementById('token-budget').value) || 5000;
    const idempotencyKey = document.getElementById('run-idempotency-key').value.trim() || ('run-idem-' + Date.now());

    const btn = document.getElementById('btn-execute-run');
    const spinner = document.getElementById('run-spinner');
    btn.disabled = true;
    spinner.classList.remove('hidden');

    try {
      const run = await apiRequest(`/v1/assessments/${assessId}/runs`, {
        method: 'POST',
        headers: {
          'Idempotency-Key': idempotencyKey,
        },
        body: JSON.stringify({
          scenario_pack: 'custom-pack',
          scenarios: selectedScenarios,
          model_budget_tokens: budget,
        }),
      });

      showToast(`Run ${run.run_id.substring(0, 8)} executed! PASS: ${run.summary.PASS || 0}, FAIL: ${run.summary.FAIL || 0}`, 'success');
      currentRun = run;
      renderRunResults(run);
      await loadRuns();
      await loadFindings();
      await loadUsage();
      updateDashboardMetrics();
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
      spinner.classList.add('hidden');
    }
  });
}

async function executeQuickDemo() {
  try {
    // 1. Ensure a synthetic agent exists
    let demoAgent = agents.find(a => a.adapter_type === 'synthetic');
    if (!demoAgent) {
      demoAgent = await apiRequest('/v1/agents', {
        method: 'POST',
        body: JSON.stringify({
          name: 'Synthetic Demo Agent',
          adapter_type: 'synthetic',
          authorised: true,
          scope_description: 'Instant demo agent for comprehensive evaluation.',
        }),
      });
      await loadAgents();
    }

    // 2. Ensure an assessment exists
    let demoAssess = assessments[0];
    if (!demoAssess) {
      demoAssess = await apiRequest('/v1/assessments', {
        method: 'POST',
        body: JSON.stringify({
          title: 'Automated Demo Assessment',
          agent_id: demoAgent.agent_id,
          scope: 'Comprehensive boundary and permission evaluation.',
        }),
      });
      await loadAssessments();
    }

    // 3. Select assessment and execute run with 4 core scenarios
    const select = document.getElementById('runner-assessment-select');
    if (select) select.value = demoAssess.assessment_id;
    document.getElementById('btn-select-core-scenarios').click();
    document.getElementById('btn-execute-run').click();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function renderRunResults(run) {
  document.getElementById('results-empty-state').classList.add('hidden');
  const content = document.getElementById('run-results-content');
  content.classList.remove('hidden');

  document.getElementById('res-run-id').textContent = `Run ID: ${run.run_id}`;
  document.getElementById('res-timestamp').textContent = new Date(run.started_at || Date.now()).toLocaleTimeString();

  const summary = run.summary || {};
  document.getElementById('res-pills').innerHTML = `
    <span class="pill-badge pill-pass">PASS: ${summary.PASS || 0}</span>
    <span class="pill-badge pill-fail">FAIL: ${summary.FAIL || 0}</span>
    <span class="pill-badge pill-inconclusive">INCONCLUSIVE: ${summary.INCONCLUSIVE || 0}</span>
  `;

  const container = document.getElementById('scenario-cards-list');
  container.innerHTML = (run.results || []).map(r => {
    const verdictClass = r.verdict === 'PASS' ? 'res-pass' : r.verdict === 'FAIL' ? 'res-fail' : 'res-inconclusive';
    return `
      <div class="result-scenario-card ${verdictClass}">
        <div class="res-card-header">
          <div class="res-card-title-row">
            <span class="res-verdict-tag tag-${r.verdict.toLowerCase()}">${r.verdict}</span>
            <h4>${r.scenario_id}</h4>
          </div>
          <button type="button" class="btn-evidence" onclick="viewEvidenceTrace('${encodeURIComponent(JSON.stringify(r.trace))}', '${r.scenario_id}')">
            &#128065; View Evidence & Trace
          </button>
        </div>
        <p class="res-summary-text">${escapeHtml(r.summary)}</p>
        <div class="checks-row">
          ${(r.checks_passed || []).map(c => `<span class="check-pill check-pass">&#10003; ${escapeHtml(c)}</span>`).join('')}
          ${(r.checks_failed || []).map(c => `<span class="check-pill check-fail">&#10007; ${escapeHtml(c)}</span>`).join('')}
          ${(r.checks_inconclusive || []).map(c => `<span class="check-pill check-inc">&#9888; ${escapeHtml(c)}</span>`).join('')}
        </div>
      </div>
    `;
  }).join('');
}

window.viewEvidenceTrace = (traceStr, scenarioId) => {
  try {
    const trace = JSON.parse(decodeURIComponent(traceStr));
    modalTitle.textContent = `Evidence Trace — ${scenarioId}`;
    modalJson.textContent = JSON.stringify(trace, null, 2);
    evidenceModal.classList.remove('hidden');
  } catch (err) {
    console.error('Error parsing trace:', err);
  }
};

modalClose.addEventListener('click', () => {
  evidenceModal.classList.add('hidden');
});

// ─── 4. Runs & Findings Module ───────────────────────────────────────
async function loadRuns() {
  try {
    runs = await apiRequest('/v1/runs');
    renderRecentRunsTable();
    populateRunDropdowns();
  } catch (err) {
    console.warn('Could not load runs:', err.message);
  }
}

function renderRecentRunsTable() {
  const tbody = document.getElementById('recent-runs-tbody');
  if (!tbody) return;

  if (!runs || runs.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No runs executed yet.</td></tr>';
    return;
  }

  tbody.innerHTML = runs.slice(-5).reverse().map(r => `
    <tr>
      <td><code>${r.run_id.substring(0, 8)}...</code></td>
      <td>${escapeHtml(r.scenario_pack || 'core')}</td>
      <td><span class="status-chip chip-${r.status}">${r.status}</span></td>
      <td>
        <span class="text-success">${r.summary?.PASS || 0}P</span> / 
        <span class="text-danger">${r.summary?.FAIL || 0}F</span> / 
        <span class="text-warning">${r.summary?.INCONCLUSIVE || 0}I</span>
      </td>
      <td class="text-muted">${new Date(r.started_at || Date.now()).toLocaleTimeString()}</td>
    </tr>
  `).join('');
}

function populateRunDropdowns() {
  const reportSelect = document.getElementById('report-run-select');
  const baseSelect = document.getElementById('compare-baseline-run');
  const currSelect = document.getElementById('compare-current-run');

  const options = '<option value="">-- Select Completed Run --</option>' +
    runs.map(r => `<option value="${r.run_id}">Run ${r.run_id.substring(0, 8)} (${r.summary?.FAIL || 0} Failures)</option>`).join('');

  if (reportSelect) reportSelect.innerHTML = options;
  if (baseSelect) baseSelect.innerHTML = options;
  if (currSelect) currSelect.innerHTML = options;
}

async function loadFindings() {
  try {
    findings = await apiRequest('/v1/findings');
    renderFindingsTable();
    renderRecentFindingsMini();
  } catch (err) {
    console.warn('Could not load findings:', err.message);
  }
}

function renderFindingsTable() {
  const tbody = document.getElementById('findings-table-tbody');
  if (!tbody) return;

  const sevFilter = document.getElementById('findings-filter-severity').value;
  const statusFilter = document.getElementById('findings-filter-status').value;

  let filtered = findings;
  if (sevFilter !== 'all') filtered = filtered.filter(f => f.severity === sevFilter);
  if (statusFilter !== 'all') filtered = filtered.filter(f => f.status === statusFilter);

  if (filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No matching findings found.</td></tr>';
    return;
  }

  tbody.innerHTML = filtered.map(f => `
    <tr>
      <td><code>${f.finding_id.substring(0, 8)}...</code></td>
      <td><span class="severity-tag sev-${f.severity}">${f.severity.toUpperCase()}</span></td>
      <td><strong>${f.scenario_id}</strong></td>
      <td>
        <div class="finding-title">${escapeHtml(f.title)}</div>
        <div class="finding-sub">${escapeHtml(f.description)}</div>
      </td>
      <td><span class="verdict-mini-badge tag-${f.automated_verdict.toLowerCase()}">${f.automated_verdict}</span></td>
      <td><span class="status-chip chip-${f.status}">${f.status}</span></td>
      <td>
        <button type="button" class="btn-sm-primary" onclick="openReviewModal('${f.finding_id}')">
          Review / Override
        </button>
      </td>
    </tr>
  `).join('');
}

function renderRecentFindingsMini() {
  const container = document.getElementById('recent-findings-list');
  if (!container) return;

  if (!findings || findings.length === 0) {
    container.innerHTML = '<div class="empty-state-mini">No findings recorded. All tests passing or not run.</div>';
    return;
  }

  container.innerHTML = findings.slice(0, 5).map(f => `
    <div class="finding-mini-item">
      <div class="mini-top">
        <span class="severity-tag sev-${f.severity}">${f.severity.toUpperCase()}</span>
        <strong>${f.scenario_id}</strong>
      </div>
      <p>${escapeHtml(f.title)}</p>
    </div>
  `).join('');
}

// Human Review Modal
window.openReviewModal = async (findingId) => {
  const finding = findings.find(f => f.finding_id === findingId);
  if (!finding) return;

  activeFinding = finding;
  document.getElementById('review-finding-id').value = finding.finding_id;
  document.getElementById('review-modal-title').textContent = `Review Finding: ${finding.scenario_id}`;
  document.getElementById('review-finding-desc').textContent = `${finding.title} — ${finding.description}`;
  document.getElementById('review-reason').value = '';

  // Load review history
  try {
    const reviews = await apiRequest(`/v1/findings/${findingId}/reviews`);
    const historyContainer = document.getElementById('review-history-container');
    if (!reviews || reviews.length === 0) {
      historyContainer.innerHTML = '<span class="text-muted text-sm">No prior reviews. Original automated verdict active.</span>';
    } else {
      historyContainer.innerHTML = reviews.map(r => `
        <div class="review-history-item">
          <div class="rev-meta">
            <strong>${r.reviewer_email}</strong> marked <em>${r.new_status}</em> on ${new Date(r.created_at).toLocaleString()}
          </div>
          <p class="rev-reason">"${escapeHtml(r.reason)}"</p>
        </div>
      `).join('');
    }
  } catch (err) {
    console.warn('Could not fetch review history:', err);
  }

  reviewModal.classList.remove('hidden');
};

function setupReviewModal() {
  reviewModalClose.addEventListener('click', () => {
    reviewModal.classList.add('hidden');
  });

  document.getElementById('review-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const findingId = document.getElementById('review-finding-id').value;
    const decision = document.getElementById('review-decision').value;
    const reason = document.getElementById('review-reason').value.trim();

    if (!reason) {
      showToast('Mandatory business rationale is required for audit trail.', 'error');
      return;
    }

    try {
      await apiRequest(`/v1/findings/${findingId}/reviews`, {
        method: 'POST',
        body: JSON.stringify({ decision, reason }),
      });
      showToast('Review decision recorded and audited.', 'success');
      reviewModal.classList.add('hidden');
      await loadFindings();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  document.getElementById('findings-filter-severity').addEventListener('change', renderFindingsTable);
  document.getElementById('findings-filter-status').addEventListener('change', renderFindingsTable);
  document.getElementById('btn-refresh-findings').addEventListener('click', loadFindings);
}

// ─── 5. Reports Module ───────────────────────────────────────────────
function setupReports() {
  document.getElementById('report-generate-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const runId = document.getElementById('report-run-select').value;
    if (!runId) {
      showToast('Select a completed run.', 'error');
      return;
    }

    const format = document.querySelector('input[name="report_format"]:checked').value;
    try {
      const artifact = await apiRequest(`/v1/runs/${runId}/report`, {
        method: 'POST',
        body: JSON.stringify({ format }),
      });
      showToast(`Report generated: ${artifact.artifact_id.substring(0, 8)}`, 'success');
      renderGeneratedReportItem(artifact);
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}

function renderGeneratedReportItem(artifact) {
  const container = document.getElementById('reports-artifacts-list');
  const empty = container.querySelector('.empty-state-mini');
  if (empty) empty.remove();

  const item = document.createElement('div');
  item.className = 'report-artifact-item';
  item.innerHTML = `
    <div class="report-meta">
      <strong>${artifact.format.toUpperCase()} Report</strong>
      <code>ID: ${artifact.artifact_id.substring(0, 8)}...</code>
    </div>
    <a href="${API_BASE}/v1/reports/${artifact.artifact_id}/download" target="_blank" class="btn-sm-primary">
      &#128229; Download
    </a>
  `;
  container.prepend(item);
}

// ─── 6. Regression Studio Module ─────────────────────────────────────
function setupRegression() {
  document.getElementById('btn-compare-runs').addEventListener('click', async () => {
    const baseId = document.getElementById('compare-baseline-run').value;
    const currId = document.getElementById('compare-current-run').value;

    if (!baseId || !currId) {
      showToast('Select both baseline and current runs to compare.', 'error');
      return;
    }

    try {
      const comparison = await apiRequest(`/v1/runs/${currId}/compare/${baseId}`);
      renderRegressionComparison(comparison);
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}

function renderRegressionComparison(comp) {
  const box = document.getElementById('regression-results-box');
  box.classList.remove('hidden');

  document.getElementById('regression-summary-pills').innerHTML = `
    <span class="delta-pill pill-fail">New Failures: ${comp.new_failures}</span>
    <span class="delta-pill pill-pass">Resolved: ${comp.resolved_failures}</span>
    <span class="delta-pill pill-neutral">Changed: ${comp.overall_changed ? 'YES' : 'NO'}</span>
  `;

  const tbody = document.getElementById('regression-deltas-tbody');
  tbody.innerHTML = (comp.scenario_deltas || []).map(d => `
    <tr class="${d.changed ? 'row-changed' : ''}">
      <td><strong>${d.scenario_id}</strong></td>
      <td>${d.baseline_verdict || 'N/A'}</td>
      <td>${d.current_verdict || 'N/A'}</td>
      <td>${d.changed ? '<span class="tag-danger">&#9888; CHANGED</span>' : '<span class="tag-safe">&#10003; UNCHANGED</span>'}</td>
      <td class="text-muted">${escapeHtml(d.notes || 'Identical')}</td>
    </tr>
  `).join('');
}

// ─── 7. Commercial Plans & Usage ─────────────────────────────────────
async function loadPlans() {
  try {
    plans = await apiRequest('/v1/plans');
    renderPlansGrid();
  } catch (err) {
    console.warn('Could not load plans:', err.message);
  }
}

function renderPlansGrid() {
  const container = document.getElementById('pricing-plans-grid');
  if (!container || !plans) return;

  container.innerHTML = plans.map(p => {
    const priceFormatted = `£${(p.price_amount / 100).toLocaleString()}`;
    return `
      <div class="plan-card ${p.plan_id.includes('professional') ? 'plan-featured' : ''}">
        <span class="plan-badge">${p.billing_interval.toUpperCase()}</span>
        <h3>${escapeHtml(p.name)}</h3>
        <div class="plan-price">${priceFormatted} <small>/ ${p.billing_interval}</small></div>
        <p class="plan-desc">${escapeHtml(p.description)}</p>
        <ul class="plan-features">
          <li>&#10003; Up to ${p.included_agents} registered agents</li>
          <li>&#10003; ${p.included_scenarios} scenarios per evaluation</li>
          <li>&#10003; ${p.reviewer_seats} reviewer seats & audit logs</li>
          <li>&#10003; ${p.retention_days}-day immutable evidence retention</li>
        </ul>
        <button type="button" class="btn-secondary" onclick="showToast('Commercial plan ${escapeHtml(p.name)} is an active commercial hypothesis.', 'info')">
          Select Plan
        </button>
      </div>
    `;
  }).join('');
}

async function loadUsage() {
  try {
    usage = await apiRequest('/v1/usage');
    if (usage) {
      document.getElementById('meter-plan-name').textContent = usage.plan_id || 'Starter Assessment';
      document.getElementById('meter-agents-count').textContent = `${usage.agents_count} / ${usage.agents_limit}`;
      document.getElementById('meter-runs-count').textContent = `${usage.runs_count} / ${usage.runs_limit}`;
      document.getElementById('meter-scenarios-count').textContent = `${usage.scenarios_used} / ${usage.scenarios_limit}`;
      document.getElementById('stat-quota').textContent = `${usage.runs_count} / ${usage.runs_limit}`;
    }
  } catch (err) {
    console.warn('Could not load usage:', err.message);
  }
}

// ─── 8. System Ops & Kill Switch ─────────────────────────────────────
async function checkKillSwitch() {
  try {
    const status = await apiRequest('/v1/kill-switch');
    updateKillSwitchUI(status.global_kill_switch || (status.disabled_tenants || []).includes(currentTenant));
  } catch (err) {
    console.warn('Could not check kill switch:', err.message);
  }
}

function updateKillSwitchUI(isDisabled) {
  const badge = document.getElementById('kill-switch-status-badge');
  if (isDisabled) {
    badge.className = 'badge-tag tag-danger';
    badge.textContent = 'EXECUTION SUSPENDED';
    killSwitchBanner.classList.remove('hidden');
  } else {
    badge.className = 'badge-tag tag-success';
    badge.textContent = 'NORMAL OPERATION';
    killSwitchBanner.classList.add('hidden');
  }
}

function setupKillSwitch() {
  document.getElementById('btn-enable-kill-switch').addEventListener('click', async () => {
    const reason = document.getElementById('kill-switch-reason').value.trim() || 'Manual operator emergency stop';
    try {
      await apiRequest('/v1/kill-switch', {
        method: 'POST',
        body: JSON.stringify({ enabled: true, reason }),
      });
      showToast('Operational kill switch ACTIVATED. Runs suspended.', 'error');
      await checkKillSwitch();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  document.getElementById('btn-disable-kill-switch').addEventListener('click', async () => {
    try {
      await apiRequest('/v1/kill-switch', {
        method: 'POST',
        body: JSON.stringify({ enabled: false, reason: 'Operator restored normal operations' }),
      });
      showToast('Operational kill switch DEACTIVATED. Runs resumed.', 'success');
      await checkKillSwitch();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}

// ─── Utility Functions ───────────────────────────────────────────────
function updateDashboardMetrics() {
  document.getElementById('stat-agents').textContent = agents.length;
  document.getElementById('stat-assessments').textContent = assessments.length;
  document.getElementById('stat-runs').textContent = runs.length;
  document.getElementById('stat-findings').textContent = findings.filter(f => f.status === 'open').length;
  document.getElementById('findings-count-badge').textContent = findings.filter(f => f.status === 'open').length;
  if (findings.length > 0) {
    document.getElementById('findings-count-badge').classList.remove('hidden');
  }
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

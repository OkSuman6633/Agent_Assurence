// Agent Assurance Laboratory — End-to-End User Journeys (J1–J7) Controller
// Directly implements and connects all Section 7 APIs:
// J1: POST /v1/assessments (Create assessment project)
// J2: POST /v1/agents (Register agent adapter & boundaries)
// J3: GET  /v1/scenarios (Policy manifest & scenario packs)
// J4: POST /v1/assessments/{id}/runs & GET /v1/runs/{id} (Evaluate run & progress)
// J5: GET  /v1/runs/{id}/findings & POST /v1/findings/{id}/reviews (Review & triage)
// J6: POST /v1/runs/{id}/report (Export assessment artifact)
// J7: GET  /v1/runs/{id}/compare/{other} (Regression delta comparison)

const API_BASE = window.location.origin.includes('8000') 
  ? window.location.origin 
  : 'http://127.0.0.1:8000';

// Global execution state
const state = {
  activeTenant: 'tenant-alpha',
  activeRole: 'assessor',
  currentAssessmentId: null,
  currentAgentId: null,
  currentRunId: null,
  previousRunId: null,
  currentReportId: null,
  findings: [],
  expressResults: null,
  expressFilter: 'all',
  isHardened: false,
};

// ─── Headers Helper (Injects Active Tenant & RBAC Role) ───────────────
function getAuthHeaders(customHeaders = {}) {
  return {
    'Content-Type': 'application/json',
    'X-Tenant-ID': state.activeTenant,
    'X-User-Role': state.activeRole,
    ...customHeaders,
  };
}

// ─── DOM Initialization ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  setupTenantAndRoleSelectors();
  setupTabs();
  setupExpressPipeline();
  setupJourneyJ1();
  setupJourneyJ2();
  setupJourneyJ3();
  setupJourneyJ4();
  setupJourneyJ5();
  setupJourneyJ6();
  setupJourneyJ7();
  setupModals();

  await checkBackendHealth();
  await loadTenantData();
});

// ─── Health Check & Tenant Setup ──────────────────────────────────────
async function checkBackendHealth() {
  const statusDot = document.querySelector('#backend-status-pill .status-dot');
  const statusText = document.getElementById('backend-status-text');

  try {
    const res = await fetch(`${API_BASE}/health`);
    if (res.ok) {
      statusDot.className = 'status-dot online';
      statusText.textContent = 'API Ready (8000)';
    } else {
      throw new Error(`HTTP ${res.status}`);
    }
  } catch (err) {
    statusDot.className = 'status-dot offline';
    statusText.textContent = 'API Disconnected';
  }
}

function setupTenantAndRoleSelectors() {
  const tenantSelect = document.getElementById('tenant-select');
  const roleSelect = document.getElementById('role-select');

  tenantSelect.addEventListener('change', async () => {
    state.activeTenant = tenantSelect.value;
    document.querySelectorAll('.active-tenant-tag').forEach(el => el.textContent = state.activeTenant);
    showToast(`Active organization switched to ${state.activeTenant}`, 'info');
    await loadTenantData();
  });

  roleSelect.addEventListener('change', () => {
    state.activeRole = roleSelect.value;
    showToast(`Assessor role set to ${state.activeRole.toUpperCase()}`, 'info');
  });
}

async function loadTenantData() {
  await loadAssessmentsList();
  await loadAgentsList();
  await loadTenantUsage();
}

async function loadTenantUsage() {
  try {
    const res = await fetch(`${API_BASE}/v1/usage`, { headers: getAuthHeaders() });
    if (res.ok) {
      const data = await res.json();
      const budgetEl = document.getElementById('quota-budget-text');
      if (budgetEl && data.token_budget_remaining !== undefined) {
        budgetEl.textContent = Number(data.token_budget_remaining).toLocaleString();
      }
    }
  } catch (_) {}
}

// ─── Tab Switching ────────────────────────────────────────────────────
function setupTabs() {
  const tabs = document.querySelectorAll('.stepper-tab');
  const panels = document.querySelectorAll('.tab-panel');

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const targetId = tab.getAttribute('data-tab');
      tabs.forEach(t => t.classList.remove('active'));
      panels.forEach(p => p.classList.remove('active'));

      tab.classList.add('active');
      const targetPanel = document.getElementById(targetId);
      if (targetPanel) {
        targetPanel.classList.add('active');
      }
    });
  });
}

function switchTab(tabId) {
  const targetTabBtn = document.querySelector(`.stepper-tab[data-tab="${tabId}"]`);
  if (targetTabBtn) {
    targetTabBtn.click();
  }
}

// ─── Toast System ─────────────────────────────────────────────────────
function showToast(message, type = 'info') {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.className = `toast-notification toast-${type}`;
  toast.classList.remove('hidden');
  setTimeout(() => toast.classList.add('hidden'), 4000);
}

function displayApiResponse(wrapperId, statusId, timeId, jsonId, status, duration, data) {
  const wrap = document.getElementById(wrapperId);
  const statusEl = document.getElementById(statusId);
  const timeEl = document.getElementById(timeId);
  const jsonEl = document.getElementById(jsonId);

  wrap.classList.remove('hidden');
  statusEl.textContent = status;
  timeEl.textContent = `${duration} ms`;
  jsonEl.textContent = JSON.stringify(data, null, 2);
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

// ─── TAB 0: EXPRESS SCANNER ───────────────────────────────────────────
function setupExpressPipeline() {
  const expressForm = document.getElementById('express-form');
  const expressUrlInput = document.getElementById('express-url-input');
  const btnExpressClear = document.getElementById('btn-express-clear');
  const btnExpressRun = document.getElementById('btn-express-run');
  const btnExpressText = document.getElementById('btn-express-text');
  const expressSpinner = document.getElementById('express-spinner');

  const presetSynthVuln = document.getElementById('preset-express-synth-vuln');
  const presetSynthHard = document.getElementById('preset-express-synth-hard');
  const presetLocal = document.getElementById('preset-express-local');

  const consoleBox = document.getElementById('express-api-console');
  const consoleLogs = document.getElementById('console-logs');
  const consoleBadge = document.getElementById('console-status-badge');

  const btnGenReport = document.getElementById('btn-express-gen-report');
  const btnJumpFindings = document.getElementById('btn-express-jump-findings');
  const btnJumpCompare = document.getElementById('btn-express-jump-compare');

  // Filter pills
  const filterPills = document.querySelectorAll('[data-express-filter]');
  filterPills.forEach(pill => {
    pill.addEventListener('click', () => {
      filterPills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      state.expressFilter = pill.getAttribute('data-express-filter');
      if (state.expressResults) {
        renderExpressRules(state.expressResults.results);
      }
    });
  });

  // Presets
  presetSynthVuln.addEventListener('click', () => {
    expressUrlInput.value = '';
    state.isHardened = false;
    clearPresetHighlights();
    presetSynthVuln.classList.add('active');
    expressUrlInput.placeholder = 'Bundled Synthetic Agent (Vulnerable Demo Mode)';
  });

  presetSynthHard.addEventListener('click', () => {
    expressUrlInput.value = '';
    state.isHardened = true;
    clearPresetHighlights();
    presetSynthHard.classList.add('active');
    expressUrlInput.placeholder = 'Bundled Synthetic Agent (Hardened / Safe Mode)';
  });

  presetLocal.addEventListener('click', () => {
    expressUrlInput.value = `${API_BASE}/v1/agent/run`;
    state.isHardened = false;
    clearPresetHighlights();
    presetLocal.classList.add('active');
  });

  btnExpressClear.addEventListener('click', () => {
    expressUrlInput.value = '';
    state.isHardened = false;
    clearPresetHighlights();
    expressUrlInput.placeholder = 'Enter Agent URL (e.g. http://127.0.0.1:8000/v1/agent/run or leave empty for synthetic demo)';
  });

  function clearPresetHighlights() {
    [presetSynthVuln, presetSynthHard, presetLocal].forEach(p => p.classList.remove('active'));
  }

  btnGenReport.addEventListener('click', async () => {
    if (!state.currentRunId) return;
    switchTab('tab-j6-export');
    document.getElementById('j6-run-id').value = state.currentRunId;
    document.getElementById('btn-call-j6').click();
  });

  btnJumpFindings.addEventListener('click', () => {
    if (!state.currentRunId) return;
    switchTab('tab-j5-review');
    document.getElementById('j5-run-id').value = state.currentRunId;
    document.getElementById('btn-call-j5').click();
  });

  btnJumpCompare.addEventListener('click', () => {
    switchTab('tab-j7-regression');
    if (state.currentRunId) {
      document.getElementById('j7-current-id').value = state.currentRunId;
    }
    if (state.previousRunId) {
      document.getElementById('j7-baseline-id').value = state.previousRunId;
    }
  });

  // Execute Pipeline (J1 -> J2 -> J4 -> J5)
  expressForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const url = expressUrlInput.value.trim();
    const scenarioPack = document.querySelector('input[name="express_pack"]:checked').value;
    const budget = parseInt(document.getElementById('express-budget-input').value) || 5000;

    btnExpressRun.disabled = true;
    expressSpinner.classList.remove('hidden');
    btnExpressText.textContent = 'Evaluating Target Agent...';

    consoleBox.classList.remove('hidden');
    consoleLogs.innerHTML = '';
    consoleBadge.textContent = 'Executing Pipeline (J1 → J4)...';
    consoleBadge.className = 'console-badge badge-running';

    document.getElementById('express-results').classList.add('hidden');

    function logConsole(verb, path, statusCode, text, timeMs) {
      const row = document.createElement('div');
      row.className = 'console-log-row';
      const isSuccess = statusCode >= 200 && statusCode < 300;
      row.innerHTML = `
        <span class="log-verb ${verb.toLowerCase()}">${verb}</span>
        <span class="log-path">${path}</span>
        <span class="log-status ${isSuccess ? 'status-ok' : 'status-err'}">${statusCode}</span>
        <span class="log-time">${timeMs}ms</span>
        <span class="log-text">${escapeHtml(text)}</span>
      `;
      consoleLogs.appendChild(row);
      consoleLogs.scrollTop = consoleLogs.scrollHeight;
    }

    try {
      // ── Step 1: POST /v1/assessments (J1) ──
      const t0 = performance.now();
      const assessPayload = {
        title: url ? `Assessment: ${url}` : (state.isHardened ? 'Assessment: Hardened Synthetic Agent' : 'Assessment: Vulnerable Synthetic Demo'),
        scope: 'Automated evaluation against tool permission and security assertions.',
        agent_manifest_ref: url || 'Synthetic Demo Agent',
      };
      const resAssess = await fetch(`${API_BASE}/v1/assessments`, {
        method: 'POST',
        headers: getAuthHeaders({ 'X-Correlation-ID': 'exp-' + Date.now() }),
        body: JSON.stringify(assessPayload),
      });
      const tAssess = Math.round(performance.now() - t0);
      const dataAssess = await resAssess.json();

      if (!resAssess.ok) {
        logConsole('POST', '/v1/assessments', resAssess.status, dataAssess.message || dataAssess.detail || 'Failed', tAssess);
        throw new Error(dataAssess.message || dataAssess.detail || `POST /v1/assessments returned ${resAssess.status}`);
      }

      const assessmentId = dataAssess.assessment_id;
      state.currentAssessmentId = assessmentId;
      document.getElementById('j4-assessment-id').value = assessmentId;
      logConsole('POST', '/v1/assessments', resAssess.status, `assessment_id: ${assessmentId} (scope_hash: ${dataAssess.scope_hash})`, tAssess);

      // ── Step 2: POST /v1/assessments/{id}/runs (J4) ──
      const t1 = performance.now();
      const runPayload = {
        scenario_pack: scenarioPack,
        adapter: url || 'synthetic',
        model_budget: budget,
        hardened: state.isHardened,
      };
      const resRun = await fetch(`${API_BASE}/v1/assessments/${assessmentId}/runs`, {
        method: 'POST',
        headers: getAuthHeaders({
          'Idempotency-Key': 'exp-run-' + Date.now(),
          'X-Correlation-ID': 'exp-corr-' + Date.now(),
        }),
        body: JSON.stringify(runPayload),
      });
      const tRun = Math.round(performance.now() - t1);
      const dataRun = await resRun.json();

      if (!resRun.ok) {
        logConsole('POST', `/v1/assessments/${assessmentId}/runs`, resRun.status, dataRun.message || dataRun.detail || 'Failed', tRun);
        throw new Error(dataRun.message || dataRun.detail || `POST /v1/assessments/{id}/runs returned ${resRun.status}`);
      }

      const runId = dataRun.run_id;
      if (state.currentRunId) {
        state.previousRunId = state.currentRunId;
      }
      state.currentRunId = runId;
      document.getElementById('j5-run-id').value = runId;
      document.getElementById('j6-run-id').value = runId;
      document.getElementById('j7-current-id').value = runId;
      if (state.previousRunId) {
        document.getElementById('j7-baseline-id').value = state.previousRunId;
      }
      logConsole('POST', `/v1/assessments/${assessmentId}/runs`, resRun.status, `run_id: ${runId} (status: ${dataRun.status})`, tRun);

      // ── Step 3: GET /v1/runs/{id} (J4 Monitor) ──
      const t2 = performance.now();
      const resGetRun = await fetch(`${API_BASE}/v1/runs/${runId}`, { headers: getAuthHeaders() });
      const tGetRun = Math.round(performance.now() - t2);
      const dataGetRun = await resGetRun.json();

      if (!resGetRun.ok) {
        logConsole('GET', `/v1/runs/${runId}`, resGetRun.status, dataGetRun.message || 'Failed', tGetRun);
        throw new Error(dataGetRun.message || `GET /v1/runs/{id} returned ${resGetRun.status}`);
      }
      logConsole('GET', `/v1/runs/${runId}`, resGetRun.status, `status: ${dataGetRun.status}, progress: ${dataGetRun.progress}, summary: ${JSON.stringify(dataGetRun.summary)}`, tGetRun);

      // ── Step 4: GET /v1/runs/{id}/findings (J5 Findings) ──
      const t3 = performance.now();
      const resFindings = await fetch(`${API_BASE}/v1/runs/${runId}/findings`, { headers: getAuthHeaders() });
      const tFindings = Math.round(performance.now() - t3);
      const dataFindings = await resFindings.json();

      if (!resFindings.ok) {
        logConsole('GET', `/v1/runs/${runId}/findings`, resFindings.status, dataFindings.message || 'Failed', tFindings);
        throw new Error(dataFindings.message || `GET /v1/runs/{id}/findings returned ${resFindings.status}`);
      }
      const findingsList = dataFindings.items || [];
      state.findings = findingsList;
      logConsole('GET', `/v1/runs/${runId}/findings`, resFindings.status, `items: ${findingsList.length}, next_cursor: ${dataFindings.next_cursor}`, tFindings);

      consoleBadge.textContent = 'Evaluation Complete (200 OK)';
      consoleBadge.className = 'console-badge badge-success';

      state.expressResults = dataGetRun;
      renderExpressResults(dataGetRun, findingsList, assessmentId, runId);
      showToast(`Evaluation Complete: ${dataGetRun.summary.FAIL > 0 ? 'Violations Detected' : 'All Rules Passed'}`, dataGetRun.summary.FAIL > 0 ? 'error' : 'success');

      await loadAssessmentsList();
      await loadTenantUsage();

    } catch (err) {
      consoleBadge.textContent = 'Pipeline Failed';
      consoleBadge.className = 'console-badge badge-fail';
      showToast(err.message, 'error');
    } finally {
      btnExpressRun.disabled = false;
      expressSpinner.classList.add('hidden');
      btnExpressText.textContent = 'Run Assurance Evaluation';
    }
  });
}

function renderExpressResults(runData, findingsList, assessmentId, runId) {
  const resultsWrap = document.getElementById('express-results');
  resultsWrap.classList.remove('hidden');
  resultsWrap.scrollIntoView({ behavior: 'smooth', block: 'start' });

  const summary = runData.summary || { PASS: 0, FAIL: 0, INCONCLUSIVE: 0 };
  const failCount = summary.FAIL || 0;
  const passCount = summary.PASS || 0;
  const totalCount = (runData.results || []).length;

  const isViolation = failCount > 0;
  const verdictBanner = document.getElementById('express-verdict-banner');
  const verdictIcon = document.getElementById('express-verdict-icon');
  const verdictEyebrow = document.getElementById('express-verdict-eyebrow');
  const verdictHeadline = document.getElementById('express-verdict-headline');
  const verdictSubtext = document.getElementById('express-verdict-subtext');
  const statsPills = document.getElementById('express-stats-pills');

  if (isViolation) {
    verdictBanner.className = 'verdict-banner banner-fail';
    verdictIcon.innerHTML = '&#9888;';
    verdictEyebrow.textContent = 'ASSURANCE EVALUATION FAILED';
    verdictHeadline.textContent = `${failCount} Policy Violations Detected`;
    verdictSubtext.textContent = 'The agent violated permission boundaries, executed forbidden tools, or bypassed approval gates.';
  } else {
    verdictBanner.className = 'verdict-banner banner-pass';
    verdictIcon.innerHTML = '&#10003;';
    verdictEyebrow.textContent = 'ASSURANCE EVALUATION PASSED';
    verdictHeadline.textContent = `All ${passCount} Safety Policies Respected`;
    verdictSubtext.textContent = 'The agent respected all tool authorization boundaries, instruction barriers, and approval gates.';
  }

  statsPills.innerHTML = `
    <div class="stat-pill-box pill-violations">
      <span class="pill-number">${failCount}</span>
      <span class="pill-name">Violations</span>
    </div>
    <div class="stat-pill-box pill-passed">
      <span class="pill-number">${passCount}</span>
      <span class="pill-name">Passed</span>
    </div>
    <div class="stat-pill-box pill-rules">
      <span class="pill-number">${totalCount}</span>
      <span class="pill-name">Evaluated</span>
    </div>
  `;

  document.getElementById('express-meta-assessment').textContent = assessmentId.substring(0, 8) + '...';
  document.getElementById('express-meta-run').textContent = runId.substring(0, 8) + '...';
  document.getElementById('express-findings-count').textContent = findingsList.length;

  document.getElementById('exp-count-all').textContent = totalCount;
  document.getElementById('exp-count-fail').textContent = failCount;
  document.getElementById('exp-count-pass').textContent = passCount;

  renderExpressRules(runData.results || []);
}

function renderExpressRules(results) {
  const container = document.getElementById('express-rules-container');
  let filtered = results;

  if (state.expressFilter === 'fail') {
    filtered = results.filter(r => r.verdict === 'FAIL');
  } else if (state.expressFilter === 'pass') {
    filtered = results.filter(r => r.verdict === 'PASS');
  }

  if (filtered.length === 0) {
    container.innerHTML = `<div class="empty-filter-state"><p>No scenarios match the filter (${state.expressFilter.toUpperCase()}).</p></div>`;
    return;
  }

  container.innerHTML = filtered.map(r => {
    const isFail = r.verdict === 'FAIL';
    const cardClass = isFail ? 'rule-card-fail' : 'rule-card-pass';
    const badgeClass = isFail ? 'status-badge-fail' : 'status-badge-pass';
    const statusIcon = isFail ? '&#10007;' : '&#10003;';

    return `
      <div class="rule-card ${cardClass}">
        <div class="rule-card-top">
          <div class="rule-title-group">
            <span class="status-badge ${badgeClass}">${statusIcon} ${r.verdict}</span>
            <h4>${escapeHtml(r.scenario_id)}</h4>
          </div>
          <button type="button" class="btn-inspect-trace" onclick="openEvidenceTrace('${escapeHtml(r.scenario_id)}')">
            &#128065; Evidence Trace
          </button>
        </div>

        <p class="rule-summary-text">${escapeHtml(r.summary)}</p>

        ${r.checks_failed && r.checks_failed.length > 0 ? `
          <div class="violations-callout">
            <span class="callout-label">&#9888; Failed Assertions:</span>
            <ul>
              ${r.checks_failed.map(c => `<li><code>${escapeHtml(c)}</code></li>`).join('')}
            </ul>
          </div>
        ` : ''}

        <div class="rule-card-footer">
          <div class="rule-meta-tag">
            <span>Oracle: <code>${escapeHtml(r.oracle_id || 'deterministic-v2')}</code></span>
            <span class="sep">&bull;</span>
            <span>Evidence Complete: <strong>${r.evidence_complete ? 'YES' : 'NO'}</strong></span>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

// ─── JOURNEY J1: CREATE ASSESSMENT ────────────────────────────────────
function setupJourneyJ1() {
  const form = document.getElementById('form-j1-assessment');
  const btn = document.getElementById('btn-call-j1');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const title = document.getElementById('j1-title').value.trim();
    const manifestRef = document.getElementById('j1-manifest-ref').value.trim();
    const scope = document.getElementById('j1-scope').value.trim();

    btn.disabled = true;
    const t0 = performance.now();

    try {
      const res = await fetch(`${API_BASE}/v1/assessments`, {
        method: 'POST',
        headers: getAuthHeaders({ 'X-Correlation-ID': 'j1-' + Date.now() }),
        body: JSON.stringify({
          title: title,
          scope: scope,
          agent_manifest_ref: manifestRef,
        }),
      });
      const duration = Math.round(performance.now() - t0);
      const data = await res.json();

      displayApiResponse(
        'resp-j1-wrap',
        'resp-j1-status',
        'resp-j1-time',
        'resp-j1-json',
        `${res.status} ${res.statusText}`,
        duration,
        data
      );

      if (res.ok && data.assessment_id) {
        state.currentAssessmentId = data.assessment_id;
        document.getElementById('j4-assessment-id').value = data.assessment_id;
        showToast(`Created Assessment: ${data.assessment_id.substring(0, 8)}... (Scope Hash: ${data.scope_hash})`, 'success');
        await loadAssessmentsList();
      } else {
        showToast(data.message || data.detail || 'Error creating assessment', 'error');
      }
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

async function loadAssessmentsList() {
  const container = document.getElementById('j1-assessments-list');
  try {
    const res = await fetch(`${API_BASE}/v1/assessments`, { headers: getAuthHeaders() });
    if (!res.ok) return;
    const items = await res.json();

    if (items.length === 0) {
      container.innerHTML = '<p class="text-sm text-muted">No assessment projects configured for this tenant yet.</p>';
      return;
    }

    container.innerHTML = items.map(a => `
      <div class="record-row" onclick="selectAssessment('${a.assessment_id}')">
        <span class="record-title"><strong>${escapeHtml(a.title)}</strong></span>
        <span class="record-id"><code>${a.assessment_id.substring(0, 8)}...</code></span>
        <span class="record-hash">Scope Hash: <code>${a.scope_hash}</code></span>
        <span class="status-badge ${a.status === 'completed' ? 'status-badge-pass' : 'status-badge-fail'}">${a.status}</span>
      </div>
    `).join('');
  } catch (_) {}
}

window.selectAssessment = (id) => {
  state.currentAssessmentId = id;
  document.getElementById('j4-assessment-id').value = id;
  showToast(`Selected Assessment: ${id.substring(0, 8)}...`, 'info');
};

// ─── JOURNEY J2: REGISTER AGENT ADAPTER ────────────────────────────────
function setupJourneyJ2() {
  const form = document.getElementById('form-j2-agent');
  const btn = document.getElementById('btn-call-j2');
  const typeSelect = document.getElementById('j2-type');
  const endpointRow = document.getElementById('j2-endpoint-row');

  typeSelect.addEventListener('change', () => {
    if (typeSelect.value === 'synthetic') {
      document.getElementById('j2-endpoint-url').value = '';
      document.getElementById('j2-endpoint-url').placeholder = 'Bundled in-process mock adapter (no URL required)';
    } else {
      document.getElementById('j2-endpoint-url').placeholder = 'http://127.0.0.1:8000/v1/agent/run or https://agent.sandbox.local/run';
    }
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('j2-name').value.trim();
    const adapterType = document.getElementById('j2-type').value;
    const endpointUrl = document.getElementById('j2-endpoint-url').value.trim();
    const hosts = document.getElementById('j2-hosts').value.split(',').map(h => h.trim()).filter(Boolean);
    const timeout = parseFloat(document.getElementById('j2-timeout').value) || 15.0;
    const authorised = document.getElementById('j2-auth-confirm').checked;

    btn.disabled = true;
    const t0 = performance.now();

    try {
      const res = await fetch(`${API_BASE}/v1/agents`, {
        method: 'POST',
        headers: getAuthHeaders({ 'X-Correlation-ID': 'j2-' + Date.now() }),
        body: JSON.stringify({
          name: name,
          adapter_type: adapterType,
          endpoint_url: endpointUrl || null,
          allowed_hosts: hosts,
          timeout_seconds: timeout,
          authorised: authorised,
          scope_description: 'Registered adapter for bounded assurance evaluation',
        }),
      });
      const duration = Math.round(performance.now() - t0);
      const data = await res.json();

      displayApiResponse(
        'resp-j2-wrap',
        'resp-j2-status',
        'resp-j2-time',
        'resp-j2-json',
        `${res.status} ${res.statusText}`,
        duration,
        data
      );

      if (res.ok && data.agent_id) {
        state.currentAgentId = data.agent_id;
        document.getElementById('j1-manifest-ref').value = data.agent_id;
        showToast(`Registered Agent Adapter: ${data.name} (${data.agent_id.substring(0, 8)}...)`, 'success');
        await loadAgentsList();
      } else {
        showToast(data.message || data.detail || 'Error registering agent', 'error');
      }
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

async function loadAgentsList() {
  const container = document.getElementById('j2-agents-list');
  try {
    const res = await fetch(`${API_BASE}/v1/agents`, { headers: getAuthHeaders() });
    if (!res.ok) return;
    const items = await res.json();

    if (items.length === 0) {
      container.innerHTML = '<p class="text-sm text-muted">No agent adapters registered for this tenant yet.</p>';
      return;
    }

    container.innerHTML = items.map(a => `
      <div class="record-row" onclick="selectAgent('${a.agent_id}', '${escapeHtml(a.endpoint_url || 'synthetic')}')">
        <span class="record-title"><strong>${escapeHtml(a.name)}</strong> (${a.adapter_type})</span>
        <span class="record-id"><code>${a.agent_id.substring(0, 8)}...</code></span>
        <span class="record-hash">${a.endpoint_url || 'In-Process Synthetic'}</span>
        <span class="status-badge status-badge-pass">${a.authorised ? 'Authorised' : 'Pending'}</span>
      </div>
    `).join('');
  } catch (_) {}
}

window.selectAgent = (agentId, endpoint) => {
  state.currentAgentId = agentId;
  document.getElementById('j1-manifest-ref').value = agentId;
  document.getElementById('j4-adapter').value = endpoint;
  showToast(`Selected Agent: ${agentId.substring(0, 8)}...`, 'info');
};

// ─── JOURNEY J3: POLICY MANIFEST & SCENARIOS ──────────────────────────
async function setupJourneyJ3() {
  const packSelect = document.getElementById('j3-pack-select');
  const manifestView = document.getElementById('j3-manifest-view');
  const btnProceed = document.getElementById('btn-j3-proceed');
  const scenariosGrid = document.getElementById('j3-scenarios-grid');

  async function updateScenariosCatalog() {
    try {
      const res = await fetch(`${API_BASE}/v1/scenarios`);
      if (!res.ok) return;
      const allScenarios = await res.json();

      let activeScenarios = allScenarios;
      if (packSelect.value === 'core-v1') {
        const coreIds = ['allowed_tool_smoke_v1', 'prompt_injection_boundary_v1', 'approval_gate_v1', 'retry_idempotency_v1'];
        activeScenarios = allScenarios.filter(s => coreIds.includes(s.scenario_id));
      }

      manifestView.value = JSON.stringify({
        schema_version: '2026-10-approval',
        scenario_pack: packSelect.value,
        deterministic_oracle: 'deterministic-v2',
        framework_mappings: ['OWASP Agentic Top 10 2026', 'NIST AI 600-1 GenAI Profile'],
        scenarios_count: activeScenarios.length,
        scenarios: activeScenarios.map(s => ({
          scenario_id: s.scenario_id,
          category: s.category,
          severity: s.severity,
          prohibited_tools: s.prohibited_tools,
        })),
      }, null, 2);

      scenariosGrid.innerHTML = activeScenarios.map(s => `
        <div class="rule-card rule-card-pass">
          <div class="rule-card-top">
            <div class="rule-title-group">
              <span class="severity-tag sev-${s.severity}">${s.severity.toUpperCase()}</span>
              <h4>${escapeHtml(s.scenario_id)}</h4>
            </div>
          </div>
          <p class="rule-summary-text">${escapeHtml(s.objective)}</p>
          <div class="rule-card-footer">
            <div class="rule-meta-tag">
              <span>Category: <em>${escapeHtml(s.category)}</em></span>
              <span class="sep">&bull;</span>
              <span>Hash: <code>${(s.fixture_hash || 'fixture').substring(0, 8)}</code></span>
            </div>
          </div>
        </div>
      `).join('');
    } catch (_) {}
  }

  packSelect.addEventListener('change', updateScenariosCatalog);
  btnProceed.addEventListener('click', () => switchTab('tab-j4-evaluate'));

  await updateScenariosCatalog();
}

// ─── JOURNEY J4: START RUN & EVALUATE ─────────────────────────────────
function setupJourneyJ4() {
  const form = document.getElementById('form-j4-run');
  const btn = document.getElementById('btn-call-j4');
  const runDetails = document.getElementById('j4-run-details');
  const summaryPills = document.getElementById('j4-summary-pills');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const assessmentId = document.getElementById('j4-assessment-id').value.trim();
    const scenarioPack = document.getElementById('j4-scenario-pack').value;
    const adapter = document.getElementById('j4-adapter').value.trim();
    const budget = parseInt(document.getElementById('j4-budget').value) || 5000;
    const hardened = document.getElementById('j4-hardened').checked;

    if (!assessmentId) {
      showToast('Assessment ID is required. Create one in J1.', 'error');
      return;
    }

    btn.disabled = true;
    const t0 = performance.now();

    try {
      const res = await fetch(`${API_BASE}/v1/assessments/${assessmentId}/runs`, {
        method: 'POST',
        headers: getAuthHeaders({
          'Idempotency-Key': 'j4-run-' + Date.now(),
          'X-Correlation-ID': 'j4-corr-' + Date.now(),
        }),
        body: JSON.stringify({
          scenario_pack: scenarioPack,
          adapter: adapter,
          model_budget: budget,
          hardened: hardened,
        }),
      });
      const duration = Math.round(performance.now() - t0);
      const data = await res.json();

      displayApiResponse(
        'resp-j4-wrap',
        'resp-j4-status',
        'resp-j4-time',
        'resp-j4-json',
        `${res.status} ${res.statusText}`,
        duration,
        data
      );

      if (res.ok && data.run_id) {
        if (state.currentRunId) {
          state.previousRunId = state.currentRunId;
        }
        state.currentRunId = data.run_id;
        document.getElementById('j5-run-id').value = data.run_id;
        document.getElementById('j6-run-id').value = data.run_id;
        document.getElementById('j7-current-id').value = data.run_id;
        if (state.previousRunId) {
          document.getElementById('j7-baseline-id').value = state.previousRunId;
        }

        runDetails.classList.remove('hidden');
        document.getElementById('j4-run-status-text').textContent = data.status.toUpperCase();
        document.getElementById('j4-progress-pct').textContent = '100%';

        const summary = data.summary || {};
        summaryPills.innerHTML = `
          <div class="stat-pill-box pill-violations">
            <span class="pill-number">${summary.FAIL || 0}</span>
            <span class="pill-name">Failures</span>
          </div>
          <div class="stat-pill-box pill-passed">
            <span class="pill-number">${summary.PASS || 0}</span>
            <span class="pill-name">Passed</span>
          </div>
          <div class="stat-pill-box pill-rules">
            <span class="pill-number">${(data.results || []).length}</span>
            <span class="pill-name">Total</span>
          </div>
        `;

        showToast(`Run Completed: ${summary.FAIL || 0} failures detected`, summary.FAIL > 0 ? 'error' : 'success');
        await loadTenantUsage();
      } else {
        showToast(data.message || data.detail || 'Error running evaluation', 'error');
      }
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

// ─── JOURNEY J5: EVIDENCE REVIEW & TRIAGE ─────────────────────────────
function setupJourneyJ5() {
  const form = document.getElementById('form-j5-findings');
  const btn = document.getElementById('btn-call-j5');
  const container = document.getElementById('j5-findings-container');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const runId = document.getElementById('j5-run-id').value.trim();
    if (!runId) {
      showToast('Run ID is required.', 'error');
      return;
    }

    btn.disabled = true;

    try {
      const res = await fetch(`${API_BASE}/v1/runs/${runId}/findings`, { headers: getAuthHeaders() });
      const data = await res.json();
      const items = data.items || [];
      state.findings = items;

      if (items.length === 0) {
        container.innerHTML = '<div class="empty-filter-state"><p>No security findings generated for this run.</p></div>';
      } else {
        container.innerHTML = items.map(f => `
          <div class="rule-card rule-card-fail">
            <div class="rule-card-top">
              <div class="rule-title-group">
                <span class="severity-tag sev-${f.severity}">${f.severity.toUpperCase()}</span>
                <span class="status-badge ${f.status === 'false_positive' ? 'status-badge-pass' : 'status-badge-fail'}">
                  ${f.status.toUpperCase()}
                </span>
                <h4>${escapeHtml(f.title || f.scenario_id)}</h4>
              </div>
              <button type="button" class="btn-inspect-trace" onclick="openReviewModal('${f.finding_id}')">
                &#9998; Mark False Positive / Review
              </button>
            </div>
            <p class="rule-summary-text">${escapeHtml(f.description)}</p>
            <div class="rule-card-footer">
              <div class="rule-meta-tag">
                <span>Category: <em>${escapeHtml(f.category)}</em></span>
                <span class="sep">&bull;</span>
                <span>ID: <code>${f.finding_id.substring(0, 8)}...</code></span>
              </div>
            </div>
          </div>
        `).join('');
      }

      showToast(`Retrieved ${items.length} findings for run ${runId.substring(0, 8)}...`, 'info');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

// ─── JOURNEY J6: EXPORT ASSESSMENT REPORT ─────────────────────────────
function setupJourneyJ6() {
  const form = document.getElementById('form-j6-report');
  const btn = document.getElementById('btn-call-j6');
  const downloadLink = document.getElementById('btn-j6-download');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const runId = document.getElementById('j6-run-id').value.trim();
    const format = document.getElementById('j6-format').value;

    if (!runId) {
      showToast('Run ID is required.', 'error');
      return;
    }

    btn.disabled = true;
    const t0 = performance.now();

    try {
      const res = await fetch(`${API_BASE}/v1/runs/${runId}/report`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ format }),
      });
      const duration = Math.round(performance.now() - t0);
      const data = await res.json();

      displayApiResponse(
        'resp-j6-wrap',
        'resp-j6-status',
        'resp-j6-time',
        'resp-j6-json',
        `${res.status} ${res.statusText}`,
        duration,
        data
      );

      if (res.ok && (data.artifact_id || data.artifact_job_id)) {
        const artifactId = data.artifact_id || data.artifact_job_id;
        state.currentReportId = artifactId;
        downloadLink.href = `${API_BASE}/v1/reports/${artifactId}/download`;
        showToast(`Official Assessment Artifact Generated: ${artifactId.substring(0, 8)}...`, 'success');
      } else {
        showToast(data.message || data.detail || 'Error generating report', 'error');
      }
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

// ─── JOURNEY J7: REGRESSION DELTA COMPARISON ──────────────────────────
function setupJourneyJ7() {
  const form = document.getElementById('form-j7-compare');
  const btn = document.getElementById('btn-call-j7');
  const container = document.getElementById('j7-deltas-container');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const currentId = document.getElementById('j7-current-id').value.trim();
    const baselineId = document.getElementById('j7-baseline-id').value.trim();

    if (!currentId || !baselineId) {
      showToast('Both Current Run ID and Baseline Run ID are required.', 'error');
      return;
    }

    btn.disabled = true;
    const t0 = performance.now();

    try {
      const res = await fetch(`${API_BASE}/v1/runs/${currentId}/compare/${baselineId}`, { headers: getAuthHeaders() });
      const duration = Math.round(performance.now() - t0);
      const data = await res.json();

      displayApiResponse(
        'resp-j7-wrap',
        'resp-j7-status',
        'resp-j7-time',
        'resp-j7-json',
        `${res.status} ${res.statusText}`,
        duration,
        data
      );

      const deltas = data.scenario_deltas || [];
      if (deltas.length === 0) {
        container.innerHTML = '<div class="empty-filter-state"><p>No scenario deltas between these two runs.</p></div>';
      } else {
        container.innerHTML = `
          <div class="comparison-summary-bar" style="grid-column: 1 / -1; margin-bottom: 12px;">
            <span>Resolved Failures: <strong class="text-success">${data.resolved_failures}</strong></span>
            <span class="sep">&bull;</span>
            <span>New Regressions: <strong class="text-danger">${data.new_failures}</strong></span>
            <span class="sep">&bull;</span>
            <span>Overall Changed: <strong>${data.overall_changed ? 'YES' : 'NO'}</strong></span>
          </div>
          ${deltas.map(d => `
            <div class="rule-card ${d.changed ? 'rule-card-fail' : 'rule-card-pass'}">
              <div class="rule-card-top">
                <div class="rule-title-group">
                  <span class="status-badge ${d.changed ? 'status-badge-fail' : 'status-badge-pass'}">
                    ${d.changed ? 'DELTA DETECTED' : 'STABLE'}
                  </span>
                  <h4>${escapeHtml(d.scenario_id)}</h4>
                </div>
              </div>
              <p class="rule-summary-text">
                Baseline Verdict: <strong>${escapeHtml(d.baseline_verdict || 'N/A')}</strong> &rarr; 
                Current Verdict: <strong>${escapeHtml(d.current_verdict || 'N/A')}</strong>
              </p>
            </div>
          `).join('')}
        `;
      }

      showToast(`Regression Compared: ${data.resolved_failures} resolved, ${data.new_failures} regressions`, 'info');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

// ─── MODALS ───────────────────────────────────────────────────────────
function setupModals() {
  const evModal = document.getElementById('evidence-modal');
  const evClose = document.getElementById('modal-close');
  const revModal = document.getElementById('review-modal');
  const revClose = document.getElementById('rev-modal-close');
  const modalRevForm = document.getElementById('modal-review-form');

  evClose.addEventListener('click', () => evModal.classList.add('hidden'));
  revClose.addEventListener('click', () => revModal.classList.add('hidden'));

  window.openEvidenceTrace = (scenarioId) => {
    if (!state.expressResults || !state.expressResults.results) return;
    const item = state.expressResults.results.find(r => r.scenario_id === scenarioId);
    if (!item) return;

    document.getElementById('modal-title').textContent = `Evidence Trace: ${scenarioId}`;
    document.getElementById('modal-scenario-tag').textContent = `Verdict: ${item.verdict}`;
    document.getElementById('modal-json').textContent = JSON.stringify(item.trace || {}, null, 2);
    evModal.classList.remove('hidden');
  };

  window.openReviewModal = (findingId) => {
    document.getElementById('rev-modal-fid').textContent = findingId;
    document.getElementById('modal-review-form').setAttribute('data-target-fid', findingId);
    revModal.classList.remove('hidden');
  };

  modalRevForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const findingId = modalRevForm.getAttribute('data-target-fid');
    const decision = document.getElementById('modal-rev-decision').value;
    const reason = document.getElementById('modal-rev-reason').value.trim();

    try {
      const res = await fetch(`${API_BASE}/v1/findings/${findingId}/reviews`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ decision, reason }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`Review Saved for ${findingId.substring(0, 8)}... (${decision})`, 'success');
        revModal.classList.add('hidden');
        if (state.currentRunId) {
          document.getElementById('btn-call-j5').click();
        }
      } else {
        showToast(data.message || data.detail || 'Error saving review', 'error');
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}

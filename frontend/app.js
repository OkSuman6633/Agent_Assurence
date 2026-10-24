// Agent Assurance Laboratory — Section 7 API Protocol Controller
// Directly implements and visualizes the exact API contract:
// 1. POST /v1/assessments
// 2. POST /v1/assessments/{id}/runs
// 3. GET /v1/runs/{id}
// 4. GET /v1/runs/{id}/findings
// 5. POST /v1/findings/{id}/reviews
// 6. POST /v1/runs/{id}/report
// 7. GET /v1/runs/{id}/compare/{other}

const API_BASE = window.location.origin.includes('8000') 
  ? window.location.origin 
  : 'http://127.0.0.1:8000';

// Global execution state
const state = {
  currentAssessmentId: null,
  currentRunId: null,
  previousRunId: null,
  currentReportId: null,
  findings: [],
  expressResults: null,
  expressFilter: 'all',
  isHardened: false,
};

// ─── DOM Initialization ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setupTabs();
  setupExpressPipeline();
  setupAssessmentEndpoint();
  setupRunsEndpoint();
  setupRunStatusEndpoint();
  setupFindingsEndpoint();
  setupReviewsEndpoint();
  setupReportsEndpoint();
  setupCompareEndpoint();
  setupModals();

  checkBackendHealth();
});

// ─── Health Check ─────────────────────────────────────────────────────
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

// ─── Helper: Format & Display API Responses ───────────────────────────
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

// ─── TAB 0: EXPRESS PIPELINE ──────────────────────────────────────────
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

  // Quick Action Buttons in Results
  btnGenReport.addEventListener('click', async () => {
    if (!state.currentRunId) return;
    switchTab('tab-reports');
    document.getElementById('report-run-id').value = state.currentRunId;
    document.getElementById('btn-call-report').click();
  });

  btnJumpFindings.addEventListener('click', () => {
    if (!state.currentRunId) return;
    switchTab('tab-findings');
    document.getElementById('findings-run-id').value = state.currentRunId;
    document.getElementById('btn-call-findings').click();
  });

  btnJumpCompare.addEventListener('click', () => {
    switchTab('tab-compare');
    if (state.currentRunId) {
      document.getElementById('comp-current-id').value = state.currentRunId;
    }
    if (state.previousRunId) {
      document.getElementById('comp-baseline-id').value = state.previousRunId;
    }
  });

  // Execute Pipeline
  expressForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const url = expressUrlInput.value.trim();
    const scenarioPack = document.querySelector('input[name="express_pack"]:checked').value;
    const budget = parseInt(document.getElementById('express-budget-input').value) || 5000;

    btnExpressRun.disabled = true;
    expressSpinner.classList.remove('hidden');
    btnExpressText.textContent = 'Running Section 7 Pipeline...';

    consoleBox.classList.remove('hidden');
    consoleLogs.innerHTML = '';
    consoleBadge.textContent = 'Executing Pipeline (Steps 1 → 4)...';
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
      // ── Step 1: POST /v1/assessments ──
      const t0 = performance.now();
      const assessPayload = {
        title: url ? `Assessment: ${url}` : (state.isHardened ? 'Assessment: Hardened Synthetic Agent' : 'Assessment: Vulnerable Synthetic Demo'),
        scope: 'Automated evaluation against tool permission and security assertions.',
        agent_manifest_ref: url || 'Synthetic Demo Agent',
      };
      const resAssess = await fetch(`${API_BASE}/v1/assessments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Correlation-ID': 'exp-' + Date.now() },
        body: JSON.stringify(assessPayload),
      });
      const tAssess = Math.round(performance.now() - t0);
      const dataAssess = await resAssess.json();

      if (!resAssess.ok) {
        logConsole('POST', '/v1/assessments', resAssess.status, dataAssess.detail || 'Failed', tAssess);
        throw new Error(dataAssess.detail || `POST /v1/assessments returned ${resAssess.status}`);
      }

      const assessmentId = dataAssess.assessment_id;
      state.currentAssessmentId = assessmentId;
      document.getElementById('run-assessment-id').value = assessmentId;
      logConsole('POST', '/v1/assessments', resAssess.status, `assessment_id: ${assessmentId} (status: ${dataAssess.status})`, tAssess);

      // ── Step 2: POST /v1/assessments/{id}/runs ──
      const t1 = performance.now();
      const runPayload = {
        scenario_pack: scenarioPack,
        adapter: url || 'synthetic',
        model_budget: budget,
        hardened: state.isHardened,
      };
      const resRun = await fetch(`${API_BASE}/v1/assessments/${assessmentId}/runs`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': 'exp-run-' + Date.now(),
          'X-Correlation-ID': 'exp-corr-' + Date.now(),
        },
        body: JSON.stringify(runPayload),
      });
      const tRun = Math.round(performance.now() - t1);
      const dataRun = await resRun.json();

      if (!resRun.ok) {
        logConsole('POST', `/v1/assessments/${assessmentId}/runs`, resRun.status, dataRun.detail || 'Failed', tRun);
        throw new Error(dataRun.detail || `POST /v1/assessments/{id}/runs returned ${resRun.status}`);
      }

      const runId = dataRun.run_id;
      if (state.currentRunId) {
        state.previousRunId = state.currentRunId;
      }
      state.currentRunId = runId;
      document.getElementById('get-run-id').value = runId;
      document.getElementById('findings-run-id').value = runId;
      document.getElementById('report-run-id').value = runId;
      logConsole('POST', `/v1/assessments/${assessmentId}/runs`, resRun.status, `run_id: ${runId} (status: ${dataRun.status})`, tRun);

      // ── Step 3: GET /v1/runs/{id} ──
      const t2 = performance.now();
      const resGetRun = await fetch(`${API_BASE}/v1/runs/${runId}`);
      const tGetRun = Math.round(performance.now() - t2);
      const dataGetRun = await resGetRun.json();

      if (!resGetRun.ok) {
        logConsole('GET', `/v1/runs/${runId}`, resGetRun.status, dataGetRun.detail || 'Failed', tGetRun);
        throw new Error(dataGetRun.detail || `GET /v1/runs/{id} returned ${resGetRun.status}`);
      }
      logConsole('GET', `/v1/runs/${runId}`, resGetRun.status, `status: ${dataGetRun.status}, progress: ${dataGetRun.progress}, summary: ${JSON.stringify(dataGetRun.summary)}`, tGetRun);

      // ── Step 4: GET /v1/runs/{id}/findings ──
      const t3 = performance.now();
      const resFindings = await fetch(`${API_BASE}/v1/runs/${runId}/findings`);
      const tFindings = Math.round(performance.now() - t3);
      const dataFindings = await resFindings.json();

      if (!resFindings.ok) {
        logConsole('GET', `/v1/runs/${runId}/findings`, resFindings.status, dataFindings.detail || 'Failed', tFindings);
        throw new Error(dataFindings.detail || `GET /v1/runs/{id}/findings returned ${resFindings.status}`);
      }
      const findingsList = dataFindings.items || [];
      state.findings = findingsList;
      logConsole('GET', `/v1/runs/${runId}/findings`, resFindings.status, `items: ${findingsList.length}, next_cursor: ${dataFindings.next_cursor}`, tFindings);

      consoleBadge.textContent = 'Pipeline Completed (200 OK)';
      consoleBadge.className = 'console-badge badge-success';

      // Store and render results
      state.expressResults = dataGetRun;
      renderExpressResults(dataGetRun, findingsList, assessmentId, runId);
      showToast(`Assessment Completed: ${dataGetRun.summary.FAIL > 0 ? 'Violations Detected' : 'All Rules Passed'}`, dataGetRun.summary.FAIL > 0 ? 'error' : 'success');

    } catch (err) {
      consoleBadge.textContent = 'Pipeline Failed';
      consoleBadge.className = 'console-badge badge-fail';
      showToast(err.message, 'error');
    } finally {
      btnExpressRun.disabled = false;
      expressSpinner.classList.add('hidden');
      btnExpressText.textContent = 'Execute Assessment Pipeline';
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
  const inconclCount = summary.INCONCLUSIVE || 0;
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
    verdictSubtext.textContent = 'The agent violated permission boundaries, executed forbidden tools, or bypassed approval checks.';
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

// ─── TAB 1: POST /v1/assessments ──────────────────────────────────────
function setupAssessmentEndpoint() {
  const form = document.getElementById('form-create-assessment');
  const btn = document.getElementById('btn-call-assessment');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const title = document.getElementById('assess-title').value.trim();
    const scope = document.getElementById('assess-scope').value.trim();
    const manifestRef = document.getElementById('assess-manifest-ref').value.trim();

    btn.disabled = true;
    const t0 = performance.now();

    try {
      const res = await fetch(`${API_BASE}/v1/assessments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Correlation-ID': 'req-' + Date.now() },
        body: JSON.stringify({
          title: title,
          scope: scope,
          agent_manifest_ref: manifestRef,
        }),
      });
      const duration = Math.round(performance.now() - t0);
      const data = await res.json();

      displayApiResponse(
        'resp-assessment-wrap',
        'resp-assessment-status',
        'resp-assessment-time',
        'resp-assessment-json',
        `${res.status} ${res.statusText}`,
        duration,
        data
      );

      if (res.ok && data.assessment_id) {
        state.currentAssessmentId = data.assessment_id;
        document.getElementById('run-assessment-id').value = data.assessment_id;
        showToast(`Created Assessment: ${data.assessment_id.substring(0, 8)}...`, 'success');
      } else {
        showToast(data.detail || 'Error creating assessment', 'error');
      }
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

// ─── TAB 2: POST /v1/assessments/{id}/runs ────────────────────────────
function setupRunsEndpoint() {
  const form = document.getElementById('form-start-run');
  const btn = document.getElementById('btn-call-run');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const assessmentId = document.getElementById('run-assessment-id').value.trim();
    const scenarioPack = document.getElementById('run-scenario-pack').value;
    const adapter = document.getElementById('run-adapter').value.trim();
    const budget = parseInt(document.getElementById('run-budget').value) || 5000;
    const hardened = document.getElementById('run-hardened').checked;

    if (!assessmentId) {
      showToast('Assessment ID is required.', 'error');
      return;
    }

    btn.disabled = true;
    const t0 = performance.now();

    try {
      const res = await fetch(`${API_BASE}/v1/assessments/${assessmentId}/runs`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': 'run-' + Date.now(),
          'X-Correlation-ID': 'corr-' + Date.now(),
        },
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
        'resp-run-wrap',
        'resp-run-status',
        'resp-run-time',
        'resp-run-json',
        `${res.status} ${res.statusText}`,
        duration,
        data
      );

      if (res.ok && data.run_id) {
        if (state.currentRunId) {
          state.previousRunId = state.currentRunId;
        }
        state.currentRunId = data.run_id;
        document.getElementById('get-run-id').value = data.run_id;
        document.getElementById('findings-run-id').value = data.run_id;
        document.getElementById('report-run-id').value = data.run_id;
        document.getElementById('comp-current-id').value = data.run_id;
        if (state.previousRunId) {
          document.getElementById('comp-baseline-id').value = state.previousRunId;
        }
        showToast(`Run Dispatched: ${data.run_id.substring(0, 8)}...`, 'success');
      } else {
        showToast(data.detail || 'Error starting run', 'error');
      }
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

// ─── TAB 3: GET /v1/runs/{id} ─────────────────────────────────────────
function setupRunStatusEndpoint() {
  const form = document.getElementById('form-get-run');
  const btn = document.getElementById('btn-call-get-run');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const runId = document.getElementById('get-run-id').value.trim();
    if (!runId) {
      showToast('Run ID is required.', 'error');
      return;
    }

    btn.disabled = true;
    const t0 = performance.now();

    try {
      const res = await fetch(`${API_BASE}/v1/runs/${runId}`);
      const duration = Math.round(performance.now() - t0);
      const data = await res.json();

      displayApiResponse(
        'resp-get-run-wrap',
        'resp-get-run-status',
        'resp-get-run-time',
        'resp-get-run-json',
        `${res.status} ${res.statusText}`,
        duration,
        data
      );

      if (res.ok) {
        state.expressResults = data;
        showToast(`Run Status: ${data.status} (Pass: ${data.summary?.PASS || 0}, Fail: ${data.summary?.FAIL || 0})`, 'info');
      } else {
        showToast(data.detail || 'Error fetching run', 'error');
      }
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

// ─── TAB 4: GET /v1/runs/{id}/findings ────────────────────────────────
function setupFindingsEndpoint() {
  const form = document.getElementById('form-get-findings');
  const btn = document.getElementById('btn-call-findings');
  const cardsWrap = document.getElementById('findings-cards-wrap');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const runId = document.getElementById('findings-run-id').value.trim();
    if (!runId) {
      showToast('Run ID is required.', 'error');
      return;
    }

    btn.disabled = true;
    const t0 = performance.now();

    try {
      const res = await fetch(`${API_BASE}/v1/runs/${runId}/findings`);
      const duration = Math.round(performance.now() - t0);
      const data = await res.json();

      displayApiResponse(
        'resp-findings-wrap',
        'resp-findings-status',
        'resp-findings-time',
        'resp-findings-json',
        `${res.status} ${res.statusText}`,
        duration,
        data
      );

      const items = data.items || [];
      state.findings = items;

      if (items.length === 0) {
        cardsWrap.innerHTML = '<div class="empty-filter-state"><p>No security findings generated for this run.</p></div>';
      } else {
        cardsWrap.innerHTML = items.map(f => `
          <div class="rule-card rule-card-fail">
            <div class="rule-card-top">
              <div class="rule-title-group">
                <span class="severity-tag sev-${f.severity}">${f.severity.toUpperCase()}</span>
                <span class="status-badge status-badge-fail">${f.status}</span>
                <h4>${escapeHtml(f.title || f.scenario_id)}</h4>
              </div>
              <button type="button" class="btn-inspect-trace" onclick="openReviewModal('${f.finding_id}')">
                &#9998; Review Finding
              </button>
            </div>
            <p class="rule-summary-text">${escapeHtml(f.description)}</p>
            <div class="rule-card-footer">
              <div class="rule-meta-tag">
                <span>Category: <em>${escapeHtml(f.category)}</em></span>
                <span class="sep">&bull;</span>
                <span>Finding ID: <code>${f.finding_id.substring(0, 8)}...</code></span>
              </div>
            </div>
          </div>
        `).join('');
      }

      showToast(`Retrieved ${items.length} findings`, 'info');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

// ─── TAB 5: POST /v1/findings/{id}/reviews ────────────────────────────
function setupReviewsEndpoint() {
  const form = document.getElementById('form-review-finding');
  const btn = document.getElementById('btn-call-review');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const findingId = document.getElementById('review-finding-id').value.trim();
    const decision = document.getElementById('review-decision').value;
    const reason = document.getElementById('review-reason').value.trim();

    if (!findingId || !reason) {
      showToast('Finding ID and reason are mandatory.', 'error');
      return;
    }

    btn.disabled = true;
    const t0 = performance.now();

    try {
      const res = await fetch(`${API_BASE}/v1/findings/${findingId}/reviews`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, reason }),
      });
      const duration = Math.round(performance.now() - t0);
      const data = await res.json();

      displayApiResponse(
        'resp-review-wrap',
        'resp-review-status',
        'resp-review-time',
        'resp-review-json',
        `${res.status} ${res.statusText}`,
        duration,
        data
      );

      if (res.ok && data.review_id) {
        showToast(`Review Recorded: ${data.review_id.substring(0, 8)}... (Decision: ${data.decision})`, 'success');
      } else {
        showToast(data.detail || 'Error submitting review', 'error');
      }
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

// ─── TAB 6: POST /v1/runs/{id}/report ─────────────────────────────────
function setupReportsEndpoint() {
  const form = document.getElementById('form-create-report');
  const btn = document.getElementById('btn-call-report');
  const downloadLink = document.getElementById('btn-direct-download');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const runId = document.getElementById('report-run-id').value.trim();
    const format = document.getElementById('report-format').value;

    if (!runId) {
      showToast('Run ID is required.', 'error');
      return;
    }

    btn.disabled = true;
    const t0 = performance.now();

    try {
      const res = await fetch(`${API_BASE}/v1/runs/${runId}/report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ format }),
      });
      const duration = Math.round(performance.now() - t0);
      const data = await res.json();

      displayApiResponse(
        'resp-report-wrap',
        'resp-report-status',
        'resp-report-time',
        'resp-report-json',
        `${res.status} ${res.statusText}`,
        duration,
        data
      );

      if (res.ok && (data.artifact_id || data.artifact_job_id)) {
        const artifactId = data.artifact_id || data.artifact_job_id;
        state.currentReportId = artifactId;
        downloadLink.href = `${API_BASE}/v1/reports/${artifactId}/download`;
        showToast(`Report Generated: ${artifactId.substring(0, 8)}...`, 'success');
      } else {
        showToast(data.detail || 'Error generating report', 'error');
      }
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

// ─── TAB 7: GET /v1/runs/{id}/compare/{other} ─────────────────────────
function setupCompareEndpoint() {
  const form = document.getElementById('form-compare-runs');
  const btn = document.getElementById('btn-call-compare');
  const deltasView = document.getElementById('compare-deltas-view');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const currentId = document.getElementById('comp-current-id').value.trim();
    const baselineId = document.getElementById('comp-baseline-id').value.trim();

    if (!currentId || !baselineId) {
      showToast('Both Current Run ID and Baseline Run ID are required.', 'error');
      return;
    }

    btn.disabled = true;
    const t0 = performance.now();

    try {
      const res = await fetch(`${API_BASE}/v1/runs/${currentId}/compare/${baselineId}`);
      const duration = Math.round(performance.now() - t0);
      const data = await res.json();

      displayApiResponse(
        'resp-compare-wrap',
        'resp-compare-status',
        'resp-compare-time',
        'resp-compare-json',
        `${res.status} ${res.statusText}`,
        duration,
        data
      );

      const deltas = data.scenario_deltas || [];
      if (deltas.length === 0) {
        deltasView.innerHTML = '<div class="empty-filter-state"><p>No scenario deltas found between runs.</p></div>';
      } else {
        deltasView.innerHTML = `
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
                    ${d.changed ? 'CHANGED' : 'STABLE'}
                  </span>
                  <h4>${escapeHtml(d.scenario_id)}</h4>
                </div>
              </div>
              <p class="rule-summary-text">
                Baseline: <strong>${escapeHtml(d.baseline_verdict || 'N/A')}</strong> &rarr; 
                Current: <strong>${escapeHtml(d.current_verdict || 'N/A')}</strong>
              </p>
            </div>
          `).join('')}
        `;
      }

      showToast(`Comparison Complete: ${data.resolved_failures} resolved, ${data.new_failures} regressions`, 'info');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

// ─── Modals Setup ─────────────────────────────────────────────────────
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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, reason }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`Review Saved for ${findingId.substring(0, 8)}... (${decision})`, 'success');
        revModal.classList.add('hidden');
        // Refresh findings tab if open
        if (state.currentRunId) {
          document.getElementById('btn-call-findings').click();
        }
      } else {
        showToast(data.detail || 'Error saving review', 'error');
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}

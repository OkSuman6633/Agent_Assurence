// ══════════════════════════════════════════════════════════════════════════
// AGENT ASSURANCE LABORATORY
// Complete Frontend Application Controller
// ══════════════════════════════════════════════════════════════════════════

// auth.js resolves the API origin so the SameSite session cookie is valid.
const API_BASE = (window.Auth && window.Auth.apiBase)
  || (window.location.origin.includes('8000')
    ? window.location.origin
    : 'http://127.0.0.1:8000');

// Global State
let currentTab = 'overview';
let pastRuns = [];
let pastFindings = [];
let registeredAgents = [];
let registeredAssessments = [];
let allScenarios = [];
let currentPlaygroundData = null;
let playgroundHardened = false;
let playgroundFilter = 'all';
let killSwitchEngaged = false;
let pendingUnsavedAgent = null;
let selectedPlaygroundAgentId = null;

// ─── Initialization ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  setupThemeToggle();
  setupNavigation();
  setupModals();
  setupPlayground();
  setupKillSwitch();
  setupMockAgentHarness();

  // Never call protected endpoints before the auth gate has a verdict.
  if (window.AuthGateReady) {
    await window.AuthGateReady;
  }

  await checkApiHealth();
  if (!window.Auth || window.Auth.isSignedIn()) {
    await refreshAllData();
  }

  // Signing in again (after an expired session) must reload tenant data.
  document.addEventListener('auth:signed-in', async () => {
    await checkApiHealth();
    await refreshAllData();
  });
});

// ─── Theme Toggle (Dark & Light) ─────────────────────────────────────────
function setupThemeToggle() {
  const toggleBtn = document.getElementById('btn-theme-toggle');
  const icon = document.getElementById('theme-toggle-icon');
  const label = document.getElementById('theme-toggle-label');

  const savedTheme = localStorage.getItem('cynsta_theme') || 'dark';
  applyTheme(savedTheme);

  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      const isDark = document.body.classList.contains('dark-theme');
      const nextTheme = isDark ? 'light' : 'dark';
      applyTheme(nextTheme);
      localStorage.setItem('cynsta_theme', nextTheme);
    });
  }

  function applyTheme(theme) {
    if (theme === 'light') {
      document.body.className = 'light-theme';
      if (icon) icon.textContent = '🌙';
      if (label) label.textContent = 'Dark Mode';
    } else {
      document.body.className = 'dark-theme';
      if (icon) icon.textContent = '☀️';
      if (label) label.textContent = 'Light Mode';
    }
  }
}

// ─── Health Probe ────────────────────────────────────────────────────────
async function checkApiHealth() {
  const dot = document.getElementById('api-status-dot');
  const text = document.getElementById('api-status-text');
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (res.ok) {
      dot.className = 'status-pulse-dot';
      text.textContent = 'Connected';
    } else {
      throw new Error(`HTTP ${res.status}`);
    }
  } catch (_) {
    dot.className = 'status-pulse-dot offline';
    text.textContent = 'Offline';
  }
}

// ─── Central Data Fetcher ────────────────────────────────────────────────
async function refreshAllData() {
  await Promise.all([
    loadOverviewMetrics(),
    loadRuns(),
    loadFindings(),
    loadAgents(),
    loadAssessments(),
    loadScenarios(),
    loadBilling(),
    loadAuditEvents(),
  ]);
}

// ─── Navigation & Breadcrumbs ────────────────────────────────────────────
function setupNavigation() {
  const navItems = document.querySelectorAll('.sidebar .nav-item[data-tab]');

  navItems.forEach(item => {
    item.addEventListener('click', () => {
      const tab = item.getAttribute('data-tab');
      switchTab(tab);

      const agentFilter = item.getAttribute('data-agent-filter');
      if (agentFilter && (tab === 'projects' || tab === 'agents')) {
        highlightAgent(agentFilter);
      }
    });
  });

  // Header test button -> opens quick scan
  document.getElementById('btn-header-quick-scan').addEventListener('click', () => {
    openModal('modal-quick-scan');
  });

  // View all incidents button in Overview
  document.getElementById('btn-view-all-incidents').addEventListener('click', () => {
    switchTab('flight-recorder');
  });

  // Quick new agent button in sidebar
  document.getElementById('btn-quick-new-project').addEventListener('click', () => {
    openModal('modal-register-agent');
  });
}

function switchTab(tabId) {
  // Alias projects to Registered Agents
  if (tabId === 'agents') tabId = 'projects';
  currentTab = tabId;

  // Update sidebar active state
  document.querySelectorAll('.sidebar .nav-item').forEach(el => {
    if (el.getAttribute('data-tab') === tabId) {
      el.classList.add('active');
    } else {
      el.classList.remove('active');
    }
  });

  // Switch tab views
  document.querySelectorAll('.tab-view').forEach(view => {
    view.classList.remove('active');
  });

  const targetView = document.getElementById(`view-${tabId}`);
  if (targetView) {
    targetView.classList.add('active');
  }

  // Workspace administration is loaded lazily, and only for authorised roles.
  if (tabId === 'team' && window.TeamView) {
    window.TeamView.load();
  }

  // Update breadcrumb
  const breadcrumbMap = {
    overview: 'Overview',
    playground: 'Playground Testing',
    'test-runs': 'Test Runs',
    'flight-recorder': 'Alerts & Findings',
    logs: 'Activity Logs',
    analytics: 'Performance Analytics',
    projects: 'Registered Agents',
    team: 'Team & Access',
    billing: 'Plans & Limits',
    settings: 'Workspace Controls',
  };
  const breadcrumbCurrent = document.getElementById('header-breadcrumb-current');
  if (breadcrumbCurrent) {
    breadcrumbCurrent.textContent = breadcrumbMap[tabId] || 'Overview';
  }
}

function highlightAgent(agentName) {
  setTimeout(() => {
    const cards = document.querySelectorAll('.agent-card');
    cards.forEach(c => {
      if (c.innerText.toLowerCase().includes(agentName.toLowerCase())) {
        c.scrollIntoView({ behavior: 'smooth', block: 'center' });
        c.style.borderColor = 'var(--accent-indigo)';
        setTimeout(() => c.style.borderColor = '', 2000);
      }
    });
  }, 100);
}

// ══════════════════════════════════════════════════════════════════════════
// VIEW 1: OVERVIEW DASHBOARD
// ══════════════════════════════════════════════════════════════════════════

async function loadOverviewMetrics() {
  try {
    const res = await fetch(`${API_BASE}/v1/overview/metrics`);
    if (!res.ok) return;
    const data = await res.json();

    if (data.kpis) {
      document.getElementById('kpi-total-requests').textContent = data.kpis.total_requests;
      document.getElementById('kpi-total-requests-trend').innerHTML = `<span class="trend-arrow">↗</span> ${data.kpis.total_requests_delta}`;
      document.getElementById('kpi-avg-latency').textContent = data.kpis.avg_latency;
      document.getElementById('kpi-avg-latency-trend').innerHTML = `<span class="trend-arrow">↘</span> ${data.kpis.avg_latency_delta}`;
      document.getElementById('kpi-pass-rate').textContent = data.kpis.pass_rate;
      document.getElementById('kpi-pass-rate-trend').innerHTML = `<span class="trend-arrow">↗</span> ${data.kpis.pass_rate_delta}`;
      document.getElementById('kpi-regressions-caught').textContent = data.kpis.regressions_caught;
      document.getElementById('kpi-regressions-trend').innerHTML = `<span class="trend-arrow">↗</span> ${data.kpis.regressions_delta}`;
    }

    renderPassRateTrend(data.pass_rate_trend);
    renderRecentRegressions(data.recent_regressions);
  } catch (err) {
    console.warn('Overview metrics load error:', err);
  }
}

function renderPassRateTrend(trendData) {
  const points = trendData?.points || [
    { day: 'Mon', rate: 93.5 },
    { day: 'Tue', rate: 95.8 },
    { day: 'Wed', rate: 89.2 },
    { day: 'Thu', rate: 96.0 },
    { day: 'Fri', rate: 98.0 },
    { day: 'Sat', rate: 97.4 },
    { day: 'Sun', rate: 99.1 },
  ];

  const svgWidth = 680;
  const svgHeight = 320;
  const paddingLeft = 50;
  const paddingRight = 30;
  const chartWidth = svgWidth - paddingLeft - paddingRight;

  const minRate = 80;
  const maxRate = 100;

  function rateToY(rate) {
    const normalized = (rate - minRate) / (maxRate - minRate);
    return (svgHeight - 40) - normalized * 250;
  }

  const coords = points.map((p, idx) => {
    const x = paddingLeft + (idx / (points.length - 1)) * chartWidth;
    const y = rateToY(p.rate);
    return { x, y, day: p.day, rate: p.rate };
  });

  let curvePathD = `M ${coords[0].x} ${coords[0].y}`;
  for (let i = 0; i < coords.length - 1; i++) {
    const cur = coords[i];
    const nxt = coords[i + 1];
    const mx = (cur.x + nxt.x) / 2;
    curvePathD += ` C ${mx} ${cur.y}, ${mx} ${nxt.y}, ${nxt.x} ${nxt.y}`;
  }

  const areaPathD = `${curvePathD} L ${coords[coords.length - 1].x} ${svgHeight - 40} L ${coords[0].x} ${svgHeight - 40} Z`;

  const curveEl = document.getElementById('chart-curve-path');
  const areaEl = document.getElementById('chart-area-path');
  if (curveEl) curveEl.setAttribute('d', curvePathD);
  if (areaEl) areaEl.setAttribute('d', areaPathD);

  const pointsGroup = document.getElementById('chart-points-group');
  if (!pointsGroup) return;

  pointsGroup.innerHTML = coords.map((c) => `
    <circle class="trend-point-dot" cx="${c.x}" cy="${c.y}" r="4"
      fill="#ffffff" stroke="#6366f1" stroke-width="2" style="cursor: pointer;"></circle>
  `).join('');
}

function renderRecentRegressions(incidents) {
  const container = document.getElementById('recent-regressions-list');
  if (!container) return;

  const items = incidents || [
    { title: 'Instruction Boundary Leakage in Support Flow', pr: 'Run #405', time: '2h ago', scenario_id: 'prompt_injection_boundary_v1' },
    { title: 'Payment Log Information Check', pr: 'Run #402', time: '4h ago', scenario_id: 'data_exfiltration_v1' },
    { title: 'Response Verification Anomaly', pr: 'Run #398', time: '6h ago', scenario_id: 'tool_response_spoofing_v1' },
  ];

  container.innerHTML = items.map(item => `
    <div class="regression-item" onclick="openFindingOrEvidence('${item.finding_id || ''}', '${item.scenario_id || ''}', '${escapeHtml(item.title)}')">
      <div class="regression-icon-wrap">!</div>
      <div class="regression-content">
        <div class="regression-title">${escapeHtml(item.title)}</div>
        <div class="regression-meta">
          <span>${escapeHtml(item.pr || 'Test Run')}</span>
          <span class="sep">&bull;</span>
          <span>${escapeHtml(item.time || 'Recent')}</span>
        </div>
      </div>
    </div>
  `).join('');
}

window.openFindingOrEvidence = (findingId, scenarioId, title) => {
  if (findingId) {
    openReviewModal(findingId);
  } else {
    openEvidenceTrace(scenarioId || 'prompt_injection_boundary_v1', title || 'Activity Trace');
  }
};

// ══════════════════════════════════════════════════════════════════════════
// VIEW 2: TEST RUNS
// ══════════════════════════════════════════════════════════════════════════

async function loadRuns() {
  try {
    const res = await fetch(`${API_BASE}/v1/runs`);
    if (!res.ok) return;
    pastRuns = await res.json();

    const countEl = document.getElementById('sidebar-runs-count');
    if (countEl) countEl.textContent = pastRuns.length;

    renderRunsTable(pastRuns);
    populateCompareDropdowns();
  } catch (err) {
    console.warn('Runs load error:', err);
  }
}

function renderRunsTable(runs) {
  const tbody = document.getElementById('runs-table-body');
  if (!tbody) return;

  if (runs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center" style="padding: 30px; color: var(--text-muted);">No test runs recorded yet. Start a test in the Playground or click '+ Start Test Run'.</td></tr>`;
    return;
  }

  tbody.innerHTML = runs.slice().reverse().map(r => {
    const passCount = r.summary?.PASS || 0;
    const failCount = r.summary?.FAIL || 0;
    const status = (r.status || 'completed').toLowerCase();
    const statusClass = status === 'completed' ? 'chip-completed' : (status === 'running' ? 'chip-running' : 'chip-fail');

    return `
      <tr>
        <td><code>${r.run_id.substring(0, 8)}...</code></td>
        <td><strong>${escapeHtml(r.agent_id ? 'Registered Agent' : 'Evaluation Target')}</strong></td>
        <td><span class="meta-chip">${escapeHtml(r.scenario_pack || 'core-v1')}</span></td>
        <td>${(r.scenarios_requested || []).length} Rules</td>
        <td>
          <span class="status-chip chip-pass">&#10003; ${passCount} Passed</span>
          ${failCount > 0 ? `<span class="status-chip chip-fail ml-4">&#9888; ${failCount} Issues</span>` : ''}
        </td>
        <td><span class="status-chip ${statusClass}">${r.status}</span></td>
        <td style="color: var(--text-muted); font-size: 0.78rem;">${r.created_at ? new Date(r.created_at).toLocaleTimeString() : 'Recent'}</td>
        <td class="text-right">
          <button type="button" class="btn-secondary" style="padding: 4px 10px; font-size: 0.76rem;" onclick="openReportModal('${r.run_id}')">
            Report
          </button>
        </td>
      </tr>
    `;
  }).join('');
}

// ══════════════════════════════════════════════════════════════════════════
// VIEW 3: ALERTS & FINDINGS
// ══════════════════════════════════════════════════════════════════════════

async function loadFindings() {
  try {
    const res = await fetch(`${API_BASE}/v1/findings`);
    if (!res.ok) return;
    pastFindings = await res.json();

    const sidebarFindings = document.getElementById('sidebar-findings-count');
    if (sidebarFindings) sidebarFindings.textContent = pastFindings.length;
    const countAll = document.getElementById('count-findings-all');
    if (countAll) countAll.textContent = pastFindings.length;
    const countOpen = document.getElementById('count-findings-open');
    if (countOpen) countOpen.textContent = pastFindings.filter(f => f.status === 'open').length;

    renderFindingsGrid(pastFindings);
  } catch (err) {
    console.warn('Findings load error:', err);
  }
}

function renderFindingsGrid(findings) {
  const container = document.getElementById('findings-grid');
  if (!container) return;

  if (findings.length === 0) {
    container.innerHTML = `<div class="card" style="grid-column: 1 / -1; text-align: center; color: var(--text-muted); padding: 40px;">No open safety alerts detected. All tested agents complied with safety boundaries!</div>`;
    return;
  }

  container.innerHTML = findings.map(f => {
    const sev = (f.severity || 'medium').toLowerCase();
    return `
      <div class="finding-card">
        <div class="finding-top-row">
          <span class="severity-pill severity-${sev}">${sev.toUpperCase()}</span>
          <span class="status-chip ${f.status === 'confirmed' ? 'chip-fail' : 'chip-pass'}">${escapeHtml(f.status)}</span>
        </div>
        <div class="finding-title">${escapeHtml(f.title || f.scenario_id)}</div>
        <div class="finding-desc">${escapeHtml(f.description || f.impact || 'Safety check alert detected during test run.')}</div>
        <div class="finding-meta-row">
          <span>Rule: <code>${escapeHtml(f.scenario_id)}</code></span>
          <button type="button" class="btn-secondary" style="padding: 4px 10px; font-size: 0.74rem;" onclick="openReviewModal('${f.finding_id}')">
            Review Alert
          </button>
        </div>
      </div>
    `;
  }).join('');
}

window.openReviewModal = async (findingId) => {
  const finding = pastFindings.find(f => f.finding_id === findingId);
  if (!finding) return;

  document.getElementById('m-review-finding-id').textContent = finding.finding_id;
  document.getElementById('m-review-details-box').innerHTML = `
    <div style="background: var(--bg-card-elevated); border: 1px solid var(--border-subtle); padding: 12px; border-radius: var(--radius-sm); margin-bottom: 14px;">
      <h4 style="color: var(--text-primary); font-size: 0.9rem;">${escapeHtml(finding.title)}</h4>
      <p style="color: var(--text-secondary); font-size: 0.8rem; margin-top: 4px;">${escapeHtml(finding.description)}</p>
      <div style="margin-top: 8px; font-size: 0.76rem; color: var(--text-muted);">
        <strong>Rule ID:</strong> <code>${finding.scenario_id}</code> | <strong>Severity:</strong> ${finding.severity}
      </div>
    </div>
  `;

  try {
    const res = await fetch(`${API_BASE}/v1/findings/${findingId}/reviews`);
    if (res.ok) {
      const reviews = await res.json();
      const pastContainer = document.getElementById('m-past-reviews-container');
      if (reviews.length > 0) {
        pastContainer.innerHTML = `
          <div style="margin-top: 10px; font-size: 0.76rem; color: var(--text-muted); border-top: 1px solid var(--border-subtle); padding-top: 8px;">
            <strong>Reviewer History:</strong>
            ${reviews.map(r => `<div>&bull; [${r.decision.toUpperCase()}]: ${escapeHtml(r.reason)}</div>`).join('')}
          </div>
        `;
      } else {
        pastContainer.innerHTML = '';
      }
    }
  } catch (_) { }

  openModal('modal-review-finding');
};

// ══════════════════════════════════════════════════════════════════════════
// VIEW 4: PLAYGROUND (Live Agent Testing)
// ══════════════════════════════════════════════════════════════════════════

function setupPlayground() {
  const form = document.getElementById('playground-scan-form');
  const urlInput = document.getElementById('playground-agent-url-input');
  const btnClear = document.getElementById('playground-btn-clear-url');

  const presetTravel = document.getElementById('pg-preset-travel');
  const presetSynthVuln = document.getElementById('pg-preset-synth-vuln');
  const presetSynthHard = document.getElementById('pg-preset-synth-hard');
  const presetBookstore = document.getElementById('pg-preset-bookstore');
  const presetLocalAgent = document.getElementById('pg-preset-local-agent');

  if (presetTravel) {
    presetTravel.addEventListener('click', () => {
      urlInput.value = 'http://127.0.0.1:8002';
      playgroundHardened = false;
      highlightPlaygroundPreset(presetTravel);
      urlInput.placeholder = 'Testing Travel Agent on Port 8002';
    });
  }

  if (presetSynthVuln) {
    presetSynthVuln.addEventListener('click', () => {
      urlInput.value = 'synthetic';
      playgroundHardened = false;
      highlightPlaygroundPreset(presetSynthVuln);
      urlInput.placeholder = 'Testing Demo Agent (Vulnerable Mode)';
    });
  }

  if (presetSynthHard) {
    presetSynthHard.addEventListener('click', () => {
      urlInput.value = 'synthetic';
      playgroundHardened = true;
      highlightPlaygroundPreset(presetSynthHard);
      urlInput.placeholder = 'Testing Demo Agent (Hardened / Safe Mode)';
    });
  }

  if (presetBookstore) {
    presetBookstore.addEventListener('click', () => {
      urlInput.value = 'http://127.0.0.1:8001';
      playgroundHardened = false;
      highlightPlaygroundPreset(presetBookstore);
      urlInput.placeholder = 'Testing Local Agent on Port 8001';
    });
  }

  presetLocalAgent.addEventListener('click', () => {
    urlInput.value = `${API_BASE}/v1/agent/run`;
    playgroundHardened = false;
    highlightPlaygroundPreset(presetLocalAgent);
    urlInput.placeholder = 'Testing Local Agent on Port 8000';
  });

  btnClear.addEventListener('click', () => {
    urlInput.value = '';
    playgroundHardened = false;
    selectedPlaygroundAgentId = null;
    document.querySelectorAll('.preset-chip').forEach(b => b.classList.remove('active'));
    urlInput.placeholder = 'Enter Agent URL or select a registered agent';
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    await executePlaygroundScan();
  });

  // Manual save agent button in results bar
  const btnManualSave = document.getElementById('pg-btn-save-agent-manual');
  if (btnManualSave) {
    btnManualSave.addEventListener('click', () => {
      if (pendingUnsavedAgent) {
        promptSaveAgentModal(pendingUnsavedAgent.url, pendingUnsavedAgent.name);
      }
    });
  }

  // Popup modal buttons for saving agent
  const btnConfirmSave = document.getElementById('btn-confirm-save-agent');
  const btnDismissSave = document.getElementById('btn-dismiss-save-agent');

  if (btnConfirmSave) {
    btnConfirmSave.addEventListener('click', async () => {
      if (pendingUnsavedAgent) {
        await saveAgentToDatabase(pendingUnsavedAgent.name, pendingUnsavedAgent.url);
        closeModal('modal-save-agent-confirm');
        const dbBadge = document.getElementById('pg-res-db-badge');
        if (dbBadge) {
          dbBadge.textContent = 'Saved in Database';
          dbBadge.className = 'status-chip chip-pass ml-8';
        }
        if (btnManualSave) btnManualSave.classList.add('hidden');
      }
    });
  }

  if (btnDismissSave) {
    btnDismissSave.addEventListener('click', () => {
      closeModal('modal-save-agent-confirm');
    });
  }

  // Download JSON directly
  const btnDownloadJson = document.getElementById('pg-btn-download-json');
  if (btnDownloadJson) {
    btnDownloadJson.addEventListener('click', (e) => {
      e.preventDefault();
      downloadPlaygroundJsonReport();
    });
  }
}

function highlightPlaygroundPreset(btn) {
  document.querySelectorAll('.preset-chip').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

async function executePlaygroundScan() {
  const urlInput = document.getElementById('playground-agent-url-input');
  const enteredUrl = urlInput.value.trim();
  const scopeEl = document.querySelector('input[name="pg_scan_scope"]:checked');
  const scope = scopeEl ? scopeEl.value : 'all';
  const budget = parseInt(document.getElementById('pg-token-budget-input').value) || 5000;

  const btnScan = document.getElementById('playground-btn-scan');
  const spinner = document.getElementById('playground-scan-spinner');
  const btnText = document.getElementById('playground-btn-scan-text');
  const indicator = document.getElementById('pg-scanning-indicator');
  const resultsSec = document.getElementById('pg-results-section');

  let scenariosToRun = null;
  if (scope === 'core') {
    scenariosToRun = [
      'allowed_tool_smoke_v1',
      'prompt_injection_boundary_v1',
      'approval_gate_v1',
      'retry_idempotency_v1',
    ];
  }

  btnScan.disabled = true;
  spinner.classList.remove('hidden');
  btnText.textContent = 'Testing Agent...';
  indicator.classList.remove('hidden');
  resultsSec.classList.add('hidden');

  const matched = registeredAgents.find(a =>
    (selectedPlaygroundAgentId && a.agent_id === selectedPlaygroundAgentId) ||
    (enteredUrl && a.endpoint_url === enteredUrl) ||
    (enteredUrl && a.endpoint_url && a.endpoint_url.replace(/\/$/, '') === enteredUrl.replace(/\/$/, ''))
  );

  const agentIdToSend = matched ? matched.agent_id : selectedPlaygroundAgentId;
  const agentName = matched ? matched.name : (enteredUrl ? `Agent @ ${enteredUrl}` : (registeredAgents[0] ? registeredAgents[0].name : 'Database Agent'));

  try {
    const payload = {
      agent_id: agentIdToSend || null,
      endpoint_url: enteredUrl || (matched ? matched.endpoint_url : null),
      agent_name: agentName,
      scenarios: scenariosToRun,
      model_budget_tokens: budget,
      hardened: playgroundHardened,
    };

    const res = await fetch(`${API_BASE}/v1/evaluate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Correlation-ID': 'test-' + Date.now(),
      },
      body: JSON.stringify(payload),
    });

    const errBanner = document.getElementById('pg-error-banner');
    if (errBanner) errBanner.classList.add('hidden');

    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: `Server returned HTTP ${res.status}` }));
      const msg = err.message || err.detail || `Testing failed with HTTP ${res.status}`;
      if (errBanner) {
        const titleEl = document.getElementById('pg-error-title');
        const msgEl = document.getElementById('pg-error-msg');
        if (titleEl) titleEl.textContent = err.code === 'AGENT_UNREACHABLE' ? 'No Agent Running on Target Port' : 'Agent Evaluation Error';
        if (msgEl) msgEl.textContent = msg;
        errBanner.classList.remove('hidden');
      }
      const resSec = document.getElementById('pg-results-section');
      if (resSec) resSec.classList.add('hidden');
      throw new Error(msg);
    }

    const data = await res.json();
    currentPlaygroundData = data;

    renderPlaygroundResults(data);

    // Friendly notification
    const isPassed = data.overall_verdict === 'PASSED';
    const isInconclusive = data.overall_verdict === 'INCONCLUSIVE';
    showToast(
      isPassed
        ? '✓ All safety checks passed!'
        : (isInconclusive ? '⚠️ Evaluation inconclusive — check rejection reasons below.' : '⚠️ Potential safety issues detected.'),
      isPassed ? 'success' : 'error'
    );

    // Requirement 2: If the agent is not already registered in the database,
    // do NOT register automatically; show a confirmation popup asking if the user wants to save it!
    if (enteredUrl && data.target && data.target.is_saved === false) {
      pendingUnsavedAgent = {
        name: agentName,
        url: enteredUrl,
      };
      // Show confirmation popup
      promptSaveAgentModal(enteredUrl, agentName);
    } else {
      pendingUnsavedAgent = null;
    }

    await refreshAllData();
  } catch (err) {
    showToast(err.message, 'error');
    if (err.message && (err.message.toLowerCase().includes('register an agent') || err.message.toLowerCase().includes('not exist in the database'))) {
      setTimeout(() => openModal('modal-register-agent'), 600);
    }
  } finally {
    btnScan.disabled = false;
    spinner.classList.add('hidden');
    btnText.textContent = 'Test Agent';
    indicator.classList.add('hidden');
  }
}

function promptSaveAgentModal(url, name) {
  const promptUrl = document.getElementById('save-agent-prompt-url');
  if (promptUrl) promptUrl.textContent = url;
  openModal('modal-save-agent-confirm');

  const btnManualSave = document.getElementById('pg-btn-save-agent-manual');
  if (btnManualSave) btnManualSave.classList.remove('hidden');
}

async function saveAgentToDatabase(name, url) {
  try {
    const res = await fetch(`${API_BASE}/v1/agents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name,
        adapter_type: 'http',
        endpoint_url: url,
        allowed_hosts: ['127.0.0.1', 'localhost'],
        scope_description: 'Registered from Playground test',
        authorised: true,
        environment: 'live',
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || 'Could not save agent to database');
    }

    showToast(`✓ Agent '${name}' saved to database (.db)!`, 'success');
    await loadAgents();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function renderPlaygroundResults(data) {
  const resultsSec = document.getElementById('pg-results-section');
  resultsSec.classList.remove('hidden');
  resultsSec.scrollIntoView({ behavior: 'smooth', block: 'start' });

  const summary = data.summary || {};
  const violations = summary.violations_detected || 0;
  const inconclusiveCount = summary.inconclusive || 0;
  const passedCount = summary.rules_passed || 0;
  const isViolation = violations > 0;
  const isInconclusive = !isViolation && (data.overall_verdict === 'INCONCLUSIVE' || inconclusiveCount > 0);

  const banner = document.getElementById('pg-verdict-banner');
  const icon = document.getElementById('pg-verdict-big-icon');
  const eyebrow = document.getElementById('pg-verdict-eyebrow');
  const headline = document.getElementById('pg-verdict-headline');
  const subtext = document.getElementById('pg-verdict-subtext');
  const statsPills = document.getElementById('pg-verdict-stats-pills');

  if (isViolation) {
    banner.className = 'verdict-banner banner-fail';
    icon.innerHTML = '⚠️';
    eyebrow.textContent = 'ATTENTION RECOMMENDED';
    headline.textContent = `${violations} Safety Issue${violations > 1 ? 's' : ''} Detected`;
    subtext.textContent = 'The agent executed sensitive tools without gating, yielded to external instructions, or leaked test data.';
  } else if (isInconclusive) {
    banner.className = 'verdict-banner banner-inconclusive';
    icon.innerHTML = '❓';
    eyebrow.textContent = 'EVALUATION INCONCLUSIVE';
    headline.textContent = `${inconclusiveCount} Check${inconclusiveCount !== 1 ? 's' : ''} Could Not Be Verified`;
    subtext.textContent = 'The target agent rejected requests, timed out, or did not return required telemetry. See each card below for the exact rejection reason.';
  } else {
    banner.className = 'verdict-banner banner-pass';
    icon.innerHTML = '✓';
    eyebrow.textContent = 'EVALUATION PASSED';
    headline.textContent = `All ${summary.total_rules_evaluated || 12} Safety Checks Passed`;
    subtext.textContent = 'The agent respected instructions, tool limits, and privacy constraints.';
  }

  statsPills.innerHTML = `
    <div class="stat-pill-box">
      <span class="pill-number" style="color: var(--accent-red);">${violations}</span>
      <span class="pill-name">Issues</span>
    </div>
    <div class="stat-pill-box">
      <span class="pill-number" style="color: var(--accent-amber, #f59e0b);">${inconclusiveCount}</span>
      <span class="pill-name">Inconclusive</span>
    </div>
    <div class="stat-pill-box">
      <span class="pill-number" style="color: var(--accent-green);">${passedCount}</span>
      <span class="pill-name">Passed</span>
    </div>
    <div class="stat-pill-box">
      <span class="pill-number">${summary.total_rules_evaluated || 12}</span>
      <span class="pill-name">Total Checks</span>
    </div>
  `;

  document.getElementById('pg-res-target-display').textContent = data.target?.endpoint_url || data.target?.name || 'Target Agent';
  document.getElementById('pg-res-run-id').textContent = data.run_id ? data.run_id.substring(0, 12) : 'active';

  const dbBadge = document.getElementById('pg-res-db-badge');
  if (dbBadge) {
    if (data.target?.is_saved) {
      dbBadge.textContent = 'Saved in Database';
      dbBadge.className = 'status-chip chip-pass ml-8';
    } else {
      dbBadge.textContent = 'Unsaved Target';
      dbBadge.className = 'status-chip chip-running ml-8';
    }
  }

  if (data.report_download_url) {
    document.getElementById('pg-btn-download-text').href = `${API_BASE}${data.report_download_url}`;
  }

  document.getElementById('pg-count-all').textContent = summary.total_rules_evaluated || 12;
  document.getElementById('pg-count-violations').textContent = violations;
  const inconEl = document.getElementById('pg-count-inconclusive');
  if (inconEl) inconEl.textContent = inconclusiveCount;
  document.getElementById('pg-count-passed').textContent = passedCount;

  renderPlaygroundRuleCards(data.rules || []);
}

function renderPlaygroundRuleCards(rules) {
  const container = document.getElementById('pg-rules-cards-container');
  if (!container) return;

  let filtered = rules;
  if (playgroundFilter === 'fail') {
    filtered = rules.filter(r => r.status === 'NEEDS ATTENTION' || r.status === 'VIOLATION DETECTED');
  } else if (playgroundFilter === 'inconclusive') {
    filtered = rules.filter(r => r.status === 'INCONCLUSIVE');
  } else if (playgroundFilter === 'pass') {
    filtered = rules.filter(r => r.status === 'PASSED');
  }

  if (filtered.length === 0) {
    container.innerHTML = `<div class="card text-center" style="color: var(--text-muted); padding: 30px;">No checks matching current filter.</div>`;
    return;
  }

  container.innerHTML = filtered.map(r => {
    const isFail = r.status === 'NEEDS ATTENTION' || r.status === 'VIOLATION DETECTED';
    const isInconclusive = r.status === 'INCONCLUSIVE';
    const isPass = r.status === 'PASSED';

    const cardClass = isFail ? 'rule-card-fail' : (isInconclusive ? 'rule-card-inconclusive' : 'rule-card-pass');
    const chipClass = isFail ? 'chip-fail' : (isInconclusive ? 'chip-running' : 'chip-pass');
    const chipLabel = isFail ? '⚠️ Needs Attention' : (isInconclusive ? '❓ Inconclusive / Rejected' : '✓ Passed');
    const reasonText = r.rejection_reason || r.violation_evidence || r.summary || '';

    const toolsList = (r.tool_events || []).map(t => {
      const argsStr = t.arguments ? Object.entries(t.arguments).map(([k, v]) => `${k}=${v}`).join(', ') : '';
      return `<span class="evidence-tool-chip">${escapeHtml(t.tool || 'tool')}(${escapeHtml(argsStr)})</span>`;
    }).join('');

    return `
      <div class="rule-card ${cardClass}">
        <div class="rule-card-top">
          <div class="rule-title-group">
            <span class="status-chip ${chipClass}">${chipLabel}</span>
            <span class="severity-pill severity-${(r.severity || 'medium').toLowerCase()}">${(r.severity || 'MED').toUpperCase()}</span>
            <h4>${escapeHtml(r.rule_name || r.scenario_id)}</h4>
          </div>
          <button type="button" class="btn-inspect-trace" onclick="openEvidenceTrace('${r.scenario_id}', '${escapeHtml(r.rule_name)}')">
            👁 View Details &amp; Evidence
          </button>
        </div>
        <p class="rule-summary-text">${escapeHtml(r.summary)}</p>

        ${isFail ? `
          <div class="violation-box">
            <div class="violation-badge-row">
              <span class="violation-badge">🚨 REJECTED AT: ${escapeHtml(r.violation_location || 'Execution Policy')}</span>
            </div>
            <div class="violation-evidence-text">
              <strong>Rejection Reason:</strong> ${escapeHtml(reasonText)}
            </div>
          </div>
        ` : (isInconclusive ? `
          <div class="inconclusive-box">
            <div class="violation-badge-row">
              <span class="inconclusive-badge">⚠️ COULD NOT VERIFY: ${escapeHtml(r.violation_location || 'Endpoint / Telemetry')}</span>
            </div>
            <div class="violation-evidence-text">
              <strong>Rejection / Failure Reason:</strong> ${escapeHtml(reasonText)}
            </div>
          </div>
        ` : '')
  }

        < !--Concrete Evidence Preview: Input Sent & Output Collected-- >
  <div class="evidence-preview-container">
    <div class="evidence-row">
      <span class="evidence-label">User Prompt Sent:</span>
      <span class="evidence-val">"${escapeHtml(r.prompt || r.trace?.input_prompt || '')}"</span>
    </div>
    <div class="evidence-row">
      <span class="evidence-label">Agent Output Collected:</span>
      <span class="evidence-val">"${escapeHtml(r.agent_output || r.trace?.output_excerpt || '(No response text)')}"</span>
    </div>
    ${toolsList ? `
            <div class="evidence-row">
              <span class="evidence-label">Tool Calls Recorded:</span>
              <div>${toolsList}</div>
            </div>
          ` : ''}
  </div>

        ${
    r.checks_failed && r.checks_failed.length > 0 ? `
          <div class="violations-callout">
            <strong>Failed Check Outcomes:</strong>
            <ul>${r.checks_failed.map(c => `<li><code>${escapeHtml(c)}</code></li>`).join('')}</ul>
          </div>
        ` : ''
  }
  < div class= "rule-card-footer" >
  <span>Category: <em>${escapeHtml(r.category || 'General')}</em></span>
          ${ isFail? `<span class="remediation-hint">💡 ${escapeHtml(r.remediation || 'Review agent instructions and permissions.')}</span>` : '<span style="color: var(--accent-green);">✓ All boundaries satisfied</span>'}
        </div >
      </div >
  `;
  }).join('');
}

function downloadPlaygroundJsonReport() {
  if (!currentPlaygroundData) {
    showToast('No test results available to download.', 'error');
    return;
  }
  const jsonStr = JSON.stringify(currentPlaygroundData, null, 2);
  const blob = new Blob([jsonStr], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `agent - assurance - report - ${ new Date().toISOString().slice(0, 10) }.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast('✓ JSON report downloaded successfully!', 'success');
}

window.openEvidenceTrace = (scenarioId, title) => {
  let traceData = {};
  let ruleObj = null;
  if (currentPlaygroundData && currentPlaygroundData.rules) {
    ruleObj = currentPlaygroundData.rules.find(x => x.scenario_id === scenarioId);
    if (ruleObj) traceData = ruleObj.trace || {};
  }

  document.getElementById('evidence-modal-title').textContent = title || `Diagnostic Details: ${ scenarioId } `;
  document.getElementById('evidence-modal-scenario').textContent = scenarioId;

  const visualContainer = document.getElementById('evidence-modal-visual');
  if (visualContainer && ruleObj) {
    const isFail = ruleObj.status === 'NEEDS ATTENTION' || ruleObj.status === 'VIOLATION DETECTED';
    const assertions = traceData.state_assertions || {};
    const assertionsList = Object.entries(assertions).map(([k, v]) => {
      const isFailed = (traceData.failed_assertions || []).includes(k);
      return `< div >& bull; <code>${escapeHtml(k)}</code>: <span style="font-weight: 600; color: ${isFailed ? 'var(--accent-red)' : 'var(--accent-green)'};">${v}</span> ${ isFailed ? '(Violation)' : '(Passed)' }</div > `;
    }).join('');

    const toolsFormatted = (traceData.tool_events || []).map(t => {
      const a = t.arguments ? JSON.stringify(t.arguments) : '{}';
      return `< div style = "background: rgba(0,0,0,0.3); border-radius: var(--radius-xs); padding: 6px 10px; margin-top: 4px; font-family: monospace; font-size: 0.76rem;" > <strong>${escapeHtml(t.tool)}</strong>: ${ escapeHtml(a) }</div > `;
    }).join('');

    visualContainer.innerHTML = `
  < div style = "display: flex; gap: 10px; align-items: center; margin-bottom: 12px;" >
        <span class="status-chip ${isFail ? 'chip-fail' : 'chip-pass'}">${isFail ? '⚠️ Violation Detected' : '✓ Passed'}</span>
        <span class="severity-pill severity-${(ruleObj.severity || 'med').toLowerCase()}">${(ruleObj.severity || 'MED').toUpperCase()}</span>
        <span style="font-size: 0.8rem; color: var(--text-muted);">Category: ${escapeHtml(ruleObj.category || 'General')}</span>
      </div >

  ${
    isFail ? `
        <div style="background: rgba(244,63,94,0.12); border: 1px solid rgba(244,63,94,0.3); border-left: 4px solid var(--accent-red); padding: 12px; border-radius: var(--radius-sm); margin-bottom: 14px;">
          <div style="font-weight: 700; color: #fb7185; font-size: 0.75rem; text-transform: uppercase;">
            📍 Violation Location: ${escapeHtml(ruleObj.violation_location || traceData.violation_location || 'Execution Behavior')}
          </div>
          <div style="color: #fecdd3; font-size: 0.82rem; margin-top: 4px; line-height: 1.45;">
            ${escapeHtml(ruleObj.violation_evidence || traceData.violation_evidence || ruleObj.summary)}
          </div>
          <div style="color: #fde047; font-size: 0.76rem; margin-top: 8px;">
            <strong>💡 Recommended Fix:</strong> ${escapeHtml(ruleObj.remediation || traceData.remediation || 'Harden agent boundaries.')}
          </div>
        </div>
      ` : `
        <div style="background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.3); border-left: 4px solid var(--accent-green); padding: 10px 12px; border-radius: var(--radius-sm); margin-bottom: 14px; font-size: 0.82rem; color: #a7f3d0;">
          ✓ All tool permissions, expected state transitions, and boundary policies satisfied.
        </div>
      `}

      < !--Conversation Evidence: Input Sent vs Output Collected-- >
      <div style="background: var(--bg-card-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px; margin-bottom: 12px;">
        <h5 style="color: var(--text-muted); font-size: 0.72rem; text-transform: uppercase; margin-bottom: 4px;">User Test Input (Prompt Sent):</h5>
        <div style="background: rgba(0,0,0,0.25); padding: 8px; border-radius: var(--radius-xs); font-size: 0.82rem; color: var(--text-primary); margin-bottom: 10px;">
          "${escapeHtml(ruleObj.prompt || traceData.input_prompt || '')}"
        </div>

        <h5 style="color: var(--text-muted); font-size: 0.72rem; text-transform: uppercase; margin-bottom: 4px;">Collected Agent Response:</h5>
        <div style="background: rgba(0,0,0,0.25); padding: 8px; border-radius: var(--radius-xs); font-size: 0.82rem; color: var(--text-primary); max-height: 140px; overflow-y: auto;">
          ${escapeHtml(ruleObj.agent_output || traceData.output_excerpt || '(No response text)')}
        </div>
      </div>

      <!--State Assertions & Tool Events Grid-- >
  <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px;">
    <div style="background: var(--bg-card-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 10px;">
      <h5 style="color: var(--text-muted); font-size: 0.72rem; text-transform: uppercase; margin-bottom: 6px;">State Assertions Evaluated:</h5>
      <div style="font-size: 0.76rem; color: var(--text-secondary); line-height: 1.5;">
        ${assertionsList || '<em>No state assertions defined</em>'}
      </div>
    </div>

    <div style="background: var(--bg-card-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 10px;">
      <h5 style="color: var(--text-muted); font-size: 0.72rem; text-transform: uppercase; margin-bottom: 6px;">Tool Invocations Recorded:</h5>
      <div style="font-size: 0.76rem; color: var(--text-secondary);">
        ${toolsFormatted || '<em>None (No tool calls executed)</em>'}
      </div>
    </div>
  </div>
`;
  }

  document.getElementById('evidence-modal-code').textContent = JSON.stringify(traceData, null, 2);
  openModal('modal-evidence');
};

// ══════════════════════════════════════════════════════════════════════════
// VIEW 5: REGISTERED AGENTS (Fetched from SQLite .db file)
// ══════════════════════════════════════════════════════════════════════════

async function loadAgents() {
  try {
    const res = await fetch(`${ API_BASE } /v1/agents`);
    if (!res.ok) return;
    registeredAgents = await res.json();

    // Update counts
    const countEl = document.getElementById('sidebar-agents-count');
    if (countEl) countEl.textContent = registeredAgents.length;

    renderSidebarAgents(registeredAgents);
    renderAgentsGrid(registeredAgents);
    populateAgentDropdowns();
  } catch (err) {
    console.warn('Agents load error:', err);
  }
}

function renderSidebarAgents(agents) {
  const container = document.getElementById('sidebar-projects-list');
  if (!container) return;

  if (agents.length === 0) {
    container.innerHTML = `< div class="sidebar-empty-hint" > No agents saved in .db file yet.</div > `;
    return;
  }

  container.innerHTML = agents.map(a => {
    const isHttp = a.adapter_type === 'http';
    const icon = isHttp ? '🌐' : '⚡';
    return `
  < button type = "button" class="nav-item project-link" data - agent - id="${a.agent_id}" onclick = "launchTestForAgent('${a.agent_id}')" title = "Test ${escapeHtml(a.name)}" >
        <span class="project-symbol">${icon}</span>
        <span>${escapeHtml(a.name)}</span>
      </button >
  `;
  }).join('');
}

function renderAgentsGrid(agents) {
  const container = document.getElementById('agents-cards-container');
  if (!container) return;

  if (agents.length === 0) {
    container.innerHTML = `
  < div class="card" style = "grid-column: 1 / -1; color: var(--text-muted); padding: 36px; text-align: center;" >
        <p style="font-size: 1rem; margin-bottom: 8px;">No agents saved in database (.db) yet.</p>
        <p style="font-size: 0.85rem; color: var(--text-secondary);">Click '+ Register New Agent' or test any URL in the Playground to save one.</p>
      </div >
  `;
    return;
  }

  container.innerHTML = agents.map(a => {
    const isHttp = a.adapter_type === 'http';
    return `
  < div class="agent-card" >
        <div class="agent-card-title">${escapeHtml(a.name)}</div>
        <p class="agent-scope-text">${escapeHtml(a.description || a.scope_description || 'Authorized evaluation target')}</p>
        <div class="agent-meta-tags">
          <span class="meta-chip">Type: <strong>${isHttp ? 'Live API' : 'Demo Simulation'}</strong></span>
          ${a.endpoint_url ? `<span class="meta-chip">URL: <code>${escapeHtml(a.endpoint_url)}</code></span>` : ''}
          <span class="meta-chip">Env: <strong>${a.environment || 'live'}</strong></span>
          <span class="meta-chip">Timeout: <strong>${a.timeout_seconds || 15}s</strong></span>
        </div>
        <div class="agent-card-actions">
          <button type="button" class="btn-card-test" onclick="launchTestForAgent('${a.agent_id}')">
            ▶ Test This Agent
          </button>
          <button type="button" class="btn-card-delete" onclick="deleteAgentFromDatabase('${a.agent_id}', '${escapeHtml(a.name)}')">
            🗑 Delete
          </button>
        </div>
      </div >
  `;
  }).join('');
}

window.launchTestForAgent = (agentId) => {
  const agent = registeredAgents.find(a => a.agent_id === agentId);
  if (!agent) return;

  selectedPlaygroundAgentId = agentId;
  switchTab('playground');
  const urlInput = document.getElementById('playground-agent-url-input');
  if (urlInput) {
    if (agent.endpoint_url) {
      urlInput.value = agent.endpoint_url;
      urlInput.placeholder = `Testing ${ agent.name } `;
    } else {
      urlInput.value = '';
      urlInput.placeholder = `Testing Registered Agent: ${ agent.name } `;
    }
  }
  showToast(`Loaded ${ agent.name } into Playground`, 'info');
};

window.deleteAgentFromDatabase = async (agentId, agentName) => {
  if (!confirm(`Are you sure you want to delete '${agentName}' from the database ? `)) {
    return;
  }
  try {
    const res = await fetch(`${ API_BASE } /v1/agents / ${ agentId } `, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error('Delete failed');
    showToast(`✓ Agent '${agentName}' deleted from database.`, 'info');
    await loadAgents();
  } catch (err) {
    showToast(err.message, 'error');
  }
};

async function loadAssessments() {
  try {
    const res = await fetch(`${ API_BASE } /v1/assessments`);
    if (!res.ok) return;
    registeredAssessments = await res.json();
    renderAssessmentsTable(registeredAssessments);
    populateAssessmentDropdowns();
  } catch (err) {
    console.warn('Assessments load error:', err);
  }
}

function renderAssessmentsTable(assessments) {
  const tbody = document.getElementById('assessments-table-body');
  if (!tbody) return;

  if (assessments.length === 0) {
    tbody.innerHTML = `< tr > <td colspan="6" class="text-center" style="padding: 24px; color: var(--text-muted);">No assessment templates configured yet.</td></tr > `;
    return;
  }

  tbody.innerHTML = assessments.map(a => `
  < tr >
      <td><strong>${escapeHtml(a.title)}</strong></td>
      <td><code>${a.agent_id ? a.agent_id.substring(0, 10) + '...' : 'Target Agent'}</code></td>
      <td><span class="meta-chip font-mono">${escapeHtml((a.scope_hash || 'SHA-256').substring(0, 12))}...</span></td>
      <td><span class="status-chip chip-completed">${a.status}</span></td>
      <td style="color: var(--text-muted); font-size: 0.76rem;">${a.created_at ? new Date(a.created_at).toLocaleDateString() : 'Active'}</td>
      <td class="text-right">
        <button type="button" class="btn-primary" style="padding: 4px 10px; font-size: 0.76rem;" onclick="openDispatchModalWithAssessment('${a.assessment_id}')">
          Start Run
        </button>
      </td>
    </tr >
  `).join('');
}

window.openDispatchModalWithAssessment = (assessmentId) => {
  const select = document.getElementById('m-dispatch-assessment');
  if (select) select.value = assessmentId;
  openModal('modal-dispatch-run');
};

// ══════════════════════════════════════════════════════════════════════════
// VIEW 6: MONITORING (LOGS & ANALYTICS)
// ══════════════════════════════════════════════════════════════════════════

async function loadAuditEvents() {
  try {
    const res = await fetch(`${ API_BASE } /v1/audit - events`);
    if (!res.ok) return;
    const events = await res.json();
    renderAuditTable(events);
  } catch (err) {
    console.warn('Audit events load error:', err);
  }
}

function renderAuditTable(events) {
  const tbody = document.getElementById('audit-table-body');
  if (!tbody) return;

  if (!events || events.length === 0) {
    tbody.innerHTML = `< tr > <td colspan="6" class="text-center" style="padding: 24px; color: var(--text-muted);">No activity recorded yet.</td></tr > `;
    return;
  }

  tbody.innerHTML = events.slice().reverse().map(e => `
  < tr >
      <td style="color: var(--text-muted); font-size: 0.76rem;">${new Date(e.timestamp).toLocaleTimeString()}</td>
      <td><strong>${escapeHtml(e.actor_email || e.actor_id)}</strong></td>
      <td><span class="meta-chip">${escapeHtml(e.action)}</span></td>
      <td>${escapeHtml(e.resource_type)}</td>
      <td><code>${(e.resource_id || '').substring(0, 10)}...</code></td>
      <td style="color: var(--text-muted); font-size: 0.74rem;">${(e.correlation_id || '').substring(0, 8)}</td>
    </tr >
  `).join('');
}

// ══════════════════════════════════════════════════════════════════════════
// VIEW 7: BILLING & EMERGENCY KILL SWITCH
// ══════════════════════════════════════════════════════════════════════════

async function loadBilling() {
  try {
    const [usageRes, plansRes] = await Promise.all([
      fetch(`${ API_BASE } /v1/usage`),
      fetch(`${ API_BASE } /v1/plans`),
    ]);

    let activePlanId = null;
    if (usageRes.ok) {
      const usage = await usageRes.json();
      activePlanId = usage.plan_id;
      renderUsageBoxes(usage);
    }

    if (plansRes.ok) {
      const plans = await plansRes.json();
      renderPlansTable(plans, activePlanId);
    }
  } catch (err) {
    console.warn('Billing load error:', err);
  }
}

function renderUsageBoxes(usage) {
  const container = document.getElementById('usage-cards-container');
  if (!container) return;

  const agentPct = Math.min(100, Math.round(((usage.agents_count || 1) / (usage.agents_limit || 25)) * 100));
  const runPct = Math.min(100, Math.round(((usage.runs_count || 2) / (usage.runs_limit || 100)) * 100));
  const scenPct = Math.min(100, Math.round(((usage.scenarios_used || 12) / (usage.scenarios_limit || 1000)) * 100));
  const planPriceFormatted = usage.base_amount_minor ? `£${ (usage.base_amount_minor / 100).toFixed(2) } ` : '';
  const intervalLabel = usage.billing_interval ? ` / ${ usage.billing_interval } ` : '';

  container.innerHTML = `
  < div class="usage-box" >
      <div class="usage-box-title">Active Plan</div>
      <div class="usage-box-num" style="font-size: 1.25rem;">${escapeHtml(usage.plan_name || usage.plan_id || 'Starter')}</div>
      <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 4px;">
        <span class="status-chip chip-pass" style="font-size: 0.72rem;">ACTIVE</span> ${planPriceFormatted}${intervalLabel}
      </div>
    </div >
    <div class="usage-box">
      <div class="usage-box-title">Agents Registered</div>
      <div class="usage-box-num">${usage.agents_count || 0} / ${usage.agents_limit || 25}</div>
      <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: ${agentPct}%;"></div></div>
    </div>
    <div class="usage-box">
      <div class="usage-box-title">Assessment Runs</div>
      <div class="usage-box-num">${usage.runs_count || 0} / ${usage.runs_limit || 100}</div>
      <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: ${runPct}%;"></div></div>
    </div>
    <div class="usage-box">
      <div class="usage-box-title">Scenarios Evaluated</div>
      <div class="usage-box-num">${usage.scenarios_used || 0} / ${usage.scenarios_limit || 1000}</div>
      <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: ${scenPct}%;"></div></div>
    </div>
`;
}

function renderPlansTable(plans, activePlanId) {
  const tbody = document.getElementById('plans-table-body');
  if (!tbody) return;

  const canManage = window.Auth && (window.Auth.has('plans:manage') || window.Auth.has('plans:write'));

  tbody.innerHTML = plans.map(p => {
    const isCurrent = p.plan_id === activePlanId;
    const actionCell = isCurrent
      ? '<span class="status-chip chip-pass">CURRENT PLAN</span>'
      : (canManage
          ? `< button type = "button" class="btn-table-action" onclick = "window.switchPlan('${p.plan_id}', '${escapeHtml(p.name)}')" > Activate Plan</button > `
          : '<span class="status-chip chip-neutral">Available</span>');

    return `
  < tr class="${isCurrent ? 'row-current-plan' : ''}" >
        <td><strong>${escapeHtml(p.name)}</strong>${isCurrent ? ' <span class="meta-chip chip-info" style="margin-left: 6px;">Active</span>' : ''}</td>
        <td>£${((p.base_amount_minor || 0) / 100).toFixed(2)}</td>
        <td><span class="meta-chip">${p.billing_interval}</span></td>
        <td>${p.included_agents}</td>
        <td>${p.maximum_runs}</td>
        <td>${p.included_scenarios}</td>
        <td>${p.retention_days} days</td>
        <td><span class="status-chip ${p.active ? 'chip-pass' : 'chip-fail'}">${p.active ? 'ACTIVE' : 'INACTIVE'}</span></td>
        <td class="text-right">${actionCell}</td>
      </tr >
  `;
  }).join('');
}

window.switchPlan = async function(planId, planName) {
  try {
    const res = await fetch(`${ API_BASE } /v1/usage / plan / ${ encodeURIComponent(planId) } `, {
      method: 'PUT',
      credentials: 'include',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || 'Failed to switch plan');
    }
    showToast(`✓ Successfully activated plan: ${ planName } `, 'success');
    await loadBilling();
  } catch (err) {
    showToast(err.message, 'error');
  }
};

function setupKillSwitch() {
  const btnToggle = document.getElementById('btn-toggle-kill-switch');
  const badge = document.getElementById('kill-switch-badge');
  const reasonInput = document.getElementById('kill-switch-reason-input');
  let globalScopeActive = false;

  // The kill switch is tenant-scoped for workspace owners: the switch is engaged when the
  // platform-wide flag is on OR this workspace sits in disabled_tenants.
  function applyStatus(data) {
    const user = window.Auth && window.Auth.currentUser ? window.Auth.currentUser() : null;
    const tenantId = user ? user.tenant_id : null;
    const disabledTenants = Array.isArray(data.disabled_tenants) ? data.disabled_tenants : [];
    globalScopeActive = !!data.global_kill_switch;
    killSwitchEngaged = globalScopeActive || (!!tenantId && disabledTenants.indexOf(tenantId) !== -1);
    updateKillSwitchUI();
  }

  async function refreshKillSwitch() {
    try {
      const res = await fetch(`${ API_BASE } /v1/kill -switch`);
      if (!res.ok) return; // 401 before the session exists: keep the last known state
      applyStatus(await res.json());
    } catch (err) {
      // Network hiccup: keep the last known state rather than claiming the control is off.
    }
  }

  document.addEventListener('auth:signed-in', refreshKillSwitch);
  // Restored sessions resolve the principal after load; re-read then so a tenant-scoped
  // pause is reflected without a manual refresh.
  if (window.AuthGateReady && typeof window.AuthGateReady.then === 'function') {
    window.AuthGateReady.then(() => {
      if (!window.Auth || window.Auth.isSignedIn()) refreshKillSwitch();
    }).catch(() => { });
  }

  btnToggle.addEventListener('click', async () => {
    const reason = reasonInput.value.trim() || 'Testing pause requested.';
    const nextState = !killSwitchEngaged;

    try {
      const res = await fetch(`${ API_BASE } /v1/kill -switch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: nextState, reason: reason }),
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.message || 'You do not have permission to change this control.');
      }
      applyStatus(data);
      showToast(`Testing ${ killSwitchEngaged ? 'PAUSED' : 'RESUMED' } successfully`, killSwitchEngaged ? 'error' : 'success');
      reasonInput.value = '';
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  function updateKillSwitchUI() {
    if (killSwitchEngaged) {
      badge.textContent = globalScopeActive ? 'Paused (All Test Runs Blocked)' : 'Paused (This Workspace)';
      badge.className = 'status-badge-inline engaged';
      btnToggle.textContent = 'Resume Testing';
      btnToggle.className = 'btn-secondary';
    } else {
      badge.textContent = 'Active (All Tests Allowed)';
      badge.className = 'status-badge-inline';
      btnToggle.textContent = 'Pause All Testing';
      btnToggle.className = 'btn-danger';
    }
  }

  // Demo Seed Button
  document.getElementById('btn-trigger-seed').addEventListener('click', async () => {
    try {
      const res = await fetch(`${ API_BASE } /v1/demo / seed`, { method: 'POST' });
      if (res.ok) {
        showToast('Sample workspace data loaded successfully!', 'success');
        await refreshAllData();
      }
    } catch (_) {
      showToast('Could not load sample data', 'error');
    }
  });
}

function setupMockAgentHarness() {
  const select = document.getElementById('mock-agent-scenario-select');
  const toggle = document.getElementById('mock-hardened-toggle');
  const btn = document.getElementById('btn-invoke-mock-agent');
  const outBlock = document.getElementById('mock-agent-output-block');

  btn.addEventListener('click', async () => {
    const sid = select.value;
    const hardened = toggle.checked;

    try {
      btn.disabled = true;
      btn.textContent = 'Sending...';
      const res = await fetch(`${ API_BASE } /v1/agent / run ? hardened = ${ hardened } `, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario_id: sid }),
      });
      const data = await res.json();
      outBlock.textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      outBlock.textContent = `Error: ${ err.message } `;
    } finally {
      btn.disabled = false;
      btn.textContent = 'Send Test Message';
    }
  });
}

// ══════════════════════════════════════════════════════════════════════════
// SCENARIOS CATALOG & MODAL DROPDOWNS
// ══════════════════════════════════════════════════════════════════════════

async function loadScenarios() {
  try {
    const res = await fetch(`${ API_BASE } /v1/scenarios`);
    if (!res.ok) return;
    allScenarios = await res.json();
    populateScenariosCheckboxes();
  } catch (_) { }
}

function populateScenariosCheckboxes() {
  const container = document.getElementById('m-dispatch-scenarios-list');
  if (!container) return;

  container.innerHTML = allScenarios.map(s => `
  < label class="scenario-checkbox-item" >
    <input type="checkbox" name="dispatch_scenarios" value="${s.scenario_id}" checked>
      <span>${escapeHtml(s.scenario_id)}</span>
    </label>
`).join('');
}

function populateAgentDropdowns() {
  const select = document.getElementById('m-assess-agent');
  if (!select) return;

  select.innerHTML = registeredAgents.map(a => `
  < option value = "${a.agent_id}" > ${ escapeHtml(a.name) } (${ a.adapter_type })</option >
    `).join('');
}

function populateAssessmentDropdowns() {
  const select = document.getElementById('m-dispatch-assessment');
  if (!select) return;

  select.innerHTML = registeredAssessments.map(a => `
    < option value = "${a.assessment_id}" > ${ escapeHtml(a.title) }</option >
      `).join('');
}

function populateCompareDropdowns() {
  const curSelect = document.getElementById('compare-modal-current-run');
  const baseSelect = document.getElementById('compare-modal-baseline-run');
  if (!curSelect || !baseSelect) return;

  const options = pastRuns.map(r => `
      < option value = "${r.run_id}" > Run ${ r.run_id.substring(0, 8) } (${ r.summary?.FAIL || 0 } Issues, ${ r.summary?.PASS || 0 } Passed)</option >
        `).join('');

  curSelect.innerHTML = options;
  baseSelect.innerHTML = options;
}

// ══════════════════════════════════════════════════════════════════════════
// MODALS MANAGEMENT & FORM SUBMISSIONS
// ══════════════════════════════════════════════════════════════════════════

function setupModals() {
  document.querySelectorAll('[data-close-modal]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.modal-backdrop').forEach(m => m.classList.add('hidden'));
    });
  });

  // Modal 1: Quick Scan
  document.getElementById('form-quick-scan').addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = document.getElementById('m-scan-url').value.trim();
    const hardened = document.getElementById('m-scan-hardened').checked;

    closeModal('modal-quick-scan');
    switchTab('playground');

    document.getElementById('playground-agent-url-input').value = url;
    playgroundHardened = hardened;
    await executePlaygroundScan();
  });

  // Modal 2: Dispatch Run
  document.getElementById('btn-open-dispatch-run-modal').addEventListener('click', () => {
    openModal('modal-dispatch-run');
  });

  document.getElementById('form-dispatch-run').addEventListener('submit', async (e) => {
    e.preventDefault();
    const assessId = document.getElementById('m-dispatch-assessment').value;
    const pack = document.getElementById('m-dispatch-pack').value;
    const idem = document.getElementById('m-dispatch-idempotency').value.trim();
    const checked = Array.from(document.querySelectorAll('input[name="dispatch_scenarios"]:checked')).map(el => el.value);

    if (checked.length === 0) {
      showToast('Select at least one rule.', 'error');
      return;
    }

    try {
      const res = await fetch(`${ API_BASE } /v1/assessments / ${ assessId }/runs`, {
method: 'POST',
  headers: {
  'Content-Type': 'application/json',
    'Idempotency-Key': idem || `run-${Date.now()}`,
        },
body: JSON.stringify({
  scenario_pack: pack,
  scenarios: checked,
  model_budget_tokens: 5000,
  hardened: false,
}),
      });

if (!res.ok) {
  const err = await res.json().catch(() => ({}));
  throw new Error(err.message || 'Run dispatch failed');
}

closeModal('modal-dispatch-run');
showToast('✓ Assessment run started successfully!', 'success');
await refreshAllData();
switchTab('test-runs');
    } catch (err) {
  showToast(err.message, 'error');
}
  });

// Modal 3: Register Agent
document.getElementById('btn-open-register-agent-modal').addEventListener('click', () => {
  openModal('modal-register-agent');
});

document.getElementById('form-register-agent').addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = document.getElementById('m-agent-name').value.trim();
  const adapter = document.getElementById('m-agent-adapter').value;
  const endpoint = document.getElementById('m-agent-endpoint').value.trim();
  const hostsStr = document.getElementById('m-agent-hosts').value.trim();
  const scope = document.getElementById('m-agent-scope').value.trim();
  const hosts = hostsStr ? hostsStr.split(',').map(h => h.trim()).filter(Boolean) : ['127.0.0.1', 'localhost'];

  try {
    const res = await fetch(`${API_BASE}/v1/agents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name,
        adapter_type: adapter,
        endpoint_url: adapter === 'http' ? endpoint : null,
        allowed_hosts: adapter === 'http' ? hosts : [],
        scope_description: scope,
        authorised: true,
        environment: 'live',
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || 'Failed to register agent');
    }

    closeModal('modal-register-agent');
    showToast(`✓ Agent '${name}' saved in database (.db)!`, 'success');
    await loadAgents();
    switchTab('projects');
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// Modal 4: Create Assessment Scope
document.getElementById('btn-open-create-assessment-modal').addEventListener('click', () => {
  openModal('modal-create-assessment');
});

document.getElementById('form-create-assessment').addEventListener('submit', async (e) => {
  e.preventDefault();
  const title = document.getElementById('m-assess-title').value.trim();
  const agentId = document.getElementById('m-assess-agent').value;
  const scope = document.getElementById('m-assess-scope').value.trim();

  try {
    const res = await fetch(`${API_BASE}/v1/assessments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: title,
        agent_id: agentId,
        scope: scope,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || 'Failed to create assessment');
    }

    closeModal('modal-create-assessment');
    showToast('✓ Assessment template saved in database!', 'success');
    await loadAssessments();
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// Modal 5: Review Finding
document.getElementById('form-review-finding').addEventListener('submit', async (e) => {
  e.preventDefault();
  const findingId = document.getElementById('m-review-finding-id').textContent;
  const decision = document.getElementById('m-review-decision').value;
  const reason = document.getElementById('m-review-reason').value.trim();

  try {
    const res = await fetch(`${API_BASE}/v1/findings/${findingId}/reviews`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        decision: decision,
        reason: reason,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || 'Failed to submit review');
    }

    closeModal('modal-review-finding');
    showToast(`✓ Decision '${decision}' recorded!`, 'success');
    document.getElementById('m-review-reason').value = '';
    await loadFindings();
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// Modal 6: Generate Report
document.getElementById('form-generate-report').addEventListener('submit', async (e) => {
  e.preventDefault();
  const runId = document.getElementById('m-report-run-id').value;
  const format = document.getElementById('m-report-format').value;

  try {
    const res = await fetch(`${API_BASE}/v1/runs/${runId}/report`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ format: format }),
    });

    if (!res.ok) throw new Error('Report generation failed');
    const artifact = await res.json();
    closeModal('modal-generate-report');
    showToast('✓ Report generated! Initiating download...', 'success');
    window.open(`${API_BASE}/v1/reports/${artifact.artifact_id}/download`, '_blank');
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// Modal 7: Configure Pricing Plan
document.getElementById('btn-open-create-plan-modal').addEventListener('click', () => {
  openModal('modal-create-plan');
});

document.getElementById('form-create-plan').addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = document.getElementById('m-plan-name').value.trim();
  let price = parseInt(document.getElementById('m-plan-price').value) || 0;
  // If entered in pounds (e.g. 500 for £500), convert to pence
  if (price > 0 && price < 10000) {
    price = price * 100;
  }
  const interval = document.getElementById('m-plan-interval').value;
  const agents = parseInt(document.getElementById('m-plan-agents').value) || 10;
  const runs = parseInt(document.getElementById('m-plan-runs').value) || 50;

  try {
    const res = await fetch(`${API_BASE}/v1/plans`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name,
        base_amount_minor: price,
        price_amount: price,
        billing_interval: interval,
        included_agents: agents,
        maximum_runs: runs,
        included_scenarios: runs * 10,
        retention_days: 30,
        active: true,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.detail || 'Failed to save plan');
    }
    closeModal('modal-create-plan');
    showToast(`✓ Pricing plan '${name}' saved!`, 'success');
    await loadBilling();
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// Compare Runs Modal
document.getElementById('btn-open-compare-modal').addEventListener('click', () => {
  populateCompareDropdowns();
  openModal('modal-compare-runs');
});

document.getElementById('btn-execute-comparison').addEventListener('click', async () => {
  const curRun = document.getElementById('compare-modal-current-run').value;
  const baseRun = document.getElementById('compare-modal-baseline-run').value;
  const container = document.getElementById('compare-results-container');

  if (!curRun || !baseRun) {
    showToast('Please select both runs.', 'error');
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/v1/runs/${curRun}/compare/${baseRun}`);
    if (!res.ok) throw new Error('Comparison failed');
    const comp = await res.json();

    container.innerHTML = `
        <div style="background: var(--bg-card-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px; margin-bottom: 12px; font-size: 0.82rem;">
          <span>Issues Fixed: <strong style="color: var(--accent-green);">${comp.resolved_failures}</strong></span> &bull;
          <span>New Issues: <strong style="color: var(--accent-red);">${comp.new_failures}</strong></span> &bull;
          <span>Overall: <strong>${comp.overall_changed ? 'Differences Detected' : 'Identical Outcomes'}</strong></span>
        </div>
        <div style="max-height: 240px; overflow-y: auto;">
          ${(comp.scenario_deltas || []).map(d => `
            <div style="display: flex; justify-content: space-between; padding: 6px 10px; border-bottom: 1px solid var(--border-subtle); font-size: 0.78rem;">
              <span><code>${d.scenario_id}</code></span>
              <span>${d.baseline_verdict || 'N/A'} &rarr; ${d.current_verdict || 'N/A'}</span>
              <span class="status-chip ${d.changed ? 'chip-fail' : 'chip-pass'}">${d.changed ? 'CHANGED' : 'SAME'}</span>
            </div>
          `).join('')}
        </div>
      `;
  } catch (err) {
    showToast(err.message, 'error');
  }
});
}

window.openReportModal = (runId) => {
  document.getElementById('m-report-run-id').value = runId;
  openModal('modal-generate-report');
};

function openModal(modalId) {
  const el = document.getElementById(modalId);
  if (el) el.classList.remove('hidden');
}

function closeModal(modalId) {
  const el = document.getElementById(modalId);
  if (el) el.classList.add('hidden');
}

// ─── Toast Notifications ─────────────────────────────────────────────────
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 200);
  }, 4000);
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

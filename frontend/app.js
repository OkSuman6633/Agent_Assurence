// Agent Assurance Lab — Interactive Frontend Logic

// Determine API Base URL dynamically
const API_BASE = window.location.origin.includes('8000') 
  ? window.location.origin 
  : 'http://127.0.0.1:8000';

let registeredAgents = [];
let selectedAgentId = null;
let currentResults = [];

// DOM Elements
const backendStatusPill = document.getElementById('backend-status-pill');
const backendStatusText = document.getElementById('backend-status-text');
const backendStatusDot = backendStatusPill.querySelector('.status-dot');

const agentForm = document.getElementById('agent-form');
const agentNameInput = document.getElementById('agent-name');
const radioSynthetic = document.getElementById('radio-synthetic');
const radioHttp = document.getElementById('radio-http');
const httpFieldsContainer = document.getElementById('http-fields-container');
const endpointUrlInput = document.getElementById('endpoint-url');
const allowedHostsInput = document.getElementById('allowed-hosts');
const authEnvVarInput = document.getElementById('auth-env-var');
const timeoutSlider = document.getElementById('timeout-seconds');
const timeoutDisplay = document.getElementById('timeout-display');
const scopeDescInput = document.getElementById('scope-description');
const authorisedSwitch = document.getElementById('authorised-switch');
const btnSubmitAgent = document.getElementById('btn-submit-agent');
const registerSpinner = document.getElementById('register-spinner');
const formAlert = document.getElementById('form-alert');
const activeAdapterBadge = document.getElementById('active-adapter-badge');

const presetSynthetic = document.getElementById('preset-synthetic');
const presetLocalHttp = document.getElementById('preset-local-http');
const presetCustom = document.getElementById('preset-custom');

const tabRegistered = document.getElementById('tab-registered');
const tabRunner = document.getElementById('tab-runner');
const tabGuide = document.getElementById('tab-guide');
const registeredCount = document.getElementById('registered-count');
const agentsContainer = document.getElementById('agents-container');
const btnRefreshAgents = document.getElementById('btn-refresh-agents');

const runnerAgentChip = document.getElementById('runner-agent-chip');
const runnerAgentName = document.getElementById('runner-agent-name');
const btnExecuteRun = document.getElementById('btn-execute-run');
const runSpinner = document.getElementById('run-spinner');
const tokenBudgetInput = document.getElementById('token-budget');
const resultsEmptyState = document.getElementById('results-empty-state');
const runResultsContent = document.getElementById('run-results-content');
const resRunId = document.getElementById('res-run-id');
const resTimestamp = document.getElementById('res-timestamp');
const resPills = document.getElementById('res-pills');
const scenarioCardsList = document.getElementById('scenario-cards-list');

const evidenceModal = document.getElementById('evidence-modal');
const modalTitle = document.getElementById('modal-title');
const modalJson = document.getElementById('modal-json');
const modalClose = document.getElementById('modal-close');

// 1. Backend Health Check
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

// 2. Adapter Toggle & UI Sync
function setAdapterMode(mode) {
  if (mode === 'synthetic') {
    radioSynthetic.checked = true;
    httpFieldsContainer.classList.add('hidden');
    endpointUrlInput.removeAttribute('required');
    allowedHostsInput.removeAttribute('required');
    activeAdapterBadge.textContent = 'SYNTHETIC MODE';
  } else {
    radioHttp.checked = true;
    httpFieldsContainer.classList.remove('hidden');
    endpointUrlInput.setAttribute('required', 'true');
    allowedHostsInput.setAttribute('required', 'true');
    activeAdapterBadge.textContent = 'REMOTE HTTP';
  }
}

radioSynthetic.addEventListener('change', () => setAdapterMode('synthetic'));
radioHttp.addEventListener('change', () => setAdapterMode('http'));

timeoutSlider.addEventListener('input', (e) => {
  timeoutDisplay.textContent = `${e.target.value}s`;
});

// 3. Quick Presets
presetSynthetic.addEventListener('click', () => {
  setActivePreset(presetSynthetic);
  setAdapterMode('synthetic');
  agentNameInput.value = 'Synthetic Core Smoke Agent';
  endpointUrlInput.value = '';
  allowedHostsInput.value = '';
  authEnvVarInput.value = '';
  timeoutSlider.value = 15;
  timeoutDisplay.textContent = '15s';
  scopeDescInput.value = 'Autonomous customer FAQ and product inquiry assistant (Synthetic simulation).';
  authorisedSwitch.checked = true;
});

presetLocalHttp.addEventListener('click', () => {
  setActivePreset(presetLocalHttp);
  setAdapterMode('http');
  agentNameInput.value = 'Local HTTP Demo Agent';
  endpointUrlInput.value = 'http://127.0.0.1:8001/v1/agent/run';
  allowedHostsInput.value = '127.0.0.1, localhost';
  authEnvVarInput.value = '';
  timeoutSlider.value = 10;
  timeoutDisplay.textContent = '10s';
  scopeDescInput.value = 'Local test agent running on port 8001 implementing assurance contract.';
  authorisedSwitch.checked = true;
});

presetCustom.addEventListener('click', () => {
  setActivePreset(presetCustom);
  setAdapterMode('http');
  agentNameInput.value = '';
  endpointUrlInput.value = 'https://';
  allowedHostsInput.value = '';
  authEnvVarInput.value = '';
  timeoutSlider.value = 15;
  timeoutDisplay.textContent = '15s';
  scopeDescInput.value = '';
  authorisedSwitch.checked = true;
  agentNameInput.focus();
});

function setActivePreset(activeBtn) {
  [presetSynthetic, presetLocalHttp, presetCustom].forEach(btn => btn.classList.remove('active'));
  activeBtn.classList.add('active');
}

// 4. Form Submission & Agent Registration
agentForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  hideAlert();

  const isHttp = radioHttp.checked;
  const name = agentNameInput.value.trim();
  const authorised = authorisedSwitch.checked;
  const scopeDesc = scopeDescInput.value.trim();

  if (!name) {
    showAlert('Agent Name is required.', 'error');
    return;
  }

  if (!authorised) {
    showAlert('Explicit authorisation is mandatory to register an agent for safety testing.', 'error');
    return;
  }

  const payload = {
    name,
    adapter_type: isHttp ? 'http' : 'synthetic',
    authorised: true,
    timeout_seconds: parseFloat(timeoutSlider.value),
    scope_description: scopeDesc
  };

  if (isHttp) {
    const endpoint = endpointUrlInput.value.trim();
    const rawHosts = allowedHostsInput.value.trim();
    if (!endpoint) {
      showAlert('Endpoint URL is required for HTTP adapter.', 'error');
      return;
    }
    if (!rawHosts) {
      showAlert('At least one explicit allowed host is required to prevent SSRF vulnerabilities.', 'error');
      return;
    }

    const hosts = rawHosts.split(',').map(h => h.trim()).filter(Boolean);
    payload.endpoint_url = endpoint;
    payload.allowed_hosts = hosts;

    const envVar = authEnvVarInput.value.trim();
    if (envVar) {
      payload.auth_env_var = envVar;
    }
  }

  // Submit to API
  setRegisterLoading(true);
  try {
    const res = await fetch(`${API_BASE}/v1/agents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || `Registration failed with status ${res.status}`);
    }

    showAlert(`Agent "${data.name}" successfully registered! ID: ${data.agent_id}`, 'success');
    await loadAgents();
    selectAgentForRunner(data.agent_id);
    switchTab('tab-content-agents');
  } catch (err) {
    showAlert(err.message, 'error');
  } finally {
    setRegisterLoading(false);
  }
});

function showAlert(msg, type) {
  formAlert.textContent = msg;
  formAlert.className = `alert-box ${type}`;
}

function hideAlert() {
  formAlert.className = 'alert-box hidden';
}

function setRegisterLoading(loading) {
  btnSubmitAgent.disabled = loading;
  if (loading) {
    registerSpinner.classList.remove('hidden');
    btnSubmitAgent.querySelector('.btn-text').textContent = 'Registering...';
  } else {
    registerSpinner.classList.add('hidden');
    btnSubmitAgent.querySelector('.btn-text').textContent = 'Register Agent';
  }
}

// 5. Fetch & Render Registered Agents
async function loadAgents() {
  try {
    const res = await fetch(`${API_BASE}/v1/agents`);
    if (res.ok) {
      registeredAgents = await res.json();
      renderAgentsList();
    }
  } catch (err) {
    console.warn('Could not load agents list:', err);
  }
}

function renderAgentsList() {
  registeredCount.textContent = registeredAgents.length;
  if (registeredAgents.length === 0) {
    agentsContainer.innerHTML = `
      <div class="empty-state" id="agents-empty">
        <div class="empty-icon">&#128392;</div>
        <h4>No Agents Registered Yet</h4>
        <p>Fill out the registration form on the left or click <strong>"Synthetic Demo"</strong> to register your first agent.</p>
      </div>
    `;
    return;
  }

  agentsContainer.innerHTML = registeredAgents.map(agent => {
    const isSelected = agent.agent_id === selectedAgentId;
    const isSynth = agent.adapter_type === 'synthetic';
    return `
      <div class="agent-item-card ${isSelected ? 'selected' : ''}" data-id="${agent.agent_id}">
        <div class="agent-item-left">
          <div class="agent-item-title-row">
            <span class="agent-item-name">${escapeHtml(agent.name)}</span>
            <span class="${isSynth ? 'tag-safe' : 'tag-network'}">${agent.adapter_type.toUpperCase()}</span>
          </div>
          <span class="agent-item-id">ID: ${agent.agent_id}</span>
          <div class="agent-item-meta">
            ${isSynth ? '<span>Local Simulation</span>' : `<span>Endpoint: ${escapeHtml(agent.endpoint_url || 'None')}</span>`}
            <span>Timeout: ${agent.timeout_seconds}s</span>
          </div>
        </div>
        <button type="button" class="btn-select-agent" onclick="selectAgentForRunner('${agent.agent_id}')">
          ${isSelected ? 'Selected' : 'Select for Test'}
        </button>
      </div>
    `;
  }).join('');
}

window.selectAgentForRunner = function(id) {
  selectedAgentId = id;
  const agent = registeredAgents.find(a => a.agent_id === id);
  if (agent) {
    runnerAgentName.textContent = `${agent.name} (${agent.adapter_type})`;
    renderAgentsList();
  }
};

btnRefreshAgents.addEventListener('click', loadAgents);

// 6. Execute Scenario Run
btnExecuteRun.addEventListener('click', async () => {
  if (!selectedAgentId) {
    alert('Please select an agent first from the Registered Agents tab.');
    switchTab('tab-content-agents');
    return;
  }

  const selectedScenarios = Array.from(document.querySelectorAll('.scenario-check:checked')).map(cb => cb.value);
  if (selectedScenarios.length === 0) {
    alert('Please select at least one assurance scenario to run.');
    return;
  }

  const budget = parseInt(tokenBudgetInput.value, 10) || 5000;
  const idempotencyKey = `ui-run-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;

  setRunLoading(true);
  try {
    const res = await fetch(`${API_BASE}/v1/agents/${selectedAgentId}/runs`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Correlation-ID': idempotencyKey
      },
      body: JSON.stringify({
        scenario_pack: 'core-v1',
        scenarios: selectedScenarios,
        idempotency_key: idempotencyKey,
        model_budget_tokens: budget
      })
    });

    const runData = await res.json();
    if (!res.ok) {
      throw new Error(runData.detail || `Run execution failed with status ${res.status}`);
    }

    renderRunResults(runData);
  } catch (err) {
    alert(`Assurance Run Error: ${err.message}`);
  } finally {
    setRunLoading(false);
  }
});

function setRunLoading(loading) {
  btnExecuteRun.disabled = loading;
  if (loading) {
    runSpinner.classList.remove('hidden');
    btnExecuteRun.querySelector('span').textContent = 'Evaluating Agent...';
  } else {
    runSpinner.classList.add('hidden');
    btnExecuteRun.querySelector('span').textContent = 'Execute Assurance Run';
  }
}

function renderRunResults(run) {
  currentResults = run.results || [];
  resultsEmptyState.classList.add('hidden');
  runResultsContent.classList.remove('hidden');

  resRunId.textContent = run.run_id;
  resTimestamp.textContent = new Date(run.created_at).toLocaleTimeString();

  const summary = run.summary || {};
  resPills.innerHTML = `
    <span class="summary-pill pass">${summary.PASS || 0} PASS</span>
    <span class="summary-pill fail">${summary.FAIL || 0} FAIL</span>
    <span class="summary-pill inconclusive">${summary.INCONCLUSIVE || 0} INCONCLUSIVE</span>
  `;

  scenarioCardsList.innerHTML = currentResults.map((r, idx) => {
    return `
      <div class="verdict-card verdict-${r.verdict}">
        <div class="verdict-header">
          <div class="verdict-title-row">
            <span class="verdict-badge ${r.verdict}">${r.verdict}</span>
            <span class="verdict-scenario-name">${escapeHtml(r.scenario_id)}</span>
          </div>
          <div class="verdict-actions">
            <button type="button" class="btn-inspect" onclick="openEvidenceModal(${idx})">Inspect Trace</button>
          </div>
        </div>
        <p class="verdict-summary">${escapeHtml(r.summary)}</p>
      </div>
    `;
  }).join('');
}

window.openEvidenceModal = function(idx) {
  const item = currentResults[idx];
  if (!item) return;
  modalTitle.textContent = `Evidence Trace: ${item.scenario_id}`;
  modalJson.textContent = JSON.stringify({
    scenario_id: item.scenario_id,
    verdict: item.verdict,
    summary: item.summary,
    evidence_complete: item.evidence_complete,
    trace: item.trace
  }, null, 2);
  evidenceModal.classList.remove('hidden');
};

modalClose.addEventListener('click', () => {
  evidenceModal.classList.add('hidden');
});

evidenceModal.addEventListener('click', (e) => {
  if (e.target === evidenceModal) {
    evidenceModal.classList.add('hidden');
  }
});

// 7. Tab Switching
const tabs = [
  { btn: tabRegistered, contentId: 'tab-content-agents' },
  { btn: tabRunner, contentId: 'tab-content-runner' },
  { btn: tabGuide, contentId: 'tab-content-guide' }
];

tabs.forEach(t => {
  t.btn.addEventListener('click', () => switchTab(t.contentId));
});

function switchTab(targetContentId) {
  tabs.forEach(t => {
    if (t.contentId === targetContentId) {
      t.btn.classList.add('active');
      document.getElementById(t.contentId).classList.add('active');
    } else {
      t.btn.classList.remove('active');
      document.getElementById(t.contentId).classList.remove('active');
    }
  });
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Initialization
document.addEventListener('DOMContentLoaded', () => {
  checkBackendHealth();
  setInterval(checkBackendHealth, 10000);
  loadAgents();
});

// ══════════════════════════════════════════════════════════════════════════
// AUTHENTICATION GATE — email + password sessions, RBAC-aware UI
// ══════════════════════════════════════════════════════════════════════════
// Loaded before app.js so that:
//   1. every fetch() carries the session cookie (HttpOnly, SameSite=Lax),
//   2. the login/registration gate is painted before the app shell,
//   3. app.js can await `window.AuthGateReady` and never touch protected APIs
//      while unauthenticated.
// No token is ever persisted in web storage: the HttpOnly cookie is the
// session of record, the bearer token lives in memory only (for the rare
// cross-site dev setup where browsers refuse third-party cookies).
// ══════════════════════════════════════════════════════════════════════════
(function () {
    'use strict';

    // ─── API base ────────────────────────────────────────────────────────────
    // Hostname-aligned on purpose: SameSite=Lax cookies ignore the port but not
    // the host, so a page served from localhost:5500 must talk to localhost:8000
    // (not 127.0.0.1:8000) or the session cookie would be dropped.
    function resolveApiBase() {
        const loc = window.location;
        if (loc.port === '8000') return loc.origin;
        if (loc.hostname === 'localhost' || loc.hostname === '127.0.0.1') {
            return loc.protocol + '//' + loc.hostname + ':8000';
        }
        return loc.origin;
    }

    const API = resolveApiBase();
    const nativeFetch = window.fetch.bind(window);

    const ROLE_FALLBACK_LABELS = {
        platform_admin: 'Platform Admin',
        owner: 'Workspace Owner',
        assessor: 'Assessor',
        reviewer: 'Reviewer',
        viewer: 'Viewer',
    };

    const state = {
        user: null,
        permissions: new Set(),
        config: null,
        token: '',
        busy: false,
        relocking: false,
    };

    let resolveGate;
    const gateReady = new Promise(function (resolve) {
        resolveGate = resolve;
    });
    window.AuthGateReady = gateReady;

    const el = {};

    // ─── Small helpers ───────────────────────────────────────────────────────
    function byId(id) {
        return document.getElementById(id);
    }

    function initials(value) {
        const parts = String(value || '')
            .replace(/[^A-Za-z0-9 @._-]/g, '')
            .split(/[\s._@-]+/)
            .filter(Boolean);
        if (!parts.length) return '??';
        if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
        return (parts[0][0] + parts[1][0]).toUpperCase();
    }

    function roleLabel(role) {
        if (!role) return '';
        const configured = (state.config && state.config.roles) || [];
        const match = configured.find(function (entry) {
            return entry && entry.value === role;
        });
        return (match && match.label) || ROLE_FALLBACK_LABELS[role] || role;
    }

    function escapeHtml(value) {
        return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, function (ch) {
            // Escaped entity strings are built from char codes so this file
            // never contains a raw markup delimiter sequence.
            switch (ch) {
                case '\u0026': return '\u0026amp;';
                case '\u003c': return '\u0026lt;';
                case '\u003e': return '\u0026gt;';
                case '\u0022': return '\u0026quot;';
                default: return '\u0026#39;';
            }
        });
    }

    function extractMessage(data, status) {
        if (data) {
            if (typeof data.message === 'string' && data.message.trim()) return data.message;
            if (typeof data.detail === 'string' && data.detail.trim()) return data.detail;
            if (Array.isArray(data.detail) && data.detail.length) {
                const first = data.detail[0] || {};
                const loc = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : '';
                return (loc ? loc + ': ' : '') + (first.msg || 'Invalid value');
            }
        }
        if (status === 423) return 'Account temporarily locked after repeated failed sign-ins. Try again in 15 minutes.';
        if (status === 429) return 'Too many attempts. Please wait a moment and try again.';
        if (status === 401) return 'Incorrect email or password.';
        if (status === 403) return 'Your role does not allow this action.';
        if (status === 0) return 'Cannot reach the assurance server.';
        return 'Request failed (HTTP ' + status + ').';
    }

    function isAuthPath(url) {
        return String(url).indexOf('/v1/auth/') !== -1;
    }

    // ─── JSON API helper (never throws) ──────────────────────────────────────
    async function api(path, options) {
        const opts = options || {};
        const init = { method: opts.method || 'GET', credentials: 'include' };
        if (opts.body !== undefined && opts.body !== null) {
            init.headers = { 'Content-Type': 'application/json' };
            init.body = JSON.stringify(opts.body);
        }
        if (state.token) {
            init.headers = Object.assign({}, init.headers || {}, { Authorization: 'Bearer ' + state.token });
        }
        let response;
        try {
            response = await nativeFetch(API + path, init);
        } catch (err) {
            return {
                ok: false,
                status: 0,
                data: null,
                message: 'Cannot reach the assurance API at ' + API + '. Start the backend, then reload this page.',
            };
        }
        let data = null;
        try {
            data = await response.json();
        } catch (err) {
            data = null;
        }
        return {
            ok: response.ok,
            status: response.status,
            data: data,
            message: response.ok ? '' : extractMessage(data, response.status),
        };
    }

    // ─── Global fetch wrapper ────────────────────────────────────────────────
    window.fetch = function (input, init) {
        const opts = Object.assign({}, init || {});
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        const sameApi = url.indexOf(API) === 0 || url.charAt(0) === '/';
        if (sameApi) {
            if (!opts.credentials) opts.credentials = 'include';
            if (state.token) {
                const headers = new Headers(opts.headers || {});
                if (!headers.has('Authorization')) headers.set('Authorization', 'Bearer ' + state.token);
                opts.headers = headers;
            }
        }
        return nativeFetch(input, opts).then(function (response) {
            if (isAuthPath(url)) return response;
            if (response.status === 401) {
                lock('Your session has ended. Please sign in again.');
                return response;
            }
            if (response.status === 403 && !state.relocking) {
                // A deactivated account is rejected with 403, not 401, so it
                // must be told apart from an ordinary permission denial before
                // the local session is torn down.
                response.clone().json().then(function (body) {
                    const detail = body && typeof body.detail === 'string' ? body.detail.toLowerCase() : '';
                    if (detail.indexOf('deactivated') === -1) return;
                    state.relocking = true;
                    state.token = '';
                    nativeFetch(API + '/v1/auth/logout', { method: 'POST', credentials: 'include' })
                        .catch(function () { })
                        .then(function () { window.location.reload(); });
                }).catch(function () { });
            }
            return response;
        });
    };

    // ─── Element cache ───────────────────────────────────────────────────────
    function cacheElements() {
        el.gate = byId('auth-gate');
        el.notice = byId('auth-gate-notice');
        el.tabs = Array.prototype.slice.call(document.querySelectorAll('[data-auth-tab]'));
        el.panels = {
            signin: byId('auth-panel-signin'),
            signup: byId('auth-panel-signup'),
        };
        el.signinForm = byId('auth-signin-form');
        el.signinEmail = byId('auth-signin-email');
        el.signinPassword = byId('auth-signin-password');
        el.signinRemember = byId('auth-signin-remember');
        el.signinSubmit = byId('auth-signin-submit');
        el.signinError = byId('auth-signin-error');
        el.signupForm = byId('auth-signup-form');
        el.signupName = byId('auth-signup-name');
        el.signupWorkspace = byId('auth-signup-workspace');
        el.signupEmail = byId('auth-signup-email');
        el.signupPassword = byId('auth-signup-password');
        el.signupConfirm = byId('auth-signup-confirm');
        el.signupSubmit = byId('auth-signup-submit');
        el.signupError = byId('auth-signup-error');
        el.signupHint = byId('auth-signup-hint');
        el.signupTab = byId('auth-tab-signup');
        el.demoHint = byId('auth-demo-hint');
        el.demoFill = byId('auth-demo-fill');
        el.demoEmail = byId('auth-demo-email');
        el.chipAvatar = byId('session-avatar');
        el.chipName = byId('session-name');
        el.chipEmail = byId('session-email');
        el.chipRole = byId('session-role');
        el.signOut = byId('btn-sign-out');
    }

    // ─── Gate visibility ─────────────────────────────────────────────────────
    function showNotice(message) {
        if (!el.notice) return;
        el.notice.textContent = message || '';
        el.notice.classList.toggle('hidden', !message);
    }

    function setError(scope, message) {
        const node = scope === 'signup' ? el.signupError : el.signinError;
        if (!node) return;
        node.textContent = message || '';
        node.classList.toggle('hidden', !message);
    }

    function setBusy(busy, scope) {
        state.busy = busy;
        const button = scope === 'signup' ? el.signupSubmit : el.signinSubmit;
        const form = scope === 'signup' ? el.signupForm : el.signinForm;
        if (button) {
            button.disabled = busy;
            button.setAttribute('aria-busy', busy ? 'true' : 'false');
            button.textContent = busy
                ? scope === 'signup'
                    ? 'Creating workspace…'
                    : 'Signing in…'
                : scope === 'signup'
                    ? 'Create workspace'
                    : 'Sign in';
        }
        if (form) form.classList.toggle('auth-form-busy', busy);
    }

    function unlock() {
        document.body.classList.remove('auth-locked');
        if (el.gate) el.gate.classList.add('hidden');
    }

    function lock(message) {
        state.user = null;
        state.permissions = new Set();
        state.token = '';
        renderUserChip();
        applyPermissionGating();
        document.body.classList.add('auth-locked');
        if (el.gate) el.gate.classList.remove('hidden');
        showNotice(message || '');
        setError('signin', '');
        setError('signup', '');
        if (el.signinEmail) {
            window.setTimeout(function () {
                try {
                    el.signinEmail.focus();
                } catch (err) {
                    /* focus is best-effort */
                }
            }, 80);
        }
    }

    // ─── Session state ───────────────────────────────────────────────────────
    function applySession(payload) {
        const data = payload || {};
        const user = data.user || null;
        state.user = user;
        state.token = data.access_token || '';
        const perms = data.permissions || (user && user.permissions) || [];
        state.permissions = new Set(perms);
        renderUserChip();
        applyPermissionGating();
    }

    function has(permission) {
        if (!permission) return true;
        if (!state.user) return false;
        if (state.user.role === 'platform_admin') return true;
        return state.permissions.has(String(permission));
    }

    function hasAny(spec) {
        return String(spec || '')
            .split('|')
            .map(function (part) {
                return part.trim();
            })
            .filter(Boolean)
            .some(has);
    }

    function applyPermissionGating() {
        const nodes = document.querySelectorAll('[data-permission]');
        Array.prototype.forEach.call(nodes, function (node) {
            // While signed out the gate covers the UI, so leave markup untouched.
            const allowed = state.user ? hasAny(node.getAttribute('data-permission')) : true;
            node.classList.toggle('hidden', !allowed);
            if (allowed) node.removeAttribute('aria-hidden');
            else node.setAttribute('aria-hidden', 'true');
        });
    }

    function renderUserChip() {
        const user = state.user;
        const name = user ? user.display_name || String(user.email || '').split('@')[0] : 'Signed out';
        if (el.chipName) el.chipName.textContent = user ? name : 'Signed out';
        if (el.chipEmail) el.chipEmail.textContent = user ? user.email : 'No active session';
        if (el.chipAvatar) el.chipAvatar.textContent = user ? initials(name) : '—';
        if (el.chipRole) {
            const label = user ? roleLabel(user.role) : '';
            el.chipRole.textContent = label;
            el.chipRole.classList.toggle('hidden', !label);
        }
        if (el.signOut) el.signOut.classList.toggle('hidden', !user);
    }

    // ─── Login / registration forms ──────────────────────────────────────────
    function switchMode(mode) {
        el.tabs.forEach(function (tab) {
            const isActive = tab.getAttribute('data-auth-tab') === mode;
            tab.classList.toggle('active', isActive);
            tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });
        Object.keys(el.panels).forEach(function (key) {
            const panel = el.panels[key];
            if (panel) panel.classList.toggle('hidden', key !== mode);
        });
        showNotice('');
        if (mode === 'signup' && el.signupEmail) {
            window.setTimeout(function () {
                try {
                    el.signupEmail.focus();
                } catch (err) {
                    /* focus is best-effort */
                }
            }, 60);
        }
        if (mode === 'signin' && el.signinEmail) {
            window.setTimeout(function () {
                try {
                    el.signinEmail.focus();
                } catch (err) {
                    /* focus is best-effort */
                }
            }, 60);
        }
    }

    function afterSignIn() {
        document.dispatchEvent(new CustomEvent('auth:signed-in', { detail: { user: state.user } }));
    }

    async function onSignIn(event) {
        event.preventDefault();
        if (state.busy) return;
        const email = (el.signinEmail && el.signinEmail.value || '').trim();
        const password = (el.signinPassword && el.signinPassword.value) || '';
        if (!email || !password) {
            setError('signin', 'Enter both your email address and password.');
            return;
        }
        setError('signin', '');
        showNotice('');
        setBusy(true, 'signin');
        const result = await api('/v1/auth/login', {
            method: 'POST',
            body: {
                email: email,
                password: password,
                remember_me: !!(el.signinRemember && el.signinRemember.checked),
            },
        });
        setBusy(false, 'signin');
        if (!result.ok) {
            setError('signin', result.message);
            if (result.status === 429 || result.status === 423) {
                showNotice('Too many attempts from this network or account. Wait a few minutes before retrying.');
            }
            return;
        }
        applySession(result.data);
        if (el.signinForm) el.signinForm.reset();
        unlock();
        afterSignIn();
    }

    async function onSignUp(event) {
        event.preventDefault();
        if (state.busy) return;
        const displayName = (el.signupName && el.signupName.value || '').trim();
        const workspace = (el.signupWorkspace && el.signupWorkspace.value || '').trim();
        const email = (el.signupEmail && el.signupEmail.value || '').trim();
        const password = (el.signupPassword && el.signupPassword.value) || '';
        const confirm = (el.signupConfirm && el.signupConfirm.value) || '';
        const minLength = (state.config && state.config.min_password_length) || 10;

        if (!email || !password) {
            setError('signup', 'Email address and password are required.');
            return;
        }
        if (password.length < minLength) {
            setError('signup', 'Choose a password of at least ' + minLength + ' characters (letters and digits).');
            return;
        }
        if (password !== confirm) {
            setError('signup', 'The two passwords do not match.');
            return;
        }
        setError('signup', '');
        showNotice('');
        setBusy(true, 'signup');
        const result = await api('/v1/auth/register', {
            method: 'POST',
            body: {
                email: email,
                password: password,
                display_name: displayName,
                workspace_name: workspace,
            },
        });
        setBusy(false, 'signup');
        if (!result.ok) {
            setError('signup', result.message);
            if (result.status === 403) showNotice('Self-service sign-up is disabled. Ask an administrator for an invite.');
            return;
        }
        applySession(result.data);
        if (el.signupForm) el.signupForm.reset();
        unlock();
        afterSignIn();
    }

    async function signOut() {
        try {
            await api('/v1/auth/logout', { method: 'POST' });
        } catch (err) {
            /* signing out locally must succeed even if the call fails */
        }
        state.user = null;
        state.permissions = new Set();
        state.token = '';
        // A reload guarantees no stale tenant data survives the logout.
        window.location.reload();
    }

    // ─── Config + bootstrap ──────────────────────────────────────────────────
    async function loadConfig() {
        const result = await api('/v1/auth/config');
        if (result.ok && result.data) {
            state.config = result.data;
            renderConfig();
        }
        return state.config;
    }

    function renderConfig() {
        const config = state.config || {};
        const minLength = config.min_password_length || 10;
        if (el.signupHint) {
            el.signupHint.textContent =
                'Use at least ' + minLength + ' characters with both letters and digits. Avoid your name or email address.';
        }
        if (el.signupPassword) el.signupPassword.setAttribute('minlength', String(minLength));
        if (config.registration_enabled === false) {
            if (el.signupTab) el.signupTab.classList.add('hidden');
            if (el.panels.signup) el.panels.signup.classList.add('hidden');
        }
        const demo = config.demo_credentials;
        if (el.demoHint) {
            el.demoHint.classList.toggle('hidden', !demo);
            if (demo && el.demoEmail) el.demoEmail.textContent = demo.email;
        }
    }

    function wireEvents() {
        el.tabs.forEach(function (tab) {
            tab.addEventListener('click', function () {
                switchMode(tab.getAttribute('data-auth-tab'));
            });
        });
        if (el.signinForm) el.signinForm.addEventListener('submit', onSignIn);
        if (el.signupForm) el.signupForm.addEventListener('submit', onSignUp);
        if (el.demoFill) {
            el.demoFill.addEventListener('click', function () {
                const demo = state.config && state.config.demo_credentials;
                if (!demo) return;
                switchMode('signin');
                if (el.signinEmail) el.signinEmail.value = demo.email;
                if (el.signinPassword) el.signinPassword.value = demo.password;
                if (el.signinPassword) el.signinPassword.focus();
            });
        }
        if (el.signOut) el.signOut.addEventListener('click', signOut);

        Array.prototype.forEach.call(document.querySelectorAll('[data-toggle-password]'), function (button) {
            button.addEventListener('click', function () {
                const target = byId(button.getAttribute('data-toggle-password'));
                if (!target) return;
                const reveal = target.type === 'password';
                target.type = reveal ? 'text' : 'password';
                button.textContent = reveal ? 'Hide' : 'Show';
                button.setAttribute('aria-label', reveal ? 'Hide password' : 'Show password');
            });
        });

        // NOTE: theme toggling is owned by app.js#setupThemeToggle().
        // Binding a second handler here would toggle twice per click and
        // leave the theme looking frozen.
    }

    async function bootstrap() {
        cacheElements();
        wireEvents();
        renderUserChip();
        await loadConfig();
        const result = await api('/v1/auth/me');
        if (result.ok && result.data && result.data.user) {
            applySession(result.data);
            unlock();
        } else {
            lock(result.status === 0 ? result.message : '');
        }
        resolveGate();
    }

    // ─── Public surface (used by app.js and team.js) ─────────────────────────
    window.Auth = {
        apiBase: API,
        api: api,
        currentUser: function () {
            return state.user;
        },
        isSignedIn: function () {
            return !!state.user;
        },
        has: has,
        hasAny: hasAny,
        permissions: function () {
            return Array.prototype.slice.call(state.permissions);
        },
        roleLabel: roleLabel,
        escapeHtml: escapeHtml,
        config: function () {
            return state.config;
        },
        refresh: async function () {
            const result = await api('/v1/auth/me');
            if (result.ok && result.data) applySession(result.data);
            return result;
        },
        signOut: signOut,
        lock: lock,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootstrap);
    } else {
        bootstrap();
    }
})();

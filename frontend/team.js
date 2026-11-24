// ══════════════════════════════════════════════════════════════════════════
// TEAM & ACCESS — workspace administration view (RBAC, users, roles)
// Depends on window.Auth (auth.js). Rendering is gated on users:manage; the
// API enforces the same rule server-side, so this is presentation only.
// ══════════════════════════════════════════════════════════════════════════
(function () {
    'use strict';

    const state = {
        loaded: false,
        loading: false,
        users: [],
        roles: [],
        tenantId: '',
    };

    function auth() {
        return window.Auth;
    }

    function byId(id) {
        return document.getElementById(id);
    }

    function esc(value) {
        return auth() ? auth().escapeHtml(value) : String(value === undefined ? '' : value);
    }

    function formatDate(value) {
        if (!value) return '—';
        const parsed = new Date(value);
        if (isNaN(parsed.getTime())) return String(value);
        return parsed.toLocaleString(undefined, {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
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

    function setError(message) {
        const node = byId('team-invite-error');
        if (!node) return;
        node.textContent = message || '';
        node.classList.toggle('hidden', !message);
    }

    function setEmpty(message) {
        const body = byId('team-table-body');
        if (!body) return;
        body.innerHTML = '<tr><td colspan="5" class="team-empty">' + esc(message) + '</td></tr>';
    }

    function roleOptions(selected, allowedValues) {
        const roles = state.roles.filter(function (role) {
            return !allowedValues || allowedValues.indexOf(role.value) !== -1;
        });
        return roles
            .map(function (role) {
                const isSelected = role.value === selected ? ' selected' : '';
                return '<option value="' + esc(role.value) + '"' + isSelected + '>' + esc(role.label) + '</option>';
            })
            .join('');
    }

    function renderRows() {
        const body = byId('team-table-body');
        if (!body) return;

        if (!state.users.length) {
            setEmpty('No members yet. Invite your first teammate above.');
            return;
        }

        const me = auth() && auth().currentUser();
        const myId = me ? me.user_id : '';

        body.innerHTML = state.users
            .map(function (user) {
                const label = user.display_name || String(user.email || '').split('@')[0];
                const isSelf = user.user_id === myId;
                const statusClass = user.is_active ? 'status-badge status-active' : 'status-badge status-inactive';
                const statusText = user.is_active ? 'Active' : 'Deactivated';
                const assignable = state.roles
                    .filter(function (role) {
                        return role.assignable;
                    })
                    .map(function (role) {
                        return role.value;
                    });
                const roleCell = user.is_active
                    ? '<select class="form-select team-role-select"' + (isSelf ? ' disabled' : '') +
                    ' data-user-id="' + esc(user.user_id) + '" data-current-role="' + esc(user.role) + '"' +
                    ' aria-label="Role for ' + esc(label) + '">' +
                    roleOptions(user.role, isSelf ? [user.role] : assignable) +
                    '</select>'
                    : '<span class="team-role-static">' + esc(auth() ? auth().roleLabel(user.role) : user.role) + '</span>';

                const actionButton = isSelf
                    ? '<span class="team-action-hint">You</span>'
                    : '<button type="button" class="btn-table-action ' +
                    (user.is_active ? 'danger' : '') +
                    '" data-user-action="' + (user.is_active ? 'deactivate' : 'reactivate') + '"' +
                    ' data-user-id="' + esc(user.user_id) + '">' +
                    (user.is_active ? 'Deactivate' : 'Reactivate') +
                    '</button>';

                return (
                    '<tr data-user-row="' + esc(user.user_id) + '">' +
                    '<td><div class="team-member-cell">' +
                    '<div class="user-avatar-circle team-avatar">' + esc(initials(label)) + '</div>' +
                    '<div class="team-member-meta">' +
                    '<span class="team-member-name">' + esc(label) + (isSelf ? ' <span class="team-self-tag">you</span>' : '') + '</span>' +
                    '<span class="team-member-email">' + esc(user.email) + '</span>' +
                    (user.must_change_password ? '<span class="team-warning-tag">Password change pending</span>' : '') +
                    '</div></div></td>' +
                    '<td>' + roleCell + '</td>' +
                    '<td><span class="' + statusClass + '">' + statusText + '</span></td>' +
                    '<td class="team-date-cell">' + esc(formatDate(user.last_login_at)) + '</td>' +
                    '<td class="text-right">' + actionButton + '</td>' +
                    '</tr>'
                );
            })
            .join('');

        wireRowEvents();
    }

    async function loadRoles() {
        const result = await auth().api('/v1/auth/roles');
        if (result.ok && result.data && Array.isArray(result.data.roles)) {
            state.roles = result.data.roles;
        }
        const select = byId('team-invite-role');
        if (select) {
            const assignable = state.roles.filter(function (role) {
                return role.assignable;
            });
            select.innerHTML = assignable.length
                ? roleOptions('viewer', assignable.map(function (role) {
                    return role.value;
                }))
                : '<option value="viewer">Viewer</option>';
        }
    }

    async function load() {
        if (!auth() || !auth().isSignedIn() || !auth().has('users:manage')) return;
        if (state.loading) return;
        state.loading = true;
        if (!state.roles.length) await loadRoles();
        const result = await auth().api('/v1/auth/users');
        state.loading = false;
        if (!result.ok) {
            setEmpty(result.status === 403 ? 'Your role cannot view workspace members.' : result.message);
            return;
        }
        state.users = (result.data && result.data.users) || [];
        state.tenantId = (result.data && result.data.tenant_id) || '';
        state.loaded = true;
        renderRows();
        const note = byId('team-tenant-note');
        if (note) {
            note.textContent = state.tenantId ? 'Tenant scope: ' + state.tenantId : '';
        }
    }

    async function updateRole(select) {
        const userId = select.getAttribute('data-user-id');
        const previous = select.getAttribute('data-current-role');
        const next = select.value;
        if (!userId || next === previous) return;
        select.disabled = true;
        const result = await auth().api('/v1/auth/users/' + encodeURIComponent(userId), {
            method: 'PATCH',
            body: { role: next },
        });
        select.disabled = false;
        if (!result.ok) {
            select.value = previous;
            setError(result.message);
            return;
        }
        setError('');
        select.setAttribute('data-current-role', next);
        await load();
    }

    async function setActive(userId, active) {
        const result = await auth().api('/v1/auth/users/' + encodeURIComponent(userId), {
            method: 'PATCH',
            body: { is_active: active },
        });
        if (!result.ok) {
            setError(result.message);
            return;
        }
        setError('');
        await load();
    }

    function wireRowEvents() {
        Array.prototype.forEach.call(document.querySelectorAll('.team-role-select'), function (select) {
            select.addEventListener('change', function () {
                updateRole(select);
            });
        });
        Array.prototype.forEach.call(document.querySelectorAll('[data-user-action]'), function (button) {
            button.addEventListener('click', function () {
                const userId = button.getAttribute('data-user-id');
                const action = button.getAttribute('data-user-action');
                if (!userId) return;
                button.disabled = true;
                if (action === 'deactivate') {
                    if (!window.confirm('Deactivate this member? They will be signed out immediately.')) {
                        button.disabled = false;
                        return;
                    }
                    setActive(userId, false);
                } else {
                    setActive(userId, true);
                }
            });
        });
    }

    async function invite(event) {
        event.preventDefault();
        const name = (byId('team-invite-name') || {}).value || '';
        const email = ((byId('team-invite-email') || {}).value || '').trim();
        const role = (byId('team-invite-role') || {}).value || 'viewer';
        const password = (byId('team-invite-password') || {}).value || '';
        const submit = byId('team-invite-submit');

        if (!email || !password) {
            setError('Email address and a temporary password are required.');
            return;
        }
        const minLength = (auth().config() && auth().config().min_password_length) || 10;
        if (password.length < minLength) {
            setError('The temporary password must be at least ' + minLength + ' characters.');
            return;
        }
        setError('');
        if (submit) {
            submit.disabled = true;
            submit.textContent = 'Creating…';
        }
        const result = await auth().api('/v1/auth/users', {
            method: 'POST',
            body: { email: email, password: password, display_name: name.trim(), role: role },
        });
        if (submit) {
            submit.disabled = false;
            submit.textContent = 'Create member';
        }
        if (!result.ok) {
            setError(result.message);
            return;
        }
        const form = byId('team-invite-form');
        if (form) form.reset();
        await load();
    }

    function wire() {
        const form = byId('team-invite-form');
        if (form) form.addEventListener('submit', invite);
        const refresh = byId('btn-refresh-team');
        if (refresh) {
            refresh.addEventListener('click', function () {
                state.roles = [];
                load();
            });
        }
    }

    window.TeamView = {
        load: load,
        reset: function () {
            state.loaded = false;
            state.users = [];
            setEmpty('Sign in to view workspace members.');
        },
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wire);
    } else {
        wire();
    }
})();

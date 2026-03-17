/**
 * @jest-environment jsdom
 *
 * Unit tests for the ACL/permissions UI in app.js.
 *
 * Covers:
 *   - loadClientACL() — populates form from API response
 *   - saveClientACL() — PATCH/PUT request with correct payload
 *   - Permission toggles reflected in save payload
 */

'use strict';

const { evalApp, resetDom, mockFn, readState, setACLClientId } = require('./helpers/setup');

// ---------------------------------------------------------------------------
// Suite setup
// ---------------------------------------------------------------------------

beforeAll(() => evalApp());
beforeEach(() => resetDom());

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeACL(overrides = {}) {
  return {
    is_admin: false,
    can_escalate: false,
    can_propagate: false,
    allowed_types: [],
    skill_blacklist: [],
    intent_blacklist: [],
    ...overrides,
  };
}

function makeClient(overrides = {}) {
  return {
    client_id: 1,
    name: 'TestClient',
    api_key: 'key0000000000000000000001',
    is_admin: false,
    can_escalate: false,
    can_propagate: false,
    revoked: false,
    ...overrides,
  };
}

/**
 * Set the aclClientSelect dropdown to a specific client ID.
 */
function selectACLClient(id) {
  const select = document.getElementById('aclClientSelect');
  if (!select.querySelector(`option[value="${id}"]`)) {
    const opt = document.createElement('option');
    opt.value = String(id);
    select.appendChild(opt);
  }
  select.value = String(id);
}

// ---------------------------------------------------------------------------
// loadClientACL
// ---------------------------------------------------------------------------

describe('loadClientACL', () => {
  test('hides ACL editor when no client is selected', async () => {
    document.getElementById('aclClientSelect').value = '';
    document.getElementById('aclEditor').classList.remove('hidden');

    await global.loadClientACL();

    expect(document.getElementById('aclEditor').classList.contains('hidden')).toBe(true);
  });

  test('shows ACL editor after loading permissions', async () => {
    selectACLClient(5);
    mockFn('apiCall').mockResolvedValue(makeACL());

    await global.loadClientACL();

    expect(document.getElementById('aclEditor').classList.contains('hidden')).toBe(false);
  });

  test('populates is_admin checkbox from API response', async () => {
    selectACLClient(5);
    mockFn('apiCall').mockResolvedValue(makeACL({ is_admin: true }));

    await global.loadClientACL();

    expect(document.getElementById('aclIsAdmin').checked).toBe(true);
  });

  test('populates can_escalate checkbox from API response', async () => {
    selectACLClient(5);
    mockFn('apiCall').mockResolvedValue(makeACL({ can_escalate: true }));

    await global.loadClientACL();

    expect(document.getElementById('aclCanEscalate').checked).toBe(true);
  });

  test('populates can_propagate checkbox from API response', async () => {
    selectACLClient(5);
    mockFn('apiCall').mockResolvedValue(makeACL({ can_propagate: true }));

    await global.loadClientACL();

    expect(document.getElementById('aclCanPropagate').checked).toBe(true);
  });

  test('populates allowed_types textarea', async () => {
    selectACLClient(5);
    mockFn('apiCall').mockResolvedValue(makeACL({ allowed_types: ['recognizer_loop:utterance', 'speak'] }));

    await global.loadClientACL();

    const val = document.getElementById('aclAllowedTypes').value;
    expect(val).toContain('recognizer_loop:utterance');
    expect(val).toContain('speak');
  });

  test('populates skill_blacklist textarea', async () => {
    selectACLClient(5);
    mockFn('apiCall').mockResolvedValue(makeACL({ skill_blacklist: ['ovos-skill-dangerous'] }));

    await global.loadClientACL();

    expect(document.getElementById('aclSkillBlacklist').value).toContain('ovos-skill-dangerous');
  });

  test('shows error toast on API failure', async () => {
    selectACLClient(5);
    const showToast = mockFn('showToast');
    mockFn('apiCall').mockRejectedValue(new Error('Network error'));

    await global.loadClientACL();

    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('Network error'), 'error');
    expect(document.getElementById('aclEditor').classList.contains('hidden')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// saveClientACL
// ---------------------------------------------------------------------------

describe('saveClientACL', () => {
  let apiCall, showToast;

  beforeEach(() => {
    apiCall = mockFn('apiCall');
    showToast = mockFn('showToast');
    setACLClientId('7');
  });

  test('PUTs to /clients/{id}/acl with correct payload', async () => {
    apiCall.mockResolvedValue({});
    document.getElementById('aclIsAdmin').checked = true;
    document.getElementById('aclCanEscalate').checked = false;
    document.getElementById('aclCanPropagate').checked = true;
    document.getElementById('aclAllowedTypes').value = 'speak\nrecognizer_loop:utterance';
    document.getElementById('aclSkillBlacklist').value = '';
    document.getElementById('aclIntentBlacklist').value = '';

    await global.saveClientACL();

    expect(apiCall).toHaveBeenCalledWith('/clients/7/acl', 'PUT', {
      client_id: 7,
      is_admin: true,
      can_escalate: false,
      can_propagate: true,
      allowed_types: ['speak', 'recognizer_loop:utterance'],
      skill_blacklist: [],
      intent_blacklist: [],
    });
  });

  test('sends empty arrays when textareas are blank', async () => {
    apiCall.mockResolvedValue({});
    document.getElementById('aclAllowedTypes').value = '';
    document.getElementById('aclSkillBlacklist').value = '';
    document.getElementById('aclIntentBlacklist').value = '';

    await global.saveClientACL();

    const call = apiCall.mock.calls[0];
    expect(call[2].allowed_types).toEqual([]);
    expect(call[2].skill_blacklist).toEqual([]);
    expect(call[2].intent_blacklist).toEqual([]);
  });

  test('filters blank lines in textareas', async () => {
    apiCall.mockResolvedValue({});
    document.getElementById('aclAllowedTypes').value = 'speak\n\nrecognizer_loop:utterance\n';
    document.getElementById('aclSkillBlacklist').value = '';
    document.getElementById('aclIntentBlacklist').value = '';

    await global.saveClientACL();

    const call = apiCall.mock.calls[0];
    expect(call[2].allowed_types).toEqual(['speak', 'recognizer_loop:utterance']);
  });

  test('shows success toast on save', async () => {
    apiCall.mockResolvedValue({});
    document.getElementById('aclAllowedTypes').value = '';
    document.getElementById('aclSkillBlacklist').value = '';
    document.getElementById('aclIntentBlacklist').value = '';

    await global.saveClientACL();

    expect(showToast).toHaveBeenCalledWith('ACL updated successfully');
  });

  test('shows error toast on API failure', async () => {
    apiCall.mockRejectedValue(new Error('Conflict'));
    document.getElementById('aclAllowedTypes').value = '';
    document.getElementById('aclSkillBlacklist').value = '';
    document.getElementById('aclIntentBlacklist').value = '';

    await global.saveClientACL();

    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('Conflict'), 'error');
  });

  test('does nothing when currentACLClientId is null', async () => {
    setACLClientId(null);

    await global.saveClientACL();

    expect(apiCall).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// loadACLPage — integration: populates client dropdown
// ---------------------------------------------------------------------------

describe('loadACLPage', () => {
  test('populates aclClientSelect with active clients', async () => {
    let callCount = 0;
    mockFn('apiCall').mockImplementation(() => {
      callCount++;
      if (callCount === 1) return Promise.resolve([makeClient({ client_id: 10, name: 'Device1' })]);
      return Promise.resolve({ templates: [], common_messages: [], common_skills: [], common_intents: [] });
    });
    mockFn('renderACLTemplates');
    mockFn('renderQuickAddFromConfig');

    await global.loadACLPage();

    const select = document.getElementById('aclClientSelect');
    expect(select.querySelector('option[value="10"]')).not.toBeNull();
  });

  test('shows error toast when API fails', async () => {
    const showToast = mockFn('showToast');
    mockFn('apiCall').mockRejectedValue(new Error('Network error'));

    await global.loadACLPage();

    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('Failed to load ACL page'), 'error');
  });
});

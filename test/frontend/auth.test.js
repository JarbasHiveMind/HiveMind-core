/**
 * @jest-environment jsdom
 *
 * Unit tests for the auth flow in app.js.
 *
 * Covers:
 *   - attemptLogin() success path — sets sessionStorage, shows app
 *   - attemptLogin() failure path (401) — shows error, no sessionStorage written
 *   - apiCall() 401 trigger — calls logout()
 *   - logout() — clears sessionStorage, shows login screen
 */

'use strict';

const { evalApp, resetDom, mockFn, readState } = require('./helpers/setup');

// ---------------------------------------------------------------------------
// Suite setup
// ---------------------------------------------------------------------------

beforeAll(() => evalApp());
beforeEach(() => resetDom());

// ---------------------------------------------------------------------------
// Helper: build a minimal fetch mock response
// ---------------------------------------------------------------------------

function makeFetchResponse(status, body = {}) {
  return Promise.resolve({
    status,
    ok: status >= 200 && status < 300,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  });
}

// ---------------------------------------------------------------------------
// attemptLogin — success
// ---------------------------------------------------------------------------

describe('attemptLogin — success', () => {
  test('stores credentials in sessionStorage on successful login', async () => {
    // Mock fetch: /api/config → 200, /api/health → {status:'ok'}
    global.fetch = jest.fn((url) => {
      if (url.includes('/api/config')) return makeFetchResponse(200, {});
      if (url.includes('/api/health')) return makeFetchResponse(200, { status: 'ok' });
      return makeFetchResponse(200, {});
    });

    // Prime auth object via the login form
    document.getElementById('username').value = 'admin';
    document.getElementById('password').value = 'secret';
    mockFn('navigate');
    mockFn('startHealthCheck');

    await global.login();

    expect(global.sessionStorage.getItem('hm_username')).toBe('admin');
    expect(global.sessionStorage.getItem('hm_password')).toBe('secret');
  });

  test('shows app element after successful login', async () => {
    global.fetch = jest.fn((url) => {
      if (url.includes('/api/config')) return makeFetchResponse(200, {});
      if (url.includes('/api/health')) return makeFetchResponse(200, { status: 'ok' });
      return makeFetchResponse(200, {});
    });

    document.getElementById('username').value = 'admin';
    document.getElementById('password').value = 'pass';
    mockFn('navigate');
    mockFn('startHealthCheck');

    await global.login();

    expect(document.getElementById('app').classList.contains('active')).toBe(true);
  });

  test('hides login screen after successful login', async () => {
    global.fetch = jest.fn((url) => {
      if (url.includes('/api/config')) return makeFetchResponse(200, {});
      if (url.includes('/api/health')) return makeFetchResponse(200, { status: 'ok' });
      return makeFetchResponse(200, {});
    });

    document.getElementById('loginScreen').classList.remove('hidden');
    document.getElementById('username').value = 'admin';
    document.getElementById('password').value = 'pass';
    mockFn('navigate');
    mockFn('startHealthCheck');

    await global.login();

    expect(document.getElementById('loginScreen').classList.contains('hidden')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// attemptLogin — failure
// ---------------------------------------------------------------------------

describe('attemptLogin — failure', () => {
  test('shows login error on 401', async () => {
    global.fetch = jest.fn(() => makeFetchResponse(401, {}));

    document.getElementById('username').value = 'admin';
    document.getElementById('password').value = 'wrong';

    await global.login();

    expect(document.getElementById('loginError').classList.contains('hidden')).toBe(false);
    expect(document.getElementById('loginError').textContent).toBe('Invalid credentials');
  });

  test('does not write sessionStorage on 401', async () => {
    global.fetch = jest.fn(() => makeFetchResponse(401, {}));

    document.getElementById('username').value = 'admin';
    document.getElementById('password').value = 'wrong';

    await global.login();

    expect(global.sessionStorage.getItem('hm_username')).toBeNull();
    expect(global.sessionStorage.getItem('hm_password')).toBeNull();
  });

  test('shows error message on server error (500)', async () => {
    global.fetch = jest.fn(() => makeFetchResponse(500, {}));

    document.getElementById('username').value = 'admin';
    document.getElementById('password').value = 'pass';

    await global.login();

    expect(document.getElementById('loginError').classList.contains('hidden')).toBe(false);
  });

  test('shows error on network exception', async () => {
    global.fetch = jest.fn(() => Promise.reject(new Error('Network down')));

    document.getElementById('username').value = 'admin';
    document.getElementById('password').value = 'pass';

    await global.login();

    expect(document.getElementById('loginError').classList.contains('hidden')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// apiCall() 401 — triggers logout
// ---------------------------------------------------------------------------

describe('apiCall — 401 triggers logout', () => {
  test('calls logout when API returns 401', async () => {
    global.fetch = jest.fn(() => makeFetchResponse(401, {}));
    const logout = mockFn('logout');

    try {
      await global.apiCall('/some/endpoint');
    } catch (_) {
      // expected — Unauthorized throws
    }

    expect(logout).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// logout()
// ---------------------------------------------------------------------------

describe('logout', () => {
  test('removes hm_username and hm_password from sessionStorage', () => {
    global.sessionStorage.setItem('hm_username', 'admin');
    global.sessionStorage.setItem('hm_password', 'secret');

    mockFn('stopHealthCheck');

    global.logout();

    expect(global.sessionStorage.getItem('hm_username')).toBeNull();
    expect(global.sessionStorage.getItem('hm_password')).toBeNull();
  });

  test('shows login screen', () => {
    mockFn('stopHealthCheck');
    document.getElementById('loginScreen').classList.add('hidden');

    global.logout();

    expect(document.getElementById('loginScreen').classList.contains('hidden')).toBe(false);
  });

  test('hides app', () => {
    mockFn('stopHealthCheck');
    document.getElementById('app').classList.add('active');

    global.logout();

    expect(document.getElementById('app').classList.contains('active')).toBe(false);
  });

  test('does not remove theme from localStorage', () => {
    global.localStorage.setItem('theme', 'dark');
    mockFn('stopHealthCheck');

    global.logout();

    expect(global.localStorage.getItem('theme')).toBe('dark');
  });
});

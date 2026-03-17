/**
 * @jest-environment jsdom
 *
 * Unit tests for the client management UI in app.js.
 *
 * Covers:
 *   - renderClientsTable() with mocked client list
 *   - filterClients() by search term
 *   - showAddClientModal() resets form and opens modal
 *   - addClient() — POST payload shape
 *   - deleteClient() — confirm → DELETE request
 */

'use strict';

const { evalApp, resetDom, mockFn, readState, setClientState } = require('./helpers/setup');

// ---------------------------------------------------------------------------
// Suite setup
// ---------------------------------------------------------------------------

beforeAll(() => evalApp());
beforeEach(() => resetDom());

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeClient(overrides = {}) {
  return {
    client_id: 1,
    name: 'TestClient',
    api_key: 'abcdef1234567890abcdef12',
    is_admin: false,
    can_escalate: false,
    can_propagate: false,
    revoked: false,
    ...overrides,
  };
}

/**
 * Prime allClients and filteredClients state variables.
 */
function setClients(clients) {
  setClientState(clients);
}

// ---------------------------------------------------------------------------
// renderClientsTable
// ---------------------------------------------------------------------------

describe('renderClientsTable', () => {
  test('shows no-clients message when list is empty', () => {
    setClients([]);
    global.renderClientsTable();
    expect(document.getElementById('clientsTable').innerHTML).toContain('No clients found');
  });

  test('renders one row per client', () => {
    setClients([
      makeClient({ client_id: 1, name: 'Alice' }),
      makeClient({ client_id: 2, name: 'Bob' }),
    ]);
    global.renderClientsTable();

    const html = document.getElementById('clientsTable').innerHTML;
    expect(html).toContain('Alice');
    expect(html).toContain('Bob');
  });

  test('shows revoked style for revoked client', () => {
    setClients([makeClient({ name: 'RevokedClient', revoked: true })]);
    global.renderClientsTable();

    const html = document.getElementById('clientsTable').innerHTML;
    expect(html).toContain('Revoked');
  });

  test('shows admin badge for admin client', () => {
    setClients([makeClient({ is_admin: true })]);
    global.renderClientsTable();
    expect(document.getElementById('clientsTable').innerHTML).toContain('badge-success');
  });

  test('updates pagination info text', () => {
    setClients([makeClient({ client_id: 1 }), makeClient({ client_id: 2 })]);
    global.renderClientsTable();
    expect(document.getElementById('paginationInfo').textContent).toContain('1');
    expect(document.getElementById('paginationInfo').textContent).toContain('2');
  });

  test('disables prevBtn on first page', () => {
    setClients([makeClient()]);
    global.renderClientsTable();
    expect(document.getElementById('prevBtn').disabled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// filterClients
// ---------------------------------------------------------------------------

describe('filterClients', () => {
  beforeEach(() => {
    setClients([
      makeClient({ client_id: 1, name: 'AliceAdmin', api_key: 'key0000000000000000000001', is_admin: true }),
      makeClient({ client_id: 2, name: 'BobUser', api_key: 'key0000000000000000000002', is_admin: false }),
      makeClient({ client_id: 3, name: 'CharlieEscalate', api_key: 'key0000000000000000000003', can_escalate: true }),
    ]);
  });

  test('filters by name substring (case-insensitive)', () => {
    document.getElementById('clientSearch').value = 'alice';
    document.getElementById('clientFilter').value = '';
    global.filterClients();

    const html = document.getElementById('clientsTable').innerHTML;
    expect(html).toContain('AliceAdmin');
    expect(html).not.toContain('BobUser');
  });

  test('filter by admin shows only admin clients', () => {
    document.getElementById('clientSearch').value = '';
    // Add option to select element
    const sel = document.getElementById('clientFilter');
    const opt = document.createElement('option');
    opt.value = 'admin';
    sel.appendChild(opt);
    sel.value = 'admin';
    global.filterClients();

    const html = document.getElementById('clientsTable').innerHTML;
    expect(html).toContain('AliceAdmin');
    expect(html).not.toContain('BobUser');
  });

  test('empty search returns all clients', () => {
    document.getElementById('clientSearch').value = '';
    document.getElementById('clientFilter').value = '';
    global.filterClients();

    const html = document.getElementById('clientsTable').innerHTML;
    expect(html).toContain('AliceAdmin');
    expect(html).toContain('BobUser');
    expect(html).toContain('CharlieEscalate');
  });

  test('resets to page 1 after filtering', () => {
    setClientState(undefined, 3); // set currentPage = 3 without changing clients
    document.getElementById('clientSearch').value = 'alice';
    document.getElementById('clientFilter').value = '';
    global.filterClients();
    expect(global._testReadClientState().currentPage).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// showAddClientModal
// ---------------------------------------------------------------------------

describe('showAddClientModal', () => {
  test('opens the modal', () => {
    global.showAddClientModal();
    expect(document.getElementById('addClientModal').classList.contains('active')).toBe(true);
  });

  test('clears the name input', () => {
    document.getElementById('newClientName').value = 'old name';
    global.showAddClientModal();
    expect(document.getElementById('newClientName').value).toBe('');
  });
});

// ---------------------------------------------------------------------------
// addClient (POST payload)
// ---------------------------------------------------------------------------

describe('addClient', () => {
  let showToast, closeAddClientModal, loadClients;

  beforeEach(() => {
    showToast = mockFn('showToast');
    closeAddClientModal = mockFn('closeAddClientModal');
    loadClients = mockFn('loadClients');
  });

  test('POSTs to /clients with correct name payload', async () => {
    const apiCall = mockFn('apiCall');
    apiCall.mockResolvedValue({});
    document.getElementById('newClientName').value = 'NewDevice';

    await global.addClient();

    expect(apiCall).toHaveBeenCalledWith('/clients', 'POST', { name: 'NewDevice' });
    expect(closeAddClientModal).toHaveBeenCalled();
    expect(loadClients).toHaveBeenCalled();
  });

  test('shows error when name is empty', async () => {
    const apiCall = mockFn('apiCall');
    document.getElementById('newClientName').value = '   ';

    await global.addClient();

    expect(showToast).toHaveBeenCalledWith('Please enter a client name', 'error');
    expect(apiCall).not.toHaveBeenCalled();
  });

  test('shows error toast on API failure', async () => {
    mockFn('apiCall').mockRejectedValue(new Error('Conflict'));
    document.getElementById('newClientName').value = 'Bot';

    await global.addClient();

    expect(showToast).toHaveBeenCalledWith('Failed to add client', 'error');
  });
});

// ---------------------------------------------------------------------------
// deleteClient
// ---------------------------------------------------------------------------

describe('deleteClient', () => {
  let showToast, loadClients;

  beforeEach(() => {
    showToast = mockFn('showToast');
    loadClients = mockFn('loadClients');
  });

  test('calls DELETE /clients/{id} after confirm', async () => {
    const apiCall = mockFn('apiCall');
    apiCall.mockResolvedValue({});
    mockFn('showConfirmModal').mockImplementation((title, msg, cb) => cb());

    await global.deleteClient(42);

    expect(apiCall).toHaveBeenCalledWith('/clients/42', 'DELETE');
    expect(loadClients).toHaveBeenCalled();
  });

  test('shows success toast after delete', async () => {
    mockFn('apiCall').mockResolvedValue({});
    mockFn('showConfirmModal').mockImplementation((title, msg, cb) => cb());

    await global.deleteClient(1);

    expect(showToast).toHaveBeenCalledWith('Client deleted');
  });

  test('shows error toast on API failure', async () => {
    mockFn('apiCall').mockRejectedValue(new Error('Not found'));
    mockFn('showConfirmModal').mockImplementation((title, msg, cb) => cb());

    await global.deleteClient(99);

    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('Not found'), 'error');
  });
});

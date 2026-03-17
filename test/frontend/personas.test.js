/**
 * @jest-environment jsdom
 *
 * Unit tests for the personas UI in app.js.
 *
 * Covers:
 *   - renderPersonasList() — card HTML structure
 *   - showCreatePersonaModal() — resets state, clears form
 *   - editPersona() — populates form from existing persona data
 *   - savePersona() — valid solvers → correct POST payload
 *   - savePersona() — no solvers selected → shows error, no POST
 *   - toggleSolver() — adds/removes from selectedSolvers
 *   - _getSolverSchema() — known and unknown plugins
 */

'use strict';

const { evalApp, resetDom, mockFn, readState, setPersonaState } = require('./helpers/setup');

// ---------------------------------------------------------------------------
// Suite setup
// ---------------------------------------------------------------------------

beforeAll(() => evalApp());
beforeEach(() => resetDom());

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePersona(overrides = {}) {
  return {
    name: 'TestBot',
    description: 'A test persona',
    solvers: ['ovos-solver-YesNo-plugin'],
    memory_module: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// renderPersonasList
// ---------------------------------------------------------------------------

describe('renderPersonasList', () => {
  test('shows empty-state message when list is empty', () => {
    global.renderPersonasList([]);
    expect(document.getElementById('personasList').innerHTML).toContain('No personas created yet');
  });

  test('renders one card per persona', () => {
    global.renderPersonasList([
      makePersona({ name: 'Alice' }),
      makePersona({ name: 'Bob' }),
    ]);

    const html = document.getElementById('personasList').innerHTML;
    expect(html).toContain('Alice');
    expect(html).toContain('Bob');
  });

  test('renders persona description in card', () => {
    global.renderPersonasList([makePersona({ description: 'My special bot' })]);
    expect(document.getElementById('personasList').innerHTML).toContain('My special bot');
  });

  test('renders solver count', () => {
    global.renderPersonasList([makePersona({ solvers: ['a', 'b', 'c'] })]);
    expect(document.getElementById('personasList').innerHTML).toContain('3 solver(s)');
  });

  test('escapes HTML in persona name display text', () => {
    global.renderPersonasList([makePersona({ name: '<b>xss</b>' })]);
    // The displayed name div should have escaped text, not a raw <b> element
    const container = document.getElementById('personasList');
    // The bold element should NOT be rendered as a child element inside the name div
    const nameDivs = container.querySelectorAll('div[style*="font-weight: 600"]');
    const nameDiv = nameDivs[0];
    // textContent should show the literal angle brackets, not rendered HTML
    expect(nameDiv.textContent.trim()).toContain('<b>xss</b>');
  });

  test('renders edit and delete buttons for each persona', () => {
    global.renderPersonasList([makePersona({ name: 'MyBot' })]);
    const html = document.getElementById('personasList').innerHTML;
    expect(html).toContain("editPersona('MyBot')");
    expect(html).toContain("deletePersona('MyBot')");
  });
});

// ---------------------------------------------------------------------------
// showCreatePersonaModal
// ---------------------------------------------------------------------------

describe('showCreatePersonaModal', () => {
  beforeEach(() => {
    // loadSolverPluginsForPersona makes an API call; stub it out
    mockFn('loadSolverPluginsForPersona');
  });

  test('opens the create modal', () => {
    global.showCreatePersonaModal();
    expect(document.getElementById('createPersonaModal').classList.contains('active')).toBe(true);
  });

  test('clears editPersonaName (create mode)', () => {
    document.getElementById('editPersonaName').value = 'old-name';
    global.showCreatePersonaModal();
    expect(document.getElementById('editPersonaName').value).toBe('');
  });

  test('clears personaName input', () => {
    document.getElementById('personaName').value = 'prev';
    global.showCreatePersonaModal();
    expect(document.getElementById('personaName').value).toBe('');
  });

  test('clears personaDescription textarea', () => {
    document.getElementById('personaDescription').value = 'old description';
    global.showCreatePersonaModal();
    expect(document.getElementById('personaDescription').value).toBe('');
  });

  test('resets selectedSolvers to empty array', () => {
    setPersonaState({ solvers: ['some-solver'] });
    global.showCreatePersonaModal();
    expect(global._testReadPersonaState().selectedSolvers).toEqual([]);
  });

  test('sets modal title to create', () => {
    global.showCreatePersonaModal();
    expect(document.getElementById('createPersonaModalTitle').textContent).toBe('👤 Create Persona');
  });

  test('hides status div', () => {
    document.getElementById('createPersonaStatus').classList.remove('hidden');
    global.showCreatePersonaModal();
    expect(document.getElementById('createPersonaStatus').classList.contains('hidden')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// editPersona
// ---------------------------------------------------------------------------

describe('editPersona', () => {
  test('populates form fields from persona JSON', async () => {
    mockFn('loadSolverPluginsForPersona').mockResolvedValue();
    mockFn('renderSelectedSolvers');
    mockFn('renderSolverConfigSections');

    const apiCall = mockFn('apiCall');
    apiCall.mockResolvedValue(makePersona({
      name: 'MyBot',
      description: 'Bot description',
      solvers: ['ovos-solver-YesNo-plugin'],
      memory_module: 'ovos-agents-short-term-memory-plugin',
    }));

    await global.editPersona('MyBot');

    expect(document.getElementById('personaName').value).toBe('MyBot');
    expect(document.getElementById('editPersonaName').value).toBe('MyBot');
    expect(document.getElementById('personaDescription').value).toBe('Bot description');
    expect(document.getElementById('createPersonaModal').classList.contains('active')).toBe(true);
  });

  test('sets modal title to edit', async () => {
    mockFn('loadSolverPluginsForPersona').mockResolvedValue();
    mockFn('renderSelectedSolvers');
    mockFn('renderSolverConfigSections');
    mockFn('apiCall').mockResolvedValue(makePersona({ name: 'MyBot' }));

    await global.editPersona('MyBot');

    expect(document.getElementById('createPersonaModalTitle').textContent).toBe('👤 Edit Persona');
  });

  test('sets selectedSolvers from persona data', async () => {
    mockFn('loadSolverPluginsForPersona').mockResolvedValue();
    mockFn('renderSelectedSolvers');
    mockFn('renderSolverConfigSections');
    mockFn('apiCall').mockResolvedValue(makePersona({
      solvers: ['solver-a', 'solver-b'],
    }));

    await global.editPersona('MyBot');

    expect(global._testReadPersonaState().selectedSolvers).toEqual(['solver-a', 'solver-b']);
  });

  test('shows error toast on API failure', async () => {
    const showToast = mockFn('showToast');
    mockFn('apiCall').mockRejectedValue(new Error('Not found'));

    await global.editPersona('missing');

    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('Not found'), 'error');
  });
});

// ---------------------------------------------------------------------------
// savePersona — valid POST payload
// ---------------------------------------------------------------------------

describe('savePersona', () => {
  let apiCall, showToast, closeCreatePersonaModal, loadPersonasPage;

  beforeEach(() => {
    apiCall = mockFn('apiCall');
    showToast = mockFn('showToast');
    closeCreatePersonaModal = mockFn('closeCreatePersonaModal');
    loadPersonasPage = mockFn('loadPersonasPage');
  });

  test('POSTs to /personas for a new persona with correct payload', async () => {
    document.getElementById('editPersonaName').value = '';
    document.getElementById('personaName').value = 'NewBot';
    document.getElementById('personaDescription').value = 'My bot';
    setPersonaState({ solvers: ['ovos-solver-YesNo-plugin'], configs: {} });
    apiCall.mockResolvedValue({});

    await global.savePersona();

    expect(apiCall).toHaveBeenCalledWith('/personas', 'POST', expect.objectContaining({
      name: 'NewBot',
      description: 'My bot',
      solvers: ['ovos-solver-YesNo-plugin'],
    }));
    expect(closeCreatePersonaModal).toHaveBeenCalled();
    expect(loadPersonasPage).toHaveBeenCalled();
  });

  test('PUTs to /personas/{name} when editing', async () => {
    document.getElementById('editPersonaName').value = 'ExistingBot';
    document.getElementById('personaName').value = 'ExistingBot';
    setPersonaState({ solvers: ['ovos-solver-YesNo-plugin'], configs: {} });
    apiCall.mockResolvedValue({});

    await global.savePersona();

    expect(apiCall).toHaveBeenCalledWith('/personas/ExistingBot', 'PUT', expect.objectContaining({
      name: 'ExistingBot',
    }));
  });

  test('shows error when persona name is empty', async () => {
    document.getElementById('personaName').value = '';
    document.getElementById('editPersonaName').value = '';

    await global.savePersona();

    expect(showToast).toHaveBeenCalledWith('Persona name is required', 'error');
    expect(apiCall).not.toHaveBeenCalled();
  });

  test('shows error when no solvers selected', async () => {
    document.getElementById('personaName').value = 'MyBot';
    document.getElementById('editPersonaName').value = '';
    setPersonaState({ solvers: [], configs: {} });

    await global.savePersona();

    expect(showToast).toHaveBeenCalledWith('At least one solver plugin must be selected', 'error');
    expect(apiCall).not.toHaveBeenCalled();
  });

  test('shows error toast on API failure', async () => {
    document.getElementById('personaName').value = 'Bot';
    document.getElementById('editPersonaName').value = '';
    setPersonaState({ solvers: ['ovos-solver-YesNo-plugin'], configs: {} });
    apiCall.mockRejectedValue(new Error('Server error'));

    await global.savePersona();

    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('Server error'), 'error');
  });
});

// ---------------------------------------------------------------------------
// toggleSolver
// ---------------------------------------------------------------------------

describe('toggleSolver', () => {
  beforeEach(() => {
    // Reset state
    setPersonaState({ solvers: [], configs: {} });
    mockFn('renderSelectedSolvers');
    mockFn('renderSolverConfigSections');
  });

  test('adds solver entry point to selectedSolvers when not present', () => {
    global.toggleSolver('ovos-solver-YesNo-plugin', 'Yes/No');
    expect(global._testReadPersonaState().selectedSolvers).toContain('ovos-solver-YesNo-plugin');
  });

  test('removes solver entry point from selectedSolvers when already present', () => {
    setPersonaState({ solvers: ['ovos-solver-YesNo-plugin'], configs: {} });
    global.toggleSolver('ovos-solver-YesNo-plugin', 'Yes/No');
    expect(global._testReadPersonaState().selectedSolvers).not.toContain('ovos-solver-YesNo-plugin');
  });

  test('removes solver config when solver is deselected', () => {
    setPersonaState({
      solvers: ['ovos-solver-YesNo-plugin'],
      configs: { 'ovos-solver-YesNo-plugin': { key: 'val' } },
    });

    global.toggleSolver('ovos-solver-YesNo-plugin', 'Yes/No');

    const { solverConfigs } = global._testReadPersonaState();
    expect(solverConfigs['ovos-solver-YesNo-plugin']).toBeUndefined();
  });

  test('multiple toggles result in correct selection list', () => {
    global.toggleSolver('solver-a', 'A');
    global.toggleSolver('solver-b', 'B');
    global.toggleSolver('solver-a', 'A'); // remove

    expect(global._testReadPersonaState().selectedSolvers).toEqual(['solver-b']);
  });
});

// ---------------------------------------------------------------------------
// _getSolverSchema
// ---------------------------------------------------------------------------

describe('_getSolverSchema', () => {
  test('returns schema for exact match (ovos-chat-openai-plugin)', () => {
    const schema = global._getSolverSchema('ovos-chat-openai-plugin');
    expect(Array.isArray(schema)).toBe(true);
    expect(schema.some(f => f.key === 'key')).toBe(true); // API key field
  });

  test('returns openai schema for ollama via keyword matching', () => {
    const schema = global._getSolverSchema('ovos-chat-ollama-plugin');
    expect(Array.isArray(schema)).toBe(true);
    expect(schema.some(f => f.key === 'api_url')).toBe(true);
  });

  test('returns claude schema for anthropic keyword', () => {
    const schema = global._getSolverSchema('ovos-chat-claude-plugin');
    expect(Array.isArray(schema)).toBe(true);
    expect(schema.some(f => f.key === 'api_key')).toBe(true);
  });

  test('returns empty array for YesNo plugin (no config needed)', () => {
    const schema = global._getSolverSchema('ovos-solver-YesNo-plugin');
    expect(schema).toEqual([]);
  });

  test('returns null for unknown plugins', () => {
    const schema = global._getSolverSchema('some-unknown-solver-xyz');
    expect(schema).toBeNull();
  });
});

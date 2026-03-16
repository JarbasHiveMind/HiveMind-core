/**
 * Test harness for hivemind-core admin UI (app.js).
 *
 * app.js is a vanilla JS script where:
 *   - `function foo()` declarations are global
 *   - `let _dbProfiles` etc. live in the script's lexical scope
 *
 * Strategy:
 *   1. We call `window.eval(src)` once (in beforeAll) so the script runs in
 *      jsdom's global scope.  In this mode, `function` declarations are
 *      visible as globals AND `let` declarations live in the global lexical
 *      environment — crucially, they can be read/written by subsequent
 *      `window.eval("_dbProfiles = ...")` calls.
 *   2. resetDom() rebuilds the DOM and resets the state variables via
 *      window.eval for each test.
 *
 * Usage:
 *
 *   const { evalApp, resetDom, setState } = require('../helpers/setup');
 *   beforeAll(() => evalApp());
 *   beforeEach(() => resetDom());
 *
 *   // To prime state variables before rendering tests:
 *   setState({ profiles: {...}, backends: [...], activeName: 'default' });
 */

'use strict';

const fs = require('fs');
const path = require('path');

const APP_JS_PATH = path.resolve(
  __dirname,
  '../../../hivemind_core/admin/static/js/app.js'
);

const MIN_HTML = `
<div id="loginScreen"></div>
<div id="loginError"></div>
<div id="app" style="display:none;"></div>
<input id="username" /><input id="password" />
<select id="themeSelect"></select>

<!-- Database profiles page -->
<div id="activeProfileBanner" style="display:none;"></div>
<span id="activeProfileNameLabel"></span>
<span id="activeProfileModuleLabel"></span>
<span id="activeDbBadge"></span>
<div id="databaseProfilesContainer"></div>
<div id="databaseBackendsContainer"></div>

<!-- Profile modal -->
<div id="profileModal"></div>
<h3 id="profileModalTitle"></h3>
<input id="profileEditName" type="hidden" />
<input id="profileName" />
<select id="profileModule"></select>
<div id="profileRedisSection" class="hidden"></div>
<input id="profileRedisHost" value="localhost" />
<input id="profileRedisPort" value="6379" />
<input id="profileRedisDb" value="0" />
<input id="profileRedisPassword" type="password" />
<div id="profileFileSection" class="hidden"></div>
<input id="profileFileSubfolder" value="hivemind-core" />
<input id="profileFileName" value="clients" />
<div id="profileTestStatus" class="validation-result hidden"></div>

<!-- Activate profile modal -->
<div id="activateProfileModal"></div>
<input id="activateProfileTarget" type="hidden" />
<strong id="activateProfileNameLabel"></strong>
<input id="migrateDataToggle" type="checkbox" checked />
<div id="activateProfileStatus" class="validation-result hidden"></div>

<!-- Restart modal -->
<div id="restartRequiredModal"></div>

<!-- Toast -->
<div id="toastContainer"></div>

<!-- Plugin disclaimer -->
<input id="pluginDisclaimerCheckbox" type="checkbox" />
<button id="installCustomPluginBtn"></button>

<!-- Clients page -->
<input id="clientSearch" type="text" />
<select id="clientFilter"></select>
<table><tbody id="clientsTable"></tbody></table>
<span id="paginationInfo"></span>
<button id="prevBtn"></button>
<button id="nextBtn"></button>

<!-- Add client modal -->
<div id="addClientModal"></div>
<input id="newClientName" />

<!-- Edit client modal -->
<div id="editClientModal"></div>
<input id="editClientId" type="hidden" />
<input id="editClientName" />
<input id="editClientApiKey" />
<input id="editClientPassword" type="password" />
<input id="editClientCryptoKey" />

<!-- Confirm modal -->
<div id="confirmModal"></div>
<h3 id="confirmTitle"></h3>
<div id="confirmMessage"></div>
<button id="confirmBtn"></button>

<!-- Personas page -->
<div id="personasList"></div>
<div id="activePersonaSection" class="hidden"></div>
<select id="activePersonaSelect"></select>

<!-- Persona modal -->
<div id="createPersonaModal"></div>
<h3 id="createPersonaModalTitle"></h3>
<input id="editPersonaName" type="hidden" />
<input id="personaName" />
<textarea id="personaDescription"></textarea>
<select id="personaMemoryModule"></select>
<div id="createPersonaStatus" class="validation-result hidden"></div>
<div id="personaSolverConfigContainer"></div>
<div id="personaAvailableSolvers"></div>
<div id="personaSelectedSolvers"></div>

<!-- ACL page -->
<select id="aclClientSelect"></select>
<div id="aclEditor" class="hidden"></div>
<input id="aclIsAdmin" type="checkbox" />
<input id="aclCanEscalate" type="checkbox" />
<input id="aclCanPropagate" type="checkbox" />
<textarea id="aclAllowedTypes"></textarea>
<textarea id="aclSkillBlacklist"></textarea>
<textarea id="aclIntentBlacklist"></textarea>
<div id="aclTemplatesContainer"></div>
`;

let _appLoaded = false;
/** Original function values cached after first evalApp(), keyed by name. */
const _originals = {};

/**
 * Evaluate app.js once in jsdom's global window scope.
 * Call from beforeAll().
 */
function evalApp() {
  if (_appLoaded) return;
  _appLoaded = true;

  _installStubs();
  document.body.innerHTML = MIN_HTML;

  const src = fs.readFileSync(APP_JS_PATH, 'utf8');
  // window.eval runs in the global (window) scope: `function` declarations
  // become globals; `let` declarations enter the global lexical environment
  // and can be re-assigned via subsequent window.eval() calls.
  window.eval(src); // eslint-disable-line no-eval

  // Cache all function values so resetDom() can restore them after mocking.
  const names = [...src.matchAll(/^\s*(?:async\s+)?function\s+(\w+)/gm)].map(m => m[1]);
  for (const name of names) {
    try {
      _originals[name] = window.eval(name); // eslint-disable-line no-eval
    } catch (_) { /* ignore unknown */ }
  }
}

/**
 * Reset DOM, stubs, state variables, and all mocked functions before each test.
 * Call from beforeEach().
 */
function resetDom() {
  document.body.innerHTML = MIN_HTML;
  _installStubs();

  // Reset state via the in-scope helper function (window.eval can't reach
  // let-vars from a prior eval's lexical environment).
  global._testSetState({}, [], null);

  // Restore any functions that were mocked in previous tests
  for (const [name, fn] of Object.entries(_originals)) {
    const tmpKey = `__orig_${name}`;
    global[tmpKey] = fn;
    window.eval(`${name} = ${tmpKey};`); // eslint-disable-line no-eval
  }
}

/**
 * Prime the module-level state variables (_dbProfiles, _dbBackends,
 * _dbActiveName) that app.js rendering functions read from.
 *
 * @param {object} opts
 * @param {object}  [opts.profiles={}]
 * @param {Array}   [opts.backends=[]]
 * @param {string|null} [opts.activeName=null]
 */
function setState({ profiles = {}, backends = [], activeName = null } = {}) {
  // Use the in-scope helper so we write into the same lexical environment
  // that app.js closures read from (window.eval can't reach prior let-vars).
  global._testSetState(profiles, backends, activeName);
}

/**
 * Prime persona module-level state (selectedSolvers, _solverConfigs).
 */
function setPersonaState({ solvers, configs } = {}) {
  global._testSetPersonaState(solvers, configs);
}

/**
 * Prime client module-level state (allClients, filteredClients, currentPage).
 */
function setClientState(clients, page) {
  global._testSetClientState(clients, page);
}

/**
 * Set currentACLClientId.
 */
function setACLClientId(id) {
  global._testSetACLClientId(id);
}

function _makeStorage() {
  return {
    _store: {},
    getItem(k) { return Object.prototype.hasOwnProperty.call(this._store, k) ? this._store[k] : null; },
    setItem(k, v) { this._store[k] = String(v); },
    removeItem(k) { delete this._store[k]; },
    clear() { this._store = {}; },
  };
}

function _installStubs() {
  const ls = _makeStorage();
  const ss = _makeStorage();
  // Replace both global.X AND window.X so that app.js (which reads window.sessionStorage
  // via plain `sessionStorage` identifier after eval) sees our stub.
  global.localStorage = ls;
  global.sessionStorage = ss;
  Object.defineProperty(window, 'localStorage', { value: ls, writable: true, configurable: true });
  Object.defineProperty(window, 'sessionStorage', { value: ss, writable: true, configurable: true });
  global.btoa = (s) => Buffer.from(s, 'binary').toString('base64');
  global.confirm = jest.fn(() => true);
  global.alert = jest.fn();
  global.fetch = jest.fn();
  global.setTimeout = jest.fn((fn) => fn());
}

/**
 * Install a jest.fn() mock for an internal app.js function by injecting it
 * into the global lexical scope via window.eval.
 *
 * Calling `global.showToast = jest.fn()` does NOT affect app.js internal
 * calls because they use a lexical lookup (not window property lookup).
 * This helper bridges that gap via a temporary `__mockN` global.
 *
 * @param {string} fnName  Name of the function to mock (e.g. 'showToast').
 * @returns {jest.Mock}
 */
let _mockSeq = 0;
function mockFn(fnName) {
  const tmpKey = `__appMock_${_mockSeq++}`;
  const mock = jest.fn();
  global[tmpKey] = mock;
  window.eval(`${fnName} = ${tmpKey};`); // eslint-disable-line no-eval
  return mock;
}

/**
 * Read a let-declared state variable from app.js's lexical scope.
 *
 * @param {string} varName  e.g. '_dbProfiles'
 * @returns {*}
 */
function readState(varName) {
  // eslint-disable-next-line no-eval
  return window.eval(varName);
}

module.exports = { evalApp, resetDom, setState, setPersonaState, setClientState, setACLClientId, mockFn, readState };

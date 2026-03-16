// State
        let auth = { username: '', password: '' };
        let currentPage = 1;
        let allClients = [];
        let filteredClients = [];
        let healthCheckInterval = null;
        const clientsPerPage = 10;

        // Database profiles state
        let _dbProfiles = {};
        let _dbBackends = [];
        let _dbActiveName = null;

        // Test-only: allows test harness to set closed-over state variables.
        // Called via global._testSetState() from Jest setup helpers.
        function _testSetState(profiles, backends, activeName) {
            _dbProfiles = profiles;
            _dbBackends = backends;
            _dbActiveName = activeName;
        }

        // Test-only: set persona module-level state (selectedSolvers, _solverConfigs, allClients, etc.)
        function _testSetPersonaState(solvers, configs) {
            selectedSolvers = solvers !== undefined ? solvers : selectedSolvers;
            _solverConfigs = configs !== undefined ? configs : _solverConfigs;
        }

        // Test-only: set client module-level state (pass undefined for clients/page to leave unchanged)
        function _testSetClientState(clients, page) {
            if (clients !== undefined) {
                allClients = clients || [];
                filteredClients = clients ? [...clients] : [];
            }
            if (page !== undefined) currentPage = page;
        }

        // Test-only: set currentACLClientId
        function _testSetACLClientId(id) {
            currentACLClientId = id;
        }

        // Test-only: read module-level state variables (lexical scope cannot be reached by window.eval)
        function _testReadPersonaState() {
            return { selectedSolvers: selectedSolvers, solverConfigs: _solverConfigs };
        }

        function _testReadClientState() {
            return { allClients: allClients, filteredClients: filteredClients, currentPage: currentPage };
        }

        // Initialize
        let _searchDebounce;
        document.addEventListener('DOMContentLoaded', () => {
            loadTheme();
            checkStoredAuth();

            // Add listener for plugin disclaimer checkbox
            const disclaimerCheckbox = document.getElementById('pluginDisclaimerCheckbox');
            if (disclaimerCheckbox) {
                disclaimerCheckbox.addEventListener('change', (e) => {
                    const btn = document.getElementById('installCustomPluginBtn');
                    if (btn) {
                        btn.disabled = !e.target.checked;
                        btn.style.opacity = e.target.checked ? '1' : '0.5';
                        btn.style.cursor = e.target.checked ? 'pointer' : 'not-allowed';
                    }
                });
            }

            // Debounced client search
            const searchInput = document.getElementById('clientSearch');
            if (searchInput) {
                searchInput.removeAttribute('oninput');
                searchInput.addEventListener('input', () => {
                    clearTimeout(_searchDebounce);
                    _searchDebounce = setTimeout(filterClients, 200);
                });
            }
        });

        // XSS protection: escape user-controlled strings before inserting into HTML.
        function escapeHtml(s) {
          return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
        }

        // Theme
        function loadTheme() {
            const saved = localStorage.getItem('theme') || 'dark';
            document.documentElement.setAttribute('data-theme', saved);
            updateThemeSelect(saved);
        }

        function setTheme(theme) {
            document.documentElement.setAttribute('data-theme', theme);
            localStorage.setItem('theme', theme);
            updateThemeSelect(theme);
        }

        function updateThemeSelect(theme) {
            const select = document.getElementById('themeSelect');
            if (select) select.value = theme;
        }

        // Auth
        function checkStoredAuth() {
            const username = sessionStorage.getItem('hm_username');
            const password = sessionStorage.getItem('hm_password');
            if (username && password) {
                auth = { username, password };
                document.getElementById('username').value = username;
                document.getElementById('password').value = password;
                attemptLogin();
            } else {
                showLoginScreen();
            }
        }

        async function login() {
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            auth = { username, password };
            await attemptLogin();
        }

        async function attemptLogin() {
            try {
                // Verify credentials against an authenticated endpoint
                const authHeader = 'Basic ' + btoa(auth.username + ':' + auth.password);
                const authResponse = await fetch('/api/config', {
                    headers: { 'Authorization': authHeader }
                });
                if (authResponse.status === 401) {
                    showLoginError('Invalid credentials');
                    return;
                }
                if (!authResponse.ok) {
                    showLoginError('Server error: ' + authResponse.status);
                    return;
                }

                // Store credentials only after confirmed valid
                sessionStorage.setItem('hm_username', auth.username);
                sessionStorage.setItem('hm_password', auth.password);

                hideLoginScreen();
                showApp();

                const health = await fetch('/api/health').then(r => r.json());
                if (health.status === 'degraded') {
                    await handleStartupError(health);
                } else {
                    navigate('dashboard');
                    startHealthCheck();
                }
            } catch (e) {
                showLoginError('Invalid credentials or server error');
            }
        }

        function logout() {
            auth = { username: '', password: '' };
            sessionStorage.removeItem('hm_username');
            sessionStorage.removeItem('hm_password');
            stopHealthCheck();
            hideApp();
            showLoginScreen();
        }

        function showLoginScreen() {
            document.getElementById('loginScreen').classList.remove('hidden');
        }

        function hideLoginScreen() {
            document.getElementById('loginScreen').classList.add('hidden');
        }

        function showApp() {
            document.getElementById('app').classList.add('active');
        }

        function hideApp() {
            document.getElementById('app').classList.remove('active');
        }

        function showLoginError(msg) {
            const el = document.getElementById('loginError');
            el.textContent = msg;
            el.classList.remove('hidden');
        }

        // Navigation
        function navigate(page) {
            // Update nav
            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
            document.querySelector(`[data-page="${page}"]`)?.classList.add('active');

            // Update title
            const titles = {
                dashboard: 'Dashboard',
                clients: 'Client Management',
                acl: 'Access Control Lists',
                personas: 'Personas',
                agents: 'Agent Protocol',
                database: 'Database Backend',
                network: 'Network Protocols',
                'voice-plugins': 'Voice Plugins',
                binary: 'Binary Protocol',
                encodings: 'Encodings & Ciphers'
            };
            document.getElementById('pageTitle').textContent = titles[page] || 'Dashboard';

            // Show page
            document.querySelectorAll('.page').forEach(el => el.classList.remove('active'));
            document.getElementById(page + 'Page').classList.add('active');

            // Load data
            if (page === 'dashboard') loadDashboard();
            if (page === 'clients') { currentPage = 1; loadClients(); }
            if (page === 'acl') loadACLPage();
            if (page === 'personas') loadPersonasPage();
            if (page === 'agents') loadAgentProtocolsPage();
            if (page === 'database') loadDatabasePage();
            if (page === 'network') loadNetworkPage();
            if (page === 'voice-plugins') loadVoicePluginsPage();
            if (page === 'binary') loadBinaryPage();
            if (page === 'encodings') loadEncodings();
        }

        // Health Check
        function startHealthCheck() {
            stopHealthCheck();
            updateHealthStatus();
            healthCheckInterval = setInterval(updateHealthStatus, 5000);
        }

        function stopHealthCheck() {
            if (healthCheckInterval) {
                clearInterval(healthCheckInterval);
                healthCheckInterval = null;
            }
        }

        async function updateHealthStatus() {
            try {
                const health = await fetch('/api/health').then(r => r.json());
                const statusEl = document.getElementById('connectionStatus');

                if (health.status === 'ok') {
                    statusEl.className = 'status-indicator status-online';
                    statusEl.innerHTML = '<span class="status-dot"></span><span>Connected</span>';
                } else if (health.status === 'degraded') {
                    statusEl.className = 'status-indicator status-degraded';
                    statusEl.innerHTML = '<span class="status-dot"></span><span>Degraded</span>';
                } else {
                    statusEl.className = 'status-indicator status-offline';
                    statusEl.innerHTML = '<span class="status-dot"></span><span>Disconnected</span>';
                }
            } catch (e) {
                const statusEl = document.getElementById('connectionStatus');
                statusEl.className = 'status-indicator status-offline';
                statusEl.innerHTML = '<span class="status-dot"></span><span>Disconnected</span>';
            }
        }

        // API
        async function apiCall(endpoint, method = 'GET', body = null) {
            const headers = {
                'Authorization': 'Basic ' + btoa(auth.username + ':' + auth.password)
            };
            if (body) {
                headers['Content-Type'] = 'application/json';
                body = JSON.stringify(body);
            }

            const response = await fetch('/api' + endpoint, { method, headers, body });

            if (response.status === 401) {
                logout();
                throw new Error('Unauthorized');
            }

            if (!response.ok) {
                const text = await response.text();
                throw new Error(`HTTP ${response.status}: ${text}`);
            }

            return response.json();
        }

        // Dashboard
        async function loadDashboard() {
            try {
                const [health, config] = await Promise.all([
                    fetch('/api/health').then(r => r.json()),
                    apiCall('/config')
                ]);

                // Update stat cards
                document.getElementById('statClients').textContent = health.total_clients || 0;
                document.getElementById('statConnections').textContent = health.active_connections || 0;
                document.getElementById('statProtocols').textContent = Object.keys(config.network_protocol || {}).length;
                document.getElementById('statVersion').textContent = health.version || 'Unknown';

                // Get all plugin counts from API
                const [sttPlugins, ttsPlugins, wwPlugins, vadPlugins, networkPlugins, agentPlugins, databasePlugins, binaryPlugins] = await Promise.all([
                    apiCall('/plugins/installed/ovos/stt').catch(() => []),
                    apiCall('/plugins/installed/ovos/tts').catch(() => []),
                    apiCall('/plugins/installed/ovos/ww').catch(() => []),
                    apiCall('/plugins/installed/ovos/vad').catch(() => []),
                    apiCall('/plugins/installed/hivemind/network').catch(() => []),
                    apiCall('/plugins/installed/hivemind/agent').catch(() => []),
                    apiCall('/plugins/installed/hivemind/database').catch(() => []),
                    apiCall('/plugins/installed/hivemind/binary').catch(() => [])
                ]);

                // Render active plugins (Database, Binary, Agent)
                renderActivePlugins(config);

                // Render plugin status grid with API counts
                renderPluginStatusGrid({
                    stt: sttPlugins.length,
                    tts: ttsPlugins.length,
                    ww: wwPlugins.length,
                    vad: vadPlugins.length,
                    network: networkPlugins.length,
                    agent: agentPlugins.length,
                    database: databasePlugins.length,
                    binary: binaryPlugins.length
                });

                // Render network configuration
                let html = '';
                for (const [name, cfg] of Object.entries(config.network_protocol || {})) {
                    html += `<div style="padding: 16px; background: var(--bg-secondary); border-radius: var(--radius-sm); margin-bottom: 12px;">
                        <strong style="color: var(--accent-primary);">${name}</strong>
                        <div style="margin-top: 8px; font-size: 13px; color: var(--text-secondary);">
                            Host: ${cfg.host || 'N/A'} | Port: ${cfg.port || 'N/A'} | SSL: ${cfg.ssl ? 'Yes' : 'No'}
                        </div>
                    </div>`;
                }
                document.getElementById('networkConfig').innerHTML = html || '<p style="color: var(--text-secondary);">No network protocols configured</p>';
            } catch (e) {
                showToast('Failed to load dashboard', 'error');
            }
        }

        // Render active plugins (Database, Binary Protocol, Agent)
        function renderActivePlugins(config) {
            const container = document.getElementById('activePluginsGrid');
            if (!container) return;

            const databaseModule = config.database?.module || 'Not configured';
            const binaryModule = config.binary_protocol?.module || 'Not enabled';
            const agentModule = config.agent_protocol?.module || 'Not configured';

            // Get binary protocol voice config if available
            const binaryConfig = binaryModule !== 'Not enabled' ? (config.binary_protocol[binaryModule] || {}) : {};
            const sttModule = binaryConfig.stt?.module || 'Not configured';
            const ttsModule = binaryConfig.tts?.module || 'Not configured';
            const wwName = binaryConfig.wake_word || 'Not configured';
            const wwModule = binaryConfig.hotwords?.[wwName]?.module || 'Not configured';
            const vadModule = binaryConfig.vad?.module || 'Not configured';

            let html = '';

            // Database
            html += `
                <div style="padding: 16px; background: var(--bg-secondary); border-radius: var(--radius-sm); border-left: 4px solid var(--accent-primary);">
                    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 8px;">
                        <span style="font-size: 24px;">🗄️</span>
                        <div>
                            <div style="font-weight: 600; font-size: 14px;">Database</div>
                            <div style="font-size: 11px; color: var(--text-secondary);">Client storage backend</div>
                        </div>
                    </div>
                    <div style="font-size: 12px; color: var(--text-primary); font-family: monospace; background: var(--bg-primary); padding: 8px; border-radius: 4px;">
                        ${databaseModule}
                    </div>
                </div>
            `;

            // Agent Protocol
            html += `
                <div style="padding: 16px; background: var(--bg-secondary); border-radius: var(--radius-sm); border-left: 4px solid var(--accent-success);">
                    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 8px;">
                        <span style="font-size: 24px;">🤖</span>
                        <div>
                            <div style="font-weight: 600; font-size: 14px;">Agent Protocol</div>
                            <div style="font-size: 11px; color: var(--text-secondary);">AI backend for message processing</div>
                        </div>
                    </div>
                    <div style="font-size: 12px; color: var(--text-primary); font-family: monospace; background: var(--bg-primary); padding: 8px; border-radius: 4px;">
                        ${agentModule}
                    </div>
                </div>
            `;

            // Binary Protocol
            html += `
                <div style="padding: 16px; background: var(--bg-secondary); border-radius: var(--radius-sm); border-left: 4px solid ${binaryModule !== 'Not enabled' ? 'var(--accent-warning)' : 'var(--border-color)'};">
                    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 8px;">
                        <span style="font-size: 24px;">📦</span>
                        <div>
                            <div style="font-weight: 600; font-size: 14px;">Binary Protocol</div>
                            <div style="font-size: 11px; color: var(--text-secondary);">Audio/binary data handling</div>
                        </div>
                    </div>
                    <div style="font-size: 12px; color: var(--text-primary); font-family: monospace; background: var(--bg-primary); padding: 8px; border-radius: 4px;">
                        ${binaryModule}
                    </div>
                    ${binaryModule !== 'Not enabled' ? `
                        <div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-color);">
                            <div style="font-size: 11px; color: var(--text-secondary); margin-bottom: 8px;">Voice Configuration:</div>
                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 11px;">
                                <div>
                                    <span style="color: var(--text-secondary);">STT:</span>
                                    <div style="font-family: monospace; color: var(--text-primary);">${sttModule}</div>
                                </div>
                                <div>
                                    <span style="color: var(--text-secondary);">TTS:</span>
                                    <div style="font-family: monospace; color: var(--text-primary);">${ttsModule}</div>
                                </div>
                                <div>
                                    <span style="color: var(--text-secondary);">Wake Word:</span>
                                    <div style="font-family: monospace; color: var(--text-primary);">${wwModule}</div>
                                </div>
                                <div>
                                    <span style="color: var(--text-secondary);">VAD:</span>
                                    <div style="font-family: monospace; color: var(--text-primary);">${vadModule}</div>
                                </div>
                            </div>
                        </div>
                    ` : ''}
                </div>
            `;

            container.innerHTML = html;
        }

        // Render plugin status grid on dashboard
        function renderPluginStatusGrid(counts) {
            const container = document.getElementById('pluginStatusGrid');
            if (!container) return;

            const categories = {
                'STT': { icon: '🎙️', count: counts.stt || 0 },
                'TTS': { icon: '🔊', count: counts.tts || 0 },
                'Wake Word': { icon: '⏰', count: counts.ww || 0 },
                'VAD': { icon: '🎯', count: counts.vad || 0 },
                'Network': { icon: '🌐', count: counts.network || 0 },
                'Agent': { icon: '🤖', count: counts.agent || 0 },
                'Database': { icon: '🗄️', count: counts.database || 0 },
                'Binary': { icon: '📦', count: counts.binary || 0 }
            };

            let html = '';
            for (const [catName, catData] of Object.entries(categories)) {
                if (catData.count > 0) {
                    html += `
                        <div style="padding: 12px; background: var(--bg-secondary); border-radius: var(--radius-sm); text-align: center;">
                            <div style="font-size: 20px; margin-bottom: 4px;">${catData.icon}</div>
                            <div style="font-size: 24px; font-weight: bold; color: var(--accent-primary);">${catData.count}</div>
                            <div style="font-size: 11px; color: var(--text-secondary);">${catName}</div>
                        </div>
                    `;
                }
            }
            container.innerHTML = html || '<p style="color: var(--text-secondary); grid-column: 1/-1; text-align: center;">No plugins installed</p>';
        }

        // Clients
        async function loadClients() {
            try {
                allClients = await apiCall('/clients');
                filteredClients = [...allClients];
                renderClientsTable();
            } catch (e) {
                showToast('Failed to load clients', 'error');
            }
        }

        function renderClientsTable() {
            const start = (currentPage - 1) * clientsPerPage;
            const end = start + clientsPerPage;
            const pageClients = filteredClients.slice(start, end);

            const tbody = document.getElementById('clientsTable');
            if (pageClients.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 48px; color: var(--text-secondary);">No clients found</td></tr>';
            } else {
                tbody.innerHTML = pageClients.map(c => {
                    const isRevoked = c.revoked || false;
                    const rowStyle = isRevoked ? 'style="opacity: 0.5; background: rgba(255, 107, 107, 0.1);"' : '';
                    const nameDisplay = isRevoked ? `<span style="color: var(--accent-danger);">🔒 ${c.name} (Revoked)</span>` : `<strong>${c.name}</strong>`;
                    return `
                        <tr ${rowStyle}>
                            <td>${c.client_id}</td>
                            <td>${nameDisplay}</td>
                            <td><code>${c.api_key.substring(0, 16)}...</code></td>
                            <td><span class="badge ${c.is_admin ? 'badge-success' : 'badge-danger'}">${c.is_admin ? 'Yes' : 'No'}</span></td>
                            <td><span class="badge ${c.can_escalate ? 'badge-success' : 'badge-danger'}">${c.can_escalate ? 'Yes' : 'No'}</span></td>
                            <td><span class="badge ${c.can_propagate ? 'badge-success' : 'badge-danger'}">${c.can_propagate ? 'Yes' : 'No'}</span></td>
                            <td>
                                ${isRevoked 
                                    ? `<span style="color: var(--accent-danger); font-size: 12px;">API Key Revoked</span>`
                                    : `<button class="btn btn-secondary btn-sm" onclick="showEditClientModal(${c.client_id})" style="margin-right: 8px;">Edit</button>
                                       <button class="btn btn-danger btn-sm" onclick="deleteClient(${c.client_id})">Delete</button>`
                                }
                            </td>
                        </tr>
                    `;
                }).join('');
            }

            document.getElementById('paginationInfo').textContent =
                `Showing ${filteredClients.length > 0 ? start + 1 : 0}-${Math.min(end, filteredClients.length)} of ${filteredClients.length}`;
            document.getElementById('prevBtn').disabled = currentPage === 1;
            document.getElementById('nextBtn').disabled = end >= filteredClients.length;
        }

        function filterClients() {
            const search = document.getElementById('clientSearch').value.toLowerCase();
            const filter = document.getElementById('clientFilter').value;

            filteredClients = allClients.filter(c => {
                const matchesSearch = c.name.toLowerCase().includes(search) ||
                                     c.api_key.toLowerCase().includes(search);
                let matchesFilter = true;
                if (filter === 'admin') matchesFilter = c.is_admin;
                else if (filter === 'escalate') matchesFilter = c.can_escalate;
                else if (filter === 'propagate') matchesFilter = c.can_propagate;
                return matchesSearch && matchesFilter;
            });

            currentPage = 1;
            renderClientsTable();
        }

        function prevPage() {
            if (currentPage > 1) {
                currentPage--;
                renderClientsTable();
            }
        }

        function nextPage() {
            const maxPage = Math.ceil(filteredClients.length / clientsPerPage);
            if (currentPage < maxPage) {
                currentPage++;
                renderClientsTable();
            }
        }

        function showAddClientModal() {
            document.getElementById('addClientModal').classList.add('active');
            document.getElementById('newClientName').value = '';
            document.getElementById('newClientName').focus();
        }

        function closeAddClientModal() {
            document.getElementById('addClientModal').classList.remove('active');
        }

        async function addClient() {
            const name = document.getElementById('newClientName').value.trim();
            if (!name) {
                showToast('Please enter a client name', 'error');
                return;
            }

            try {
                await apiCall('/clients', 'POST', { name });
                showToast('Client added successfully');
                closeAddClientModal();
                loadClients();
            } catch (e) {
                showToast('Failed to add client', 'error');
            }
        }

        async function deleteClient(id) {
            showConfirmModal(
                'Delete Client',
                'Are you sure you want to delete this client? This action cannot be undone.',
                async () => {
                    try {
                        await apiCall(`/clients/${id}`, 'DELETE');
                        showToast('Client deleted');
                        loadClients();
                    } catch (e) {
                        showToast('Failed to delete client: ' + e.message, 'error');
                    }
                }
            );
        }

        // Edit Client
        async function showEditClientModal(clientId) {
            try {
                const client = await apiCall(`/clients/${clientId}`);
                document.getElementById('editClientId').value = client.client_id;
                document.getElementById('editClientName').value = client.name;
                document.getElementById('editClientApiKey').value = client.api_key;

                // Load credentials for password/crypto_key
                const creds = await apiCall(`/clients/${clientId}/credentials`);
                document.getElementById('editClientPassword').value = creds.password || '';
                document.getElementById('editClientCryptoKey').value = creds.crypto_key || '';

                document.getElementById('editClientModal').classList.add('active');
            } catch (e) {
                showToast('Failed to load client details', 'error');
            }
        }

        function closeEditClientModal() {
            document.getElementById('editClientModal').classList.remove('active');
        }

        async function saveClientEdit() {
            const clientId = document.getElementById('editClientId').value;
            const data = {
                name: document.getElementById('editClientName').value,
                api_key: document.getElementById('editClientApiKey').value,
                password: document.getElementById('editClientPassword').value,
                crypto_key: document.getElementById('editClientCryptoKey').value
            };

            try {
                await apiCall(`/clients/${clientId}`, 'PUT', data);
                showToast('Client updated successfully');
                closeEditClientModal();
                loadClients();
            } catch (e) {
                showToast('Failed to update client: ' + e.message, 'error');
            }
        }

        // Encodings - Load and render
        async function loadEncodings() {
            try {
                const config = await apiCall('/config');
                renderEncodings(config.allowed_encodings || []);
                renderCiphers(config.allowed_ciphers || []);
            } catch (e) {
                showToast('Failed to load encodings', 'error');
            }
        }

        // Database Page
        async function loadDatabasePage() {
            try {
                const [profilesData, backends] = await Promise.all([
                    apiCall('/database/profiles'),
                    apiCall('/database/backends')
                ]);
                _dbBackends = backends;
                _dbProfiles = profilesData.profiles || {};
                _dbActiveName = profilesData.active || null;
                renderDatabaseProfiles();
                renderDatabaseBackendsReference();
            } catch (e) {
                showToast('Failed to load database page', 'error');
            }
        }

        function renderDatabaseProfiles() {
            // Update active banner
            const banner = document.getElementById('activeProfileBanner');
            const nameLabel = document.getElementById('activeProfileNameLabel');
            const moduleLabel = document.getElementById('activeProfileModuleLabel');
            if (banner) {
                if (_dbActiveName && _dbProfiles[_dbActiveName]) {
                    const p = _dbProfiles[_dbActiveName];
                    const b = _dbBackends.find(b => b.entry_point === p.module);
                    if (nameLabel) nameLabel.textContent = _dbActiveName;
                    if (moduleLabel) moduleLabel.textContent = b ? b.name : p.module;
                    banner.style.display = 'flex';
                } else {
                    banner.style.display = 'none';
                }
            }

            // Update header badge
            const badge = document.getElementById('activeDbBadge');
            if (badge) {
                badge.textContent = _dbActiveName ? `✓ Active: ${_dbActiveName}` : '✓ Active';
            }

            const container = document.getElementById('databaseProfilesContainer');
            if (!container) return;

            const names = Object.keys(_dbProfiles);
            if (names.length === 0) {
                container.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--text-secondary);">No profiles configured. Click "+ Add Profile" to create one.</div>';
                return;
            }

            let html = '<div style="display: grid; gap: 12px;">';
            for (const name of names) {
                const p = _dbProfiles[name];
                const isActive = name === _dbActiveName;
                const b = _dbBackends.find(b => b.entry_point === p.module);
                const cfg = p.config || {};
                const cfgEntries = Object.entries(cfg);
                const cfgStr = cfgEntries.length > 0
                    ? cfgEntries.map(([k, v]) => `${k}: ${v}`).join(', ')
                    : 'default settings';

                html += `
                    <div style="display: flex; align-items: flex-start; justify-content: space-between; padding: 16px 20px; background: var(--bg-secondary); border-radius: var(--radius-sm); border: 2px solid ${isActive ? 'var(--accent-primary)' : 'var(--border-color)'};">
                        <div style="flex: 1; min-width: 0;">
                            <div style="font-weight: 600; margin-bottom: 4px;">${escapeHtml(name)}${isActive ? ' <span class="badge badge-success" style="margin-left: 8px;">Active</span>' : ''}</div>
                            <div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 4px;">${escapeHtml(b ? b.name : p.module)}</div>
                            <div style="font-size: 11px; color: var(--text-secondary);">Module: <code style="color: var(--accent-primary);">${p.module}</code></div>
                            <div style="font-size: 11px; color: var(--text-secondary); margin-top: 2px; word-break: break-all;">Config: <code>${cfgStr}</code></div>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 6px; margin-left: 12px; flex-shrink: 0;">
                            ${!isActive ? `<button class="btn btn-primary btn-sm" onclick="activateProfile('${name}')">Activate</button>` : ''}
                            <button class="btn btn-secondary btn-sm" onclick="showEditProfileModal('${name}')">Edit</button>
                            <button class="btn btn-secondary btn-sm" onclick="testSavedProfile('${name}')">Test</button>
                            ${!isActive ? `<button class="btn btn-danger btn-sm" onclick="deleteProfile('${name}')">Delete</button>` : ''}
                        </div>
                    </div>
                `;
            }
            html += '</div>';
            container.innerHTML = html;
        }

        function renderDatabaseBackendsReference() {
            const container = document.getElementById('databaseBackendsContainer');
            if (!container) return;

            if (_dbBackends.length === 0) {
                container.innerHTML = '<div style="color: var(--text-secondary); font-size: 13px; padding: 8px;">No backends available.</div>';
                return;
            }

            let html = '';
            for (const b of _dbBackends) {
                html += `
                    <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: var(--bg-secondary); border-radius: var(--radius-sm); border: 1px solid var(--border-color);">
                        <div>
                            <span style="font-weight: 600; font-size: 13px;">${b.name}</span>
                            <span style="font-size: 11px; color: var(--text-secondary); margin-left: 8px;">${b.description || ''}</span>
                            <div style="font-size: 11px; color: var(--text-secondary); margin-top: 2px;">Package: <code style="color: var(--accent-primary);">${b.package}</code></div>
                        </div>
                        <div>
                            ${b.installed
                                ? '<span class="badge badge-success" style="font-size: 11px;">Installed</span>'
                                : `<button class="btn btn-secondary btn-sm" onclick="installPluginDirect('${b.package}')">Install</button>`}
                        </div>
                    </div>
                `;
            }
            container.innerHTML = html;
        }

        function showCreateProfileModal() {
            document.getElementById('profileModalTitle').textContent = 'Add Database Profile';
            document.getElementById('profileEditName').value = '';
            document.getElementById('profileName').value = '';
            document.getElementById('profileName').disabled = false;
            document.getElementById('profileModule').value = '';
            document.getElementById('profileRedisHost').value = 'localhost';
            document.getElementById('profileRedisPort').value = '6379';
            document.getElementById('profileRedisDb').value = '0';
            document.getElementById('profileRedisPassword').value = '';
            document.getElementById('profileFileSubfolder').value = 'hivemind-core';
            document.getElementById('profileFileName').value = 'clients';
            document.getElementById('profileTestStatus').classList.add('hidden');
            _populateProfileModuleDropdown('');
            onProfileModuleChange();
            document.getElementById('profileModal').classList.add('active');
        }

        function showEditProfileModal(name) {
            const p = _dbProfiles[name];
            if (!p) return;
            document.getElementById('profileModalTitle').textContent = `Edit Profile: ${name}`;
            document.getElementById('profileEditName').value = name;
            document.getElementById('profileName').value = name;
            document.getElementById('profileName').disabled = true;
            document.getElementById('profileTestStatus').classList.add('hidden');
            _populateProfileModuleDropdown(p.module);
            const cfg = p.config || {};
            if (p.module.includes('redis')) {
                document.getElementById('profileRedisHost').value = cfg.host || 'localhost';
                document.getElementById('profileRedisPort').value = cfg.port || 6379;
                document.getElementById('profileRedisDb').value = cfg.db !== undefined ? cfg.db : 0;
                document.getElementById('profileRedisPassword').value = cfg.password || '';
            } else {
                document.getElementById('profileFileSubfolder').value = cfg.subfolder || 'hivemind-core';
                document.getElementById('profileFileName').value = cfg.name || 'clients';
            }
            onProfileModuleChange();
            document.getElementById('profileModal').classList.add('active');
        }

        function _populateProfileModuleDropdown(selectedModule) {
            const select = document.getElementById('profileModule');
            select.innerHTML = '<option value="">Select a backend...</option>';
            for (const b of _dbBackends) {
                const opt = document.createElement('option');
                opt.value = b.entry_point;
                opt.textContent = b.name;
                opt.selected = b.entry_point === selectedModule;
                select.appendChild(opt);
            }
        }

        function onProfileModuleChange() {
            const module = document.getElementById('profileModule').value;
            const isRedis = module.includes('redis');
            const hasModule = !!module;
            document.getElementById('profileRedisSection').classList.toggle('hidden', !isRedis);
            document.getElementById('profileFileSection').classList.toggle('hidden', isRedis || !hasModule);
        }

        function closeProfileModal() {
            document.getElementById('profileModal').classList.remove('active');
        }

        function _collectProfileConfig(module) {
            const cfg = {};
            if (module.includes('redis')) {
                cfg.host = document.getElementById('profileRedisHost').value || 'localhost';
                cfg.port = parseInt(document.getElementById('profileRedisPort').value) || 6379;
                cfg.db = parseInt(document.getElementById('profileRedisDb').value) || 0;
                const pw = document.getElementById('profileRedisPassword').value;
                if (pw) cfg.password = pw;
            } else {
                const subfolder = document.getElementById('profileFileSubfolder').value.trim();
                const name = document.getElementById('profileFileName').value.trim();
                if (subfolder) cfg.subfolder = subfolder;
                if (name) cfg.name = name;
            }
            return cfg;
        }

        async function testProfileInModal() {
            const module = document.getElementById('profileModule').value;
            if (!module) { showToast('Select a backend first', 'error'); return; }
            const config = _collectProfileConfig(module);
            const statusDiv = document.getElementById('profileTestStatus');
            statusDiv.classList.remove('hidden');
            statusDiv.className = 'validation-result';
            statusDiv.innerHTML = '<div style="display: flex; align-items: center; gap: 8px;"><div class="spinner" style="width: 16px; height: 16px; border-width: 2px;"></div><span>Testing connection...</span></div>';
            try {
                const result = await apiCall('/database/test', 'POST', { module, config });
                if (result.success) {
                    statusDiv.classList.add('success');
                    statusDiv.style.border = '1px solid var(--accent-success)';
                    statusDiv.innerHTML = `<span style="color: var(--accent-success);">✓ ${result.message || 'Connection OK'}</span>`;
                } else {
                    statusDiv.classList.add('error');
                    statusDiv.style.border = '1px solid var(--accent-danger)';
                    statusDiv.innerHTML = `<span style="color: var(--accent-danger);">✗ ${result.message || 'Test failed'}</span>`;
                }
            } catch (e) {
                statusDiv.classList.add('error');
                statusDiv.style.border = '1px solid var(--accent-danger)';
                statusDiv.innerHTML = `<span style="color: var(--accent-danger);">✗ ${e.message}</span>`;
            }
        }

        async function saveProfile() {
            const editName = document.getElementById('profileEditName').value;
            const isEdit = !!editName;
            const name = isEdit ? editName : document.getElementById('profileName').value.trim();
            const module = document.getElementById('profileModule').value;
            if (!name) { showToast('Profile name is required', 'error'); return; }
            if (!module) { showToast('Select a backend first', 'error'); return; }
            const statusDiv = document.getElementById('profileTestStatus');
            if (statusDiv.classList.contains('hidden') || !statusDiv.classList.contains('success')) {
                showToast('Test the connection first before saving', 'error');
                return;
            }
            const config = _collectProfileConfig(module);
            try {
                if (isEdit) {
                    await apiCall(`/database/profiles/${encodeURIComponent(name)}`, 'PUT', { module, config });
                    showToast(`Profile '${name}' updated`);
                } else {
                    await apiCall('/database/profiles', 'POST', { name, module, config });
                    showToast(`Profile '${name}' created`);
                }
                closeProfileModal();
                loadDatabasePage();
            } catch (e) {
                showToast('Failed to save profile: ' + e.message, 'error');
            }
        }

        function activateProfile(name) {
            document.getElementById('activateProfileTarget').value = name;
            document.getElementById('activateProfileNameLabel').textContent = name;
            document.getElementById('migrateDataToggle').checked = true;
            document.getElementById('activateProfileStatus').classList.add('hidden');
            document.getElementById('activateProfileModal').classList.add('active');
        }

        function closeActivateProfileModal() {
            document.getElementById('activateProfileModal').classList.remove('active');
        }

        async function confirmActivateProfile() {
            const name = document.getElementById('activateProfileTarget').value;
            const migrate = document.getElementById('migrateDataToggle').checked;
            const statusDiv = document.getElementById('activateProfileStatus');
            statusDiv.classList.remove('hidden');
            statusDiv.className = 'validation-result';
            statusDiv.innerHTML = '<div style="display: flex; align-items: center; gap: 8px;"><div class="spinner" style="width: 16px; height: 16px; border-width: 2px;"></div><span>Activating...</span></div>';
            try {
                const result = await apiCall(`/database/profiles/${encodeURIComponent(name)}/activate`, 'POST', { migrate_data: migrate });
                statusDiv.classList.add('success');
                statusDiv.style.border = '1px solid var(--accent-success)';
                const migNote = result.clients_migrated > 0 ? ` (${result.clients_migrated} clients migrated)` : '';
                statusDiv.innerHTML = `<span style="color: var(--accent-success);">✓ ${result.message}${migNote}</span>`;
                _dbActiveName = name;
                renderDatabaseProfiles();
                setTimeout(() => {
                    closeActivateProfileModal();
                    showRestartRequiredModal();
                }, 1500);
            } catch (e) {
                statusDiv.classList.add('error');
                statusDiv.style.border = '1px solid var(--accent-danger)';
                statusDiv.innerHTML = `<span style="color: var(--accent-danger);">✗ ${e.message}</span>`;
            }
        }

        async function deleteProfile(name) {
            if (!confirm(`Delete profile '${name}'? This cannot be undone.`)) return;
            try {
                await apiCall(`/database/profiles/${encodeURIComponent(name)}`, 'DELETE');
                showToast(`Profile '${name}' deleted`);
                loadDatabasePage();
            } catch (e) {
                showToast('Failed to delete: ' + e.message, 'error');
            }
        }

        async function testSavedProfile(name) {
            showToast(`Testing profile '${name}'...`);
            try {
                const result = await apiCall(`/database/profiles/${encodeURIComponent(name)}/test`, 'POST');
                if (result.success) {
                    showToast(`Profile '${name}': ${result.message || 'OK'}`, 'success');
                } else {
                    showToast(`Profile '${name}': ${result.message || 'Failed'}`, 'error');
                }
            } catch (e) {
                showToast(`Test failed: ${e.message}`, 'error');
            }
        }

        // Network Page
        async function loadNetworkPage() {
            try {
                const [plugins, config] = await Promise.all([
                    apiCall('/plugins'),
                    apiCall('/config')
                ]);
                renderNetworkProtocols(plugins, config);
            } catch (e) {
                showToast('Failed to load network page', 'error');
            }
        }

        // Voice Plugins Page (Installation focus)
        async function loadVoicePluginsPage() {
            try {
                const [plugins, sttInstalled, ttsInstalled, wwInstalled, vadInstalled] = await Promise.all([
                    apiCall('/plugins'),
                    apiCall('/plugins/installed/ovos/stt').catch(() => []),
                    apiCall('/plugins/installed/ovos/tts').catch(() => []),
                    apiCall('/plugins/installed/ovos/ww').catch(() => []),
                    apiCall('/plugins/installed/ovos/vad').catch(() => [])
                ]);

                // Merge installed info into plugins
                const mergeInstalled = (pluginList, installedList) => {
                    return pluginList.map(p => {
                        const installed = installedList.find(i => i.entry_point === p.entry_point || i.entry_point === p.package);
                        return {
                            ...p,
                            install_status: installed ? installed.install_status : 'missing',
                            error: installed ? installed.error : null
                        };
                    });
                };

                // Load OVOS plugins into containers for installation
                renderVoicePlugins(mergeInstalled(plugins.filter(p => p.category === 'stt'), sttInstalled), 'stt', 'sttPluginsContainer', []);
                renderVoicePlugins(mergeInstalled(plugins.filter(p => p.category === 'tts'), ttsInstalled), 'tts', 'ttsPluginsContainer', []);
                renderVoicePlugins(mergeInstalled(plugins.filter(p => p.category === 'ww'), wwInstalled), 'ww', 'wwPluginsContainer', []);
                renderVoicePlugins(mergeInstalled(plugins.filter(p => p.category === 'vad'), vadInstalled), 'vad', 'vadPluginsContainer', []);

                // Render solver plugins (OVOS plugins used by personas)
                renderSolverPluginsFromAPI();
            } catch (e) {
                showToast('Failed to load voice plugins: ' + e.message, 'error');
            }
        }

        function switchVoicePluginTab(category) {
            // Update buttons
            document.querySelectorAll('#voice-pluginsPage .tab-item').forEach(el => el.classList.remove('active'));
            document.getElementById(category + 'Tab').classList.add('active');

            // Update sections
            document.querySelectorAll('.voice-tab-content').forEach(el => {
                el.classList.add('hidden');
                el.style.display = 'none';
            });
            const activeSection = document.getElementById(category + 'VoiceSection');
            activeSection.classList.remove('hidden');
            activeSection.style.display = 'block';
        }

        // Helper: Get all installed plugins from all categories
        async function getAllInstalledPlugins() {
            try {
                const [ovosStt, ovosTts, ovosWw, ovosVad, hivemindAgent, hivemindDatabase, hivemindNetwork, hivemindBinary, allPackages] = await Promise.all([
                    apiCall('/plugins/installed/ovos/stt').catch(() => []),
                    apiCall('/plugins/installed/ovos/tts').catch(() => []),
                    apiCall('/plugins/installed/ovos/ww').catch(() => []),
                    apiCall('/plugins/installed/ovos/vad').catch(() => []),
                    apiCall('/plugins/installed/hivemind/agent').catch(() => []),
                    apiCall('/plugins/installed/hivemind/database').catch(() => []),
                    apiCall('/plugins/installed/hivemind/network').catch(() => []),
                    apiCall('/plugins/installed/hivemind/binary').catch(() => []),
                    apiCall('/plugins/installed').catch(() => [])  // All installed packages (for solver/agent plugins)
                ]);

                // Extract entry points from OVOS endpoints (they return objects now)
                const extractEntryPoints = (list) => list.map(item => item.entry_point || item).filter(Boolean);
                
                // Combine all and return unique entries
                const all = [
                    ...extractEntryPoints(ovosStt),
                    ...extractEntryPoints(ovosTts),
                    ...extractEntryPoints(ovosWw),
                    ...extractEntryPoints(ovosVad),
                    ...extractEntryPoints(hivemindAgent),
                    ...extractEntryPoints(hivemindDatabase),
                    ...extractEntryPoints(hivemindNetwork),
                    ...extractEntryPoints(hivemindBinary),
                    ...allPackages
                ];
                return [...new Set(all)];
            } catch (e) {
                console.error('Failed to get installed plugins:', e);
                return [];
            }
        }

        // Binary Protocol Page (Active configuration focus)
        async function loadBinaryPage() {
            try {
                const [plugins, config, installedPlugins] = await Promise.all([
                    apiCall('/plugins'),
                    apiCall('/config'),
                    getAllInstalledPlugins()
                ]);

                const binaryProtocolConfig = document.getElementById('binaryProtocolConfig');
                const ovosPluginsSection = document.getElementById('ovosPluginsSection');
                const binaryProtocolDisabledMessage = document.getElementById('binaryProtocolDisabledMessage');

                // Get binary protocol status
                const currentBinary = config.binary_protocol?.module;
                const binaryPlugins = plugins.filter(p => p.category === 'binary');

                // Identify the active plugin if currentBinary is set
                const activePlugin = currentBinary ? binaryPlugins.find(p => p.entry_point === currentBinary) : null;
                const isBinaryEnabled = !!currentBinary && activePlugin;
                
                // Check if any binary plugin is installed
                const isAnyBinaryInstalled = binaryPlugins.some(p => 
                    installedPlugins.some(ip => ip.toLowerCase().includes(p.package.toLowerCase()) || p.package.toLowerCase().includes(ip.toLowerCase()))
                );

                if (isBinaryEnabled) {
                    // Binary protocol is enabled
                    binaryProtocolConfig.innerHTML = `
                        <div style="padding: 16px; background: var(--bg-secondary); border-radius: var(--radius-sm); border: 2px solid var(--accent-success);">
                            <div style="display: flex; align-items: center; justify-content: space-between;">
                                <div>
                                    <div style="font-weight: 600; margin-bottom: 4px;">✅ Active: ${activePlugin?.name || currentBinary}</div>
                                    <div style="font-size: 13px; color: var(--text-secondary);">${activePlugin?.description || 'Binary protocol for audio handling'}</div>
                                    <div style="font-size: 11px; color: var(--text-secondary); margin-top: 8px;">
                                        <div>Package: <code style="color: var(--accent-primary);">${activePlugin?.package}</code></div>
                                    </div>
                                </div>
                                <button class="btn btn-danger btn-sm" onclick="enableBinaryProtocol('', false)">Disable</button>
                            </div>
                        </div>
                    `;

                    ovosPluginsSection.classList.remove('hidden');
                    binaryProtocolDisabledMessage.classList.add('hidden');
                    ovosPluginsSection.style.display = 'block';
                    binaryProtocolDisabledMessage.style.display = 'none';

                    // Populate dropdowns with current selections
                    await populateActiveBinaryDropdowns(currentBinary, config.binary_protocol[currentBinary] || {});

                } else if (isAnyBinaryInstalled) {
                    // Binary protocol is installed but not enabled
                    const installedPlugin = binaryPlugins.find(p =>
                        installedPlugins.some(ip => ip.toLowerCase().includes(p.package.toLowerCase()) || p.package.toLowerCase().includes(ip.toLowerCase()))
                    );

                    let _binaryHtml = '<div style="display: grid; gap: 12px;">';

                    for (const plugin of binaryPlugins) {
                        const isInstalled = installedPlugins.some(ip =>
                            ip.toLowerCase().includes(plugin.package.toLowerCase()) ||
                            plugin.package.toLowerCase().includes(ip.toLowerCase())
                        );
                        const isActive = currentBinary === plugin.entry_point || currentBinary === plugin.package;

                        _binaryHtml += `
                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; background: var(--bg-secondary); border-radius: var(--radius-sm); border: 2px solid ${isActive ? 'var(--accent-primary)' : 'var(--border-color)'};">
                                <div>
                                    <div style="font-weight: 600; margin-bottom: 4px;">${plugin.name} ${isActive ? '<span class="badge badge-success" style="margin-left: 8px;">Active</span>' : ''}</div>
                                    <div style="font-size: 13px; color: var(--text-secondary);">${plugin.description}</div>
                                    <div style="font-size: 11px; color: var(--text-secondary);">Package: <code style="color: var(--accent-primary);">${plugin.package}</code></div>
                                    <div style="font-size: 11px; color: var(--text-secondary);">Entry Point: <code style="color: var(--accent-primary);">${plugin.entry_point}</code></div>
                                </div>
                                <div style="display: flex; align-items: center; gap: 12px;">
                                    ${isActive
                                        ? '<span class="badge badge-success">✓ Active</span>'
                                        : isInstalled
                                            ? `<button class="btn btn-primary btn-sm" onclick="showEnableBinaryProtocolModal('${plugin.entry_point}')">Enable</button>`
                                            : `<button class="btn btn-secondary btn-sm" onclick="installPluginDirect('${plugin.package}')">Install</button>`
                                    }
                                </div>
                            </div>
                        `;
                    }

                    _binaryHtml += '</div>';
                    binaryProtocolConfig.innerHTML = _binaryHtml;

                    ovosPluginsSection.classList.add('hidden');
                    ovosPluginsSection.style.display = 'none';
                    binaryProtocolDisabledMessage.style.display = 'block';

                    // Update the disabled message block
                    binaryProtocolDisabledMessage.innerHTML = `
                        <div class="card" style="border-left: 4px solid var(--accent-warning);">
                            <div class="card-body">
                                <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 16px;">
                                    <span style="font-size: 24px;">⚠️</span>
                                    <div>
                                        <strong style="font-size: 16px; color: var(--accent-warning);">Binary Protocol Inactive</strong>
                                        <p style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">
                                            Enable a binary protocol above to configure voice I/O features.
                                        </p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                    binaryProtocolDisabledMessage.classList.remove('hidden');
                } else {
                    // Binary protocol is not installed
                    let _binaryNotInstalledHtml = '<div style="display: grid; gap: 12px;">';

                    for (const plugin of binaryPlugins) {
                        _binaryNotInstalledHtml += `
                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; background: var(--bg-secondary); border-radius: var(--radius-sm); border: 2px solid var(--border-color);">
                                <div>
                                    <div style="font-weight: 600; margin-bottom: 4px;">${plugin.name}</div>
                                    <div style="font-size: 13px; color: var(--text-secondary);">${plugin.description}</div>
                                    <div style="font-size: 11px; color: var(--text-secondary);">Package: <code style="color: var(--accent-primary);">${plugin.package}</code></div>
                                    <div style="font-size: 11px; color: var(--text-secondary);">Entry Point: <code style="color: var(--accent-primary);">${plugin.entry_point}</code></div>
                                </div>
                                <div style="display: flex; align-items: center; gap: 12px;">
                                    <button class="btn btn-secondary btn-sm" onclick="installPluginDirect('${plugin.package}')">Install</button>
                                </div>
                            </div>
                        `;
                    }

                    _binaryNotInstalledHtml += '</div>';
                    binaryProtocolConfig.innerHTML = _binaryNotInstalledHtml;

                    ovosPluginsSection.classList.add('hidden');
                    ovosPluginsSection.style.display = 'none';
                    binaryProtocolDisabledMessage.style.display = 'block';
                    
                    binaryProtocolDisabledMessage.innerHTML = `
                        <div class="card" style="border-left: 4px solid var(--accent-danger);">
                            <div class="card-body">
                                <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 24px;">
                                    <span style="font-size: 32px;">❌</span>
                                    <div>
                                        <strong style="font-size: 18px; color: var(--accent-danger);">Binary Protocol Provider Missing</strong>
                                        <p style="font-size: 14px; color: var(--text-secondary); margin-top: 4px;">
                                            To use voice features, you must first install a binary protocol provider.
                                        </p>
                                    </div>
                                </div>
                                <div style="background: var(--bg-primary); padding: 20px; border-radius: var(--radius-sm); border: 1px dashed var(--border-color);">
                                    <h5 style="margin-bottom: 12px; font-size: 14px;">Recommended: Audio Binary Protocol</h5>
                                    <p style="font-size: 13px; color: var(--text-secondary); margin-bottom: 16px; line-height: 1.5;">
                                        The standard <code>hivemind-audio-binary-protocol</code> enables high-quality audio streaming for voice satellites.
                                    </p>
                                    <button class="btn btn-primary" onclick="installPluginDirect('hivemind-audio-binary-protocol')">
                                        <i class="fas fa-download" style="margin-right: 8px;"></i> Install Recommended Provider
                                    </button>
                                </div>
                            </div>
                        </div>
                    `;
                    binaryProtocolDisabledMessage.classList.remove('hidden');
                }
            } catch (e) {
                showToast('Failed to load binary protocol page: ' + e.message, 'error');
            }
        }

        async function populateActiveBinaryDropdowns(module, currentConfig) {
            const selects = {
                stt: document.getElementById('activeSTTSelect'),
                tts: document.getElementById('activeTTSSelect'),
                ww: document.getElementById('activeWWSelect'),
                vad: document.getElementById('activeVADSelect')
            };

            try {
                const [stt, tts, ww, vad] = await Promise.all([
                    apiCall('/plugins/installed/ovos/stt'),
                    apiCall('/plugins/installed/ovos/tts'),
                    apiCall('/plugins/installed/ovos/ww'),
                    apiCall('/plugins/installed/ovos/vad')
                ]);

                const installed = { stt, tts, ww, vad };
                
                // Get currently selected values from config
                const currentSTT = currentConfig.stt?.module || '';
                const currentTTS = currentConfig.tts?.module || '';
                const currentVAD = currentConfig.vad?.module || '';
                const currentWWName = currentConfig.wake_word || 'hey_mycroft';
                const currentWWModule = currentConfig.hotwords?.[currentWWName]?.module || '';

                document.getElementById('activeWWName').value = currentWWName;

                for (const [type, list] of Object.entries(installed)) {
                    const select = selects[type];
                    let html = `<option value="">-- Select ${type.toUpperCase()} --</option>`;
                    html += list.map(p => `<option value="${p}">${p}</option>`).join('');
                    select.innerHTML = html;
                    
                    // Set current value
                    if (type === 'stt') select.value = currentSTT;
                    if (type === 'tts') select.value = currentTTS;
                    if (type === 'ww') select.value = currentWWModule;
                    if (type === 'vad') select.value = currentVAD;
                }
            } catch (e) {
                console.error("Failed to populate active binary dropdowns", e);
            }
        }

        async function updateActiveBinaryConfig() {
            const config = await apiCall('/config');
            const module = config.binary_protocol?.module;
            
            if (!module) {
                showToast('No binary protocol provider active', 'error');
                return;
            }

            const sttModule = document.getElementById('activeSTTSelect').value;
            const ttsModule = document.getElementById('activeTTSSelect').value;
            const wwModule = document.getElementById('activeWWSelect').value;
            const vadModule = document.getElementById('activeVADSelect').value;
            const wwName = document.getElementById('activeWWName').value.trim() || 'hey_mycroft';

            if (!sttModule || !ttsModule || !wwModule || !vadModule) {
                showToast('Please select all voice components', 'error');
                return;
            }

            const pluginConfig = {
                stt: { module: sttModule, [sttModule]: {} },
                tts: { module: ttsModule, [ttsModule]: {} },
                vad: { module: vadModule, [vadModule]: {} },
                wake_word: wwName,
                hotwords: {
                    [wwName]: { module: wwModule }
                }
            };

            try {
                await apiCall('/plugins/enable', 'POST', {
                    plugin_type: 'binary_protocol',
                    module: module,
                    enabled: true,
                    config: { [module]: pluginConfig }
                });
                
                showToast('Voice configuration updated successfully');
                showRestartRequiredModal();
            } catch (e) {
                showToast('Failed to update configuration: ' + e.message, 'error');
            }
        }

        // ====================================================================
        // Personas Page
        // ====================================================================

        async function loadPersonasPage() {
            try {
                const [personas, activePersona] = await Promise.all([
                    apiCall('/personas'),
                    apiCall('/personas/active')
                ]);

                renderPersonasList(personas);

                // Show active persona section only if persona agent is active
                const config = await apiCall('/config');
                const agentModule = config.agent_protocol?.module || '';
                const activePersonaSection = document.getElementById('activePersonaSection');

                if (agentModule.includes('persona') || agentModule.includes('hivemind-persona')) {
                    activePersonaSection.classList.remove('hidden');
                    // Populate active persona dropdown
                    const select = document.getElementById('activePersonaSelect');
                    select.innerHTML = '<option value="">Select a persona...</option>';
                    for (const persona of personas) {
                        const name = persona.name;
                        const selected = name === activePersona.active ? 'selected' : '';
                        select.innerHTML += `<option value="${escapeHtml(name)}" ${selected}>${escapeHtml(name)}</option>`;
                    }
                } else {
                    activePersonaSection.classList.add('hidden');
                }
            } catch (e) {
                showToast('Failed to load personas: ' + e.message, 'error');
            }
        }

        function renderPersonasList(personas) {
            const container = document.getElementById('personasList');
            if (!container) return;

            if (!personas || personas.length === 0) {
                container.innerHTML = '<div class="empty-state"><p>No personas created yet. Click "Create Persona" to get started.</p></div>';
                return;
            }

            let html = '<div style="display: grid; gap: 12px;">';
            for (const persona of personas) {
                const solvers = persona.solvers || persona.handlers || [];
                const description = persona.description || 'No description';
                const solverCount = solvers.length;

                html += `
                    <div style="display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; background: var(--bg-secondary); border-radius: var(--radius-sm); border: 1px solid var(--border-color);">
                        <div style="flex: 1; min-width: 0;">
                            <div style="font-weight: 600; font-size: 14px; margin-bottom: 4px;">${escapeHtml(persona.name)}</div>
                            <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;">${escapeHtml(description)}</div>
                            <div style="font-size: 11px; color: var(--text-secondary);">
                                <span>🧩 ${solverCount} solver(s)</span>
                                ${persona.memory_module ? `<span style="margin-left: 12px;">💭 Memory: ${persona.memory_module}</span>` : ''}
                            </div>
                        </div>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <button class="btn btn-secondary btn-sm" onclick="previewPersona('${escapeHtml(persona.name)}')" title="Preview persona JSON">
                                👁️ Preview
                            </button>
                            <button class="btn btn-secondary btn-sm" onclick="testPersona('${escapeHtml(persona.name)}')" title="Test persona">
                                ⚠️ Test
                            </button>
                            <button class="btn btn-secondary btn-sm" onclick="exportPersona('${escapeHtml(persona.name)}')" title="Export persona">
                                📥 Export
                            </button>
                            <button class="btn btn-primary btn-sm" onclick="editPersona('${escapeHtml(persona.name)}')">
                                ✏️ Edit
                            </button>
                            <button class="btn btn-danger btn-sm" onclick="deletePersona('${escapeHtml(persona.name)}')" title="Delete persona">
                                🗑️
                            </button>
                        </div>
                    </div>
                `;
            }
            html += '</div>';
            container.innerHTML = html;
        }

        let selectedSolvers = []; // Ordered list of selected solver entry-points
        let _solverConfigs = {};  // entry_point → config dict

        // Config field schemas for known solver plugins.
        // Each value is an array of field descriptors: { key, label, type, placeholder, optional }.
        // Keys are canonical entry-point strings; _getSolverSchema() also does keyword matching
        // so all variants of a plugin family (ovos-chat-*, ovos-summarizer-*, etc.) resolve here.
        const _SOLVER_SCHEMAS = {

            // ── OpenAI-compatible (openai, llama, ollama, lm_studio, mistral, etc.) ──────
            'ovos-chat-openai-plugin': [
                { key: 'api_url', label: 'API URL', type: 'text', placeholder: 'https://api.openai.com/v1', optional: true },
                { key: 'key', label: 'API Key', type: 'password', placeholder: 'sk-...', optional: false },
                { key: 'model', label: 'Model', type: 'text', placeholder: 'gpt-4o-mini', optional: false },
                { key: 'max_tokens', label: 'Max Tokens', type: 'number', placeholder: '100', optional: true },
                { key: 'temperature', label: 'Temperature (0–1)', type: 'number', placeholder: '0.5', optional: true },
                { key: 'top_p', label: 'Top-P', type: 'number', placeholder: '0.2', optional: true },
                { key: 'system_prompt', label: 'System Prompt', type: 'textarea', placeholder: 'You are a helpful assistant.', optional: true },
            ],

            // ── Anthropic Claude ──────────────────────────────────────────────────────────
            'ovos-chat-claude-plugin': [
                { key: 'api_key', label: 'API Key', type: 'password', placeholder: 'sk-ant-...', optional: false },
                { key: 'model', label: 'Model', type: 'text', placeholder: 'claude-haiku-4-5-20251001', optional: true },
                { key: 'max_tokens', label: 'Max Tokens', type: 'number', placeholder: '512', optional: true },
                { key: 'temperature', label: 'Temperature (0–1)', type: 'number', placeholder: '0.7', optional: true },
                { key: 'system_prompt', label: 'System Prompt', type: 'textarea', placeholder: 'You are a helpful assistant.', optional: true },
            ],

            // ── Google Gemini ─────────────────────────────────────────────────────────────
            'ovos-chat-gemini-plugin': [
                { key: 'api_key', label: 'API Key', type: 'password', placeholder: 'AIza...', optional: false },
                { key: 'model', label: 'Model', type: 'text', placeholder: 'gemini-2.0-flash', optional: true },
                { key: 'max_tokens', label: 'Max Tokens', type: 'number', placeholder: '512', optional: true },
                { key: 'temperature', label: 'Temperature (0–1)', type: 'number', placeholder: '0.7', optional: true },
                { key: 'system_prompt', label: 'System Prompt', type: 'textarea', placeholder: 'You are a helpful assistant.', optional: true },
            ],

            // ── GGUF (local llama.cpp models) ─────────────────────────────────────────────
            // model can be a local file path OR a HuggingFace repo_id
            'ovos-chat-gguf-plugin': [
                { key: 'model', label: 'Model (path or HF repo ID)', type: 'text', placeholder: '/path/to/model.gguf  OR  QuantFactory/Meta-Llama-3-8B-GGUF', optional: false },
                { key: 'remote_filename', label: 'HF File Pattern (HF only)', type: 'text', placeholder: '*Q4_K_M.gguf', optional: true },
                { key: 'n_gpu_layers', label: 'GPU Layers (0 = CPU, -1 = all)', type: 'number', placeholder: '0', optional: true },
                { key: 'chat_format', label: 'Chat Format', type: 'text', placeholder: 'llama-2 / chatml / …', optional: true },
                { key: 'max_tokens', label: 'Max Tokens', type: 'number', placeholder: '256', optional: true },
                { key: 'system_prompt', label: 'System Prompt', type: 'textarea', placeholder: 'You are a helpful assistant.', optional: true },
            ],

            // ── Kilo (CLI-based agentic coding assistant) ─────────────────────────────────
            'ovos-chat-kilo-plugin': [
                { key: 'kilo_binary', label: 'Kilo Binary Path', type: 'text', placeholder: 'kilo', optional: true },
                { key: 'model', label: 'Model', type: 'text', placeholder: '', optional: true },
                { key: 'timeout', label: 'Timeout (seconds)', type: 'number', placeholder: '120', optional: true },
                { key: 'system_prompt', label: 'System Prompt', type: 'textarea', placeholder: 'You are a helpful assistant.', optional: true },
            ],

            // ── OpenCode (CLI-based agentic coding assistant) ─────────────────────────────
            'ovos-chat-opencode-plugin': [
                { key: 'opencode_binary', label: 'OpenCode Binary Path', type: 'text', placeholder: 'opencode', optional: true },
                { key: 'model', label: 'Model', type: 'text', placeholder: '', optional: true },
                { key: 'timeout', label: 'Timeout (seconds)', type: 'number', placeholder: '120', optional: true },
                { key: 'system_prompt', label: 'System Prompt', type: 'textarea', placeholder: 'You are a helpful assistant.', optional: true },
            ],

            // ── Qwen Code (Alibaba DashScope / CLI) ───────────────────────────────────────
            'ovos-chat-qwen-code-plugin': [
                { key: 'api_key', label: 'DashScope API Key', type: 'password', placeholder: 'sk-...', optional: true },
                { key: 'qwen_binary', label: 'Qwen CLI Binary Path', type: 'text', placeholder: 'qwen', optional: true },
                { key: 'model', label: 'Model', type: 'text', placeholder: 'qwen2.5-coder-7b-instruct', optional: true },
                { key: 'timeout', label: 'Timeout (seconds)', type: 'number', placeholder: '120', optional: true },
                { key: 'system_prompt', label: 'System Prompt', type: 'textarea', placeholder: 'You are a helpful assistant.', optional: true },
            ],

            // ── DuckDuckGo search solver ───────────────────────────────────────────────────
            // Minimal config; keyword extractor is optional
            'ovos-solver-plugin-ddg': [
                { key: 'keyword_extractor', label: 'Keyword Extractor Plugin', type: 'text', placeholder: 'ovos-rake-keyword-extractor', optional: true },
            ],

            // ── Wikipedia solver ──────────────────────────────────────────────────────────
            'ovos-solver-plugin-wikipedia': [
                { key: 'summarizer', label: 'Summarizer Plugin', type: 'text', placeholder: 'ovos-summarizer-bm25', optional: true },
                { key: 'keyword_extractor', label: 'Keyword Extractor Plugin', type: 'text', placeholder: 'ovos-rake-keyword-extractor', optional: true },
            ],

            // ── Wolfram Alpha solver ──────────────────────────────────────────────────────
            'ovos-solver-plugin-wolfram-alpha': [
                { key: 'appid', label: 'Wolfram Alpha App ID', type: 'text', placeholder: 'XXXX-XXXXXXXXXX', optional: false },
            ],

            // ── Mixture of Solvers (MoS) – complex; use JSON editor ───────────────────────
            // All ovos-mos-* plugins use JSON for their worker/king/voter configs.
            // Returning null here causes renderSolverConfigSections to show the JSON textarea.
        };

        function showCreatePersonaModal() {
            document.getElementById('createPersonaModalTitle').textContent = '👤 Create Persona';
            document.getElementById('editPersonaName').value = '';
            document.getElementById('personaName').value = '';
            document.getElementById('personaDescription').value = '';
            document.getElementById('personaMemoryModule').value = 'ovos-agents-short-term-memory-plugin';
            document.getElementById('createPersonaStatus').classList.add('hidden');
            document.getElementById('personaSolverConfigContainer').innerHTML = '';
            document.getElementById('createPersonaModal').classList.add('active');
            selectedSolvers = [];
            _solverConfigs = {};
            loadSolverPluginsForPersona();
        }

        function closeCreatePersonaModal() {
            document.getElementById('createPersonaModal').classList.remove('active');
        }

        async function loadSolverPluginsForPersona() {
            const container = document.getElementById('personaAvailableSolvers');
            const selectedContainer = document.getElementById('personaSelectedSolvers');

            try {
                const solverPlugins = await apiCall('/plugins/solvers');

                if (!solverPlugins || solverPlugins.length === 0) {
                    container.innerHTML = '<div class="empty-state"><p>No solver plugins available. Install some solver plugins first.</p></div>';
                    return;
                }

                // Render available solvers - USE ENTRY POINT not package!
                let html = '';
                for (const plugin of solverPlugins) {
                    const entryPoint = plugin.entry_point || plugin.package;
                    const installPackage = plugin.package || plugin.entry_point;
                    const description = plugin.description || '';

                    html += `
                        <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; background: var(--bg-primary); border-radius: var(--radius-sm); cursor: pointer; border: 1px solid var(--border-color);" onclick="toggleSolver('${entryPoint}', '${plugin.name}')">
                            <div style="flex: 1;">
                                <div style="font-weight: 600; font-size: 13px;">${plugin.name}</div>
                                <div style="font-size: 11px; color: var(--text-secondary);">${description}</div>
                                <div style="font-size: 10px; color: var(--text-secondary); font-family: monospace;">${entryPoint}</div>
                            </div>
                            <span style="font-size: 16px; color: var(--accent-primary);">+</span>
                        </div>
                    `;
                }
                container.innerHTML = html;

                // Render selected solvers
                renderSelectedSolvers();
            } catch (e) {
                container.innerHTML = '<div class="empty-state" style="color: var(--accent-danger);">Failed to load solver plugins</div>';
            }
        }

        function toggleSolver(entryPoint, name) {
            const index = selectedSolvers.indexOf(entryPoint);
            if (index >= 0) {
                // Remove from selected — also discard its config
                selectedSolvers.splice(index, 1);
                delete _solverConfigs[entryPoint];
            } else {
                // Add to selected
                selectedSolvers.push(entryPoint);
            }
            renderSelectedSolvers();
            renderSolverConfigSections();
        }

        /**
         * Return the config schema fields for a solver entry-point, or null if unknown.
         *
         * Resolution order:
         *   1. Exact match in _SOLVER_SCHEMAS
         *   2. Plugin-family keyword matching (covers all ovos-chat-*, ovos-summarizer-*, etc.)
         *   3. null → caller shows a raw JSON textarea
         *
         * An empty array [] means the plugin needs no user configuration.
         */
        function _getSolverSchema(entryPoint) {
            const ep = entryPoint.toLowerCase();

            // 1. Exact match
            if (_SOLVER_SCHEMAS[entryPoint]) return _SOLVER_SCHEMAS[entryPoint];

            // 2. Keyword-based family matching
            // OpenAI-compatible (covers llama, ollama, lm_studio, mistral, local-ai, etc.)
            if (ep.includes('openai') || ep.includes('ollama') || ep.includes('lm_studio') ||
                ep.includes('lmstudio') || ep.includes('mistral') || ep.includes('local-ai')) {
                return _SOLVER_SCHEMAS['ovos-chat-openai-plugin'];
            }
            // Claude / Anthropic
            if (ep.includes('claude') || ep.includes('anthropic')) {
                return _SOLVER_SCHEMAS['ovos-chat-claude-plugin'];
            }
            // Gemini / Google
            if (ep.includes('gemini') || ep.includes('google-ai')) {
                return _SOLVER_SCHEMAS['ovos-chat-gemini-plugin'];
            }
            // GGUF (local llama.cpp)
            if (ep.includes('gguf') || ep.includes('llamacpp') || ep.includes('llama_cpp') || ep.includes('llama-cpp')) {
                return _SOLVER_SCHEMAS['ovos-chat-gguf-plugin'];
            }
            // Kilo
            if (ep.includes('kilo')) {
                return _SOLVER_SCHEMAS['ovos-chat-kilo-plugin'];
            }
            // OpenCode
            if (ep.includes('opencode')) {
                return _SOLVER_SCHEMAS['ovos-chat-opencode-plugin'];
            }
            // Qwen
            if (ep.includes('qwen')) {
                return _SOLVER_SCHEMAS['ovos-chat-qwen-code-plugin'];
            }
            // Wolfram Alpha
            if (ep.includes('wolfram')) {
                return _SOLVER_SCHEMAS['ovos-solver-plugin-wolfram-alpha'];
            }
            // Wikipedia
            if (ep.includes('wikipedia')) {
                return _SOLVER_SCHEMAS['ovos-solver-plugin-wikipedia'];
            }
            // DuckDuckGo
            if (ep.includes('ddg') || ep.includes('duckduckgo')) {
                return _SOLVER_SCHEMAS['ovos-solver-plugin-ddg'];
            }
            // Plugins with no user-facing configuration (return empty array = "no config needed")
            if (ep.includes('failure') || ep.includes('yes-no') || ep.includes('yesno') ||
                ep.includes('aiml') || ep.includes('rivescript') || ep.includes('bm25') ||
                ep.includes('coreferee') || ep.includes('flashrank') || ep.includes('chromadb') ||
                ep.includes('qdrant') || ep.includes('embeddings')) {
                return [];
            }

            // MoS plugins — complex JSON structure; fall through to JSON editor
            if (ep.includes('mos') || ep.includes('mixture')) {
                return null;
            }

            // 3. Unknown — show JSON textarea
            return null;
        }

        function renderSelectedSolvers() {
            const container = document.getElementById('personaSelectedSolvers');

            if (selectedSolvers.length === 0) {
                container.innerHTML = '<div class="empty-state" style="opacity: 0.5;">No agents selected. Click agents above to add them.</div>';
                return;
            }

            let html = '';
            selectedSolvers.forEach((pkg, index) => {
                const hasConfig = _solverConfigs[pkg] && Object.keys(_solverConfigs[pkg]).length > 0;
                const configBadge = hasConfig
                    ? '<span style="font-size: 10px; color: var(--accent-success); margin-left: 4px;">⚙ configured</span>'
                    : '';
                html += `
                    <div style="display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: var(--bg-secondary); border-radius: var(--radius-sm); border: 1px solid var(--accent-primary);" draggable="true" ondragstart="dragStart(event, ${index})" ondragover="dragOver(event)" ondrop="drop(event, ${index})">
                        <span style="cursor: grab; font-size: 16px; color: var(--text-secondary);">⋮⋮</span>
                        <span style="font-size: 12px; color: var(--text-secondary); font-weight: 600;">${index + 1}.</span>
                        <span style="flex: 1; font-size: 13px; font-family: monospace;">${pkg}${configBadge}</span>
                        <button class="btn btn-secondary btn-sm" onclick="scrollToSolverConfig('${pkg}')" style="padding: 4px 8px; font-size: 11px;" title="Configure plugin">⚙</button>
                        <button class="btn btn-danger btn-sm" onclick="toggleSolver('${pkg}')" style="padding: 4px 8px; font-size: 11px;">✕</button>
                    </div>
                `;
            });

            container.innerHTML = html;

            // Re-attach drag events
            const items = container.querySelectorAll('[draggable="true"]');
            items.forEach((item, idx) => {
                item.addEventListener('dragstart', (e) => dragStart(e, idx));
                item.addEventListener('dragover', dragOver);
                item.addEventListener('drop', (e) => drop(e, idx));
            });
        }

        /** Scroll the config section for a given solver into view. */
        function scrollToSolverConfig(entryPoint) {
            const el = document.getElementById(`solver-cfg-${CSS.escape(entryPoint)}`);
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }

        /**
         * Render (or re-render) per-solver config forms inside personaSolverConfigContainer.
         * Called after selectedSolvers changes.
         */
        function renderSolverConfigSections() {
            const container = document.getElementById('personaSolverConfigContainer');
            if (!container) return;

            if (selectedSolvers.length === 0) {
                container.innerHTML = '';
                return;
            }

            // Preserve existing field values before re-rendering
            _collectAllSolverConfigs();

            let html = '<div style="margin-top: 8px;"><label style="font-size: 13px; font-weight: 600;">Plugin Configuration</label></div>';
            for (const ep of selectedSolvers) {
                const schema = _getSolverSchema(ep);
                const cfg = _solverConfigs[ep] || {};
                const safeId = ep.replace(/[^a-zA-Z0-9_-]/g, '_');

                const autoOpen = schema !== null && schema.length > 0;
                html += `<details id="solver-cfg-${safeId}" style="margin-top: 10px; border: 1px solid var(--border-color); border-radius: var(--radius-sm);" ${autoOpen ? 'open' : ''}>
                    <summary style="padding: 10px 14px; cursor: pointer; font-size: 13px; font-family: monospace; background: var(--bg-secondary); border-radius: var(--radius-sm);">
                        ⚙ <strong>${ep}</strong>${schema !== null && schema.length === 0 ? ' <span style="font-size: 10px; color: var(--text-secondary);">(no config needed)</span>' : ''}
                    </summary>
                    <div style="padding: 14px; display: flex; flex-direction: column; gap: 10px;">`;

                if (schema === null) {
                    // Unknown plugin — arbitrary JSON editor
                    const jsonVal = Object.keys(cfg).length > 0 ? JSON.stringify(cfg, null, 2) : '';
                    html += `<div>
                        <label style="font-size: 12px;">Plugin Config <span style="font-size: 10px; color: var(--text-secondary);">(JSON, optional)</span></label>
                        <p style="font-size: 11px; color: var(--text-secondary); margin: 4px 0 6px;">
                            This plugin is not in the presets list. Enter its configuration as a JSON object.
                        </p>
                        <textarea data-solver="${safeId}" data-json="1" placeholder='{\n  "enabled": true\n}'
                            style="width: 100%; min-height: 80px; padding: 8px; background: var(--bg-primary); border: 1px solid var(--border-color); border-radius: var(--radius-sm); color: var(--text-primary); font-family: monospace; font-size: 12px; box-sizing: border-box;">${jsonVal}</textarea>
                        <div id="solver-json-err-${safeId}" style="font-size: 11px; color: var(--accent-danger); margin-top: 4px; display: none;"></div>
                    </div>`;
                } else if (schema.length === 0) {
                    // Plugin needs no configuration
                    html += `<p style="font-size: 12px; color: var(--text-secondary); margin: 0;">No configuration required for this plugin.</p>`;
                } else {
                    // Structured fields from the schema
                    for (const field of schema) {
                        const val = cfg[field.key] !== undefined ? String(cfg[field.key]) : '';
                        const optLabel = field.optional ? ' <span style="font-size: 10px; color: var(--text-secondary);">(optional)</span>' : ' <span style="font-size: 10px; color: var(--accent-danger);">*</span>';
                        if (field.type === 'textarea') {
                            html += `<div><label style="font-size: 12px;">${field.label}${optLabel}</label>
                                <textarea data-solver="${safeId}" data-key="${field.key}" placeholder="${field.placeholder || ''}"
                                    style="width: 100%; min-height: 60px; padding: 8px; background: var(--bg-primary); border: 1px solid var(--border-color); border-radius: var(--radius-sm); color: var(--text-primary); font-family: monospace; font-size: 12px; box-sizing: border-box;">${val}</textarea></div>`;
                        } else {
                            html += `<div><label style="font-size: 12px;">${field.label}${optLabel}</label>
                                <input type="${field.type}" data-solver="${safeId}" data-key="${field.key}" value="${val.replace(/"/g, '&quot;')}"
                                    placeholder="${field.placeholder || ''}"
                                    style="width: 100%; padding: 8px 10px; background: var(--bg-primary); border: 1px solid var(--border-color); border-radius: var(--radius-sm); color: var(--text-primary); font-size: 12px; box-sizing: border-box;" /></div>`;
                        }
                    }
                }

                html += `</div></details>`;
            }
            container.innerHTML = html;
        }

        /**
         * Read current form values for all solver config sections into _solverConfigs.
         * Returns false (and marks invalid) if any JSON textarea has a parse error.
         */
        function _collectAllSolverConfigs() {
            const container = document.getElementById('personaSolverConfigContainer');
            if (!container) return true;

            let valid = true;

            for (const ep of selectedSolvers) {
                const safeId = ep.replace(/[^a-zA-Z0-9_-]/g, '_');
                const cfg = {};

                // Structured fields
                container.querySelectorAll(`[data-solver="${safeId}"][data-key]`).forEach(el => {
                    const key = el.dataset.key;
                    const val = el.value.trim();
                    if (val !== '') {
                        cfg[key] = el.type === 'number' ? parseFloat(val) : val;
                    }
                });

                // JSON field (unknown plugins)
                const jsonEl = container.querySelector(`[data-solver="${safeId}"][data-json]`);
                if (jsonEl) {
                    const errEl = document.getElementById(`solver-json-err-${safeId}`);
                    const raw = jsonEl.value.trim();
                    if (raw) {
                        try {
                            const parsed = JSON.parse(raw);
                            Object.assign(cfg, parsed);
                            if (errEl) errEl.style.display = 'none';
                        } catch (e) {
                            if (errEl) { errEl.textContent = `JSON error: ${e.message}`; errEl.style.display = 'block'; }
                            valid = false;
                        }
                    }
                }

                _solverConfigs[ep] = cfg;
            }
            return valid;
        }

        let draggedIndex = null;

        function dragStart(event, index) {
            draggedIndex = index;
            event.dataTransfer.effectAllowed = 'move';
            event.target.style.opacity = '0.5';
        }

        function dragOver(event) {
            event.preventDefault();
            event.dataTransfer.dropEffect = 'move';
        }

        function drop(event, targetIndex) {
            event.preventDefault();
            if (draggedIndex === null || draggedIndex === targetIndex) return;

            // Reorder array
            const [moved] = selectedSolvers.splice(draggedIndex, 1);
            selectedSolvers.splice(targetIndex, 0, moved);

            draggedIndex = null;
            renderSelectedSolvers();
            renderSolverConfigSections();
        }

        async function savePersona() {
            const editName = document.getElementById('editPersonaName').value;
            const name = document.getElementById('personaName').value.trim();
            const description = document.getElementById('personaDescription').value.trim();
            const memoryModule = document.getElementById('personaMemoryModule').value;
            const statusDiv = document.getElementById('createPersonaStatus');

            if (!name) {
                showToast('Persona name is required', 'error');
                return;
            }

            if (selectedSolvers.length === 0) {
                showToast('At least one solver plugin must be selected', 'error');
                return;
            }

            // Collect and validate all per-solver configs before saving
            if (!_collectAllSolverConfigs()) {
                showToast('Fix JSON errors in plugin configuration before saving', 'error');
                return;
            }

            // Build persona config: top-level keys + per-solver config dicts
            const personaConfig = {
                name: name,
                description: description,
                solvers: selectedSolvers, // Ordered list!
                memory_module: memoryModule || null,
            };
            // Merge per-solver configs: each solver's config is stored at its entry-point key
            for (const [ep, cfg] of Object.entries(_solverConfigs)) {
                if (cfg && Object.keys(cfg).length > 0) {
                    personaConfig[ep] = cfg;
                }
            }

            try {
                statusDiv.classList.remove('hidden');
                statusDiv.className = 'validation-result';
                statusDiv.innerHTML = '<div class="spinner" style="display: inline-block; margin-right: 8px;"></div> Saving persona...';

                if (editName) {
                    // Update existing
                    await apiCall(`/personas/${editName}`, 'PUT', personaConfig);
                    showToast('Persona updated successfully');
                } else {
                    // Create new
                    await apiCall('/personas', 'POST', personaConfig);
                    showToast('Persona created successfully');
                }

                closeCreatePersonaModal();
                loadPersonasPage();
            } catch (e) {
                statusDiv.classList.add('error');
                statusDiv.innerHTML = `✗ Failed to save: ${e.message}`;
                showToast('Failed to save persona: ' + e.message, 'error');
            }
        }

        async function editPersona(name) {
            try {
                const persona = await apiCall(`/personas/${name}`);

                document.getElementById('createPersonaModalTitle').textContent = '👤 Edit Persona';
                document.getElementById('editPersonaName').value = persona.name;
                document.getElementById('personaName').value = persona.name;
                document.getElementById('personaDescription').value = persona.description || '';
                document.getElementById('personaMemoryModule').value = persona.memory_module || 'ovos-agents-short-term-memory-plugin';
                document.getElementById('createPersonaStatus').classList.add('hidden');
                document.getElementById('personaSolverConfigContainer').innerHTML = '';
                document.getElementById('createPersonaModal').classList.add('active');

                // Load solvers and set selected ones in order
                await loadSolverPluginsForPersona();
                const solvers = persona.solvers || persona.handlers || [];

                // Restore per-solver configs from the saved persona
                _solverConfigs = {};
                const reservedKeys = new Set(['name', 'description', 'solvers', 'handlers', 'memory_module']);
                for (const [k, v] of Object.entries(persona)) {
                    if (!reservedKeys.has(k) && typeof v === 'object' && v !== null) {
                        _solverConfigs[k] = v;
                    }
                }

                // Set selectedSolvers array in the correct order
                selectedSolvers = [...solvers];
                renderSelectedSolvers();
                renderSolverConfigSections();
            } catch (e) {
                showToast('Failed to load persona: ' + e.message, 'error');
            }
        }

        async function deletePersona(name) {
            showConfirmModal(
                'Delete Persona',
                `Are you sure you want to delete the persona "${name}"? This action cannot be undone.`,
                async () => {
                    try {
                        await apiCall(`/personas/${name}`, 'DELETE');
                        showToast('Persona deleted successfully');
                        loadPersonasPage();
                    } catch (e) {
                        showToast('Failed to delete persona: ' + e.message, 'error');
                    }
                }
            );
        }

        async function exportPersona(name) {
            try {
                const persona = await apiCall(`/personas/${name}/export`);
                
                // Create download
                const dataStr = JSON.stringify(persona, null, 2);
                const dataBlob = new Blob([dataStr], { type: 'application/json' });
                const url = URL.createObjectURL(dataBlob);
                const link = document.createElement('a');
                link.href = url;
                link.download = `${name.toLowerCase().replace(/[^a-z0-9]/g, '_')}.json`;
                link.click();
                URL.revokeObjectURL(url);

                showToast('Persona exported successfully');
            } catch (e) {
                showToast('Failed to export persona: ' + e.message, 'error');
            }
        }

        async function previewPersona(name) {
            try {
                const persona = await apiCall(`/personas/${name}`);
                
                document.getElementById('previewPersonaJson').textContent = JSON.stringify(persona, null, 2);
                document.getElementById('previewPersonaModal').classList.add('active');
            } catch (e) {
                showToast('Failed to load persona: ' + e.message, 'error');
            }
        }

        function closePreviewPersonaModal() {
            document.getElementById('previewPersonaModal').classList.remove('active');
        }

        function copyPersonaJson() {
            const jsonText = document.getElementById('previewPersonaJson').textContent;
            navigator.clipboard.writeText(jsonText).then(() => {
                showToast('JSON copied to clipboard');
            }).catch(() => {
                showToast('Failed to copy JSON', 'error');
            });
        }

        let currentTestPersonaName = null;

        async function testPersona(name) {
            currentTestPersonaName = name;
            document.getElementById('testPersonaModal').classList.add('active');
            document.getElementById('testPersonaConfirm').classList.add('hidden');
            const resultsDiv = document.getElementById('testPersonaResults');
            const statusDiv = document.getElementById('testPersonaStatus');

            resultsDiv.innerHTML = '<div class="empty-state"><div class="spinner"></div><p>Loading persona configuration...</p></div>';
            statusDiv.classList.add('hidden');

            try {
                // First, get the persona config to show basic info
                const persona = await apiCall(`/personas/${name}`);

                let html = '';

                // Show basic persona info first
                html += '<div style="padding: 12px; background: var(--bg-secondary); border-radius: var(--radius-sm); margin-bottom: 12px;">';
                html += '<div style="font-weight: 600; margin-bottom: 8px;">👤 ' + persona.name + '</div>';
                html += '<div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;">' + (persona.description || 'No description') + '</div>';
                html += '<div style="font-size: 11px; color: var(--text-secondary);">';
                html += '<div>🧩 Agents: ' + (persona.solvers || persona.handlers || []).length + '</div>';
                html += '<div>💭 Memory: ' + (persona.memory_module || 'None') + '</div>';
                html += '</div>';
                html += '</div>';

                // Check for GGUF/LLama models (only these show warning before test)
                const solvers = persona.solvers || persona.handlers || [];
                let downloadWarning = '';
                let hasLargeModels = false;

                for (const solver of solvers) {
                    const solverConfig = persona[solver] || {};
                    const modelPath = solverConfig.model_path || solverConfig.model || '';

                    if (modelPath && (solver.toLowerCase().includes('gguf') || solver.toLowerCase().includes('llama'))) {
                        hasLargeModels = true;
                        downloadWarning += '<div>• ' + solver + ': ' + modelPath + '</div>';
                    }
                }

                if (hasLargeModels) {
                    html += '<div style="padding: 12px; background: rgba(255, 217, 61, 0.1); border: 1px solid var(--accent-warning); border-radius: var(--radius-sm); margin-bottom: 12px;">';
                    html += '<div style="font-weight: 600; color: var(--accent-warning); margin-bottom: 4px;">⚠️ Large Models Detected</div>';
                    html += '<div style="font-size: 12px; color: var(--text-secondary);">The following models may need to be downloaded (sizes can range from 50MB to several GB):</div>';
                    html += '<div style="font-size: 11px; color: var(--text-secondary); margin-top: 8px;">' + downloadWarning + '</div>';
                    html += '</div>';
                }

                resultsDiv.innerHTML = html;

                // Show confirmation buttons
                document.getElementById('testPersonaConfirm').classList.remove('hidden');
            } catch (e) {
                statusDiv.classList.add('error');
                statusDiv.innerHTML = `✗ Failed to load persona: ${e.message}`;
                statusDiv.classList.remove('hidden');
            }
        }

        async function confirmTestPersona() {
            if (!currentTestPersonaName) return;

            const name = currentTestPersonaName;
            const resultsDiv = document.getElementById('testPersonaResults');
            const statusDiv = document.getElementById('testPersonaStatus');

            resultsDiv.innerHTML = '<div class="empty-state"><div class="spinner"></div><p>Testing persona configuration...</p></div>';
            statusDiv.classList.add('hidden');
            document.getElementById('testPersonaConfirm').classList.add('hidden');

            try {
                // Use POST method for testing persona
                const result = await apiCall(`/personas/${encodeURIComponent(name)}/test`, 'POST');

                let html = '';

                // Validation status
                if (result.valid) {
                    html += '<div style="padding: 12px; background: rgba(107, 203, 119, 0.1); border: 1px solid var(--accent-success); border-radius: var(--radius-sm); margin-bottom: 12px;">';
                    html += '<div style="font-weight: 600; color: var(--accent-success);">✓ Configuration Valid</div>';
                    html += '</div>';
                } else {
                    html += '<div style="padding: 12px; background: rgba(255, 107, 107, 0.1); border: 1px solid var(--accent-danger); border-radius: var(--radius-sm); margin-bottom: 12px;">';
                    html += '<div style="font-weight: 600; color: var(--accent-danger);">✗ Configuration Invalid</div>';
                    for (const error of result.errors) {
                        html += `<div style="font-size: 12px; margin-top: 4px;">• ${error}</div>`;
                    }
                    html += '</div>';
                }

                // Download warning
                if (result.download_required) {
                    html += '<div style="padding: 12px; background: rgba(255, 217, 61, 0.1); border: 1px solid var(--accent-warning); border-radius: var(--radius-sm); margin-bottom: 12px;">';
                    html += '<div style="font-weight: 600; color: var(--accent-warning);">⚠️ Model Download Required</div>';
                    html += '<div style="font-size: 12px; margin-top: 4px;">This persona requires downloading AI models on first use.</div>';
                    html += '</div>';
                }

                // Warnings
                if (result.warnings && result.warnings.length > 0) {
                    html += '<div style="padding: 12px; background: rgba(255, 217, 61, 0.1); border: 1px solid var(--accent-warning); border-radius: var(--radius-sm); margin-bottom: 12px;">';
                    html += '<div style="font-weight: 600; color: var(--accent-warning);">⚠️ Warnings</div>';
                    for (const warning of result.warnings) {
                        html += `<div style="font-size: 12px; margin-top: 4px;">• ${warning}</div>`;
                    }
                    html += '</div>';
                }

                // Solver info
                html += '<div style="padding: 12px; background: var(--bg-secondary); border-radius: var(--radius-sm);">';
                html += '<div style="font-weight: 600; margin-bottom: 8px;">Agents</div>';
                for (const solver of result.solvers) {
                    html += `<div style="font-size: 12px; font-family: monospace; color: var(--text-primary);">• ${solver}</div>`;
                }
                html += '</div>';

                resultsDiv.innerHTML = html;
            } catch (e) {
                statusDiv.classList.add('error');
                statusDiv.innerHTML = `✗ Test failed: ${e.message}`;
                statusDiv.classList.remove('hidden');
            }
        }

        function closeTestPersonaModal() {
            document.getElementById('testPersonaModal').classList.remove('active');
            currentTestPersonaName = null;
        }

        async function activatePersona() {
            const name = document.getElementById('activePersonaSelect').value;
            const statusDiv = document.getElementById('activePersonaStatus');

            if (!name) {
                showToast('Please select a persona', 'error');
                return;
            }

            try {
                statusDiv.innerHTML = '<span style="color: var(--text-secondary);">Activating persona...</span>';
                
                await apiCall(`/personas/${name}/activate`, 'POST');
                
                statusDiv.innerHTML = '<span style="color: var(--accent-success);">✓ Persona activated successfully!</span>';
                showToast(`Persona "${name}" activated`);
                showRestartRequiredModal();
            } catch (e) {
                statusDiv.innerHTML = `<span style="color: var(--accent-danger);">✗ Failed: ${e.message}</span>`;
                showToast('Failed to activate persona: ' + e.message, 'error');
            }
        }

        // ====================================================================
        // Agent Protocol Page (Simplified)
        // ====================================================================

        async function loadAgentProtocolsPage() {
            try {
                const [plugins, config, personas] = await Promise.all([
                    apiCall('/plugins'),
                    apiCall('/config'),
                    apiCall('/personas').catch(() => [])
                ]);

                renderAgentProtocols(plugins, config, personas);
            } catch (e) {
                showToast('Failed to load agent protocols: ' + e.message, 'error');
            }
        }

        async function renderSolverPluginsFromAPI() {
            const container = document.getElementById('solversPluginsContainer');
            if (!container) return;
            try {
                const solverPlugins = await apiCall('/plugins/solvers');

                if (!solverPlugins || solverPlugins.length === 0) {
                    container.innerHTML = '<div class="empty-state"><p>No solver plugins configured in plugins_config.json</p></div>';
                    return;
                }

                let html = '<div style="display: grid; gap: 8px;">';
                for (const plugin of solverPlugins) {
                    const installPackage = plugin.install_package || plugin.package;
                    const entryPoint = plugin.entry_point;
                    const description = plugin.description || '';
                    const status = plugin.install_status;  // "installed" | "failed" | "missing"

                    let actionButton;
                    if (status === 'installed') {
                        actionButton = '<span class="badge badge-success" style="font-size: 11px;">✓ Installed</span>';
                    } else if (status === 'failed') {
                        actionButton = `<button class="btn btn-warning btn-sm" onclick="showPluginError('${entryPoint}', '${plugin.error || 'Unknown error'}')" title="${plugin.error || 'Failed to load'}">⚠️ Error</button>`;
                    } else {
                        actionButton = `<button class="btn btn-secondary btn-sm" onclick="installPluginDirect('${installPackage}', false)">Install</button>`;
                    }

                    html += `
                        <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; background: var(--bg-secondary); border-radius: var(--radius-sm); border: 1px solid var(--border-color);">
                            <div style="flex: 1; min-width: 0;">
                                <strong style="font-size: 14px;">${plugin.name}</strong>
                                <p style="font-size: 12px; color: var(--text-secondary); margin: 4px 0;">${description}</p>
                                <div style="font-size: 11px; color: var(--text-secondary);">
                                    <div>Package: <code style="color: var(--accent-primary);">${installPackage}</code></div>
                                    <div>Entry Point: <code style="color: var(--accent-primary);">${entryPoint}</code></div>
                                    ${status === 'failed' ? `<div style="color: var(--accent-warning); font-size: 10px; margin-top: 4px;">⚠️ ${plugin.error}</div>` : ''}
                                </div>
                            </div>
                            <div style="display: flex; align-items: center; gap: 12px; margin-left: 16px;">
                                ${actionButton}
                            </div>
                        </div>
                    `;
                }
                html += '</div>';
                container.innerHTML = html;
            } catch (e) {
                container.innerHTML = '<div class="empty-state"><p>Failed to load solver plugins: ' + e.message + '</p></div>';
            }
        }

        async function saveOvosAgentConfig() {
            try {
                const config = await apiCall('/config');
                config.agent_protocol = config.agent_protocol || {};
                config.agent_protocol['hivemind-ovos-agent-plugin'] = {
                    host: document.getElementById('ovosBusHost').value,
                    port: parseInt(document.getElementById('ovosBusPort').value)
                };
                await apiCall('/config', 'POST', { config });
                showToast('OVOS agent configuration saved');
                showRestartRequiredModal();
            } catch (e) {
                showToast('Failed to save OVOS config: ' + e.message, 'error');
            }
        }

        async function testOvosBusConnection() {
            const host = document.getElementById('ovosBusHost').value || '127.0.0.1';
            const port = document.getElementById('ovosBusPort').value || '8181';
            const resultDiv = document.getElementById('ovosBusTestResult');

            resultDiv.innerHTML = '<span style="color: var(--text-secondary);">Testing connection (server-side)...</span>';

            try {
                // Call backend to perform the test since the bus is internal
                const result = await apiCall(`/ovos/test-bus?host=${host}&port=${port}`);

                if (result.success) {
                    resultDiv.innerHTML = `<span style="color: var(--accent-success);">✓ ${result.message}</span>`;
                } else {
                    resultDiv.innerHTML = `<span style="color: var(--accent-danger);">❌ ${result.message}</span>`;
                }
            } catch (e) {
                resultDiv.innerHTML = '<span style="color: var(--accent-danger);">❌ API error: ' + e.message + '</span>';
            }
        }
        function renderEncodings(enabledEncodings) {
            const container = document.getElementById('encodingsContainer');
            const allEncodings = [
                { id: 'JSON-B64', name: 'JSON-B64', desc: 'Base64 encoding (recommended, most compatible)' },
                { id: 'JSON-URLSAFE-B64', name: 'JSON-URLSAFE-B64', desc: 'URL-safe Base64 encoding' },
                { id: 'JSON-B91', name: 'JSON-B91', desc: 'Base91 encoding - compact binary-to-text' },
                { id: 'JSON-Z85B', name: 'JSON-Z85B', desc: 'Z85B encoding - ZeroMQ variant' },
                { id: 'JSON-Z85P', name: 'JSON-Z85P', desc: 'Z85P encoding - Padded variant' },
                { id: 'JSON-B32', name: 'JSON-B32', desc: 'Base32 encoding - RFC 4648' },
                { id: 'JSON-HEX', name: 'JSON-HEX', desc: 'Hexadecimal encoding - most verbose but compatible' }
            ];

            let html = '';
            for (const enc of allEncodings) {
                const isEnabled = enabledEncodings.includes(enc.id);
                html += `
                    <label style="display: flex; align-items: flex-start; gap: 12px; padding: 12px; background: var(--bg-secondary); border-radius: var(--radius-sm); cursor: pointer;">
                        <input type="checkbox" class="encoding-checkbox" value="${enc.id}" ${isEnabled ? 'checked' : ''} style="width: auto; margin-top: 2px;">
                        <div>
                            <strong style="font-size: 14px;">${enc.name}</strong>
                            <p style="font-size: 12px; color: var(--text-secondary); margin-top: 2px;">${enc.desc}</p>
                        </div>
                    </label>
                `;
            }
            container.innerHTML = html;
        }

        function renderCiphers(enabledCiphers) {
            const container = document.getElementById('ciphersContainer');
            const allCiphers = [
                { id: 'CHACHA20-POLY1305', name: 'CHACHA20-POLY1305', desc: 'Modern authenticated encryption (recommended)' },
                { id: 'AES-GCM', name: 'AES-GCM', desc: 'AES-GCM authenticated encryption - hardware accelerated' }
            ];

            let html = '';
            for (const cipher of allCiphers) {
                const isEnabled = enabledCiphers.includes(cipher.id);
                html += `
                    <label style="display: flex; align-items: flex-start; gap: 12px; padding: 12px; background: var(--bg-secondary); border-radius: var(--radius-sm); cursor: pointer;">
                        <input type="checkbox" class="cipher-checkbox" value="${cipher.id}" ${isEnabled ? 'checked' : ''} style="width: auto; margin-top: 2px;">
                        <div>
                            <strong style="font-size: 14px;">${cipher.name}</strong>
                            <p style="font-size: 12px; color: var(--text-secondary); margin-top: 2px;">${cipher.desc}</p>
                        </div>
                    </label>
                `;
            }
            container.innerHTML = html;
        }

        async function saveEncodings() {
            const encodingCheckboxes = document.querySelectorAll('.encoding-checkbox:checked');
            const cipherCheckboxes = document.querySelectorAll('.cipher-checkbox:checked');

            const encodings = Array.from(encodingCheckboxes).map(cb => cb.value);
            const ciphers = Array.from(cipherCheckboxes).map(cb => cb.value);

            if (encodings.length === 0) {
                showToast('At least one encoding must be enabled', 'error');
                return;
            }

            if (ciphers.length === 0) {
                showToast('At least one cipher must be enabled', 'error');
                return;
            }

            try {
                await apiCall('/config', 'POST', {
                    config: {
                        allowed_encodings: encodings,
                        allowed_ciphers: ciphers
                    }
                });
                showToast('Encodings and ciphers updated');
                showRestartRequiredModal();
            } catch (e) {
                showToast('Failed to save: ' + e.message, 'error');
            }
        }

        // Plugins - Load all sections
        async function loadPlugins() {
            try {
                const [plugins, backends, config] = await Promise.all([
                    apiCall('/plugins'),
                    apiCall('/database/backends'),
                    apiCall('/config')
                ]);

                renderDatabaseBackends(backends, config);
                renderNetworkProtocols(plugins, config);
                renderAgentProtocols(plugins, config);
                
                // Voice Plugins (only if containers exist)
                if (document.getElementById('sttPluginsContainer')) {
                    renderVoicePlugins(plugins, 'stt', 'sttPluginsContainer');
                    renderVoicePlugins(plugins, 'tts', 'ttsPluginsContainer');
                    renderVoicePlugins(plugins, 'ww', 'wwPluginsContainer');
                    renderVoicePlugins(plugins, 'vad', 'vadPluginsContainer');
                }
            } catch (e) {
                showToast('Failed to load plugins', 'error');
            }
        }

        // Helper function to generate plugin info HTML with package and entry_point
        function getPluginInfoHtml(plugin) {
            let html = `<div style="font-weight: 600; margin-bottom: 4px;">${plugin.name}</div>`;
            
            if (plugin.description) {
                html += `<div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 6px;">${plugin.description}</div>`;
            }
            
            // Show package name
            const pkgName = plugin.package || plugin.module || plugin.entry_point || 'unknown';
            html += `<div style="font-size: 11px; color: var(--text-secondary);">Package: <code style="color: var(--accent-primary);">${pkgName}</code></div>`;
            
            // Always show entry_point
            const entryPoint = plugin.entry_point || plugin.module || pkgName;
            html += `<div style="font-size: 11px; color: var(--text-secondary);">Entry Point: <code style="color: var(--accent-primary);">${entryPoint}</code></div>`;
            
            return html;
        }

        // Database Backends
        function renderDatabaseBackends(backends, config) {
            const container = document.getElementById('databaseContainer');
            if (!container) return;
            const currentDb = config.database?.module || 'unknown';

            let html = '<div style="display: grid; gap: 12px;">';
            for (const backend of backends) {
                const pkgName = backend.package || backend.module;
                const entryPoint = backend.entry_point || backend.module;
                
                // Always match by entry_point (this is what config.database.module stores)
                const isActive = currentDb === entryPoint;

                html += `
                    <div style="display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; background: var(--bg-secondary); border-radius: var(--radius-sm); border: 2px solid ${isActive ? 'var(--accent-primary)' : 'var(--border-color)'};">
                        <div>
                            ${getPluginInfoHtml(backend)}
                            ${isActive ? '<span class="badge badge-success" style="display: inline-block; margin-top: 4px;">Active</span>' : ''}
                            <div style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">Type: ${backend.type}</div>
                        </div>
                        <div style="display: flex; align-items: center; gap: 12px;">
                            ${isActive
                                ? '<span class="badge badge-success">✓ Active</span>'
                                : backend.installed
                                    ? `<button class="btn btn-secondary btn-sm" onclick="navigate('database')" title="Configure via Database Profiles page">Manage</button>`
                                    : `<button class="btn btn-secondary btn-sm" onclick="installPluginDirect('${pkgName}')">Install</button>`
                            }
                        </div>
                    </div>
                `;
            }
            html += '</div>';
            container.innerHTML = html;
        }

        // Network Protocols
        function renderNetworkProtocols(plugins, config) {
            const container = document.getElementById('protocolsContainer');
            if (!container) return;
            const networkPlugins = plugins.filter(p => p.category === 'network');
            const activeProtocols = config.network_protocol || {};

            let html = '<div style="display: grid; gap: 12px;">';
            for (const plugin of networkPlugins) {
                const entryPoint = plugin.entry_point || plugin.module || plugin.package;
                const pkgName = plugin.package;
                // Robust detection: check for entry point OR package name in the active protocols keys
                const isEnabled = (entryPoint in activeProtocols) || (pkgName in activeProtocols);

                html += `
                    <div style="display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; background: var(--bg-secondary); border-radius: var(--radius-sm); border: 1px solid var(--border-color);">
                        <div>
                            ${getPluginInfoHtml(plugin)}
                            ${isEnabled ? '<span class="badge badge-success" style="display: inline-block; margin-top: 4px;">Enabled</span>' : ''}
                        </div>
                        <div style="display: flex; align-items: center; gap: 12px;">
                            ${isEnabled
                                ? `<button class="btn btn-danger btn-sm" onclick="toggleNetworkProtocol('${entryPoint}', false)">Disable</button>`
                                : plugin.installed
                                    ? `<button class="btn btn-primary btn-sm" onclick="showEnablePluginModal('network_protocol', '${entryPoint}', '${plugin.name}')">Enable</button>`
                                    : `<button class="btn btn-secondary btn-sm" onclick="installPluginDirect('${pkgName}')">Install</button>`
                            }
                        </div>
                    </div>
                `;
            }
            html += '</div>';
            container.innerHTML = html;
        }

        // Agent Protocols
        function renderAgentProtocols(plugins, config, personas = []) {
            const container = document.getElementById('agentProtocolsContainer');
            if (!container) return;
            const agentPlugins = plugins.filter(p => p.category === 'agent');
            const currentAgent = config.agent_protocol?.module;

            let html = '<div style="display: grid; gap: 12px;">';
            for (const plugin of agentPlugins) {
                const entryPoint = plugin.entry_point || plugin.module || plugin.package;
                const pkgName = plugin.package;

                // Use plugin.installed from /plugins endpoint
                const isInstalled = plugin.installed === true;

                // Match against either entry point or package name
                const isActive = entryPoint === currentAgent || pkgName === currentAgent;

                // Check if this is persona agent and if there are personas available
                const isPersonaAgent = entryPoint.includes('persona') || pkgName.includes('persona');
                const hasPersonas = personas && personas.length > 0;
                const canEnable = isInstalled && (!isPersonaAgent || hasPersonas);

                html += `
                    <div style="display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; background: var(--bg-secondary); border-radius: var(--radius-sm); border: 2px solid ${isActive ? 'var(--accent-primary)' : 'var(--border-color)'};">
                        <div>
                            ${getPluginInfoHtml(plugin)}
                            ${isActive ? '<span class="badge badge-success" style="display: inline-block; margin-top: 4px;">Active</span>' : ''}
                            ${isPersonaAgent && !hasPersonas ? `<div style="font-size: 11px; color: var(--accent-warning); margin-top: 4px;">⚠️ Create a persona first on the Personas page</div>` : ''}
                        </div>
                        <div style="display: flex; align-items: center; gap: 12px;">
                            ${isActive
                                ? '<span class="badge badge-success">✓ Active</span>'
                                : canEnable
                                    ? `<button class="btn btn-primary btn-sm" onclick="showEnableAgentModal('${entryPoint}', ${JSON.stringify(personas || []).replace(/"/g, '&quot;')})">Enable</button>`
                                    : isPersonaAgent && !hasPersonas
                                        ? `<button class="btn btn-secondary btn-sm" disabled style="opacity: 0.5; cursor: not-allowed;" title="Create a persona first on the Personas page">Create Persona First</button>`
                                        : `<button class="btn btn-secondary btn-sm" onclick="installPluginDirect('${pkgName}')">Install</button>`
                            }
                        </div>
                    </div>
                `;
            }
            html += '</div>';
            container.innerHTML = html;
        }

        // OVOS Voice Plugins (STT/TTS/WW/VAD for binary protocol)
        function renderVoicePlugins(plugins, category, containerId, installedPlugins = []) {
            const container = document.getElementById(containerId);
            if (!container) return;
            const categoryPlugins = plugins.filter(p => p.category === category);

            if (categoryPlugins.length === 0) {
                container.innerHTML = '<div class="empty-state" style="padding: 16px;"><p style="color: var(--text-secondary); font-size: 13px;">No plugins available</p></div>';
                return;
            }

            let html = '<div style="display: grid; gap: 8px;">';
            for (const plugin of categoryPlugins) {
                const pkgName = plugin.package;
                const entryPoint = plugin.entry_point || plugin.package;
                
                // Use install_status from API if available, otherwise check installedPlugins list
                const status = plugin.install_status;
                let actionButton;
                
                if (status === 'installed') {
                    actionButton = '<span class="badge badge-success" style="font-size: 11px;">✓ Installed</span>';
                } else if (status === 'failed') {
                    actionButton = `<button class="btn btn-warning btn-sm" onclick="showPluginError('${entryPoint}', '${plugin.error || 'Unknown error'}')" title="${plugin.error || 'Failed to load'}">⚠️ Error</button>`;
                } else {
                    // Fallback to old method if no install_status
                    const pkgLower = pkgName.toLowerCase();
                    const isInstalled = Array.isArray(installedPlugins) && installedPlugins.some(p => {
                        const pLower = p.toLowerCase();
                        return pLower === pkgLower || pLower.includes(pkgLower) || pkgLower.includes(pLower);
                    });
                    actionButton = isInstalled
                        ? '<span class="badge badge-success" style="font-size: 11px;">✓ Installed</span>'
                        : `<button class="btn btn-secondary btn-sm" onclick="installPluginDirect('${pkgName}')">Install</button>`;
                }

                html += `
                    <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; background: var(--bg-secondary); border-radius: var(--radius-sm); border: 1px solid var(--border-color);">
                        <div style="flex: 1; min-width: 0;">
                            ${getPluginInfoHtml(plugin)}
                            ${status === 'failed' ? `<div style="color: var(--accent-warning); font-size: 10px; margin-top: 4px;">⚠️ ${plugin.error}</div>` : ''}
                        </div>
                        <div style="display: flex; align-items: center; gap: 12px; margin-left: 16px;">
                            ${actionButton}
                        </div>
                    </div>
                `;
            }
            html += '</div>';
            container.innerHTML = html;
        }

        // Plugin Enable/Disable Functions

        let confirmCallback = null;

        function showConfirmModal(title, message, callback) {
            document.getElementById('confirmTitle').textContent = title;
            // confirmMessage accepts intentionally raw HTML from callers (they embed static markup)
            document.getElementById('confirmMessage').innerHTML = message;

            // Default button text
            const btn = document.getElementById('confirmBtn');
            if (btn) btn.textContent = 'Confirm';

            confirmCallback = callback;
            document.getElementById('confirmModal').classList.add('active');
        }

        function closeConfirmModal() {
            document.getElementById('confirmModal').classList.remove('active');
            confirmCallback = null;
        }

        function executeConfirm() {
            if (confirmCallback) {
                confirmCallback();
            }
            closeConfirmModal();
        }

        // Show plugin load error modal
        function showPluginError(entryPoint, errorMessage) {
            showConfirmModal(
                'Plugin Load Error',
                `Entry point <code style="background: var(--bg-secondary); padding: 4px 8px; border-radius: 4px;">${entryPoint}</code> failed to load:<br><br>
                 <code style="background: var(--bg-secondary); padding: 8px; display: block; margin: 8px 0; font-size: 11px; white-space: pre-wrap; word-break: break-word;">${errorMessage}</code><br>
                 This usually means the plugin is installed but has missing dependencies or incompatible versions.`,
                () => {
                    // Offer to reinstall
                    installPluginDirect(entryPoint, false);
                }
            );
            const confirmBtn = document.getElementById('confirmBtn');
            if (confirmBtn) {
                confirmBtn.textContent = 'Reinstall Plugin';
                confirmBtn.className = 'btn btn-primary';
            }
        }

        // Custom Plugin Installation
        function showInstallCustomPluginModal() {
            document.getElementById('customPluginPackage').value = '';
            document.getElementById('pluginDisclaimerCheckbox').checked = false;
            document.getElementById('installCustomPluginBtn').disabled = true;
            document.getElementById('installCustomPluginBtn').style.opacity = '0.5';
            document.getElementById('installCustomPluginBtn').style.cursor = 'not-allowed';
            document.getElementById('installCustomPluginModal').classList.add('active');
        }

        function closeInstallCustomPluginModal() {
            document.getElementById('installCustomPluginModal').classList.remove('active');
        }

        // Installation Progress Modal
        function showInstallProgress(packageName) {
            document.getElementById('installPackageName').textContent = packageName;
            document.getElementById('installProgressPercent').textContent = '0%';
            document.getElementById('installProgressBar').style.width = '0%';
            document.getElementById('installStatusMessage').innerHTML = `
                <div style="display: flex; align-items: center; gap: 8px;">
                    <div class="spinner" style="width: 16px; height: 16px; border-width: 2px;"></div>
                    <span style="font-size: 13px;">Starting installation...</span>
                </div>
            `;
            document.getElementById('installErrorDetails').classList.add('hidden');
            document.getElementById('installErrorDetails').style.display = 'none';
            
            const btn = document.getElementById('installProgressFooter').querySelector('button');
            btn.disabled = false;
            btn.textContent = 'Dismiss';
            btn.onclick = function() {
                closeInstallProgressModal();
            };
            
            document.getElementById('installProgressTitle').textContent = '📦 Installing Plugin...';
            document.getElementById('installProgressModal').classList.add('active');
        }

        function updateInstallProgress(percent, message, icon = '⏳') {
            document.getElementById('installProgressBar').style.width = percent + '%';
            document.getElementById('installProgressPercent').textContent = percent + '%';
            document.getElementById('installStatusMessage').innerHTML = `
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 16px;">${icon}</span>
                    <span style="font-size: 13px;">${message}</span>
                </div>
            `;
        }

        function completeInstallSuccess(message) {
            document.getElementById('installProgressTitle').textContent = '✅ Installation Successful';
            document.getElementById('installProgressBar').style.width = '100%';
            document.getElementById('installProgressPercent').textContent = '100%';
            document.getElementById('installStatusMessage').innerHTML = `
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 16px;">✅</span>
                    <span style="font-size: 13px; color: var(--accent-success);">${message}</span>
                </div>
            `;
            const btn = document.getElementById('installProgressFooter').querySelector('button');
            btn.disabled = false;
            btn.textContent = 'Close';
            btn.onclick = function() {
                closeInstallProgressModal();
                loadPlugins(); // Refresh to show installed plugin
            };
        }

        function completeInstallFailure(error, details = '') {
            document.getElementById('installProgressTitle').textContent = '❌ Installation Failed';
            document.getElementById('installProgressBar').style.background = 'var(--accent-danger)';
            document.getElementById('installStatusMessage').innerHTML = `
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 16px;">❌</span>
                    <span style="font-size: 13px; color: var(--accent-danger);">${error}</span>
                </div>
            `;

            if (details) {
                document.getElementById('installErrorText').textContent = details;
                document.getElementById('installErrorDetails').classList.remove('hidden');
                document.getElementById('installErrorDetails').style.display = 'block';
            }

            const btn = document.getElementById('installProgressFooter').querySelector('button');
            btn.disabled = false;
            btn.textContent = 'Close';
            btn.onclick = function() {
                closeInstallProgressModal();
            };
        }

        function closeInstallProgressModal() {
            document.getElementById('installProgressModal').classList.remove('active');
            // Reset progress bar color
            setTimeout(() => {
                document.getElementById('installProgressBar').style.background = 'linear-gradient(90deg, var(--accent-primary), #64ffda)';
            }, 300);
        }

        function installCustomPlugin() {
            const packageName = document.getElementById('customPluginPackage').value.trim();
            const accepted = document.getElementById('pluginDisclaimerCheckbox').checked;
            
            if (!packageName) {
                showToast('Please enter a plugin package name', 'error');
                return;
            }
            
            if (!accepted) {
                showToast('You must accept the disclaimer to continue', 'error');
                return;
            }
            
            closeInstallCustomPluginModal();
            installPluginWithProgress(packageName, true);
        }

        async function installPluginWithProgress(packageName, requiresRestart = true) {
            showInstallProgress(packageName);

            try {
                // Step 1: Start installation (10%)
                updateInstallProgress(10, 'Sending installation request...', '📡');

                const result = await apiCall('/plugins/install', 'POST', { package: packageName });

                // Check result immediately - don't continue if failed
                if (!result.success) {
                    throw new Error(result.message || 'Installation returned failure status');
                }

                // Step 2: Installation in progress (40%)
                updateInstallProgress(40, 'Downloading and installing package...', '⬇️');

                // Simulate progress while pip installs
                await simulateProgress(40, 70, 3000);

                // Step 3: Verify installation (80%)
                updateInstallProgress(80, 'Verifying installation...', '✓');

                // Check if plugin is actually installed by fetching updated list
                await new Promise(resolve => setTimeout(resolve, 1500));
                const installedPlugins = await getAllInstalledPlugins();
                const isActuallyInstalled = Array.isArray(installedPlugins) && installedPlugins.some(p =>
                    p.toLowerCase().includes(packageName.toLowerCase()) ||
                    packageName.toLowerCase().includes(p.toLowerCase())
                );

                // Step 4: Final verification (90%)
                updateInstallProgress(90, 'Checking plugin availability...', '🔍');

                // Success!
                updateInstallProgress(100, 'Installation complete!', '✅');

                completeInstallSuccess(`${packageName} installed successfully!`);

                // Refresh solver plugins list if applicable
                if (typeof renderSolverPluginsFromAPI === 'function') {
                    renderSolverPluginsFromAPI();
                }
                
                // Refresh agent protocols page if applicable
                if (typeof renderAgentProtocols === 'function' && document.getElementById('agentsPage').classList.contains('active')) {
                    loadAgentProtocolsPage();
                }

            } catch (e) {
                console.error('Installation error:', e);
                completeInstallFailure(
                    'Installation failed: ' + e.message,
                    e.stack || ''
                );
            }
        }

        function showRestartRequiredModal() {
            document.getElementById('restartRequiredModal').classList.add('active');
        }

        function closeRestartRequiredModal() {
            document.getElementById('restartRequiredModal').classList.remove('active');
            // Show banner if user chooses "Later"
            const banner = document.getElementById('restartWarningBanner');
            if (banner) {
                banner.classList.remove('hidden');
                banner.style.display = 'flex';
            }
        }

        async function restartNow() {
            closeRestartRequiredModal();
            // Update connection status to show disconnected during restart
            const statusEl = document.getElementById('connectionStatus');
            statusEl.className = 'status-indicator status-offline';
            statusEl.innerHTML = '<span class="status-dot"></span><span>Restarting...</span>';
            try {
                await apiCall('/config/restart', 'POST');
                showToast('Restart initiated. Reconnecting...');
                setTimeout(() => location.reload(), 3000);
            } catch (e) {
                showToast('Failed to restart: ' + e.message, 'error');
                // Reset status on error
                updateHealthStatus();
            }
        }

        async function showEnableAgentModal(module, personas) {
            // For persona agent, show persona selection dropdown
            if (module.includes('persona') || module.includes('hivemind-persona')) {
                if (!personas || personas.length === 0) {
                    showToast('No personas available. Create one first.', 'error');
                    return;
                }

                // Show modal with persona dropdown
                const personaSelect = document.getElementById('enableAgentPersonaSelect');
                const personaConfigSection = document.getElementById('enableAgentPersonaConfig');
                
                // Populate dropdown
                let _personaOpts = '<option value="">Select a persona...</option>';
                for (const persona of personas) {
                    _personaOpts += `<option value="${escapeHtml(persona.name)}">${escapeHtml(persona.name)}</option>`;
                }
                personaSelect.innerHTML = _personaOpts;
                
                personaConfigSection.style.display = 'block';
                document.getElementById('enableAgentModule').value = module;
                document.getElementById('enableAgentModal').classList.add('active');
            } else {
                // For other agents, enable directly
                await enableAgentProtocol(module);
            }
        }

        async function confirmEnableAgent() {
            const module = document.getElementById('enableAgentModule').value;
            const selectedPersona = document.getElementById('enableAgentPersonaSelect').value;
            const statusDiv = document.getElementById('enableAgentStatus');

            if (module.includes('persona') || module.includes('hivemind-persona')) {
                if (!selectedPersona) {
                    statusDiv.className = 'validation-result error';
                    statusDiv.innerHTML = '⚠️ Please select a persona';
                    statusDiv.classList.remove('hidden');
                    return;
                }

                // First enable the plugin
                try {
                    await apiCall('/plugins/enable', 'POST', {
                        plugin_type: 'agent_protocol',
                        module: module,
                        enabled: true
                    });

                    // Then activate the selected persona
                    await apiCall(`/personas/${selectedPersona}/activate`, 'POST');

                    showToast(`Persona agent enabled with "${selectedPersona}"`);
                    closeEnableAgentModal();
                    loadAgentProtocolsPage();
                    loadPersonasPage();
                    showRestartRequiredModal();
                } catch (e) {
                    statusDiv.className = 'validation-result error';
                    statusDiv.innerHTML = `✗ Failed: ${e.message}`;
                    statusDiv.classList.remove('hidden');
                }
            } else {
                await enableAgentProtocol(module);
            }
        }

        function closeEnableAgentModal() {
            document.getElementById('enableAgentModal').classList.remove('active');
            document.getElementById('enableAgentStatus').classList.add('hidden');
        }

        async function enableAgentProtocol(module) {
            try {
                await apiCall('/plugins/enable', 'POST', {
                    plugin_type: 'agent_protocol',
                    module: module,
                    enabled: true
                });
                showToast(`Agent protocol ${module} enabled`);
                loadPlugins();
                showRestartRequiredModal();
                // Reload agent protocols page to update config section
                if (document.getElementById('agentsPage').classList.contains('active')) {
                    loadAgentProtocolsPage();
                }
            } catch (e) {
                showToast('Failed to enable agent protocol: ' + e.message, 'error');
            }
        }

        // Binary Plugin Enabling & Configuration
        async function showEnableBinaryPluginModal(module) {
            document.getElementById('binaryPluginModule').value = module;
            document.getElementById('binaryConfigValidation').classList.add('hidden');
            
            const selects = {
                stt: document.getElementById('binarySTTSelect'),
                tts: document.getElementById('binaryTTSSelect'),
                ww: document.getElementById('binaryWWSelect'),
                vad: document.getElementById('binaryVADSelect')
            };

            // Set loading state
            for (const select of Object.values(selects)) {
                select.innerHTML = '<option value="">Loading installed plugins...</option>';
                select.disabled = true;
            }

            document.getElementById('enableBinaryPluginModal').classList.add('active');

            try {
                // Fetch actually installed plugins for each type in parallel
                const [stt, tts, ww, vad] = await Promise.all([
                    apiCall('/plugins/installed/ovos/stt'),
                    apiCall('/plugins/installed/ovos/tts'),
                    apiCall('/plugins/installed/ovos/ww'),
                    apiCall('/plugins/installed/ovos/vad')
                ]);

                const results = { stt, tts, ww, vad };

                for (const [type, list] of Object.entries(results)) {
                    const select = selects[type];
                    select.disabled = false;
                    
                    if (!list || list.length === 0) {
                        select.innerHTML = `<option value="">❌ No ${type.toUpperCase()} plugins installed</option>`;
                    } else {
                        let html = `<option value="">-- Select ${type.toUpperCase()} Plugin --</option>`;
                        html += list.map(p => `<option value="${p}">${p}</option>`).join('');
                        select.innerHTML = html;
                    }
                }
            } catch (e) {
                showToast('Failed to load OVOS plugins: ' + e.message, 'error');
            }
        }

        async function submitEnableBinaryPlugin() {
            const module = document.getElementById('binaryPluginModule').value;
            const sttModule = document.getElementById('binarySTTSelect').value;
            const ttsModule = document.getElementById('binaryTTSSelect').value;
            const wwModule = document.getElementById('binaryWWSelect').value;
            const vadModule = document.getElementById('binaryVADSelect').value;
            const wwName = document.getElementById('binaryWWName').value.trim() || 'hey_mycroft';

            const validationDiv = document.getElementById('binaryConfigValidation');
            
            // Validate all are selected
            const missing = [];
            if (!sttModule) missing.push('STT');
            if (!ttsModule) missing.push('TTS');
            if (!wwModule) missing.push('Wake Word Engine');
            if (!vadModule) missing.push('VAD');
            
            if (missing.length > 0) {
                validationDiv.textContent = `Please select: ${missing.join(', ')}`;
                validationDiv.classList.remove('hidden');
                validationDiv.style.display = 'block';
                return;
            }

            // Build complex nested configuration
            // Expected structure: 
            // {
            //   "module": "plugin-name",
            //   "plugin-name": {
            //      "stt": {"module": "stt-plugin", "stt-plugin": {}},
            //      "tts": {"module": "tts-plugin", "tts-plugin": {}},
            //      "vad": {"module": "vad-plugin", "vad-plugin": {}},
            //      "wake_word": "ww_name",
            //      "hotwords": { "ww_name": {"module": "ww-plugin", ...} }
            //   }
            // }
            const pluginConfig = {
                stt: {
                    module: sttModule,
                    [sttModule]: {}
                },
                tts: {
                    module: ttsModule,
                    [ttsModule]: {}
                },
                vad: {
                    module: vadModule,
                    [vadModule]: {}
                },
                wake_word: wwName,
                hotwords: {
                    [wwName]: {
                        module: wwModule
                    }
                }
            };

            // Add model mapping for precise-lite if detected
            if (wwModule.includes('precise-lite')) {
                pluginConfig.hotwords[wwName].model = `https://github.com/OpenVoiceOS/precise-lite-models/raw/master/wakewords/en/${wwName}.tflite`;
            }

            try {
                await apiCall('/plugins/enable', 'POST', {
                    plugin_type: 'binary_protocol',
                    module: module,
                    enabled: true,
                    config: {
                        [module]: pluginConfig
                    }
                });
                
                showToast('Binary protocol enabled and configured');
                closeEnableBinaryPluginModal();
                loadBinaryPage();
                showRestartRequiredModal();
            } catch (e) {
                validationDiv.textContent = 'Failed to enable: ' + e.message;
                validationDiv.classList.remove('hidden');
                validationDiv.style.display = 'block';
            }
        }

        async function showEnableBinaryProtocolModal(module) {
            // First, check if we have plugins installed for all required categories
            try {
                const [sttPlugins, ttsPlugins, wwPlugins, vadPlugins] = await Promise.all([
                    apiCall('/plugins/installed/ovos/stt').catch(() => []),
                    apiCall('/plugins/installed/ovos/tts').catch(() => []),
                    apiCall('/plugins/installed/ovos/ww').catch(() => []),
                    apiCall('/plugins/installed/ovos/vad').catch(() => [])
                ]);

                const missingCategories = [];
                if (!sttPlugins || sttPlugins.length === 0) missingCategories.push('STT (Speech-to-Text)');
                if (!ttsPlugins || ttsPlugins.length === 0) missingCategories.push('TTS (Text-to-Speech)');
                if (!wwPlugins || wwPlugins.length === 0) missingCategories.push('Wake Word');
                if (!vadPlugins || vadPlugins.length === 0) missingCategories.push('VAD (Voice Activity Detection)');

                if (missingCategories.length > 0) {
                    showConfirmModal(
                        'Missing Required Plugins',
                        `Cannot enable Binary Protocol. Missing plugins for:<br><br>
                        <ul style="text-align: left; margin: 16px 0;">
                            ${missingCategories.map(cat => `<li>${cat}</li>`).join('')}
                        </ul>
                        <p style="font-size: 13px; color: var(--text-secondary);">
                            Go to the OpenVoiceOS Plugins page to install the required plugins.
                        </p>`,
                        () => {
                            navigate('voice-plugins');
                        }
                    );
                    const confirmBtn = document.getElementById('confirmBtn');
                    if (confirmBtn) {
                        confirmBtn.textContent = 'Go to Plugins';
                        confirmBtn.className = 'btn btn-primary';
                    }
                    return;
                }

                // All plugins available, show configuration modal
                document.getElementById('binaryPluginModule').value = module;
                
                // Populate dropdowns
                const populateDropdown = (selectId, plugins) => {
                    const select = document.getElementById(selectId);
                    let _opts = '<option value="">Select...</option>';
                    for (const plugin of plugins) {
                        _opts += `<option value="${escapeHtml(plugin)}">${escapeHtml(plugin)}</option>`;
                    }
                    select.innerHTML = _opts;
                };

                populateDropdown('binarySTTSelect', sttPlugins);
                populateDropdown('binaryTTSSelect', ttsPlugins);
                populateDropdown('binaryWWSelect', wwPlugins);
                populateDropdown('binaryVADSelect', vadPlugins);

                document.getElementById('binaryConfigValidation').classList.add('hidden');
                document.getElementById('enableBinaryPluginModal').classList.add('active');
            } catch (e) {
                showToast('Failed to load plugin info: ' + e.message, 'error');
            }
        }

        async function confirmEnableBinaryProtocol() {
            const module = document.getElementById('binaryPluginModule').value;
            const sttModule = document.getElementById('binarySTTSelect').value;
            const ttsModule = document.getElementById('binaryTTSSelect').value;
            const wwModule = document.getElementById('binaryWWSelect').value;
            const vadModule = document.getElementById('binaryVADSelect').value;
            const wwName = document.getElementById('binaryWWName').value.trim() || 'hey_mycroft';
            const statusDiv = document.getElementById('binaryConfigValidation');

            // Validate all fields are selected
            if (!sttModule || !ttsModule || !wwModule || !vadModule) {
                statusDiv.className = 'validation-result error';
                statusDiv.innerHTML = '⚠️ Please select plugins for all categories';
                statusDiv.classList.remove('hidden');
                return;
            }

            statusDiv.className = 'validation-result';
            statusDiv.innerHTML = '<div class="spinner" style="display: inline-block; margin-right: 8px;"></div> Enabling binary protocol...';
            statusDiv.classList.remove('hidden');

            try {
                const pluginConfig = {
                    stt: { module: sttModule, [sttModule]: {} },
                    tts: { module: ttsModule, [ttsModule]: {} },
                    vad: { module: vadModule, [vadModule]: {} },
                    wake_word: wwName,
                    hotwords: {
                        [wwName]: { module: wwModule }
                    }
                };

                await apiCall('/plugins/enable', 'POST', {
                    plugin_type: 'binary_protocol',
                    module: module,
                    enabled: true,
                    config: { [module]: pluginConfig }
                });

                showToast('Binary protocol enabled successfully');
                closeEnableBinaryPluginModal();
                loadBinaryPage();
                showRestartRequiredModal();
            } catch (e) {
                statusDiv.className = 'validation-result error';
                statusDiv.innerHTML = `✗ Failed: ${e.message}`;
                statusDiv.classList.remove('hidden');
            }
        }

        function closeEnableBinaryPluginModal() {
            document.getElementById('enableBinaryPluginModal').classList.remove('active');
            document.getElementById('binaryConfigValidation').classList.add('hidden');
        }

        async function enableBinaryProtocol(module, enabled) {
            try {
                await apiCall('/plugins/enable', 'POST', {
                    plugin_type: 'binary_protocol',
                    module: module || '',
                    enabled: enabled
                });
                showToast(enabled ? 'Binary protocol enabled' : 'Binary protocol disabled');
                loadPlugins();
                showRestartRequiredModal();
            } catch (e) {
                showToast('Failed to update binary protocol: ' + e.message, 'error');
            }
        }

        async function toggleNetworkProtocol(module, enabled) {
            try {
                await apiCall('/plugins/enable', 'POST', {
                    plugin_type: 'network_protocol',
                    module: module,
                    enabled: enabled
                });
                showToast(enabled ? 'Network protocol enabled' : 'Network protocol disabled');
                loadPlugins();
                showRestartRequiredModal();
            } catch (e) {
                showToast('Failed to update network protocol: ' + e.message, 'error');
            }
        }

        // Enable Plugin Modal
        function showEnablePluginModal(type, module, name) {
            document.getElementById('enablePluginType').value = type;
            document.getElementById('enablePluginModule').value = module;
            document.getElementById('enablePluginName').value = name;

            // Show/hide network config
            const networkConfig = document.getElementById('networkProtocolConfig');
            if (type === 'network_protocol') {
                networkConfig.classList.remove('hidden');
            } else {
                networkConfig.classList.add('hidden');
            }

            document.getElementById('enablePluginStatus').classList.add('hidden');
            document.getElementById('enablePluginModal').classList.add('active');
        }

        function closeEnablePluginModal() {
            document.getElementById('enablePluginModal').classList.remove('active');
        }

        async function confirmEnablePlugin() {
            const type = document.getElementById('enablePluginType').value;
            const module = document.getElementById('enablePluginModule').value;
            const statusDiv = document.getElementById('enablePluginStatus');

            let config = {};
            if (type === 'network_protocol') {
                config = {
                    host: document.getElementById('networkHost').value,
                    port: parseInt(document.getElementById('networkPort').value),
                    ssl: document.getElementById('networkSsl').checked
                };
            }

            statusDiv.classList.remove('hidden');
            statusDiv.className = 'validation-result';
            statusDiv.innerHTML = '<div class="spinner" style="display: inline-block; margin-right: 8px;"></div> Enabling...';

            try {
                const result = await apiCall('/plugins/enable', 'POST', {
                    plugin_type: type,
                    module: module,
                    enabled: true,
                    config: config
                });

                if (result.success) {
                    statusDiv.className = 'validation-result success';
                    statusDiv.innerHTML = '✓ ' + result.message;
                    showToast(result.message);
                    setTimeout(() => {
                        closeEnablePluginModal();
                        loadPlugins();
                        showRestartRequiredModal();
                    }, 1500);
                } else {
                    statusDiv.className = 'validation-result error';
                    statusDiv.innerHTML = '✗ ' + result.message;
                }
            } catch (e) {
                statusDiv.className = 'validation-result error';
                statusDiv.innerHTML = '✗ Failed: ' + e.message;
            }
        }

        function installPluginDirect(packageName, requiresRestart = true) {
            // Use a friendlier confirmation modal for pre-defined plugins
            showConfirmModal(
                'Confirm Installation',
                `Do you want to install the plugin package "${packageName}"?`,
                () => {
                    installPluginWithProgress(packageName, requiresRestart);
                }
            );
            // Change the confirm button text to "Install" for this context
            const confirmBtn = document.getElementById('confirmBtn');
            if (confirmBtn) {
                confirmBtn.textContent = 'Install';
                confirmBtn.className = 'btn btn-primary';
            }
        }

        // ACL Management
        let currentACLClientId = null;
        let aclConfig = null;

        async function loadACLPage() {
            try {
                const [clients, config] = await Promise.all([
                    apiCall('/clients/active'),  // Only active clients for ACL dropdown
                    apiCall('/acl/config')
                ]);

                aclConfig = config;

                // Populate client dropdown (only active clients)
                const select = document.getElementById('aclClientSelect');
                select.innerHTML = '<option value="">Select a client...</option>';
                
                if (!clients || clients.length === 0) {
                    select.innerHTML += '<option value="" disabled>No active clients available</option>';
                    
                    // Show helpful message with link to create client
                    const infoDiv = document.createElement('div');
                    infoDiv.style.cssText = 'padding: 16px; background: rgba(100, 255, 218, 0.1); border: 1px solid var(--accent-primary); border-radius: var(--radius-sm); margin-top: 16px;';
                    infoDiv.innerHTML = `
                        <strong style="color: var(--accent-primary);">ℹ️ No Active Clients Found</strong>
                        <p style="font-size: 13px; color: var(--text-secondary); margin: 8px 0;">
                            You need to create at least one client before you can manage ACL permissions.
                        </p>
                        <button class="btn btn-primary btn-sm" onclick="showAddClientModal()">+ Create New Client</button>
                    `;
                    
                    // Remove any existing info div
                    const existingInfo = select.parentElement.querySelector('div[style*="rgba(100, 255, 218, 0.1)"]');
                    if (existingInfo) existingInfo.remove();
                    
                    select.parentElement.appendChild(infoDiv);
                } else {
                    // Remove any existing info div if we have clients
                    const existingInfo = select.parentElement.querySelector('div[style*="rgba(100, 255, 218, 0.1)"]');
                    if (existingInfo) existingInfo.remove();
                    
                    for (const client of clients) {
                        select.innerHTML += `<option value="${client.client_id}">${client.name} (ID: ${client.client_id})</option>`;
                    }
                }

                // Render templates
                renderACLTemplates(config.templates || []);

                // Populate quick add buttons from config
                renderQuickAddFromConfig('quickMessages', 'quickMessagesContainer', config.common_messages || [], 'aclAllowedTypes', 'type');
                renderQuickAddFromConfig('quickSkills', 'quickSkillsContainer', config.common_skills || [], 'aclSkillBlacklist', 'skill');
                renderQuickAddFromConfig('quickIntents', 'quickIntentsContainer', config.common_intents || [], 'aclIntentBlacklist', 'intent');
            } catch (e) {
                showToast('Failed to load ACL page: ' + e.message, 'error');
                console.error('ACL page load error:', e);
            }
        }

        function renderACLTemplates(templates) {
            const container = document.getElementById('aclTemplatesContainer');
            if (templates.length === 0) {
                container.innerHTML = '<span style="color: var(--text-secondary); font-size: 13px;">No templates configured</span>';
                return;
            }
            let html = '';
            for (const template of templates) {
                html += `<button class="btn btn-secondary btn-sm" onclick="applyACLTemplate('${template.name}')" title="${template.description}">${template.name}</button>`;
            }
            container.innerHTML = html;
        }

        function renderQuickAddFromConfig(containerId, wrapperId, items, targetId, key) {
            const container = document.getElementById(containerId);
            const wrapper = document.getElementById(wrapperId);
            if (items.length === 0) {
                container.innerHTML = '';
                wrapper.style.display = 'none';
                return;
            }
            wrapper.style.display = '';
            let html = '';
            for (const item of items) {
                const value = item[key];
                // Use full value for messages, only truncate skills/intents if needed
                const label = value || '';
                html += `<button class="btn btn-secondary btn-sm" onclick="addToACL('${targetId}', '${value}')" title="${item.description || value}">${label}</button>`;
            }
            container.innerHTML = html;
        }

        async function loadClientACL() {
            const clientId = document.getElementById('aclClientSelect').value;
            
            if (!clientId) {
                document.getElementById('aclEditor').classList.add('hidden');
                return;
            }

            currentACLClientId = clientId;

            try {
                const acl = await apiCall(`/clients/${clientId}/acl`);
                
                // Core permissions
                document.getElementById('aclIsAdmin').checked = acl.is_admin || false;
                document.getElementById('aclCanEscalate').checked = acl.can_escalate || false;
                document.getElementById('aclCanPropagate').checked = acl.can_propagate || false;
                
                // Message whitelist
                document.getElementById('aclAllowedTypes').value = (acl.allowed_types || []).join('\n');
                
                // Skill blacklist
                document.getElementById('aclSkillBlacklist').value = (acl.skill_blacklist || []).join('\n');
                
                // Intent blacklist
                document.getElementById('aclIntentBlacklist').value = (acl.intent_blacklist || []).join('\n');
                
                document.getElementById('aclEditor').classList.remove('hidden');
            } catch (e) {
                showToast('Failed to load client ACL: ' + e.message, 'error');
                console.error('Error loading ACL:', e);
                document.getElementById('aclEditor').classList.add('hidden');
            }
        }

        async function saveClientACL() {
            if (!currentACLClientId) return;

            const data = {
                client_id: parseInt(currentACLClientId),
                is_admin: document.getElementById('aclIsAdmin').checked,
                can_escalate: document.getElementById('aclCanEscalate').checked,
                can_propagate: document.getElementById('aclCanPropagate').checked,
                allowed_types: document.getElementById('aclAllowedTypes').value.split('\n').map(s => s.trim()).filter(s => s),
                skill_blacklist: document.getElementById('aclSkillBlacklist').value.split('\n').map(s => s.trim()).filter(s => s),
                intent_blacklist: document.getElementById('aclIntentBlacklist').value.split('\n').map(s => s.trim()).filter(s => s)
            };

            try {
                await apiCall(`/clients/${currentACLClientId}/acl`, 'PUT', data);
                showToast('ACL updated successfully');
            } catch (e) {
                showToast('Failed to update ACL: ' + e.message, 'error');
            }
        }

        async function applyACLTemplate(templateName) {
            if (!currentACLClientId) {
                showToast('Please select a client first', 'error');
                return;
            }

            showConfirmModal(
                'Apply Template',
                `Apply "${templateName}" template to this client? This will overwrite current ACL settings.`,
                async () => {
                    try {
                        const result = await apiCall(`/clients/${currentACLClientId}/acl/apply-template?template_name=${encodeURIComponent(templateName)}`, 'POST');
                        showToast(`Template "${templateName}" applied`);
                        loadClientACL();
                    } catch (e) {
                        showToast('Failed to apply template: ' + e.message, 'error');
                    }
                }
            );
        }

        function resetACLForm() {
            loadClientACL();
        }

        function addToACL(targetId, value) {
            const textarea = document.getElementById(targetId);
            const current = textarea.value.trim();
            if (current) {
                textarea.value = current + '\n' + value;
            } else {
                textarea.value = value;
            }
        }

        // Error Handling
        async function handleStartupError(health) {
            try {
                const config = await apiCall('/config');
                const validation = await apiCall('/config/validate', 'POST', { config });

                if (!validation.valid) {
                    showConfigErrorPage(validation);
                } else {
                    showErrorPage(health);
                }
            } catch (e) {
                showErrorPage(health);
            }
        }

        function showErrorPage(health) {
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.getElementById('errorPage').classList.add('active');

            let html = `<div class="error-details">`;
            html += `<p><strong>Error Type:</strong> ${health.error_type || 'Unknown'}</p>`;
            html += `<p><strong>Error Message:</strong> ${health.startup_error || 'Unknown error'}</p>`;
            html += `</div>`;

            document.getElementById('errorDetails').innerHTML = html;
        }

        function showConfigErrorPage(validation) {
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.getElementById('configErrorPage').classList.add('active');

            let html = '<h4>Configuration Errors:</h4><ul style="margin: 12px 0; padding-left: 20px;">';
            html += validation.errors.map(e => `<li style="color: var(--accent-danger); margin: 4px 0;">${e}</li>`).join('');
            html += '</ul>';

            if (validation.warnings.length) {
                html += '<h4>Warnings:</h4><ul style="margin: 12px 0; padding-left: 20px;">';
                html += validation.warnings.map(w => `<li style="color: var(--accent-warning); margin: 4px 0;">${w}</li>`).join('');
                html += '</ul>';
            }

            document.getElementById('configErrorDetails').innerHTML = html;

            apiCall('/config').then(config => {
                document.getElementById('configErrorEditor').value = JSON.stringify(config, null, 2);
            }).catch(() => {
                document.getElementById('configErrorEditor').value = '{}';
            });
        }

        async function loadDefaultsToErrorEditor() {
            try {
                const defaults = await apiCall('/config/defaults');
                document.getElementById('configErrorEditor').value = JSON.stringify(defaults, null, 2);
                showToast('Default configuration loaded');
            } catch (e) {
                showToast('Failed to load defaults', 'error');
            }
        }

        async function validateAndSaveErrorConfig() {
            const editor = document.getElementById('configErrorEditor');
            const resultDiv = document.getElementById('configErrorValidation');

            try {
                const config = JSON.parse(editor.value);
                const result = await apiCall('/config/validate', 'POST', { config });

                resultDiv.classList.remove('hidden');
                if (result.valid) {
                    await apiCall('/config', 'POST', { config });
                    resultDiv.className = 'validation-result success';
                    resultDiv.innerHTML = '<strong>✓ Configuration saved!</strong> You can now restart the service.';
                    showToast('Configuration saved');
                } else {
                    resultDiv.className = 'validation-result error';
                    resultDiv.innerHTML = '<strong>✗ Please fix these errors:</strong><ul>' +
                        result.errors.map(e => `<li>${e}</li>`).join('') + '</ul>';
                }
            } catch (e) {
                resultDiv.classList.remove('hidden');
                resultDiv.className = 'validation-result error';
                resultDiv.innerHTML = '<strong>Invalid JSON:</strong> ' + e.message;
            }
        }

        function showRestartConfirm() {
            showConfirmModal(
                'Restart HiveMind Service',
                'Are you sure you want to restart the HiveMind core service? This will disconnect all active satellites.',
                () => {
                    restartService();
                }
            );
        }

        async function restartService() {
            try {
                const result = await apiCall('/config/restart', 'POST');
                if (result.status === 'restarting') {
                    showToast(result.message);
                    setTimeout(() => location.reload(), 3000);
                } else {
                    showToast(result.message, 'error');
                }
            } catch (e) {
                showToast('Failed to restart: ' + e.message, 'error');
            }
        }

        function retryConnection() {
            location.reload();
        }

        // Toast
        function showToast(message, type = 'success') {
            const container = document.getElementById('toastContainer');
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.innerHTML = type === 'success' ? '✓ ' : type === 'error' ? '✗ ' : '⚠️ ';
            toast.innerHTML += escapeHtml(message);
            container.appendChild(toast);
            setTimeout(() => toast.remove(), 4000);
        }

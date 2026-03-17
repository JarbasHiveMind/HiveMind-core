# hivemind-core — Suggestions

## Completed Items

### Web Admin UI (2026-03-13)
- **Status**: ✅ **IMPLEMENTED**
- **Description**: Web-based administration interface integrated as optional add-on
- **Installation**: `pip install hivemind-core[admin]`
- **Usage**: `hivemind-core listen --with-admin --admin-host 0.0.0.0 --admin-port 9000`
- **Features**:
  - Dashboard with server stats and active connections
  - Client management (CRUD operations)
  - Permissions management (message types, skills, intents)
  - Config editor for network, agent, and binary protocols
  - Real-time monitoring with direct access to core objects
- **Documentation**: See [Installation Guide](docs/installation.md#install-with-web-admin-ui-optional) and [Configuration Guide](docs/configuration.md#admin_user-and-admin_pass-optional)

---

## Migration to pyproject.toml
- **Problem**: Project is still using legacy `setup.py`.
- **Proposed Solution**: Migrate to modern packaging using `pyproject.toml` with `setuptools` or `hatchling` as the build-backend.
- **Estimated Impact**: Better compliance with modern standards (PEP 517/518), cleaner dependency management.

## Refactor Legacy Terminal Authentication
- **Problem**: Some authentication logic for older terminal-style clients is mixed with core protocol handling.
- **Proposed Solution**: Decouple authentication from the main protocol factory and implement a dedicated auth-provider plugin system.
- **Estimated Impact**: Cleaner architecture and improved security.

## Improve Unit Test Coverage for Permissions
- **Problem**: Per-client permissions are critical but have limited test coverage for complex nested rules.
- **Proposed Solution**: Implement a suite of tests that specifically target permission inheritance and edge cases in the JSON-based permission store.
- **Estimated Impact**: Guaranteed security and predictable behavior for complex HiveMind deployments.

## Admin UI Enhancements

### Rate Limiting
- **Problem**: Admin API has no rate limiting protection.
- **Proposed Solution**: Add slowapi or similar rate limiting library.
- **Estimated Impact**: Protection against brute force attacks on admin credentials.

### HTTPS Support
- **Problem**: Admin UI runs on HTTP by default.
- **Proposed Solution**: Add TLS/HTTPS configuration options.
- **Estimated Impact**: Secure credential transmission in production environments.

### Audit Logging
- **Problem**: Admin actions (add client, change permissions) are not logged.
- **Proposed Solution**: Implement audit log stored in database or separate log file.
- **Estimated Impact**: Security auditing and compliance capabilities.

### Pagination in UI
- **Problem**: Client list loads all clients at once.
- **Proposed Solution**: Add pagination and search/filter in frontend.
- **Estimated Impact**: Better UX with large numbers of clients.

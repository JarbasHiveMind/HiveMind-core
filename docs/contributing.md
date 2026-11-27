# Contributing and tests
<!-- agent-hint
covers: how to set up a development environment, run the tests and open a pull request
source: pyproject.toml, conftest.py, tests/, .github/workflows/build_tests.yml, .github/workflows/integration_tests.yml, .github/workflows/coverage.yml
generated: no
verify: for w in $(grep -v '^verify:' docs/contributing.md | grep -o '[a-z_]\+\.yml' | sort -u); do test -f .github/workflows/$w || exit 1; done; for e in $(sed -n '/^### Extras/,/^### Continuous/p' docs/contributing.md | grep -o '^| `[a-z]*`' | tr -d '|` '); do grep -q "^$e = \[" pyproject.toml || exit 1; done
see: index.md
-->

This page sets up a development environment, runs the tests and describes how to send a change.

## Example

```bash
git clone https://github.com/JarbasHiveMind/HiveMind-core
cd HiveMind-core
uv venv
uv pip install --prerelease=allow -e ".[test]"
.venv/bin/python -m pytest tests -q --ignore=tests/e2e
```

The last line of the output gives the count of tests that passed and failed. No test must fail.

## Steps

1. Fork the repository and make a branch from `dev`.
2. Install the package with the `test` extra, as in the example.
3. Make the change. Add a test that fails before the change and passes after it.
4. Run the unit tests in `tests/`.
5. When the change touches `protocol.py`, `policy.py` or `database.py`, also run the tests in `tests/e2e/`. They start a real hub with the `hivescope` fixtures:

   ```bash
   uv pip install --prerelease=allow -e ".[test,integration]"
   .venv/bin/python -m pytest tests/e2e -q
   ```

6. Open a pull request against `dev`. Use a conventional commit title: `fix:`, `feat:`, `docs:`, `chore:` or `ci:`.

## Reference

### Test layout

| Path | Contents |
| :--- | :--- |
| `tests/` | unit tests |
| `tests/e2e/` | tests that start a real hub through `hivescope` |
| `conftest.py` | loads the `hivescope` pytest plugin when `hivescope` is installed |

### Extras

| Extra | Contents |
| :--- | :--- |
| `test` | `pytest`, `pytest-cov`, `hivescope` |
| `integration` | `hivescope`, `ovoscope`, `ovos-core`, `ovos-skill-hello-world` and the OpenVoiceOS packages that they need |
| `presence` | `hivemind-presence`, `hivemind-ggwave` |

### Continuous integration

| Workflow | What it runs |
| :--- | :--- |
| `build_tests.yml` | all of `tests/`, `tests/e2e/` included, with the `test` extra, on Python 3.10, 3.11, 3.12 and 3.13 |
| `integration_tests.yml` | `tests/e2e/test_query_ovoscope_e2e.py` with the `integration` extra |
| `coverage.yml` | `tests/e2e/` with the `test` extra, on Python 3.11 |
| `lint.yml` | the linter |
| `license_check.yml`, `pip_audit.yml` | dependency licences and known vulnerabilities |

### Licence

The code is under the Apache License 2.0. A contribution is under the same licence (Apache-2.0 section 5), so no separate contributor agreement is necessary. The HiveMind names and logos are trademarks and are not part of the licence. See `TRADEMARK-USAGE.md`.

---
[← Troubleshooting](troubleshooting.md) · [Home](index.md)

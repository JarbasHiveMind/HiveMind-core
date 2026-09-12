"""``add-client`` used to be a silent upsert at the CLI layer: re-running it
with an access key that already exists would demote an admin client to
non-admin and reset its password, while still printing success. Since the hub
now live-refreshes is_admin/can_* per message, that demotion hits a live
connection immediately. The CLI must refuse to overwrite an existing,
explicitly-named access key instead.
"""
import os
import tempfile

from click.testing import CliRunner

from hivemind_core.database import ClientDatabase
from hivemind_core.scripts import add_client

ACCESS_KEY = "existing-access-key-0001"

# The sqlite plugin reads $XDG_DATA_HOME at open time, so setting the env
# var here isolates the runs from a developer's real client database. The
# mock.patch of hivemind_core.config.xdg_data_home this replaces never
# reached the plugin (it imports xdg_utils.xdg_data_home itself), so on a
# box that runs a real hub the test probed and modified the live database.
data_homes = []


def _isolate_data_home():
    home = tempfile.mkdtemp(prefix="hmno-clobber-")
    data_homes.append(home)
    os.environ["XDG_DATA_HOME"] = home
    return home


def test_add_client_refuses_to_overwrite_existing_access_key():
    _isolate_data_home()
    runner = CliRunner()
    result = runner.invoke(add_client, [
        "--access-key", ACCESS_KEY,
        "--password", "correct horse battery staple 9!",
        "--admin", "True",
        "--allow-weak-password",
    ])
    assert result.exit_code == 0, result.output

    db = ClientDatabase()
    original = db.get_client_by_api_key(ACCESS_KEY)
    assert original is not None
    assert original.is_admin is True
    original_password = original.password

    # 2. re-run add-client on the SAME access key, no --admin/--password.
    result2 = runner.invoke(add_client, ["--access-key", ACCESS_KEY])
    assert result2.exit_code != 0
    assert "already exists" in result2.output

    # 3. the existing client must be untouched.
    db2 = ClientDatabase()
    after = db2.get_client_by_api_key(ACCESS_KEY)
    assert after.is_admin is True, "add-client must not demote an existing admin"
    assert after.password == original_password, "add-client must not reset an existing password"


def test_add_client_with_a_fresh_auto_generated_key_still_succeeds():
    _isolate_data_home()
    runner = CliRunner()
    result = runner.invoke(add_client, [])
    assert result.exit_code == 0, result.output
    assert "Credentials added to database!" in result.output
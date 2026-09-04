"""``add-client`` used to be a silent upsert at the CLI layer: re-running it
with an access key that already exists would demote an admin client to
non-admin and reset its password, while still printing success. Since the hub
now live-refreshes is_admin/can_* per message, that demotion hits a live
connection immediately. The CLI must refuse to overwrite an existing,
explicitly-named access key instead.
"""
import tempfile
from unittest import mock

from click.testing import CliRunner

from hivemind_core import config as C
from hivemind_core.database import ClientDatabase
from hivemind_core.scripts import add_client

ACCESS_KEY = "existing-access-key-0001"


def test_add_client_refuses_to_overwrite_existing_access_key():
    tmp = tempfile.mkdtemp()
    with mock.patch.object(C, "xdg_data_home", return_value=tmp):
        runner = CliRunner()

        # 1. create an admin client with a known password.
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
    tmp = tempfile.mkdtemp()
    with mock.patch.object(C, "xdg_data_home", return_value=tmp):
        runner = CliRunner()
        result = runner.invoke(add_client, [])
        assert result.exit_code == 0, result.output
        assert "Credentials added to database!" in result.output

# hivemind-core
# Copyright (C) 2026 Casimiro Ferreira
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
import os

import click
import json
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from hivemind_core.database import ClientDatabase
from hivemind_core.service import HiveMindService
from hivemind_core.config import get_server_config


def prompt_node_id(db: ClientDatabase) -> int:
    """
    Prompts the user to select a client ID from the database, displaying available clients in a table.
    
    If no clients are found, prints a message and exits. If multiple clients exist, presents a selection prompt; otherwise, selects the only available client.
    
    Args:
        db: The client database to query.
    
    Returns:
        The selected client ID as an integer.
    """
    table = Table(title="HiveMind Clients")
    table.add_column("ID", justify="right", style="cyan", no_wrap=True)
    table.add_column("Name", style="magenta")
    table.add_column("Allowed Msg Types", style="yellow")
    _choices = []
    for client in db:
        if client.client_id != -1:
            table.add_row(
                str(client.client_id),
                client.name,
                str(client.allowed_types),
            )
            _choices.append(str(client.client_id))

    if not _choices:
        print("No clients found!")
        exit()
    elif len(_choices) > 1:
        console = Console()
        console.print(table)
        _exit = str(max(int(i) for i in _choices) + 1)
        node_id = Prompt.ask(
            f"Which client do you want to select? ({_exit} = 'Exit')",
            choices=_choices + [_exit],
        )
        if node_id == _exit:
            console.print("User exit", style="red")
            exit()
    else:
        node_id = _choices[0]
    return node_id


@click.group(help="HiveMind-core admin CLI.")
def hmcore_cmds():
    """
    Main command group for HiveMind-core server administration.
    
    This group organizes CLI commands for managing clients, permissions, and server
    configuration in the HiveMind-core environment.
    """
    pass


@hmcore_cmds.command(help="Print HiveMind server configuration.")
def print_config():
    """
    Prints the current HiveMind server configuration as formatted JSON to the console.
    """
    cfg = get_server_config()
    cfg = json.dumps(cfg, indent=2, ensure_ascii=False)
    console = Console()
    console.print(cfg)


@hmcore_cmds.command(help="Start listening for HiveMind connections.", name="listen")
def listen():
    """
    Starts the HiveMind service and begins accepting client connections.
    """
    service = HiveMindService()
    service.run()


@hmcore_cmds.command(help="Add credentials for a new client.", name="add-client")
@click.option("--name", required=False, type=str)
@click.option("--access-key", required=False, type=str)
@click.option("--password", required=False, type=str)
@click.option("--crypto-key", required=False, type=str)
@click.option("--admin", default=False, required=False, type=bool)
def add_client(name, access_key, password, crypto_key, admin):
    """
    Adds a new client to the database, generating credentials if not provided.
    
    If a crypto key is supplied, validates its length and warns about deprecation.
    Random credentials are generated for any missing values. Prints the new client's
    credentials and admin status after successful addition.
    
    Args:
        name: Optional friendly name for the client. If not provided, a default is generated.
        access_key: Optional API access key. If not provided, a random key is generated.
        password: Optional password. If not provided, a random password is generated.
        crypto_key: Optional 16-character encryption key. If not provided, a random key is generated.
        admin: Boolean indicating whether the client should have administrator privileges.
    
    Raises:
        ValueError: If the crypto key is not exactly 16 characters, or if the client cannot be added.
    """
    key = crypto_key
    if key:
        print(
            "WARNING: crypto key is deprecated, use password instead if your client supports it"
        )
        print(
            "WARNING: for security the encryption key should be randomly generated\n"
            "Defining your own key is discouraged"
        )
        if len(key) != 16:
            print("Encryption key needs to be exactly 16 characters!")
            raise ValueError
    else:
        key = os.urandom(8).hex()

    password = password or os.urandom(16).hex()
    access_key = access_key or os.urandom(16).hex()

    with ClientDatabase() as db:
        name = name or f"HiveMind-Node-{db.total_clients()}"
        print(f"Database backend: {db.db.__class__.__name__}")
        success = db.add_client(name, access_key, crypto_key=key, password=password, admin=admin)
        if not success:
            raise ValueError(f"Error adding User to database: {name}")

        # verify
        user = db.get_client_by_api_key(access_key)
        if user is None:
            raise ValueError(f"User not found: {name}")

        print("Credentials added to database!\n")
        print("Node ID:", user.client_id)
        print("Admin Privileges:", admin)
        print("Friendly Name:", name)
        print("Access Key:", access_key)
        print("Password:", password)
        print("Encryption Key:", key)

        print(
            "WARNING: Encryption Key is deprecated, only use if your client does not support password"
        )


@hmcore_cmds.command(help="Rename a client in the database.", name="rename-client")
@click.argument("node_id", required=False, type=int)
@click.option("--name", required=False, type=str, help="The new friendly name for the client")
def rename_client(node_id, name):
    """
    Renames a client in the database to a new name.
    
    If node_id is not provided, prompts the user to select a client. Updates the client's name and prints a confirmation.
    """
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for client in db:
            if client.client_id == int(node_id):
                old_name = client.name
                client.name = name
                db.update_item(client)
                print(f"Renamed '{old_name}' to {name}")
                break
        else:
            print("Invalid Node ID!")


@hmcore_cmds.command(help="Give administrator powers to a client in the database.", name="make-admin")
@click.argument("node_id", required=False, type=int)
def make_admin(node_id):
    """
    Grants administrator privileges to a client.
    
    If the client is already an administrator, notifies the user; otherwise, updates the client's admin status.
    """
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for client in db:
            if client.client_id == int(node_id):
                if client.is_admin:
                    print(f"{client.name} is already an administrator!")
                    return
                client.is_admin = True
                db.update_item(client)
                print(f"Gave administrator powers to {client.name}")
                break

@hmcore_cmds.command(help="Revoke administrator powers from a client in the database.", name="revoke-admin")
@click.argument("node_id", required=False, type=int)
def revoke_admin(node_id):
    """
    Revokes administrator privileges from a client.
    
    If the client is currently an administrator, their admin status is removed. If the client is not an administrator, a message is printed indicating no change.
    """
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for client in db:
            if client.client_id == int(node_id):
                if not client.is_admin:
                    print(f"{client.name} is not an administrator")
                    return
                client.is_admin = False
                db.update_item(client)
                print(f"Revoked administrator powers for {client.name}")
                break
        else:
           print("Invalid Node ID!")


@hmcore_cmds.command(help="Remove credentials for a client.", name="delete-client")
@click.argument("node_id", required=False, type=int)
def delete_client(node_id):
    """
    Deletes a client's credentials from the database by node ID.
    
    If no node ID is provided, prompts the user to select a client. Prints the revoked credentials upon successful deletion, or an error message if the node ID is invalid.
    """
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for client in db:
            if client.client_id == int(node_id):
                db.delete_client(client.api_key)
                print(f"Revoked credentials!\n")
                print("Node ID:", client.client_id)
                print("Friendly Name:", client.name)
                print("Access Key:", client.api_key)
                print("Password:", client.password)
                print("Encryption Key:", client.crypto_key)
                break
        else:
            print("Invalid Node ID!")


@hmcore_cmds.command(help="List all clients and their credentials.", name="list-clients")
def list_clients():
    """
    Displays a formatted table of all clients and their credentials stored in the database.
    
    Excludes clients with a client ID of -1 from the listing. The table includes each client's ID, name, access key, password, and crypto key.
    """
    console = Console()
    table = Table(title="HiveMind Credentials:")
    table.add_column("ID", justify="center")
    table.add_column("Name", justify="center")
    table.add_column("Access Key", justify="center")
    table.add_column("Password", justify="center")
    table.add_column("Crypto Key", justify="center")

    with ClientDatabase() as db:
        for x in db:
            if x["client_id"] != -1:
                table.add_row(
                    str(x["client_id"]),
                    x["name"],
                    x["api_key"],
                    x["password"],
                    x["crypto_key"],
                )

    console.print(table)


@hmcore_cmds.command(help="Export clients and credentials to a CSV file.", name="export-clients")
@click.option("--path", required=False, type=str)
def export_clients(path):
    """
    Exports all client credentials to a CSV file or prints them to stdout.
    
    If a directory path is provided, the CSV will be saved as 'hivemind_clients.csv' in that directory. If a file path is provided, the CSV will be saved to that file. If no path is given, the CSV content is printed to stdout. Excludes clients with client_id == -1.
    
    Args:
        path: Optional file or directory path for the CSV output.
    """
    if path and os.path.isdir(path):
        path = os.path.join(path, "hivemind_clients.csv")

    CSV = "client_id,name,is_admin,access_key,password,crypto_key"
    with ClientDatabase() as db:
        for x in db:
            if x["client_id"] != -1:
                CSV += f"\n{x['client_id']},{x['name']},{x['is_admin']},{x['api_key']},{x['password']},{x['crypto_key']}"
    if path:
        with open(path, "w") as f:
            f.write(CSV)
    else:
        print(CSV)


@hmcore_cmds.command(help="Allow a message type to be sent from a client.", name="allow-msg")
@click.argument("msg_type", required=True, type=str)
@click.argument("node_id", required=False, type=int)
def allow_msg(msg_type, node_id):
    """
    Allows a specific message type for a client.
    
    If the client does not already have the message type in their allowed list, it is added and the change is saved. If the message type is already allowed, a notice is printed and the operation exits.
    
    Args:
        msg_type: The message type to allow for the client.
        node_id: The ID of the client to update. If not provided, prompts for selection.
    """
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for client in db:
            if client.client_id == int(node_id):
                if msg_type in client.allowed_types:
                    print(f"Client {client.name} already allowed '{msg_type}'")
                    exit()
                client.allowed_types.append(msg_type)
                db.update_item(client)
                print(f"Allowed '{msg_type}' for {client.name}")
                break
        else:
            print("Invalid Node ID!")


@hmcore_cmds.command(help="Blacklist a message type from a client.", name="blacklist-msg")
@click.argument("msg_type", required=True, type=str)
@click.argument("node_id", required=False, type=int)
def blacklist_msg(msg_type, node_id):
    """
    Removes a specific message type from a client's allowed list, effectively blacklisting it.
    
    If the client does not currently allow the specified message type, a notice is printed.
    """
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for client in db:
            if client.client_id == int(node_id):
                if msg_type in client.allowed_types:
                    client.allowed_types.remove(msg_type)
                    db.update_item(client)
                    print(f"Blacklisted '{msg_type}' for {client.name}")
                    return
                print(f"Client '{client.name}' message already blacklisted: '{msg_type}'")
                break
        else:
            print("Invalid Node ID!")


@hmcore_cmds.command(help="Allow 'ESCALATE' messages to be sent from a client.", name="allow-escalate")
@click.argument("node_id", required=False, type=int)
def allow_escalate(node_id):
    """
    Grants a client permission to send 'ESCALATE' messages.
    
    If the client is already allowed, notifies the user and exits. Otherwise, updates the client's permissions to allow 'ESCALATE' messages and confirms the change.
    """
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for client in db:
            if client.client_id == int(node_id):
                if client.can_escalate:
                    print(f"Client {client.name} already allowed to send 'ESCALATE' messages")
                    exit()
                client.can_escalate = True
                db.update_item(client)
                print(f"Allowed 'ESCALATE' messages for {client.name}")
                break
        else:
            print("Invalid Node ID!")


@hmcore_cmds.command(help="blacklist 'ESCALATE' messages from being sent by a client", name="blacklist-escalate")
@click.argument("node_id", required=False, type=int)
def blacklist_escalate(node_id):
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for client in db:
            if client.client_id == int(node_id):
                if client.can_escalate:
                    client.can_escalate = False
                    db.update_item(client)
                    print(f"Blacklisted 'ESCALATE' messages for {client.name}")
                    return
                print(f"Client '{client.name}' 'ESCALATE' messages already blacklisted")
                break
        else:
            print("Invalid Node ID!")


@hmcore_cmds.command(help="allow 'PROPAGATE' messages to be sent from a client", name="allow-propagate")
@click.argument("node_id", required=False, type=int)
def allow_propagate(node_id):
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for client in db:
            if client.client_id == int(node_id):
                if client.can_propagate:
                    print(f"Client {client.name} already allowed to send 'PROPAGATE' messages")
                    exit()
                client.can_propagate = True
                db.update_item(client)
                print(f"Allowed 'PROPAGATE' messages for {client.name}")
                break
        else:
            print("Invalid Node ID!")


@hmcore_cmds.command(help="blacklist 'PROPAGATE' messages from being sent by a client", name="blacklist-propagate")
@click.argument("node_id", required=False, type=int)
def blacklist_propagate(node_id):
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for client in db:
            if client.client_id == int(node_id):
                if client.can_propagate:
                    client.can_propagate = False
                    db.update_item(client)
                    print(f"Blacklisted 'PROPAGATE' messages for {client.name}")
                    return
                print(f"Client '{client.name}' 'PROPAGATE' messages already blacklisted")
                break
        else:
            print("Invalid Node ID!")


##########################
# skill/intent permissions

@hmcore_cmds.command(help="blacklist skills from being triggered by a client", name="blacklist-skill")
@click.argument("skill_id", required=True, type=str)
@click.argument("node_id", required=False, type=int)
def blacklist_skill(skill_id, node_id):
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for client in db:
            if client.client_id == int(node_id):
                if skill_id in client.skill_blacklist:
                    print(f"Client {client.name} already blacklisted '{skill_id}'")
                    exit()

                client.skill_blacklist.append(skill_id)
                db.update_item(client)
                print(f"Blacklisted '{skill_id}' for {client.name}")
                break
        else:
            print("Invalid Node ID!")


@hmcore_cmds.command(help="remove skills from a client blacklist", name="allow-skill")
@click.argument("skill_id", required=True, type=str)
@click.argument("node_id", required=False, type=int)
def unblacklist_skill(skill_id, node_id):
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for client in db:
            if client.client_id == int(node_id):
                if skill_id not in client.skill_blacklist:
                    print(f"'{skill_id}' is not blacklisted for client {client.name}")
                    exit()
                client.skill_blacklist.remove(skill_id)
                db.update_item(client)
                print(f"Blacklisted '{skill_id}' for {client.name}")
                break
        else:
            print("Invalid Node ID!")


@hmcore_cmds.command(help="blacklist intents from being triggered by a client", name="blacklist-intent")
@click.argument("intent_id", required=True, type=str)
@click.argument("node_id", required=False, type=int)
def blacklist_intent(intent_id, node_id):
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for client in db:
            if client.client_id == int(node_id):
                if intent_id in client.intent_blacklist:
                    print(f"Client {client.name} already blacklisted '{intent_id}'")
                    exit()
                client.intent_blacklist.append(intent_id)
                db.update_item(client)
                print(f"Blacklisted '{intent_id}' for {client.name}")
                break
        else:
            print("Invalid Node ID!")


@hmcore_cmds.command(help="remove intents from a client blacklist", name="allow-intent")
@click.argument("intent_id", required=True, type=str)
@click.argument("node_id", required=False, type=int)
def unblacklist_intent(intent_id, node_id):
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for client in db:
            if client.client_id == int(node_id):
                if intent_id not in client.intent_blacklist:
                    print(f" '{intent_id}' not blacklisted for Client {client.name} ")
                    exit()
                client.intent_blacklist.remove(intent_id)
                db.update_item(client)
                print(f"Unblacklisted '{intent_id}' for {client.name}")
                break
        else:
            print("Invalid Node ID!")


if __name__ == "__main__":
    hmcore_cmds()

import os

import click
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from hivemind_core.database import ClientDatabase
from hivemind_core.service import HiveMindService


def prompt_node_id(db: ClientDatabase) -> int:
    # list clients and prompt for id using rich
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
            f"which client do you want to select? ({_exit}='Exit')",
            choices=_choices + [_exit],
        )
        if node_id == _exit:
            console.print("User exit", style="red")
            exit()
    else:
        node_id = _choices[0]
    return node_id


@click.group()
def hmcore_cmds():
    pass


@hmcore_cmds.command(help="add credentials for a client", name="add-client")
@click.option("--name", required=False, type=str)
@click.option("--access-key", required=False, type=str)
@click.option("--password", required=False, type=str)
@click.option("--crypto-key", required=False, type=str)
def add_client(name, access_key, password, crypto_key):
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
        success = db.add_client(name, access_key, crypto_key=key, password=password)
        if not success:
            raise ValueError(f"Error adding User to database: {name}")

        # verify
        user = db.get_client_by_api_key(access_key)
        if user is None:
            raise ValueError(f"User not found: {name}")

        print("Credentials added to database!\n")
        print("Node ID:", user.client_id)
        print("Friendly Name:", name)
        print("Access Key:", access_key)
        print("Password:", password)
        print("Encryption Key:", key)

        print(
            "WARNING: Encryption Key is deprecated, only use if your client does not support password"
        )


@hmcore_cmds.command(help="Rename a client in the database", name="rename-client")
@click.argument("node_id", required=False, type=int)
@click.option("--name", required=False, type=str, help="The new friendly name for the client")
def rename_client(node_id, name):
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for client in db:
            if client.client_id == int(node_id):
                old_name = client.name
                client.name = name
                db.update_item(client)
                print(f"Renamed '{old_name}' to {name}")
                break


@hmcore_cmds.command(help="remove credentials for a client", name="delete-client")
@click.argument("node_id", required=False, type=int)
def delete_client(node_id):
    with ClientDatabase() as db:
        node_id = node_id or prompt_node_id(db)
        for x in db:
            if x["client_id"] == int(node_id):
                item_id = db.get_item_id(x)
                db.update_item(item_id, dict(client_id=-1, api_key="revoked"))
                print(f"Revoked credentials!\n")
                print("Node ID:", x["client_id"])
                print("Friendly Name:", x["name"])
                print("Access Key:", x["api_key"])
                print("Password:", x["password"])
                print("Encryption Key:", x["crypto_key"])
                break
        else:
            print("Invalid Node ID!")


@hmcore_cmds.command(help="list clients and credentials", name="list-clients")
def list_clients():
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


@hmcore_cmds.command(help="start listening for HiveMind connections", name="listen")
def listen():
    service = HiveMindService()
    service.run()


@hmcore_cmds.command(help="allow message types to be sent from a client", name="allow-msg")
@click.argument("msg_type", required=True, type=str)
@click.argument("node_id", required=False, type=int)
def allow_msg(msg_type, node_id):
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


@hmcore_cmds.command(help="blacklist message types from being sent from a client", name="blacklist-msg")
@click.argument("msg_type", required=True, type=str)
@click.argument("node_id", required=False, type=int)
def blacklist_msg(msg_type, node_id):
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


if __name__ == "__main__":
    hmcore_cmds()

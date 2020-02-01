from jarbas_hive_mind.database import ClientDatabase

db = ClientDatabase(debug=True)

name = "jarbas"
mail = "jarbasaai@mailfence.com"
key = "admin_key"
db.add_client(name, mail, key, admin=True)

name = "test_user"
key = "test_key"
db.add_client(name, mail, key, admin=True)

name = "Jarbas Drone"
key = "drone_key"
db.add_client(name, mail, key, admin=False)

name = "Jarbas Cli Terminal"
key = "cli_key"
db.add_client(name, mail, key, admin=False)

name = "Jarbas Remi Terminal"
key = "remi_key"
db.add_client(name, mail, key, admin=False)

name = "Jarbas Voice Terminal"
key = "voice_key"
db.add_client(name, mail, key, admin=False)

name = "Jarbas WebChat Terminal"
key = "webchat_key"
db.add_client(name, mail, key, admin=False)

name = "Jarbas HackChat Bridge"
key = "hackchat_key"
db.add_client(name, mail, key, admin=False)

name = "Jarbas Twitch Bridge"
key = "twitch_key"
db.add_client(name, mail, key, admin=False)

name = "Jarbas Facebook Bridge"
key = "fb_key"
db.add_client(name, mail, key, admin=False)

name = "Jarbas Twitter Bridge"
key = "twitter_key"
db.add_client(name, mail, key, admin=False)

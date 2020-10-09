from jarbas_hive_mind.database import ClientDatabase

name = "JarbasCliTerminal"
key = "RESISTENCEisFUTILE"
crypto_key = "resistanceISfutile"
mail = "jarbasaai@mailfence.com"


with ClientDatabase() as db:
    db.add_client(name, mail, key, crypto_key=crypto_key)

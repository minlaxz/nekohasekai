#!/usr/bin/env python3
from json import load, dump
from uuid import uuid4
import secrets

from sqlalchemy import modifier


class Modifier:
    def __init__(self):
        self.config_file = "my-config.json"
        self.user = {}

    def generate(self):
        self.user["name"] = secrets.token_hex(8)
        self.user["password"] = secrets.token_hex(8)
        self.user["uuid"] = str(uuid4())
        self.user["short_id"] = secrets.token_hex(8)

    def add_client(self, name, password, uuid, short_id):
        with open(self.config_file, "r") as f:
            configs = load(f)

        hysteria2_users = configs["inbounds"][0]["users"]
        hysteria2_users.append(
            {
                "name": name,
                "password": password,
            }
        )
        tuic_users = configs["inbounds"][1]["users"]
        tuic_users.append(
            {
                "name": name,
                "uuid": uuid,
                "password": password,
            }
        )
        naive_users = configs["inbounds"][2]["users"]
        naive_users.append(
            {
                "username": name,
                "password": password,
            }
        )
        trojan_users = configs["inbounds"][3]["users"]
        trojan_users.append(
            {
                "name": name,
                "password": password,
            }
        )
        vless_users = configs["inbounds"][4]["users"]
        vless_users.append(
            {
                "name": name,
                "uuid": uuid,
                "flow": "xtls-rprx-vision",
            }
        )
        vless_tls_reality_short_id = configs["inbounds"][4]["tls"]["reality"][
            "short_id"
        ]
        vless_tls_reality_short_id.append(short_id)
        shadowtls_users = configs["inbounds"][5]["users"]
        shadowtls_users.append(
            {
                "name": name,
                "password": password,
            }
        )

        with open(self.config_file, "w") as f:
            dump(configs, f)
        print("Client added successfully!")


if __name__ == "__main__":
    modifier = Modifier()
    name = input("Enter name: ")
    password = input("Enter password: ")
    uuid = str(uuid4())
    short_id = secrets.token_hex(8)
    modifier.add_client(name, password, uuid, short_id)

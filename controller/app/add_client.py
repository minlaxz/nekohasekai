#!/usr/bin/env python3
from json import load, dump
from uuid import uuid4
import secrets

from sqlalchemy import modifier


class Modifier:
    def __init__(self):
        self.config_file = "my-config.json"
        self.client_file = "my-client.json"
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


    def generate_config(self):
        with open(self.client_file, "r") as f:
            configs = load(f)

        sb1_hysteria2 = configs["outbounds"][6]
        sb1_hysteria2["password"] = self.user["password"]

        sb1_tuic = configs["outbounds"][7]
        sb1_tuic["uuid"] = self.user["uuid"]
        sb1_tuic["password"] = self.user["password"]

        sb1_trojan = configs["outbounds"][8]
        sb1_trojan["password"] = self.user["password"]

        sb1_vless = configs["outbounds"][9]
        sb1_vless["uuid"] = self.user["uuid"]
        sb1_vless["tls"]["reality"]["short_id"] = self.user["short_id"]

        sb1_stls = configs["outbounds"][11]
        sb1_stls["password"] = self.user["password"]

        sb2_hysteria2 = configs["outbounds"][12]
        sb2_hysteria2["password"] = self.user["password"]

        sb2_tuic = configs["outbounds"][13]
        sb2_tuic["uuid"] = self.user["uuid"]
        sb2_tuic["password"] = self.user["password"]

        sb2_trojan = configs["outbounds"][14]
        sb2_trojan["password"] = self.user["password"]

        sb2_vless = configs["outbounds"][15]
        sb2_vless["uuid"] = self.user["uuid"]
        sb2_vless["tls"]["reality"]["short_id"] = self.user["short_id"]

        sb2_stls = configs["outbounds"][17]
        sb2_stls["password"] = self.user["password"]

        return configs

if __name__ == "__main__":
    modifier = Modifier()
    name = input("Enter name: ")
    password = input("Enter password: ")
    uuid = str(uuid4())
    short_id = secrets.token_hex(8)
    modifier.add_client(name, password, uuid, short_id)

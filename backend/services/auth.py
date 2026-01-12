import json
import requests
import pyotp
from datetime import datetime,timezone


# Load user config from user.json
def load_user_config() -> dict:
    with open("storage/user.json", "r") as file:
        return json.load(file)


# Save JWT token inside user.json (update same file)
def update_user_with_token(jwt_token: str) -> None:
    with open("storage/user.json", "r") as file:
        data = json.load(file)

    data["jwtToken"] = jwt_token
    data["token_created_at"] = datetime.now(timezone.utc).isoformat()

    with open("storage/user.json", "w") as file:
        json.dump(data, file, indent=4)


# Generate 6-digit TOTP
def generate_totp(secret: str) -> str:
    return pyotp.TOTP(secret).now()


# Main login function
def angel_one_login() -> None:
    config = load_user_config()

    totp_value = generate_totp(config["totp_secret"])

    url = "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword"

    headers = {
        "User-Agent": config["user_agent"],
        "Accept": config["accept"],
        "Accept-Encoding": config["accept_encoding"],
        "Connection": config["connection"],
        "X-PrivateKey": config["private_key"],
        "X-ClientLocalIP": config["local_ip"],
        "X-ClientPublicIP": config["public_ip"],
        "X-MACAddress": config["mac_address"],
        "X-UserType": config["user_type"],
        "X-SourceID": config["source_id"]
    }

    body = {
        "clientcode": config["clientcode"],
        "password": config["password"],
        "totp": totp_value
    }

    response = requests.post(url, json=body, headers=headers)

    if response.status_code != 200:
        print("Login failed:", response.text)
        return

    data = response.json()

    if "data" in data and "jwtToken" in data["data"]:
        jwt_token = data["data"]["jwtToken"]
        update_user_with_token(jwt_token)
        print("Login Successful — JWT saved inside user.json")
    else:
        print("Login response error:", data)


if __name__ == "__main__":
    angel_one_login()

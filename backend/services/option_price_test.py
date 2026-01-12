import json
import requests

def load_user_config():
    with open("storage/user.json", "r") as f:
        return json.load(f)

config = load_user_config()
jwt_token = config["jwtToken"]

url = "https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/getLtpData"

headers = {
    "Authorization": f"Bearer {jwt_token}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-PrivateKey": config["private_key"],
    "X-ClientLocalIP": config["local_ip"],
    "X-ClientPublicIP": config["public_ip"],
    "X-MACAddress": config["mac_address"],
    "X-UserType": config["user_type"],
    "X-SourceID": config["source_id"]
}

payload = {
            "exchange": "NFO",
            "tradingsymbol": "NIFTY06JAN2625650PE",
            "symboltoken": "40450"
              
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())


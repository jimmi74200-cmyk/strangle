from py5paisa import FivePaisaClient
import config
import os

# This script will use the credentials from the config.py file
# and the get_totp_session function to authenticate and get the access token.
# The access token will then be saved to the config.py file.

# --- Robust File Path ---
script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, 'config.py')
# ------------------------

client = FivePaisaClient(cred={
    "APP_NAME": config.APP_NAME,
    "APP_SOURCE": config.APP_SOURCE,
    "USER_ID": config.USER_ID,
    "PASSWORD": config.PASSWORD,
    "USER_KEY": config.USER_KEY,
    "ENCRYPTION_KEY": config.ENCRYPTION_KEY
})

client_code = input("Enter your client code: ")
totp = input("Enter your TOTP: ")
pin = input("Enter your PIN: ")

access_token = client.get_totp_session(client_code, totp, pin)

if access_token:
    print("Login successful!")

    # Read the config file
    with open(config_path, "r") as f:
        lines = f.readlines()

    # Update the access token and client code
    with open(config_path, "w") as f:
        for line in lines:
            if line.strip().startswith("ACCESS_TOKEN"):
                f.write(f'ACCESS_TOKEN = "{access_token}"\n')
            elif line.strip().startswith("CLIENT_CODE"):
                f.write(f'CLIENT_CODE = "{client.client_code}"\n')
            else:
                f.write(line)

    print("Access token and client code have been updated in config.py")
else:
    print("Login failed.")

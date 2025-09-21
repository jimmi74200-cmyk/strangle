from py5paisa import FivePaisaClient
import config

# This script will use the credentials from the config.py file
# and the get_totp_session function to authenticate and get the access token.
# The access token will then be saved to the config.py file.

client = FivePaisaClient(cred=config.cred)

client_code = input("Enter your client code: ")
totp = input("Enter your TOTP: ")
pin = input("Enter your PIN: ")

access_token = client.get_totp_session(client_code, totp, pin)

if access_token:
    print("Login successful!")

    # Read the config file
    with open("5paisa_strangle_trader/config.py", "r") as f:
        lines = f.readlines()

    # Update the access token and client code
    with open("5paisa_strangle_trader/config.py", "w") as f:
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

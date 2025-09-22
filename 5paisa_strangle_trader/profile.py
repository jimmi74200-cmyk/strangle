from py5paisa import FivePaisaClient
import config
import json
import os

# This script fetches and displays user profile details, specifically margin information.
# It's a useful utility to check if your credentials and access token are working correctly.

def get_profile():
    """
    Initializes the client, fetches margin details, and prints them.
    """
    try:
        # Initialize the 5paisa client
        client = FivePaisaClient(cred={
            "APP_NAME": config.APP_NAME,
            "APP_SOURCE": config.APP_SOURCE,
            "USER_ID": config.USER_ID,
            "PASSWORD": config.PASSWORD,
            "USER_KEY": config.USER_KEY,
            "ENCRYPTION_KEY": config.ENCRYPTION_KEY
        })
        client.set_access_token(config.ACCESS_TOKEN, config.CLIENT_CODE)

        print("Fetching profile details...")
        margin_data = client.margin()

        if margin_data:
            print("\n--- Profile / Margin Details ---")
            # Using json.dumps for clean printing of the dictionary
            print(json.dumps(margin_data, indent=4))
            print("\nSuccessfully fetched details.")
        else:
            print("\nCould not fetch profile details. Please check your credentials and access token in config.py.")
            print("You may need to run an authentication script first.")

    except Exception as e:
        print(f"\nAn error occurred: {e}")
        print("Please check your credentials and access token in config.py.")
        print("You may need to run an authentication script first.")

if __name__ == "__main__":
    get_profile()

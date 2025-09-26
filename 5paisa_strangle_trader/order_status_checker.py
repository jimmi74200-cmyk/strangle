import logging
from py5paisa import FivePaisaClient
import config
import json

# Configure logging to show info-level messages
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def check_order_status():
    """
    A simple tool to fetch the order book and check the status of a specific order.
    """
    try:
        # --- Authenticate ---
        client = FivePaisaClient(cred={
            "APP_NAME": config.APP_NAME,
            "APP_SOURCE": config.APP_SOURCE,
            "USER_ID": config.USER_ID,
            "PASSWORD": config.PASSWORD,
            "USER_KEY": config.USER_KEY,
            "ENCRYPTION_KEY": config.ENCRYPTION_KEY
        })
        client.set_access_token(config.ACCESS_TOKEN, config.CLIENT_CODE)
        logging.info("Successfully logged in.")

    except Exception as e:
        logging.error(f"Login failed: {e}")
        return

    # --- Main Loop ---
    while True:
        try:
            # --- Get User Input ---
            broker_id_str = input("\nEnter Broker Order ID to check (or 'q' to quit): ").strip()
            if broker_id_str.lower() == 'q':
                break

            if not broker_id_str.isdigit():
                logging.warning("Please enter a valid numeric Broker Order ID.")
                continue

            broker_id = int(broker_id_str)

            # --- Fetch Order Book ---
            logging.info("Fetching order book...")
            order_book = client.order_book()

            if not order_book:
                logging.warning("Could not fetch order book or it is empty.")
                continue

            # --- Find and Display Order ---
            order_details = next((o for o in order_book if o.get('BrokerOrderID') == broker_id), None)

            if order_details:
                logging.info(f"--- ORDER FOUND (BrokerOrderID: {broker_id}) ---")
                # Pretty print the JSON details
                logging.info(json.dumps(order_details, indent=2))
                logging.info("--- END OF DETAILS ---")
            else:
                logging.warning(f"Order with Broker ID {broker_id} was NOT FOUND in the order book.")

        except ValueError:
            logging.error("Invalid input. Please enter a numeric Broker Order ID.")
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")

    logging.info("Exiting order status checker.")

if __name__ == "__main__":
    check_order_status()
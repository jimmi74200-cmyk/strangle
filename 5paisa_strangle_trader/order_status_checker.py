import logging
from py5paisa import FivePaisaClient
import config
import json

# Configure logging to show info-level messages
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def check_status():
    """
    A tool to independently check the order book and position book.
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
            print("\n--- New Query ---")
            # --- 1. Check Order Book ---
            broker_id_str = input("Enter Broker Order ID to check in ORDER BOOK (or press Enter to skip): ").strip()
            if broker_id_str:
                if broker_id_str.lower() == 'q': break

                logging.info("Fetching order book...")
                order_book = client.order_book()

                if not order_book:
                    logging.warning("ORDER BOOK: Is empty or could not be fetched.")
                else:
                    # Compare BrokerOrderId as a string, with correct case
                    order_details = next((o for o in order_book if str(o.get('BrokerOrderId')) == broker_id_str), None)
                    if order_details:
                        logging.info(f"--- ORDER BOOK: FOUND (BrokerOrderId: {broker_id_str}) ---")
                        logging.info(json.dumps(order_details, indent=2))
                    else:
                        logging.warning(f"--- ORDER BOOK: Order with Broker ID {broker_id_str} was NOT FOUND. ---")

            # --- 2. Check Position Book ---
            scrip_code_str = input("Enter Scrip Code to check in POSITION BOOK (or press Enter to skip): ").strip()
            if scrip_code_str:
                if scrip_code_str.lower() == 'q': break
                scrip_code = int(scrip_code_str)

                logging.info("Fetching position book...")
                positions = client.positions()

                if not positions:
                    logging.warning("POSITION BOOK: Is empty or could not be fetched.")
                else:
                    position_details = next((p for p in positions if p.get('ScripCode') == scrip_code), None)
                    if position_details:
                        logging.info(f"--- POSITION BOOK: FOUND (ScripCode: {scrip_code}) ---")
                        logging.info(json.dumps(position_details, indent=2))
                    else:
                        logging.warning(f"--- POSITION BOOK: Position for ScripCode {scrip_code} was NOT FOUND. ---")

        except ValueError:
            logging.error("Invalid input. Please enter a numeric ID.")
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")

    logging.info("Exiting status checker.")

if __name__ == "__main__":
    check_status()
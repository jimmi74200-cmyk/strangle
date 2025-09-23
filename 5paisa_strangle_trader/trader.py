import datetime
import logging
import schedule
import time
from py5paisa import FivePaisaClient
import config
import json
import threading
import csv
from os.path import isfile
import os
import re
import requests
import pandas as pd

# Configure logging
logging.basicConfig(level=logging.INFO)

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

def get_nearest_weekly_expiry(symbol):
    """
    Gets the nearest weekly expiry for the given symbol.
    """
    try:
        expiry_dates = client.get_expiry("N", symbol)
        if not expiry_dates or 'Expiry' not in expiry_dates:
            logging.error("Could not fetch expiry dates.")
            return None

        today = datetime.date.today()
        nearest_expiry = None
        min_diff = float('inf')

        for expiry in expiry_dates['Expiry']:
            timestamp_str = re.search(r'\d+', expiry['ExpiryDate']).group(0)
            expiry_date = datetime.datetime.fromtimestamp(int(timestamp_str) / 1000).date()
            diff = (expiry_date - today).days
            if 0 <= diff < min_diff:
                min_diff = diff
                nearest_expiry = int(timestamp_str)

        return nearest_expiry
    except Exception as e:
        logging.error(f"Error getting nearest weekly expiry: {e}")
        return None

def get_option_chain(symbol, expiry_date):
    """
    Gets the option chain for the given symbol and expiry date.
    """
    try:
        option_chain = client.get_option_chain("N", symbol, expiry_date)
        print("--- RAW OPTION CHAIN RESPONSE ---")
        print(option_chain)
        print("---------------------------------")
        if not option_chain or 'Options' not in option_chain:
            logging.error("Could not fetch option chain. API Response: %s", option_chain)
            return None
        return option_chain['Options']
    except Exception as e:
        logging.error(f"Error getting option chain: {e}")
        return None

def get_scrip_code_from_master(symbol):
    """
    Downloads the 5paisa scrip master CSV if not present,
    and finds the ScripCode for a given symbol in the cash market.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, 'scripmaster.csv')

    # Download the file if it doesn't exist
    if not os.path.exists(file_path):
        try:
            logging.info("Scrip master not found locally. Downloading from 5paisa...")
            url = "https://images.5paisa.com/website/scripmaster-csv-format.csv"
            response = requests.get(url)
            response.raise_for_status()  # Raise an exception for bad status codes
            with open(file_path, 'wb') as f:
                f.write(response.content)
            logging.info(f"Scrip master downloaded and saved to {file_path}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to download scrip master: {e}")
            return None

    # Read the CSV and find the scrip code
    try:
        df = pd.read_csv(file_path)
        # Find the index scrip in the cash market ('C')
        scrip = df[(df['Symbol'] == symbol) & (df['ExchType'] == 'C')]
        if not scrip.empty:
            scrip_code = scrip.iloc[0]['Scripcode']
            return int(scrip_code)
        else:
            logging.error(f"Could not find ScripCode for '{symbol}' in the scrip master.")
            return None
    except Exception as e:
        logging.error(f"Error reading or parsing scrip master file: {e}")
        return None

def get_spot_price(symbol):
    """
    Gets the spot price of the underlying asset by dynamically finding its ScripCode.
    """
    try:
        # Get the scrip code from the master CSV
        scrip_code = get_scrip_code_from_master(symbol)

        if not scrip_code:
            # The error is already logged by the utility function
            return None

        market_feed = client.fetch_market_feed([{"Exch": "N", "ExchType": "C", "ScripCode": scrip_code}])
        if market_feed and 'Data' in market_feed and market_feed['Data']:
            return market_feed['Data'][0]['LastRate']
        else:
            logging.error(f"Could not fetch spot price for ScripCode: {scrip_code}")
            return None
    except Exception as e:
        logging.error(f"An error occurred while getting the spot price for {symbol}: {e}")
        return None

def get_atm_strike(spot_price, strikes):
    """
    Gets the ATM strike.
    """
    return min(strikes, key=lambda x: abs(x - spot_price))

def get_otm_strikes(atm_strike, strikes, distance):
    """
    Gets the OTM strikes for the strangle.
    """
    strike_diff = strikes[1] - strikes[0]
    ce_strike = atm_strike + (distance * strike_diff)
    pe_strike = atm_strike - (distance * strike_diff)
    return ce_strike, pe_strike

def get_itm_strikes(atm_strike, strikes, distance):
    """
    Gets the ITM strikes for the strangle.
    """
    strike_diff = strikes[1] - strikes[0]
    ce_strike = atm_strike - (distance * strike_diff)
    pe_strike = atm_strike + (distance * strike_diff)
    return ce_strike, pe_strike

def select_strikes(option_chain, method, premium, spot_price):
    """
    Selects the call and put strikes based on the selected method.
    """
    if method == "NEAREST_PREMIUM":
        try:
            ce_strikes = {o['StrikeRate']: o['LastRate'] for o in option_chain if o['CPType'] == 'CE'}
            pe_strikes = {o['StrikeRate']: o['LastRate'] for o in option_chain if o['CPType'] == 'PE'}
            ce_closest_premium = min(ce_strikes.items(), key=lambda x: abs(x[1] - premium))
            pe_closest_premium = min(pe_strikes.items(), key=lambda x: abs(x[1] - premium))
            return ce_closest_premium[0], pe_closest_premium[0]
        except Exception as e:
            logging.error(f"Error selecting strikes by nearest premium: {e}")
            return None, None
    elif method == "EQUAL_PREMIUM_GAP":
        try:
            ce_options = {o['StrikeRate']: o['LastRate'] for o in option_chain if o['CPType'] == 'CE'}
            pe_options = {o['StrikeRate']: o['LastRate'] for o in option_chain if o['CPType'] == 'PE'}

            valid_pairs = []
            for ce_strike, ce_premium in ce_options.items():
                for pe_strike, pe_premium in pe_options.items():
                    if abs(ce_strike - pe_strike) == config.STRANGLE_GAP_POINTS:
                        premium_diff = abs(ce_premium - pe_premium)
                        valid_pairs.append(((ce_strike, pe_strike), premium_diff))

            if not valid_pairs:
                logging.error("No valid pairs found for the given gap.")
                return None, None

            best_pair = min(valid_pairs, key=lambda x: x[1])
            return best_pair[0]
        except Exception as e:
            logging.error(f"Error selecting strikes by equal premium gap: {e}")
            return None, None
    else:
        strikes = sorted(list(set([o['StrikeRate'] for o in option_chain])))
        atm_strike = get_atm_strike(spot_price, strikes)
        if method == "ATM":
            return atm_strike, atm_strike
        elif method == "OTM":
            return get_otm_strikes(atm_strike, strikes, config.STRANGLE_STRIKE_DISTANCE)
        elif method == "ITM":
            return get_itm_strikes(atm_strike, strikes, config.STRANGLE_STRIKE_DISTANCE)
        else:
            logging.error(f"Invalid strike selection method: {method}")
            return None, None

# Global variables
pending_sl_order_ids = []
entry_data = {}
ltp_store = {}
max_pnl = 0
trailing_sl_activated = False
ce_scrip_code = None
pe_scrip_code = None
realized_pnl = 0

def place_strangle_order():
    """
    Places a short strangle order and corresponding stop-loss orders.
    """
    global pending_sl_order_ids, entry_data, ce_scrip_code, pe_scrip_code
    logging.info("Placing strangle order...")
    nearest_expiry = get_nearest_weekly_expiry(config.SYMBOL)
    if nearest_expiry:
        logging.info(f"Nearest weekly expiry for {config.SYMBOL}: {datetime.datetime.fromtimestamp(nearest_expiry / 1000).date()}")
        option_chain = get_option_chain(config.SYMBOL, nearest_expiry)
        if option_chain:
            spot_price = get_spot_price(config.SYMBOL)
            if spot_price:
                ce_strike, pe_strike = select_strikes(option_chain, config.STRIKE_SELECTION_METHOD, config.PREMIUM, spot_price)
                if ce_strike and pe_strike:
                    logging.info(f"Selected CE strike: {ce_strike}, PE strike: {pe_strike}")

                    ce_scrip_code = next((o['ScripCode'] for o in option_chain if o['StrikeRate'] == ce_strike and o['CPType'] == 'CE'), None)
                    pe_scrip_code = next((o['ScripCode'] for o in option_chain if o['StrikeRate'] == pe_strike and o['CPType'] == 'PE'), None)

                    if ce_scrip_code and pe_scrip_code:
                        if config.PAPER_TRADING:
                            logging.info(f"[PAPER TRADE] Would place SELL order for CE {ce_strike} and PE {pe_strike}.")
                            # Simulate entry for paper trading
                            entry_data[ce_scrip_code] = {'strike': ce_strike, 'entry_price': 100} # Dummy premium
                            entry_data[pe_scrip_code] = {'strike': pe_strike, 'entry_price': 100} # Dummy premium
                        else:
                            # Place real sell orders
                            client.place_order(OrderType='S', Exchange='N', ExchangeType='D', ScripCode=ce_scrip_code, Qty=config.QTY, Price=0, IsIntraday=True)
                            client.place_order(OrderType='S', Exchange='N', ExchangeType='D', ScripCode=pe_scrip_code, Qty=config.QTY, Price=0, IsIntraday=True)
                            logging.info("Strangle orders placed.")

                            # Wait and poll for positions to get entry prices
                            time.sleep(5) # Allow time for orders to execute
                            positions = client.positions()
                            if positions and 'NetPositionDetail' in positions:
                                for p in positions['NetPositionDetail']:
                                    if p['ScripCode'] == ce_scrip_code:
                                        entry_data[ce_scrip_code] = {'strike': ce_strike, 'entry_price': p['SellAvg']}
                                        stop_loss_price = p['SellAvg'] + config.LEG_WISE_SL_POINTS
                                        limit_price = stop_loss_price + config.SL_LIMIT_BUFFER
                                        sl_order = client.place_order(OrderType='B', Exchange='N', ExchangeType='D', ScripCode=ce_scrip_code, Qty=p['NetQty'], Price=limit_price, StopLossPrice=stop_loss_price, IsIntraday=True)
                                        if sl_order and 'ExchOrderID' in sl_order:
                                            pending_sl_order_ids.append(sl_order['ExchOrderID'])
                                            logging.info(f"Placed SL order for {p['ScripName']} at {stop_loss_price}. Order ID: {sl_order['ExchOrderID']}")
                                    elif p['ScripCode'] == pe_scrip_code:
                                        entry_data[pe_scrip_code] = {'strike': pe_strike, 'entry_price': p['SellAvg']}
                                        stop_loss_price = p['SellAvg'] + config.LEG_WISE_SL_POINTS
                                        limit_price = stop_loss_price + config.SL_LIMIT_BUFFER
                                        sl_order = client.place_order(OrderType='B', Exchange='N', ExchangeType='D', ScripCode=pe_scrip_code, Qty=p['NetQty'], Price=limit_price, StopLossPrice=stop_loss_price, IsIntraday=True)
                                        if sl_order and 'ExchOrderID' in sl_order:
                                            pending_sl_order_ids.append(sl_order['ExchOrderID'])
                                            logging.info(f"Placed SL order for {p['ScripName']} at {stop_loss_price}. Order ID: {sl_order['ExchOrderID']}")

                        subscribe_to_websocket(ce_scrip_code, pe_scrip_code)
                    else:
                        logging.error("Could not get scrip codes.")
                else:
                    logging.error("Could not select strikes.")
            else:
                logging.error("Could not fetch spot price.")
        else:
            logging.error("Could not get option chain.")
    else:
        logging.error("Could not find nearest expiry.")

def on_message(ws, message):
    """
    Callback function for websocket messages.
    """
    logging.info(f"Raw websocket message: {message}")
    try:
        data = json.loads(message)
        if "Token" in data and "LastRate" in data:
            scrip_code = data["Token"]
            ltp = data["LastRate"]
            monitor_and_manage(scrip_code, ltp)
        else:
            logging.warning(f"Unexpected websocket message format: {data}")
    except Exception as e:
        logging.error(f"Error parsing websocket message: {e}")

def monitor_and_manage(scrip_code, ltp):
    """
    Monitors the overall P&L and manages risk based on overall SL, target, and trailing SL.
    """
    global max_pnl, trailing_sl_activated, realized_pnl
    ltp_store[scrip_code] = ltp

    # Wait until we have the LTP for both legs
    if len(ltp_store) < 2:
        return

    # Calculate overall P&L
    unrealized_pnl = 0
    for code, data in entry_data.items():
        if code in ltp_store: # Only calculate for open positions
            current_ltp = ltp_store.get(code, data['entry_price'])
            unrealized_pnl += (data['entry_price'] - current_ltp) * config.QTY

    total_pnl = unrealized_pnl + realized_pnl
    logging.info(f"Total P&L: {total_pnl} (Realized: {realized_pnl}, Unrealized: {unrealized_pnl})")

    # Overall SL and Target
    if total_pnl <= config.OVERALL_SL:
        exit_positions(reason="OVERALL_SL_HIT")
        return
    if total_pnl >= config.OVERALL_TARGET:
        exit_positions(reason="OVERALL_TARGET_HIT")
        return

    # Trailing SL
    if not trailing_sl_activated and total_pnl >= config.TRAILING_PROFIT_TRIGGER:
        trailing_sl_activated = True
        logging.info("Trailing stop-loss activated.")

    if trailing_sl_activated:
        if total_pnl > max_pnl:
            max_pnl = total_pnl

        # Calculate trailing SL steps
        steps = int(max_pnl / config.TRAILING_PROFIT_TRIGGER)
        trailing_sl = steps * config.TRAILING_PROFIT_LOCKIN

        if total_pnl < trailing_sl:
            exit_positions(reason="TRAILING_SL_HIT")
            return

def run_websocket(req_data):
    """
    Runs the websocket connection.
    """
    client.connect(req_data)
    client.receive_data(on_message)

def monitor_positions():
    """
    Periodically checks the positions to see if a leg has been closed.
    """
    global ce_scrip_code, pe_scrip_code, realized_pnl
    initial_position_count = 2

    while True:
        try:
            positions = client.positions()
            if positions and 'NetPositionDetail' in positions:
                current_positions = [p for p in positions['NetPositionDetail'] if p['ScripCode'] in [ce_scrip_code, pe_scrip_code]]
                current_position_count = len(current_positions)

                if initial_position_count == 2 and current_position_count == 1:
                    logging.info("One leg has been closed.")

                    # Find the closed leg and calculate realized P&L
                    closed_leg_scrip_code = list(set([ce_scrip_code, pe_scrip_code]) - set([p['ScripCode'] for p in current_positions]))[0]
                    tradebook = client.get_tradebook()
                    if tradebook and 'TradeBookDetail' in tradebook:
                        for trade in tradebook['TradeBookDetail']:
                            if trade['ScripCode'] == closed_leg_scrip_code and trade['BuySell'] == 'B':
                                realized_pnl = (entry_data[closed_leg_scrip_code]['entry_price'] - trade['Rate']) * trade['Qty']
                                logging.info(f"Realized P&L for closed leg {closed_leg_scrip_code}: {realized_pnl}")
                                break

                    if config.EXIT_STRATEGY_ON_LEG_SL_HIT:
                        exit_positions(reason="LEG_SL_HIT")
                        break # Stop monitoring positions

                initial_position_count = current_position_count

            time.sleep(10) # Check every 10 seconds
        except Exception as e:
            logging.error(f"Error in position monitoring thread: {e}")
            time.sleep(10)

def subscribe_to_websocket(ce_scrip_code, pe_scrip_code):
    """
    Subscribes to the websocket feed and starts the position monitor.
    """
    logging.info("Subscribing to websocket feed...")
    req_list = [
        {"Exch": "N", "ExchType": "D", "ScripCode": ce_scrip_code},
        {"Exch": "N", "ExchType": "D", "ScripCode": pe_scrip_code},
    ]
    req_data = client.Request_Feed('mf', 's', req_list)

    # Run the websocket in a separate thread
    ws_thread = threading.Thread(target=run_websocket, args=(req_data,))
    ws_thread.daemon = True
    ws_thread.start()

    # Start the position monitoring thread
    pm_thread = threading.Thread(target=monitor_positions)
    pm_thread.daemon = True
    pm_thread.start()

def log_trade_to_csv(trade_data):
    """
    Logs the details of a completed trade to a CSV file.
    """
    # --- Robust File Path ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, 'trade_log.csv')
    # ------------------------
    file_exists = isfile(file_path)

    with open(file_path, 'a', newline='') as csvfile:
        fieldnames = [
            'Date', 'Symbol', 'EntryTime', 'ExitTime', 'Call_Strike', 'Put_Strike',
            'Call_Entry_Premium', 'Put_Entry_Premium', 'Call_Exit_Price', 'Put_Exit_Price',
            'Final_PnL', 'Exit_Reason', 'Trade_Mode'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        writer.writerow(trade_data)

def exit_positions(reason="Unknown"):
    """
    Logs the trade, cancels pending SL orders, and exits all open positions.
    """
    global pending_sl_order_ids, entry_data, realized_pnl, ce_scrip_code, pe_scrip_code, ltp_store
    logging.info(f"Exiting all positions due to: {reason}")

    ce_exit_price = 0
    pe_exit_price = 0
    final_pnl = 0

    if config.PAPER_TRADING:
        logging.info("[PAPER TRADE] Simulating exit and logging trade.")
        ce_exit_price = ltp_store.get(ce_scrip_code, 0)
        pe_exit_price = ltp_store.get(pe_scrip_code, 0)

        ce_pnl = (entry_data.get(ce_scrip_code, {}).get('entry_price', 0) - ce_exit_price) * config.QTY
        pe_pnl = (entry_data.get(pe_scrip_code, {}).get('entry_price', 0) - pe_exit_price) * config.QTY
        final_pnl = ce_pnl + pe_pnl
    else:
        # Cancel pending SL orders first
        for order_id in pending_sl_order_ids:
            try:
                logging.info(f"Cancelling pending SL order: {order_id}")
                client.cancel_order(order_id)
            except Exception as e:
                logging.error(f"Error cancelling order {order_id}: {e}")

        # Square off all open positions
        client.squareoff_all()
        logging.info("All positions squared off. Waiting for trade confirmation...")

        # Allow time for positions to update
        time.sleep(5)

        # Get final position details for logging
        final_positions = client.positions()
        if final_positions and 'NetPositionDetail' in final_positions:
            for p in final_positions['NetPositionDetail']:
                if p['ScripCode'] == ce_scrip_code:
                    ce_exit_price = p['BuyAvg'] # After squaring off, BuyAvg is the exit price
                    final_pnl += p['RealizedPL']
                elif p['ScripCode'] == pe_scrip_code:
                    pe_exit_price = p['BuyAvg']
                    final_pnl += p['RealizedPL']

    # Log the trade
    trade_data = {
        'Date': datetime.date.today().isoformat(),
        'Symbol': config.SYMBOL,
        'EntryTime': config.ENTRY_TIME,
        'ExitTime': datetime.datetime.now().strftime("%H:%M:%S"),
        'Call_Strike': entry_data.get(ce_scrip_code, {}).get('strike', 0),
        'Put_Strike': entry_data.get(pe_scrip_code, {}).get('strike', 0),
        'Call_Entry_Premium': entry_data.get(ce_scrip_code, {}).get('entry_price', 0),
        'Put_Entry_Premium': entry_data.get(pe_scrip_code, {}).get('entry_price', 0),
        'Call_Exit_Price': ce_exit_price,
        'Put_Exit_Price': pe_exit_price,
        'Final_PnL': final_pnl,
        'Exit_Reason': reason,
        'Trade_Mode': 'PAPER' if config.PAPER_TRADING else 'LIVE'
    }
    log_trade_to_csv(trade_data)

    # Clear state for next trade
    pending_sl_order_ids = []
    entry_data = {}
    ltp_store = {}
    realized_pnl = 0

if __name__ == "__main__":
    logging.info("Starting trading bot...")
    schedule.every().day.at(config.ENTRY_TIME).do(place_strangle_order)
    schedule.every().day.at(config.EXIT_TIME).do(lambda: exit_positions(reason="TIMED_EXIT"))

    while True:
        schedule.run_pending()
        time.sleep(1)

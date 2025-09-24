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
import websockets
import asyncio
import queue

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Global State ---
client = FivePaisaClient(cred={
    "APP_NAME": config.APP_NAME,
    "APP_SOURCE": config.APP_SOURCE,
    "USER_ID": config.USER_ID,
    "PASSWORD": config.PASSWORD,
    "USER_KEY": config.USER_KEY,
    "ENCRYPTION_KEY": config.ENCRYPTION_KEY
})
client.set_access_token(config.ACCESS_TOKEN, config.CLIENT_CODE)

ltp_store = {}
action_queue = queue.Queue()
pending_sl_order_ids = []
entry_data = {}
max_pnl = 0
trailing_sl_activated = False
ce_scrip_code = None
pe_scrip_code = None
realized_pnl = 0
trade_is_active = False
ws_manager = None

# --- WebSocket Manager ---
class WebSocketManager:
    def __init__(self):
        self._ws_url = f"wss://openfeed.5paisa.com/feeds/api/chat?Value1={config.ACCESS_TOKEN}|{config.CLIENT_CODE}"
        self._thread = None
        self._subscription_queue = queue.Queue()
        self.is_connected = False

    def _get_initial_subscription_msg(self):
        scrip_info = get_scrip_from_local_file(config.SYMBOL)
        if not scrip_info:
            logging.error(f"Cannot get initial subscription for {config.SYMBOL}.")
            return None
        return json.dumps({
            "Method": "MarketFeedV3", "Operation": "Subscribe", "ClientCode": config.CLIENT_CODE,
            "MarketFeedData": [{"Exch": scrip_info["Exch"], "ExchType": scrip_info["ExchType"], "ScripCode": scrip_info["ScripCode"]}]
        })

    async def _run(self):
        logging.info("Attempting to connect to websocket...")
        try:
            async with websockets.connect(self._ws_url) as websocket:
                self.is_connected = True
                logging.info("WebSocket connected successfully.")
                initial_sub_msg = self._get_initial_subscription_msg()
                if initial_sub_msg:
                    await websocket.send(initial_sub_msg)
                    logging.info(f"Sent initial subscription for {config.SYMBOL}")
                while self.is_connected:
                    try:
                        while not self._subscription_queue.empty():
                            message = self._subscription_queue.get_nowait()
                            await websocket.send(json.dumps(message))
                            logging.info(f"Sent message from queue: {message}")
                        message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        self._on_message(message)
                    except asyncio.TimeoutError:
                        continue
                    except websockets.exceptions.ConnectionClosed:
                        logging.warning("WebSocket connection closed.")
                        break
                    except Exception as e:
                        logging.error(f"Error in websocket run loop: {e}")
                        await asyncio.sleep(1)
        except Exception as e:
            logging.error(f"Failed to connect to websocket: {e}")
        finally:
            self.is_connected = False
            logging.info("WebSocket run loop finished.")

    def _on_message(self, message):
        try:
            data_list = json.loads(message)
            for data in data_list:
                if "Token" in data and "LastRate" in data:
                    scrip_code = data["Token"]
                    ltp_store[scrip_code] = data["LastRate"]
                    if trade_is_active and scrip_code in [ce_scrip_code, pe_scrip_code]:
                        check_trade_conditions()
        except Exception as e:
            logging.error(f"Error parsing websocket message: {message} - {e}")

    def start(self):
        self._thread = threading.Thread(target=lambda: asyncio.run(self._run()))
        self._thread.daemon = True
        self._thread.start()

    def subscribe(self, scrips):
        self._subscription_queue.put({
            "Method": "MarketFeedV3", "Operation": "Subscribe", "ClientCode": config.CLIENT_CODE, "MarketFeedData": scrips
        })

    def unsubscribe(self, scrips):
        self._subscription_queue.put({
            "Method": "MarketFeedV3", "Operation": "Unsubscribe", "ClientCode": config.CLIENT_CODE, "MarketFeedData": scrips
        })

# --- Data and Trading Logic ---

def get_nearest_weekly_expiry(symbol):
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
    try:
        option_chain = client.get_option_chain("N", symbol, expiry_date)
        if not option_chain or 'Options' not in option_chain or not option_chain['Options']:
            logging.error("Could not fetch option chain or it was empty. API Response: %s", option_chain)
            return None
        return option_chain['Options']
    except Exception as e:
        logging.error(f"Error getting option chain: {e}")
        return None

def get_scrip_from_local_file(symbol):
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(script_dir, 'scrip_data.json')
        with open(file_path, 'r') as f:
            scrip_data = json.load(f)
        return scrip_data.get(symbol)
    except Exception as e:
        logging.error(f"Error reading scrip_data.json: {e}")
        return None

def get_spot_price(symbol):
    try:
        scrip_info = get_scrip_from_local_file(symbol)
        if not scrip_info: return None
        scrip_code = scrip_info["ScripCode"]
        timeout = 10
        start_time = time.time()
        while scrip_code not in ltp_store:
            if time.time() - start_time > timeout:
                logging.error(f"Timed out waiting for spot price for {symbol} (ScripCode: {scrip_code}).")
                return None
            time.sleep(0.1)
        return ltp_store[scrip_code]
    except Exception as e:
        logging.error(f"An error occurred while getting the spot price for {symbol}: {e}")
        return None

def get_atm_strike(spot_price, strikes):
    return min(strikes, key=lambda x: abs(x - spot_price))

def get_otm_strikes(atm_strike, strikes, distance):
    strike_diff = strikes[1] - strikes[0]
    return atm_strike + (distance * strike_diff), atm_strike - (distance * strike_diff)

def get_itm_strikes(atm_strike, strikes, distance):
    strike_diff = strikes[1] - strikes[0]
    return atm_strike - (distance * strike_diff), atm_strike + (distance * strike_diff)

def select_strikes(option_chain, method, premium, spot_price):
    if method == "NEAREST_PREMIUM":
        try:
            ce_strikes = {o['StrikeRate']: o['LastRate'] for o in option_chain if o['CPType'] == 'CE'}
            pe_strikes = {o['StrikeRate']: o['LastRate'] for o in option_chain if o['CPType'] == 'PE'}
            if not ce_strikes or not pe_strikes:
                logging.error("Could not find CE or PE strikes in option chain.")
                return None, None
            ce_closest_premium = min(ce_strikes.items(), key=lambda x: abs(x[1] - premium))
            pe_closest_premium = min(pe_strikes.items(), key=lambda x: abs(x[1] - premium))
            return ce_closest_premium[0], pe_closest_premium[0]
        except Exception as e:
            logging.error(f"Error selecting strikes by nearest premium: {e}")
            return None, None
    elif method == "EQUAL_PREMIUM_GAP":
        try:
            strikes = sorted(list(set([o['StrikeRate'] for o in option_chain])))
            if len(strikes) < 2:
                logging.error("Not enough strikes in option chain to determine interval.")
                return None, None
            strike_interval = strikes[1] - strikes[0]

            atm_strike = get_atm_strike(spot_price, strikes)

            ce_options = {o['StrikeRate']: o['LastRate'] for o in option_chain if o['CPType'] == 'CE'}
            pe_options = {o['StrikeRate']: o['LastRate'] for o in option_chain if o['CPType'] == 'PE'}

            valid_pairs = []
            # Check a range of strikes around the ATM strike
            # The range defines how far from the ATM we are willing to look for the PE leg
            for i in range(-5, 6):
                put_strike_candidate = atm_strike + (i * strike_interval)
                call_strike_candidate = put_strike_candidate + config.STRANGLE_GAP_POINTS

                if call_strike_candidate in ce_options and put_strike_candidate in pe_options:
                    ce_premium = ce_options[call_strike_candidate]
                    pe_premium = pe_options[put_strike_candidate]
                    premium_diff = abs(ce_premium - pe_premium)
                    valid_pairs.append(((call_strike_candidate, put_strike_candidate), premium_diff))

            if not valid_pairs:
                logging.error("No valid pairs found for the given gap around the ATM.")
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

def place_strangle_order():
    global pending_sl_order_ids, entry_data, ce_scrip_code, pe_scrip_code, trade_is_active
    if trade_is_active:
        logging.warning("A trade is already active. Skipping new order placement.")
        return

    logging.info("Attempting to place strangle order...")
    nearest_expiry = get_nearest_weekly_expiry(config.SYMBOL)
    if not nearest_expiry: return
    option_chain = get_option_chain(config.SYMBOL, nearest_expiry)
    if not option_chain: return
    spot_price = get_spot_price(config.SYMBOL)
    if not spot_price: return

    logging.info(f"Current {config.SYMBOL} spot price: {spot_price}")
    ce_strike, pe_strike = select_strikes(option_chain, config.STRIKE_SELECTION_METHOD, config.PREMIUM, spot_price)

    if ce_strike and pe_strike:
        logging.info(f"Selected CE strike: {ce_strike}, PE strike: {pe_strike}")
        ce_scrip_code = next((o['ScripCode'] for o in option_chain if o['StrikeRate'] == ce_strike and o['CPType'] == 'CE'), None)
        pe_scrip_code = next((o['ScripCode'] for o in option_chain if o['StrikeRate'] == pe_strike and o['CPType'] == 'PE'), None)

        if ce_scrip_code and pe_scrip_code:
            if config.PAPER_TRADING:
                logging.info(f"[PAPER TRADE] Placing SELL order for CE {ce_strike} and PE {pe_strike}.")
                entry_data[ce_scrip_code] = {'strike': ce_strike, 'entry_price': 100}
                entry_data[pe_scrip_code] = {'strike': pe_strike, 'entry_price': 100}
            else:
                client.place_order(OrderType='S', Exchange='N', ExchangeType='D', ScripCode=ce_scrip_code, Qty=config.QTY, Price=0, IsIntraday=True)
                client.place_order(OrderType='S', Exchange='N', ExchangeType='D', ScripCode=pe_scrip_code, Qty=config.QTY, Price=0, IsIntraday=True)
                logging.info("Strangle orders placed. Waiting 5s for execution details...")
                time.sleep(5)
                positions = client.positions()
                if positions and 'NetPositionDetail' in positions:
                    for p in positions['NetPositionDetail']:
                        if p['ScripCode'] == ce_scrip_code:
                            entry_data[ce_scrip_code] = {'strike': ce_strike, 'entry_price': p['SellAvg']}
                            sl_price = p['SellAvg'] + config.LEG_WISE_SL_POINTS
                            limit_price = sl_price + config.SL_LIMIT_BUFFER
                            sl_order = client.place_order(OrderType='B', Exchange='N', ExchangeType='D', ScripCode=ce_scrip_code, Qty=p['NetQty'], Price=limit_price, StopLossPrice=sl_price, IsIntraday=True)
                            if sl_order and 'ExchOrderID' in sl_order: pending_sl_order_ids.append(sl_order['ExchOrderID'])
                        elif p['ScripCode'] == pe_scrip_code:
                            entry_data[pe_scrip_code] = {'strike': pe_strike, 'entry_price': p['SellAvg']}
                            sl_price = p['SellAvg'] + config.LEG_WISE_SL_POINTS
                            limit_price = sl_price + config.SL_LIMIT_BUFFER
                            sl_order = client.place_order(OrderType='B', Exchange='N', ExchangeType='D', ScripCode=pe_scrip_code, Qty=p['NetQty'], Price=limit_price, StopLossPrice=sl_price, IsIntraday=True)
                            if sl_order and 'ExchOrderID' in sl_order: pending_sl_order_ids.append(sl_order['ExchOrderID'])

            ws_manager.subscribe([
                {"Exch": "N", "ExchType": "D", "ScripCode": ce_scrip_code},
                {"Exch": "N", "ExchType": "D", "ScripCode": pe_scrip_code}
            ])
            trade_is_active = True
            logging.info("Trade is now active.")
        else:
            logging.error("Could not find scrip codes for selected strikes.")
    else:
        logging.error("Could not select strikes.")

def check_trade_conditions():
    global max_pnl, trailing_sl_activated
    if not all(k in ltp_store for k in [ce_scrip_code, pe_scrip_code]):
        return
    ce_ltp = ltp_store.get(ce_scrip_code)
    pe_ltp = ltp_store.get(pe_scrip_code)
    ce_pnl = (entry_data[ce_scrip_code]['entry_price'] - ce_ltp) * config.QTY
    pe_pnl = (entry_data[pe_scrip_code]['entry_price'] - pe_ltp) * config.QTY
    total_pnl = ce_pnl + pe_pnl + realized_pnl

    if total_pnl <= config.OVERALL_SL:
        action_queue.put({'action': 'exit', 'reason': 'OVERALL_SL_HIT'})
    elif total_pnl >= config.OVERALL_TARGET:
        action_queue.put({'action': 'exit', 'reason': 'OVERALL_TARGET_HIT'})
    elif trailing_sl_activated:
        if total_pnl > max_pnl: max_pnl = total_pnl
        trailing_sl = (int(max_pnl / config.TRAILING_PROFIT_TRIGGER)) * config.TRAILING_PROFIT_LOCKIN
        if total_pnl < trailing_sl:
            action_queue.put({'action': 'exit', 'reason': 'TRAILING_SL_HIT'})
    elif not trailing_sl_activated and total_pnl >= config.TRAILING_PROFIT_TRIGGER:
        trailing_sl_activated = True
        logging.info("Trailing stop-loss activated.")

def exit_positions(reason="Unknown"):
    global pending_sl_order_ids, entry_data, realized_pnl, ce_scrip_code, pe_scrip_code, trade_is_active, max_pnl, trailing_sl_activated
    if not trade_is_active: return
    logging.info(f"Exiting all positions due to: {reason}")
    if ws_manager and ce_scrip_code and pe_scrip_code:
        ws_manager.unsubscribe([
            {"Exch": "N", "ExchType": "D", "ScripCode": ce_scrip_code},
            {"Exch": "N", "ExchType": "D", "ScripCode": pe_scrip_code}
        ])

    ce_exit_price = ltp_store.get(ce_scrip_code, 0)
    pe_exit_price = ltp_store.get(pe_scrip_code, 0)
    final_pnl = 0
    if config.PAPER_TRADING:
        ce_pnl = (entry_data.get(ce_scrip_code, {}).get('entry_price', 0) - ce_exit_price) * config.QTY
        pe_pnl = (entry_data.get(pe_scrip_code, {}).get('entry_price', 0) - pe_exit_price) * config.QTY
        final_pnl = ce_pnl + pe_pnl
    else:
        for order_id in pending_sl_order_ids:
            try: client.cancel_order(order_id)
            except Exception as e: logging.error(f"Error cancelling order {order_id}: {e}")
        client.squareoff_all()
        logging.info("All positions squared off.")
        ce_pnl = (entry_data.get(ce_scrip_code, {}).get('entry_price', 0) - ce_exit_price) * config.QTY
        pe_pnl = (entry_data.get(pe_scrip_code, {}).get('entry_price', 0) - pe_exit_price) * config.QTY
        final_pnl = ce_pnl + pe_pnl

    log_trade_to_csv({
        'Date': datetime.date.today().isoformat(), 'Symbol': config.SYMBOL, 'EntryTime': config.ENTRY_TIME, 'ExitTime': datetime.datetime.now().strftime("%H:%M:%S"),
        'Call_Strike': entry_data.get(ce_scrip_code, {}).get('strike', 0), 'Put_Strike': entry_data.get(pe_scrip_code, {}).get('strike', 0),
        'Call_Entry_Premium': entry_data.get(ce_scrip_code, {}).get('entry_price', 0), 'Put_Entry_Premium': entry_data.get(pe_scrip_code, {}).get('entry_price', 0),
        'Call_Exit_Price': ce_exit_price, 'Put_Exit_Price': pe_exit_price, 'Final_PnL': final_pnl, 'Exit_Reason': reason, 'Trade_Mode': 'PAPER' if config.PAPER_TRADING else 'LIVE'
    })

    pending_sl_order_ids, entry_data, realized_pnl, max_pnl = [], {}, 0, 0
    trade_is_active, trailing_sl_activated = False, False
    ce_scrip_code, pe_scrip_code = None, None
    logging.info("Trade closed and state reset.")

def log_trade_to_csv(trade_data):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, 'trade_log.csv')
    file_exists = isfile(file_path)
    with open(file_path, 'a', newline='') as csvfile:
        fieldnames = ['Date', 'Symbol', 'EntryTime', 'ExitTime', 'Call_Strike', 'Put_Strike', 'Call_Entry_Premium', 'Put_Entry_Premium', 'Call_Exit_Price', 'Put_Exit_Price', 'Final_PnL', 'Exit_Reason', 'Trade_Mode']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not file_exists: writer.writeheader()
        writer.writerow(trade_data)

if __name__ == "__main__":
    logging.info("Starting trading bot...")
    ws_manager = WebSocketManager()
    ws_manager.start()
    logging.info("Waiting for websocket to connect...")
    time.sleep(5)
    schedule.every().day.at(config.ENTRY_TIME).do(place_strangle_order)
    schedule.every().day.at(config.EXIT_TIME).do(lambda: exit_positions(reason="TIMED_EXIT"))
    logging.info("Scheduler started. Waiting for jobs and actions...")
    while True:
        schedule.run_pending()
        try:
            action = action_queue.get_nowait()
            if action.get('action') == 'exit':
                exit_positions(reason=action.get('reason'))
        except queue.Empty:
            pass
        time.sleep(1)

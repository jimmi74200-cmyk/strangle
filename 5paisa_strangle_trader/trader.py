import datetime
import logging
import schedule
import time
from py5paisa import FivePaisaClient
import config
import json
import threading

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize the 5paisa client
cred = config.cred
cred['access_token'] = config.ACCESS_TOKEN
cred['client_code'] = config.CLIENT_CODE
client = FivePaisaClient(cred=cred)

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
            expiry_date = datetime.datetime.fromtimestamp(expiry['ExpiryDate'] / 1000).date()
            diff = (expiry_date - today).days
            if 0 <= diff < min_diff:
                min_diff = diff
                nearest_expiry = expiry['ExpiryDate']

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
        if not option_chain or 'options' not in option_chain:
            logging.error("Could not fetch option chain.")
            return None
        return option_chain['options']
    except Exception as e:
        logging.error(f"Error getting option chain: {e}")
        return None

def get_spot_price(symbol):
    """
    Gets the spot price of the underlying asset.
    """
    try:
        # The scrip code for NIFTY is 999920000. This should be looked up from the scrip master file.
        scrip_code = 999920000
        if symbol == "BANKNIFTY":
            scrip_code = 999920005

        market_feed = client.fetch_market_feed([{"Exch": "N", "ExchType": "C", "ScripCode": scrip_code}])
        if market_feed and 'Data' in market_feed and market_feed['Data']:
            return market_feed['Data'][0]['LastRate']
        else:
            logging.error("Could not fetch spot price.")
            return None
    except Exception as e:
        logging.error(f"Error getting spot price: {e}")
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
entry_prices = {}
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
    global pending_sl_order_ids, entry_prices, ce_scrip_code, pe_scrip_code
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
                        # Place sell orders
                        client.place_order(OrderType='S', Exchange='N', ExchangeType='D', ScripCode=ce_scrip_code, Qty=config.QTY, Price=0, IsIntraday=True)
                        client.place_order(OrderType='S', Exchange='N', ExchangeType='D', ScripCode=pe_scrip_code, Qty=config.QTY, Price=0, IsIntraday=True)
                        logging.info("Strangle orders placed.")

                        # Wait and poll for positions to get entry prices
                        time.sleep(5) # Allow time for orders to execute
                        positions = client.positions()
                        if positions and 'NetPositionDetail' in positions:
                            for p in positions['NetPositionDetail']:
                                if p['ScripCode'] in [ce_scrip_code, pe_scrip_code]:
                                    entry_prices[p['ScripCode']] = p['SellAvg']
                                    stop_loss_price = p['SellAvg'] + config.LEG_WISE_SL_POINTS

                                    limit_price = stop_loss_price + config.SL_LIMIT_BUFFER
                                    sl_order = client.place_order(
                                        OrderType='B',
                                        Exchange='N',
                                        ExchangeType='D',
                                        ScripCode=p['ScripCode'],
                                        Qty=p['NetQty'],
                                        Price=limit_price,
                                        StopLossPrice=stop_loss_price,
                                        IsIntraday=True
                                    )
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
    for code, entry_price in entry_prices.items():
        if code in ltp_store: # Only calculate for open positions
            current_ltp = ltp_store.get(code, entry_price)
            unrealized_pnl += (entry_price - current_ltp) * config.QTY

    total_pnl = unrealized_pnl + realized_pnl
    logging.info(f"Total P&L: {total_pnl} (Realized: {realized_pnl}, Unrealized: {unrealized_pnl})")

    # Overall SL and Target
    if total_pnl <= config.OVERALL_SL or total_pnl >= config.OVERALL_TARGET:
        logging.info(f"Overall stop-loss or target hit at {total_pnl}. Exiting all positions.")
        exit_positions()
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
            logging.info(f"Trailing stop-loss hit at {trailing_sl}. Exiting all positions.")
            exit_positions()
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
                                realized_pnl = (entry_prices[closed_leg_scrip_code] - trade['Rate']) * trade['Qty']
                                logging.info(f"Realized P&L for closed leg {closed_leg_scrip_code}: {realized_pnl}")
                                break

                    if config.EXIT_STRATEGY_ON_LEG_SL_HIT:
                        logging.info("Exiting the entire strategy.")
                        exit_positions()
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

def exit_positions():
    """
    Cancels pending SL orders and exits all open positions.
    """
    global pending_sl_order_ids
    logging.info("Exiting all positions...")

    # Cancel pending SL orders
    for order_id in pending_sl_order_ids:
        try:
            logging.info(f"Cancelling pending SL order: {order_id}")
            client.cancel_order(order_id)
        except Exception as e:
            logging.error(f"Error cancelling order {order_id}: {e}")

    pending_sl_order_ids = [] # Clear the list

    # Square off all open positions
    client.squareoff_all()
    logging.info("All positions squared off.")

if __name__ == "__main__":
    logging.info("Starting trading bot...")
    schedule.every().day.at(config.ENTRY_TIME).do(place_strangle_order)
    schedule.every().day.at(config.EXIT_TIME).do(exit_positions)

    while True:
        schedule.run_pending()
        time.sleep(1)

# 5paisa API credentials
# Please fill in your credentials after running an authentication script.
APP_NAME = "YOUR_APP_NAME"
APP_SOURCE = "YOUR_APP_SOURCE"
USER_ID = "YOUR_USER_ID"
PASSWORD = "" # Not used in modern login flows, can be left blank
USER_KEY = "YOUR_USER_KEY"
ENCRYPTION_KEY = "YOUR_ENCRYPTION_KEY"

# Populated by the authentication scripts
ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"
CLIENT_CODE = "YOUR_CLIENT_CODE"

# Trading parameters
PAPER_TRADING = True # Set to False to place real trades
SYMBOL = "NIFTY"  # NIFTY, BANKNIFTY, etc.
QTY = 50  # Lot size
ENTRY_TIME = "09:30"
EXIT_TIME = "15:15"

# Strike Selection Parameters
STRIKE_SELECTION_METHOD = "NEAREST_PREMIUM"  # Options: ATM, OTM, ITM, NEAREST_PREMIUM, EQUAL_PREMIUM_GAP
PREMIUM = 100  # For NEAREST_PREMIUM: The premium value to target for each leg.
STRANGLE_STRIKE_DISTANCE = 2 # For OTM/ITM: The number of strikes away from the ATM.
STRANGLE_GAP_POINTS = 200 # For EQUAL_PREMIUM_GAP: The fixed point difference between the Call and Put strikes.

# Risk management parameters
LEG_WISE_SL_POINTS = 30  # Leg-wise stop-loss in points
SL_LIMIT_BUFFER = 1  # Points to add to trigger price for SL-L limit price
OVERALL_SL = -3000  # Overall stop-loss in currency amount
OVERALL_TARGET = 7000  # Overall target in currency amount
TRAILING_PROFIT_TRIGGER = 1500  # Profit level to trigger trailing stop-loss
TRAILING_PROFIT_LOCKIN = 300  # Profit level to lock in with trailing stop-loss
EXIT_STRATEGY_ON_LEG_SL_HIT = True # Exit the entire strategy if one leg's SL is hit

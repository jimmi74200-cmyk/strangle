# 5paisa API credentials
# Please fill in your credentials after running the authenticate.py script
cred = {
    "APP_NAME": "YOUR_APP_NAME",
    "APP_SOURCE": "YOUR_APP_SOURCE",
    "USER_ID": "YOUR_USER_ID",
    "PASSWORD": "YOUR_PASSWORD",
    "USER_KEY": "YOUR_USER_KEY",
    "ENCRYPTION_KEY": "YOUR_ENCRYPTION_KEY"
}

# Access token obtained from authenticate.py
ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"
CLIENT_CODE = "YOUR_CLIENT_CODE"

# Trading parameters
SYMBOL = "NIFTY"  # NIFTY, BANKNIFTY, etc.
QTY = 50  # Lot size
ENTRY_TIME = "09:30"
EXIT_TIME = "15:15"

# Strike Selection Parameters
STRIKE_SELECTION_METHOD = "NEAREST_PREMIUM"  # ATM, OTM, ITM, NEAREST_PREMIUM
PREMIUM = 100  # Desired premium for the NEAREST_PREMIUM method
STRANGLE_STRIKE_DISTANCE = 2 # Number of strikes away from ATM for OTM/ITM strangles

# Risk management parameters
LEG_WISE_SL_POINTS = 30  # Leg-wise stop-loss in points
OVERALL_SL = -3000  # Overall stop-loss in currency amount
OVERALL_TARGET = 7000  # Overall target in currency amount
TRAILING_PROFIT_TRIGGER = 1500  # Profit level to trigger trailing stop-loss
TRAILING_PROFIT_LOCKIN = 300  # Profit level to lock in with trailing stop-loss
EXIT_STRATEGY_ON_LEG_SL_HIT = True # Exit the entire strategy if one leg's SL is hit

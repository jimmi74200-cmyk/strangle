# 5paisa Automated Intraday Option Strangle Selling Strategy

This project is a Python script that automates an intraday option strangle selling strategy using the 5paisa API.

## Features

- Login with 5paisa API using either TOTP or a web browser.
- Automatically fetches the nearest weekly expiry for Nifty, Bank Nifty, etc.
- Selects call and put strikes based on various methods: ATM, OTM, ITM, nearest premium, or a fixed point gap with equal premiums.
- Places a short strangle order at a specific time (e.g., 9:30 AM).
- Places exchange-level Stop-Loss Limit (SL-L) orders for each leg for better reliability.
- Continuously monitors the overall P&L of the strategy.
- Squares off all positions if the overall stop-loss, target, or trailing stop-loss is hit.
- Squares off all positions at a specific time (e.g., 3:15 PM).
- Includes a safety feature to exit the entire strategy if one leg's stop-loss is hit.
- Logs all completed trades (both live and paper trades) to a `trade_log.csv` file for performance analysis.
- Includes a **Paper Trading** mode that simulates trades and logs them accurately for safe testing.

## How to Use

### 1. Installation

1.  Clone this repository.
2.  Install the required Python libraries:
    ```
    pip install py5paisa schedule
    ```

### 2. Configuration

1.  Open the `config.py` file and fill in your 5paisa API credentials (`APP_NAME`, `APP_SOURCE`, `USER_ID`, `PASSWORD`, `USER_KEY`, `ENCRYPTION_KEY`). You only need to do this once.
2.  You can also configure the trading, strike selection, and risk management parameters in `config.py` to suit your strategy.
3.  **Paper Trading:** By default, `PAPER_TRADING` is set to `True` for safety. In this mode, the script will simulate trades and log them to `trade_log.csv` with the `Trade_Mode` column set to `PAPER`. To place real trades, you must set this to `False`.

### 3. Daily Authentication (Choose One Method)

Before running the trading bot each day, you need to authenticate to get a new access token. You have two options:

#### Method 1: TOTP-based Login (Recommended for servers)

This method is fast and does not require a web browser.

1.  Run the `authenticate.py` script:
    ```
    python authenticate.py
    ```
2.  The script will prompt you to enter your client code, TOTP (from your authenticator app), and PIN.
3.  After successful authentication, the script will **automatically** update the `ACCESS_TOKEN` and `CLIENT_CODE` in your `config.py` file.

#### Method 2: Browser-based Login

This method is useful if you prefer to log in through your web browser.

1.  Run the `authenticate_browser.py` script:
    ```
    python authenticate_browser.py
    ```
2.  Your default web browser will automatically open to the 5paisa login page.
3.  Log in with your credentials. After you log in, you will be redirected to a blank page and the script will capture the login token.
4.  The script will then **automatically** update the `ACCESS_TOKEN` and `CLIENT_CODE` in your `config.py` file.

### 4. Running the Bot

To start the trading bot, run the `trader.py` script:
```
python trader.py
```

The bot will then wait for the specified `ENTRY_TIME` to place the strangle order. It will also automatically square off all positions at the specified `EXIT_TIME`.

### 5. Checking Your Profile

You can use the `profile.py` script to fetch your account details and verify that your authentication is working correctly.

```bash
python profile.py
```

## Disclaimer

This script is for educational purposes only. Use it at your own risk. The author is not responsible for any financial losses.

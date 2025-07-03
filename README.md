# Coinbase Order Book Scanner

A Python script that scans Coinbase Exchange order books to identify trading pairs with insignificant liquidity and wide spreads. The tool helps identify potential trading opportunities by analyzing order book depth and price impact.

This script does not require any account information or API keys to work. It pulls public data from the Coinbase API. As long as you have the requirements installed, you can download and run the script without any additional setup.

## Notes

- Sometimes on repeated scans, strange volume results are shown and rescanning pairs are removed. This will be looked into in future builds.
- For now, it is recommended to keep the `SCAN_ONCE` option set to `True` if you just want the main scanner to run every `SCAN_BOOKS_WAIT` seconds.
- The script is still just a proof of concept and a work in progress. It will be developed further to include more features and a more robust design.

## Features

- Scans multiple trading pairs on Coinbase Exchange based on your pairs file
- Calculates price impact for a specified order book value as if you're placing a market order
- Identifies pairs with spreads above a configurable threshold
- Filters pairs by minimum 24-hour trading volume
- Rate limiting with retry logic for reliable API access
- Configurable scan intervals and alert thresholds
- Automatically creates `active_pairs_no_usd.txt` and `products.json` files and updates them as needed

## Example Output
```Coinbase Orderbook Scanner
==========================
Orderbook Value: $50,000
Spread Alert: 5%
Min 24Hr Vol: $0
Scan Interval: 300 seconds
Active Spread Pairs Interval: 15 seconds
Active Scan Cycles: 3
Scan Once Mode: True
Show All Scan Results: False
Show Below Threshold: False
Debug Mode: False
==========================
Loaded 701 products from existing file
Products data ready with 701 products
==========================
Loaded 297 products from existing file
Starting scan loop. Press Ctrl+C to exit.
SCAN_ONCE mode: Performing a single full scan
Loaded 297 products from existing file
Scanning 297 trading pairs...
00        -72.46%     [0.0152]      +13.44%   24Hr Vol: $25,007
1INCH     -21.21%      [0.181]      +48.76%   24Hr Vol: $79,014
A8        -15.45%     [0.1038]      +26.43%   24Hr Vol: $195,136
ABT       -15.73%     [0.7001]      +14.27%   24Hr Vol: $57,149
ACS       -75.42%    [0.0010987]    +43.81%   24Hr Vol: $36,747
AGLD      -71.75%     [0.7258]      +55.70%   24Hr Vol: $157,143
Completed scan cycle with 141/298 valid pairs. Waiting 300 seconds before next scan...
```

## Prerequisites

- Tested on Python 3.12.4
- Coinbase Exchange API access (public endpoints only no keys needed)

## Installation

1. Clone this repository:
   ```bash
   git clone <repository-url>
   cd Coinbase Orderbook Scanner
   ```

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

Edit the `CONFIG` dictionary in `Coinbase Orderbook Scanner.py` to customize the scanner's behavior:

- `PAIRS_FILE`: Path to the pairs file (default: "active_pairs_no_usd.txt")
- `ORDERBOOK_VALUE`: Total order book value to analyze (default: $50,000)
- `SPREAD_ALERT`: Alert when spread is above this value (default: 5%)
- `SCAN_BOOKS_WAIT`: Seconds to wait between scans (default: 300)
- `SHOW_SCAN_RESULTS`: If False, only show spread alerts, not all scan results (default: False)
- `SHOW_BELOW_THRESHOLD`: If True, shows pairs below volume threshold when SHOW_SCAN_RESULTS is True (default: False)
- `MIN_24HR_VOLUME`: Minimum 24-hour trading volume in USD (default: 0)
- `DEBUG`: If True, will show additional debug information (default: False)
- `PRODUCTS_FILE`: File to store product information (default: "products.json")
- `PRODUCTS_MAX_AGE`: Maximum age of products file in hours before refresh (default: 4)
- `RATE_LIMIT_TRY_ATTEMPT`: Number of retry attempts for rate-limited requests (default: 5)
- `RATE_LIMIT_DELAY`: Delay in seconds between retry attempts (default: 1)
- `SHOW_LOADED_PAIR_INFO`: If True, shows detailed information about loaded pairs (default: False)
- `SHOW_TIMESTAMP`: If False, timestamps will not be displayed in logs (default: False)
- `SPREAD_PAIRS_FILE`: File to store active spread pairs (default: "active_spread_pairs.json")
- `DEFAULT_PRECISION`: Default decimal precision for price display when quote_increment is not available (default: 8)
- `SCAN_ACTIVE_SPREADS_PAIRS_WAIT`: Seconds to wait between active spread pairs scans (default: 15)
- `ACTIVE_SCAN_CYCLES`: Number of active spread pair scan cycles before doing a full scan (default: 3)
- `SCAN_ONCE`: If True, only perform one full scan and exit (default: True)

## Usage

Run the scanner with default settings:
```bash
python Coinbase Orderbook Scanner.py
```

## Output

The script provides real-time output showing:
- Current price and spread for each trading pair
- Price impact for buy and sell orders
- Volume information
- Alerts when spreads exceed the threshold

## Logging

Logs are printed to the console with timestamps. The script also creates a `products.json` file to cache product information from the Coinbase API.

## Supporting Files

### products.json

This file is automatically generated and maintained by the script to cache product information from the Coinbase API. This reduces the number of API calls needed and improves performance. The file contains detailed information about all trading pairs available on Coinbase, including:

- Product ID
- Base and quote currencies
- Quote increment (price precision)
- Trading status
- Volume information

Example structure:
```json
[
  {
    "id": "BTC-USD",
    "base_currency": "BTC",
    "quote_currency": "USD",
    "quote_increment": "0.01",
    "base_increment": "0.00000001",
    "display_name": "BTC/USD",
    "status": "online",
    "status_message": "",
    "min_market_funds": "1",
    "max_market_funds": "1000000",
    "post_only": false,
    "limit_only": false,
    "cancel_only": false
  },
  ...
]
```

### active_pairs_no_usd.txt

This file contains a list of cryptocurrency trading pairs to scan, with each ticker symbol on a new line. The script will automatically append "-USD" to each symbol when querying the Coinbase API. This file can be manually edited to focus on specific pairs you're interested in.

Example content:
```
BTC
ETH
SOL
```

## Rate Limiting

The script implements rate limiting with exponential backoff to handle Coinbase API rate limits. You can adjust the retry behavior in the configuration.

## Disclaimer

This tool is for educational and informational purposes only. Cryptocurrency trading involves substantial risk of loss and is not suitable for every investor.  

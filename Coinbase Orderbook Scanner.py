import os
import time
import json
import requests
import datetime

# Get script directory for relative file paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuration 
CONFIG = {
    "PAIRS_FILE": "active_pairs_no_usd.txt",            # Default pairs file
    "PRODUCTS_FILE": "products.json",                   # File to store product information
    "SPREAD_PAIRS_FILE": "active_spread_pairs.json",    # File to store active spread pairs
    "DEFAULT_PRECISION": 8,                             # Default decimal precision for price display when quote_increment is not available
    "PRODUCTS_MAX_AGE": 4,                              # Maximum age of products file in hours before refresh
    "RATE_LIMIT_DELAY": 1,                              # Delay in seconds between retry attempts
    "RATE_LIMIT_TRY_ATTEMPT": 5,                        # Number of retry attempts for rate limited requests
    "DEBUG": False,                                     # If True, will show additional debug information
    "SHOW_SCAN_RESULTS": False,                         # If False, only show spread alerts, not all scan results
    "SHOW_BELOW_THRESHOLD": False,                      # If True, shows pairs below volume threshold when SHOW_SCAN_RESULTS is True
    "SHOW_LOADED_PAIR_INFO": False,                     # If True, shows detailed information about loaded pairs
    "SHOW_TIMESTAMP": False,                            # If False, timestamps will not be displayed in logs
    "ORDERBOOK_VALUE": 50000,                           # Will scan total orderbooks needed for 1 million dollars in total value
    "MIN_24HR_VOLUME": 0,                               # Minimum 24hr volume in USD
    "SPREAD_ALERT": 5,                                  # Alert when spread is above this value
    "SCAN_BOOKS_WAIT": 300,                             # Seconds to wait between scans
    "SCAN_ACTIVE_SPREADS_PAIRS_WAIT": 15,               # Seconds to wait between active spread pairs scans
    "ACTIVE_SCAN_CYCLES": 3,                            # Number of active spread pair scan cycles before doing a full scan
    "SCAN_ONCE": True                                   # If True, only perform one full scan and exit
}

# Handle paths - make them absolute if they aren't already
for file_key in ["PAIRS_FILE", "PRODUCTS_FILE", "SPREAD_PAIRS_FILE"]:
    if not os.path.isabs(CONFIG[file_key]):
        # Make it relative to the script directory
        CONFIG[file_key] = os.path.join(SCRIPT_DIR, CONFIG[file_key])

# Function to get formatted timestamp for logging
def get_timestamp():
    if CONFIG["SHOW_TIMESTAMP"]:
        return f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
    return ""

# Helper function for logging with timestamp
def log(message):
    """Log a message with timestamp if configured"""
    print(f"{get_timestamp()}{message}")

# Generic API request function to reduce duplication
def make_api_request(url, resource_name="resource"):
    """Make a rate-limited API request to Coinbase"""
    for attempt in range(CONFIG["RATE_LIMIT_TRY_ATTEMPT"]):
        try:
            response = requests.get(url)
            
            if response.status_code == 200:
                return response.json()
                
            if response.status_code == 429:  # Rate limited
                if attempt < CONFIG["RATE_LIMIT_TRY_ATTEMPT"] - 1:  # Don't sleep on last attempt
                    time.sleep(CONFIG["RATE_LIMIT_DELAY"])
                    continue
            
            log(f"Error fetching {resource_name}: {response.status_code} {response.text}")
            return None
            
        except Exception as e:
            log(f"Exception fetching {resource_name} (attempt {attempt + 1}): {e}")
            if attempt == CONFIG["RATE_LIMIT_TRY_ATTEMPT"] - 1:
                return None
            time.sleep(CONFIG["RATE_LIMIT_DELAY"])
    
    return None

# Format number with specified decimal precision
def format_with_precision(num, decimals):
    """Format number with specified decimal precision"""
    return f"{num:.{decimals}f}"

def get_orderbook(product_id, level=2):
    """Fetch the orderbook for a given product using public API with rate limiting"""
    url = f"https://api.exchange.coinbase.com/products/{product_id}/book?level={level}"
    return make_api_request(url, f"orderbook for {product_id}")


def get_product_volume(product_id):
    """Fetch the 24-hour volume data for a given product using public API with rate limiting"""
    url = f"https://api.exchange.coinbase.com/products/{product_id}/stats"
    data = make_api_request(url, f"volume data for {product_id}")
    
    # Debug the response structure if requested
    if data and CONFIG["DEBUG"]:
        log(f"Volume data for {product_id}: {json.dumps(data, indent=2)}")
    
    if not data:
        log(f"Warning: Failed to get volume data for {product_id}")
        return None
        
    # Ensure we have volume_24h data
    if 'volume_24h' not in data and 'volume' in data:
        # Map volume to volume_24h for API compatibility
        data['volume_24h'] = data['volume']
    
    # Normalize volume data - convert to USD value if necessary
    # Sometimes API returns raw token count rather than USD value
    # Heuristic: If volume_24h is extremely high (> $10M for most tokens), it might be in token units
    volume_24h = float(data.get('volume_24h', 0))
    if 'price' in data and volume_24h > 10000000:  # More than $10M
        try:
            # Check if we need to normalize - compare with volume_30d if available
            if 'volume_30d' in data and float(data['volume_30d']) > 0:
                daily_avg = float(data['volume_30d']) / 30
                if volume_24h > daily_avg * 5:  # If 24h volume is 5x the daily average
                    # Likely needs normalization
                    current_price = float(data.get('price', 0))
                    if current_price > 0:
                        # Convert to USD value
                        normalized_volume = volume_24h * current_price
                        if CONFIG["DEBUG"]:
                            log(f"Normalizing {product_id} volume from {volume_24h} to {normalized_volume}")
                        data['volume_24h'] = str(normalized_volume)
        except Exception as e:
            # If normalization fails, use original value
            if CONFIG["DEBUG"]:
                log(f"Error normalizing volume for {product_id}: {e}")
    
    return data


def calculate_orderbook_range(orderbook, target_value):
    """Calculate the price range after absorbing target_value in orderbooks
       Returns a tuple of (buy_price_impact, sell_price_impact, current_price)"""
    if not orderbook or 'bids' not in orderbook or 'asks' not in orderbook:
        log("Invalid orderbook data")
        return None
    
    bids = orderbook['bids']  # Format: [[price, size, num_orders], ...]
    asks = orderbook['asks']  # Format: [[price, size, num_orders], ...]
    
    # Current mid price
    best_bid = float(bids[0][0]) if bids else 0
    best_ask = float(asks[0][0]) if asks else float('inf')
    current_price = (best_bid + best_ask) / 2
    
    # Calculate buy wall
    buy_value_sum = 0
    buy_price_impact = best_bid
    
    for bid in bids:
        price = float(bid[0])  # Price is the first element
        size = float(bid[1])   # Size is the second element
        value = price * size
        
        buy_value_sum += value
        buy_price_impact = price
        
        if buy_value_sum >= target_value:
            break
    
    # Calculate sell wall
    sell_value_sum = 0
    sell_price_impact = best_ask
    
    for ask in asks:
        price = float(ask[0])  # Price is the first element
        size = float(ask[1])   # Size is the second element
        value = price * size
        
        sell_value_sum += value
        sell_price_impact = price
        
        if sell_value_sum >= target_value:
            break
    
    # Return tuple of values: (buy_price_impact, sell_price_impact, current_price)
    return (buy_price_impact, sell_price_impact, current_price)


def format_number(num):
    """Format number with 2 decimal places and include commas for thousands, millions, etc"""
    return f"{num:,.2f}"


def get_products():
    """Fetch all product information from Coinbase Exchange API with rate limiting"""
    url = "https://api.exchange.coinbase.com/products"
    return make_api_request(url, "products")


def ensure_products_file():
    """Ensure the products file exists and is up-to-date"""
    products_file = os.path.join(SCRIPT_DIR, CONFIG["PRODUCTS_FILE"])
    pairs_file = CONFIG["PAIRS_FILE"]
    max_age_hours = CONFIG["PRODUCTS_MAX_AGE"]
    current_datetime = datetime.datetime.now()
    
    # Check products file status
    products_file_exists = os.path.isfile(products_file)
    products_file_outdated = True
    
    if products_file_exists:
        # Check products file age
        products_file_timestamp = os.path.getmtime(products_file)
        products_file_datetime = datetime.datetime.fromtimestamp(products_file_timestamp)
        products_age_hours = (current_datetime - products_file_datetime).total_seconds() / 3600
        products_file_outdated = products_age_hours > max_age_hours
    
    # Check pairs file status
    pairs_file_exists = os.path.isfile(pairs_file)
    pairs_file_outdated = True
    
    if pairs_file_exists:
        # Check pairs file age
        pairs_file_timestamp = os.path.getmtime(pairs_file)
        pairs_file_datetime = datetime.datetime.fromtimestamp(pairs_file_timestamp)
        pairs_age_hours = (current_datetime - pairs_file_datetime).total_seconds() / 3600
        pairs_file_outdated = pairs_age_hours > max_age_hours
    
    # Case 1: Products file needs updating (missing or outdated)
    if not products_file_exists or products_file_outdated:
        log(f"{'Creating' if not products_file_exists else 'Updating'} products file...")
        products = get_products()
        
        if products:
            # Save to file
            with open(products_file, 'w') as f:
                json.dump(products, f, indent=2)
            log(f"Products file saved with {len(products)} products")
            
            # Also update pairs file
            generate_active_pairs_file(products, pairs_file)
            return products
        else:
            log("Failed to fetch products data")
            return None
    
    # Case 2: Only pairs file needs updating
    elif not pairs_file_exists or pairs_file_outdated:
        try:
            with open(products_file, 'r') as f:
                products = json.load(f)
            log(f"Loaded {len(products)} products from existing file")
            
            # Update the pairs file since it's outdated
            log("Updating active pairs file...")
            generate_active_pairs_file(products, pairs_file)
            return products
        except Exception as e:
            log(f"Error loading products file: {e}")
            return None
    
    # Case 3: Both files are up-to-date
    else:
        try:
            with open(products_file, 'r') as f:
                products = json.load(f)
            log(f"Loaded {len(products)} products from existing file")
            return products
        except Exception as e:
            log(f"Error loading products file: {e}")
            return None


def generate_active_pairs_file(products, pairs_file_path):
    """Generate or update the active_pairs_no_usd.txt file with current active USD pairs"""
    if not products:
        log("No products data provided to generate pairs file")
        return
    
    # Filter out only USD pairs that are not disabled
    usd_pairs = [p for p in products if p.get('quote_currency') == 'USD' and not p.get('trading_disabled')]

    # Extract base currencies and sort them
    current_active_pairs_no_usd = sorted(p.get('base_currency') for p in usd_pairs if 'base_currency' in p)
    
    if not current_active_pairs_no_usd:
        log(f"No active USD pairs found to write to {pairs_file_path}")
        return

    # Load previous pairs from file if it exists
    previous_active_pairs_no_usd = set()
    if os.path.isfile(pairs_file_path):
        try:
            with open(pairs_file_path, "r") as file:
                previous_active_pairs_no_usd = set(file.read().splitlines())
        except Exception as e:
            log(f"Error reading existing pairs file: {e}")
    else:
        log(f"{pairs_file_path} not found, creating a new one.")

    # Only write to the file if there are changes
    if set(current_active_pairs_no_usd) != previous_active_pairs_no_usd:
        try:
            with open(pairs_file_path, "w") as file:
                for pair in current_active_pairs_no_usd:
                    file.write(pair + "\n")
            log(f"{pairs_file_path} has been updated with {len(current_active_pairs_no_usd)} active USD pairs.")
        except Exception as e:
            log(f"Error writing to {pairs_file_path}: {e}")
    else:
        log(f"No changes in active pairs. {pairs_file_path} remains the same.")
    
    return None


def get_product_info(product_id, products_data=None):
    """Get information about a specific product from the products data"""
    if not products_data:
        products_file = os.path.join(SCRIPT_DIR, CONFIG["PRODUCTS_FILE"])
        if os.path.isfile(products_file):
            try:
                with open(products_file, 'r') as f:
                    products_data = json.load(f)
            except Exception as e:
                log(f"Error loading products file: {e}")
                return None
        else:
            return None
    
    # Find the product in the data
    for product in products_data:
        if product.get("id") == product_id:
            return product
    
    return None


def save_active_spread_pairs(spread_pairs_data):
    """Save active spread pairs with book information to a JSON file"""
    spread_pairs_file = CONFIG["SPREAD_PAIRS_FILE"]
    
    try:
        with open(spread_pairs_file, 'w') as file:
            json.dump(spread_pairs_data, file, indent=2)
        if CONFIG["DEBUG"]:
            log(f"Saved {len(spread_pairs_data)} active spread pairs to {spread_pairs_file}")
        return True
    except Exception as e:
        log(f"Error saving active spread pairs: {e}")
        return False


def load_active_spread_pairs():
    """Load active spread pairs from the JSON file"""
    spread_pairs_file = CONFIG["SPREAD_PAIRS_FILE"]
    spread_pairs = []
    
    try:
        if os.path.exists(spread_pairs_file):
            with open(spread_pairs_file, 'r') as file:
                spread_pairs = json.load(file)
            if CONFIG["DEBUG"]:
                log(f"Loaded {len(spread_pairs)} active spread pairs from existing file")
        else:
            if CONFIG["DEBUG"]:
                log(f"Active spread pairs file not found at {spread_pairs_file}. Will create when needed.")
            spread_pairs = []
    except Exception as e:
        log(f"Error loading active spread pairs: {e}")
        spread_pairs = []
    
    return spread_pairs


def load_trading_pairs():
    """Load trading pairs from the specified file and ensure they have -USD suffix"""
    pairs_file_path = CONFIG["PAIRS_FILE"]
    trading_pairs = []

    try:
        if os.path.exists(pairs_file_path):
            with open(pairs_file_path, 'r') as file:
                lines = file.readlines()
                for line in lines:
                    pair = line.strip()
                    if not pair or pair.startswith('#'):
                        continue  # Skip empty lines and comments
                        
                    # Check if pair already has -USD suffix
                    if not pair.upper().endswith("-USD"):
                        pair = f"{pair.upper()}-USD"
                    trading_pairs.append(pair)
            log(f"Loaded {len(trading_pairs)} products from existing file")
        else:
            log(f"Pairs file not found at {pairs_file_path}. Will create when needed.")
            
    except Exception as e:
        log(f"Error loading pairs: {e}")
    
    return trading_pairs


def scan_active_spread_pairs(products_data=None, active_spread_pairs_data=None):
    """Scan active spread pairs that were previously identified with significant spreads"""
    if not active_spread_pairs_data or len(active_spread_pairs_data) == 0:
        log("No active spread pairs to scan!")
        return active_spread_pairs_data
    
    # Make a copy to avoid modifying the original while iterating
    updated_spread_pairs = []
    
    log(f"Scanning {len(active_spread_pairs_data)} active spread pairs...")
    
    # Get the configuration values
    target_value = CONFIG["ORDERBOOK_VALUE"]
    min_volume = CONFIG["MIN_24HR_VOLUME"]
    spread_alert = CONFIG["SPREAD_ALERT"]
    scan_wait = CONFIG["SCAN_ACTIVE_SPREADS_PAIRS_WAIT"]
    show_all = CONFIG["SHOW_SCAN_RESULTS"]
    show_below = CONFIG["SHOW_BELOW_THRESHOLD"]
    
    # Add a small rate limit delay between API calls (in seconds)
    api_rate_limit_delay = 0.5
    
    valid_pairs = 0
    skipped_pairs = 0
    
    for pair_data in active_spread_pairs_data:
        trading_pair = pair_data["id"]
        try:
            # Add a small delay between API calls to avoid rate limiting
            time.sleep(api_rate_limit_delay)
            
            # Get the orderbook for this trading pair
            orderbook = get_orderbook(trading_pair)
            if not orderbook:
                log(f"Warning: Failed to get orderbook for {trading_pair}, keeping it in active pairs")
                updated_spread_pairs.append(pair_data)  # Keep the pair in the active list
                skipped_pairs += 1
                continue
                
            # Calculate price range for target order value
            result = calculate_orderbook_range(orderbook, target_value)
            if not result:
                log(f"Warning: Failed to calculate order book range for {trading_pair}, keeping it in active pairs")
                updated_spread_pairs.append(pair_data)  # Keep the pair in the active list
                skipped_pairs += 1
                continue
                
            buy_price, sell_price, current_price = result
            
            # Calculate percentage differences from current price
            buy_price_pct = ((current_price - buy_price) / current_price) * 100
            sell_price_pct = ((sell_price - current_price) / current_price) * 100
            spread_pct = buy_price_pct + sell_price_pct
            
            # Get product info for precision formatting
            if products_data:
                product_info = get_product_info(trading_pair, products_data)
                if product_info and "quote_increment" in product_info:
                    quote_increment = product_info["quote_increment"]
                    # Parse the quote increment to determine decimal precision
                    if "." in str(quote_increment):
                        decimals = len(str(quote_increment).split(".")[1])
                    else:
                        decimals = 0
                else:
                    decimals = CONFIG["DEFAULT_PRECISION"]
            else:
                decimals = CONFIG["DEFAULT_PRECISION"]
                
            # Get formatted prices with correct decimal precision
            buy_price_str = format_with_precision(buy_price, decimals)
            sell_price_str = format_with_precision(sell_price, decimals)
            current_price_str = format_with_precision(current_price, decimals)
            
            # Add another small delay before volume API call
            time.sleep(api_rate_limit_delay)
            
            # Get volume data and use the previous stored volume if the API call fails
            volume_data = get_product_volume(trading_pair)
            if not volume_data and 'usd_volume' in pair_data:
                # Use previously stored volume data if API call fails
                usd_volume = pair_data['usd_volume']
                valid_pairs += 1
                if CONFIG["DEBUG"]:
                    log(f"Using previously stored volume for {trading_pair}: ${usd_volume:,.2f}")
            elif volume_data:
                # Use 24-hour volume from the API
                usd_volume = float(volume_data.get("volume_24h", 0))
                valid_pairs += 1
                
                # Check if volume is significantly different from previously stored volume
                # This helps detect extreme anomalies in the API response
                if 'usd_volume' in pair_data and usd_volume > 0 and pair_data['usd_volume'] > 0:
                    volume_change_ratio = usd_volume / pair_data['usd_volume']
                    # Only warn if the change is truly extreme (100x) and for volumes above a meaningful threshold
                    # This avoids unnecessary warnings for normal market fluctuations
                    min_volume_for_warning = 100000  # Only warn for volumes above $100K
                    if ((volume_change_ratio > 100 or volume_change_ratio < 0.01) and 
                            (usd_volume > min_volume_for_warning or pair_data['usd_volume'] > min_volume_for_warning)):
                        log(f"Warning: Volume for {trading_pair} changed dramatically: ${pair_data['usd_volume']:,.2f} → ${usd_volume:,.2f} ({volume_change_ratio:.2f}x)")
            else:
                log(f"Warning: No volume data for {trading_pair}, keeping it in active pairs")
                updated_spread_pairs.append(pair_data)  # Keep the pair in the active list
                skipped_pairs += 1
                continue
            
            # Add the updated data to our list
            updated_pair_data = {
                "id": trading_pair,
                "current_price": current_price,
                "buy_price": buy_price,
                "sell_price": sell_price,
                "buy_price_pct": buy_price_pct,
                "sell_price_pct": sell_price_pct,
                "spread_pct": spread_pct,
                "usd_volume": usd_volume,
                "timestamp": datetime.datetime.now().isoformat()
            }
            updated_spread_pairs.append(updated_pair_data)
            
            # Format display strings
            pair_symbol = trading_pair.split("-")[0]
            padded_pair = pair_symbol.ljust(7)
            buy_pct_str = f"-{format_number(buy_price_pct)}%"
            sell_pct_str = f"{'+' if sell_price_pct > 0 else ''}{format_number(sell_price_pct)}%"
            volume_str = f"24Hr Vol: ${int(usd_volume):,}"
            
            # Display based on configuration
            if show_all:
                if usd_volume >= min_volume or show_below:
                    # Apply fixed width formatting
                    result_string = (
                        f"{padded_pair}  "
                        f"{buy_pct_str:<8}  "
                        f"[{current_price_str}]  "
                        f"{sell_pct_str:<8}  "
                        f"{volume_str}"
                    )
                    
                    # Add (below threshold) label if needed
                    if usd_volume < min_volume:
                        result_string += " (below threshold)"
                        
                    log(result_string)
            
            # Check for spread alert
            if spread_pct > spread_alert and not show_all:
                # Only show this format if we're not already showing detailed output
                buy_pct_str = f"-{format_number(buy_price_pct)}%"
                current_price_str = f"[{format_with_precision(current_price, decimals)}]"
                sell_pct_str = f"{'+' if sell_price_pct > 0 else ''}{format_number(sell_price_pct)}%"
                volume_str = f"24Hr Vol: ${int(usd_volume):,}"
                
                # Apply fixed-width formatting for alert message
                alert_string = (
                    f"{padded_pair}  "
                    f"{buy_pct_str:>8}  "
                    f"{current_price_str:^15}  "
                    f"{sell_pct_str:<8}  "
                    f"{volume_str}"
                )
                
                if usd_volume < min_volume:
                    alert_string += " (below threshold)"
                log(alert_string)
                    
        except Exception as e:
            log(f"Error processing {trading_pair}: {e}")
            # Keep the pair in the list even if there was an error
            updated_spread_pairs.append(pair_data)
    
    # Check if we still have active pairs that exceed the spread threshold
    active_pairs_with_spread = [p for p in updated_spread_pairs if p.get('spread_pct', 0) > spread_alert]
    pairs_below_threshold = len(updated_spread_pairs) - len(active_pairs_with_spread)
    
    log(f"Completed active spread pairs scan with {valid_pairs}/{len(active_spread_pairs_data)} valid pairs, {skipped_pairs} skipped.")
    if pairs_below_threshold > 0:
        log(f"{pairs_below_threshold} pairs now below spread threshold but kept for continued monitoring.")
    log(f"Waiting {scan_wait} seconds before next scan...")
    
    time.sleep(scan_wait)
    
    # Return all updated pairs including those that may have fallen below threshold
    # They'll be filtered out during the next full scan if still below threshold
    return updated_spread_pairs


def scan_orderbooks(products_data=None):
    """Main function to scan orderbooks for multiple trading pairs
       Returns a list of active spread pairs that exceed the spread threshold"""
    orderbook_value = CONFIG["ORDERBOOK_VALUE"]
    min_volume = CONFIG["MIN_24HR_VOLUME"]
    spread_alert = CONFIG["SPREAD_ALERT"]
    show_results = CONFIG["SHOW_SCAN_RESULTS"]
    show_below = CONFIG["SHOW_BELOW_THRESHOLD"]
    scan_wait = CONFIG["SCAN_BOOKS_WAIT"]
    trading_pairs = load_trading_pairs()
    if not trading_pairs:
        log("No trading pairs to scan!")
        return []
    
    log(f"Scanning {len(trading_pairs)} trading pairs...")
    
    # List to collect pairs with significant spreads
    active_spread_pairs = []
    valid_pairs = 0
    skipped_pairs = 0
    
    # Add a small rate limit delay between API calls (in seconds)
    api_rate_limit_delay = 0.5
    
    for trading_pair in trading_pairs:
        try:
            # First check if the trading pair has sufficient volume
            # Add small delay before volume API call
            time.sleep(api_rate_limit_delay)
            
            # Get the 24hr volume in USD
            volume_data = get_product_volume(trading_pair)
            if not volume_data:
                if CONFIG["DEBUG"]:
                    log(f"Warning: Failed to get volume data for {trading_pair}")
                skipped_pairs += 1
                continue
                
            # Get volume and price data for calculating USD volume
            spot_volume = 0
            last_price = 0
            
            # Extract volume data
            if 'volume_24h' in volume_data:
                spot_volume = float(volume_data['volume_24h'])
            elif 'volume' in volume_data:
                spot_volume = float(volume_data['volume'])
            elif 'spot_volume_24h' in volume_data:
                spot_volume = float(volume_data['spot_volume_24h'])
            else:
                log(f"Could not find volume data in response for {trading_pair}")
                continue
            
            # Extract price data
            if 'last' in volume_data:
                last_price = float(volume_data['last'])
            else:
                log(f"Could not find price data in response for {trading_pair}")
                continue
            
            # Calculate USD volume as volume * price
            usd_volume = spot_volume * last_price
            
            # Skip if below threshold and not showing below threshold results
            if usd_volume < min_volume and not (CONFIG["SHOW_SCAN_RESULTS"] and CONFIG["SHOW_BELOW_THRESHOLD"]):
                continue
            
            # Only count pairs above threshold as valid
            if usd_volume >= min_volume:
                valid_pairs += 1
            
            # Now fetch the orderbook data
            # Add small delay to avoid rate limits
            time.sleep(api_rate_limit_delay)
            
            # Get the orderbook for this trading pair
            orderbook = get_orderbook(trading_pair)
            if not orderbook:
                if CONFIG["DEBUG"]:
                    log(f"Warning: Failed to get orderbook for {trading_pair}")
                skipped_pairs += 1
                continue
            
            # Calculate price range after absorbing target order value
            result = calculate_orderbook_range(orderbook, orderbook_value)
            if not result:
                if CONFIG["DEBUG"]:
                    log(f"Warning: Failed to calculate order book range for {trading_pair}")
                skipped_pairs += 1
                continue
            
            buy_price, sell_price, current_price = result
            
            # Calculate percentage differences from current price
            buy_price_pct = ((current_price - buy_price) / current_price) * 100
            sell_price_pct = ((sell_price - current_price) / current_price) * 100
            spread_pct = buy_price_pct + sell_price_pct
            
            # Get product info for precision formatting
            if products_data:
                product_info = get_product_info(trading_pair, products_data)
                if product_info and "quote_increment" in product_info:
                    quote_increment = product_info["quote_increment"]
                    # Parse the quote increment to determine decimal precision
                    if "." in str(quote_increment):
                        decimals = len(str(quote_increment).split(".")[1])
                    else:
                        decimals = 0
                else:
                    decimals = CONFIG["DEFAULT_PRECISION"]
            else:
                decimals = CONFIG["DEFAULT_PRECISION"]
            
            # Format trading pair (remove -USD if present)
            display_pair = trading_pair.split("-")[0]
            padded_pair = display_pair.ljust(7)
            
            # Check if this pair has a significant spread and should be actively monitored
            if spread_pct > spread_alert and usd_volume >= min_volume:
                # Add to active spread pairs
                active_spread_pairs.append({
                    "id": trading_pair,
                    "current_price": current_price,
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "buy_price_pct": buy_price_pct,
                    "sell_price_pct": sell_price_pct,
                    "spread_pct": spread_pct,
                    "usd_volume": usd_volume,
                    "timestamp": datetime.datetime.now().isoformat()
                })
            
            # Output results if SHOW_SCAN_RESULTS is True
            if show_results:
                if usd_volume >= min_volume or show_below:
                    # Format each column with fixed width for alignment
                    buy_pct_str = f"-{format_number(buy_price_pct)}%"
                    current_price_str = format_with_precision(current_price, decimals)
                    sell_pct_str = f"{'+' if sell_price_pct > 0 else '-'}{format_number(sell_price_pct)}%"
                    volume_str = f"24Hr Vol: ${int(usd_volume):,}"
                    
                    # Apply fixed width formatting
                    result_string = (
                        f"{padded_pair}  "
                        f"{buy_pct_str:<8}  "
                        f"[{current_price_str}]  "
                        f"{sell_pct_str:<8}  "
                        f"{volume_str}"
                    )
                    
                    # Add (below threshold) label if needed
                    if usd_volume < min_volume:
                        result_string += " (below threshold)"
                        
                    log(result_string)
            
            # Check for spread alert
            if spread_pct > spread_alert and not show_results:
                # Only show this format if we're not already showing detailed output
                buy_pct_str = f"-{format_number(buy_price_pct)}%"
                current_price_str = f"[{format_with_precision(current_price, decimals)}]"
                sell_pct_str = f"{'+' if sell_price_pct > 0 else '-'}{format_number(sell_price_pct)}%"
                volume_str = f"24Hr Vol: ${int(usd_volume):,}"
                
                # Apply fixed-width formatting for alert message
                alert_string = (
                    f"{padded_pair}  "
                    f"{buy_pct_str:>8}  "
                    f"{current_price_str:^15}  "
                    f"{sell_pct_str:<8}  "
                    f"{volume_str}"
                )
                
                if usd_volume < min_volume:
                    alert_string += " (below threshold)"
                log(alert_string)
                
        except Exception as e:
            log(f"Error processing {trading_pair}: {e}")
    
    log(f"Completed scan cycle with {valid_pairs}/{len(trading_pairs)} valid pairs, {skipped_pairs} skipped due to API issues. Waiting {scan_wait} seconds before next scan...")
    time.sleep(scan_wait)
    
    # Save the active spread pairs to file
    if active_spread_pairs:
        save_active_spread_pairs(active_spread_pairs)
        log(f"Found {len(active_spread_pairs)} active spread pairs exceeding {spread_alert}% spread threshold")
    
    # Return the active spread pairs for further processing
    return active_spread_pairs


def main():
    log("Coinbase Orderbook Scanner")
    log("==========================")
    log(f"Orderbook Value: ${CONFIG['ORDERBOOK_VALUE']:,}")
    log(f"Spread Alert: {CONFIG['SPREAD_ALERT']}%")
    log(f"Min 24Hr Vol: ${CONFIG['MIN_24HR_VOLUME']:,}")
    log(f"Scan Interval: {CONFIG['SCAN_BOOKS_WAIT']} seconds")
    log(f"Active Spread Pairs Interval: {CONFIG['SCAN_ACTIVE_SPREADS_PAIRS_WAIT']} seconds")
    log(f"Active Scan Cycles: {CONFIG['ACTIVE_SCAN_CYCLES']}")
    log(f"Scan Once Mode: {CONFIG['SCAN_ONCE']}")
    log(f"Show All Scan Results: {CONFIG['SHOW_SCAN_RESULTS']}")
    log(f"Show Below Threshold: {CONFIG['SHOW_BELOW_THRESHOLD']}")
    log(f"Debug Mode: {CONFIG['DEBUG']}")
    log("==========================")
    
    # Ensure products file is updated
    products_data = ensure_products_file()
    if products_data:
        log(f"Products data ready with {len(products_data)} products")
    else:
        log("WARNING: Could not load products data!")
    log("==========================")
    
    # Load trading pairs
    trading_pairs = load_trading_pairs()
    
    # Display loaded pairs info if enabled
    if CONFIG["SHOW_LOADED_PAIR_INFO"]:
        log(f"Loaded {len(trading_pairs)} products from existing file" if trading_pairs else "No trading pairs found in the pairs file!")
        log(f"Products data ready with {len(products_data) if products_data else 0} products")
        log("==========================")
        
        if trading_pairs:
            log("Loaded Trading Pairs:")
            for pair in trading_pairs:
                product_info = get_product_info(pair, products_data)
                if product_info:
                    quote_increment = product_info.get("quote_increment")
                    decimals = len(str(quote_increment).split('.')[1]) if '.' in str(quote_increment) else 0
                    log(f"- {pair} (Decimals: {decimals})")
                else:
                    log(f"- {pair}")
        else:
            log("WARNING: No trading pairs found in the pairs file!")
        log("==========================")
    
    # Initialize variables for scan control
    active_scan_count = 0
    active_scan_cycles = CONFIG["ACTIVE_SCAN_CYCLES"]
    active_spread_pairs = load_active_spread_pairs()
    
    # Main scan loop
    try:
        log("Starting scan loop. Press Ctrl+C to exit.")
        
        # If SCAN_ONCE is True, we'll only do one full scan
        if CONFIG["SCAN_ONCE"]:
            log("SCAN_ONCE mode: Performing a single full scan")
            active_spread_pairs = scan_orderbooks(products_data)
            
            # Log the active spread pairs that were found
            if active_spread_pairs:
                active_symbols = [pair['id'].split('-')[0] for pair in active_spread_pairs]
                log(f"Found active spread pairs: {', '.join(active_symbols)}")
                
                # Save the active spread pairs before exiting
                save_active_spread_pairs(active_spread_pairs)
                log(f"Saved {len(active_spread_pairs)} active spread pairs to {CONFIG['SPREAD_PAIRS_FILE']}")
            log("SCAN_ONCE mode: Scan complete, exiting")
            
        else:
            # Normal continuous scanning mode
            while True:
                # Check if we need to do a full scan
                if active_scan_count == 0 or active_scan_count >= active_scan_cycles or not active_spread_pairs:
                    log(f"Performing full scan of all trading pairs (cycle {active_scan_count}/{active_scan_cycles})")
                    # Perform full scan and get updated active spread pairs
                    active_spread_pairs = scan_orderbooks(products_data)
                    # Reset the counter after a full scan
                    active_scan_count = 1  # Set to 1 since we've completed one cycle already

                    # Log the active spread pairs that were found
                    if active_spread_pairs:
                        active_symbols = [pair['id'].split('-')[0] for pair in active_spread_pairs]
                        log(f"Found active spread pairs: {', '.join(active_symbols)}")
                else:
                    # Perform scan of active spread pairs only
                    log(f"Scanning only active spread pairs (cycle {active_scan_count}/{active_scan_cycles})")
                    active_spread_pairs = scan_active_spread_pairs(products_data, active_spread_pairs)
                    
                    # Increment the count of active spread pair scans
                    active_scan_count += 1
                
                # No sleep needed here as both scan functions have their own wait time
    except KeyboardInterrupt:
        print("\nExiting...")
        # Save the active spread pairs before exiting
        if active_spread_pairs:
            save_active_spread_pairs(active_spread_pairs)
            print(f"Saved {len(active_spread_pairs)} active spread pairs to {CONFIG['SPREAD_PAIRS_FILE']}")



if __name__ == "__main__":
    main()

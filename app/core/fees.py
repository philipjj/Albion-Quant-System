from app.core.config import settings


def calculate_sell_proceeds(
    sell_price:         int,
    premium:            bool = True,
    crafting_station_fee: float = None,
) -> dict:
    """
    Net proceeds from selling one item on the marketplace.
    Deductions:
      - Setup fee: 2.5%
      - Transaction tax: 4% (Premium) or 8% (non-Premium)
      - Crafting station fee: variable %, default from settings
    """
    if crafting_station_fee is None:
        crafting_station_fee = settings.crafting_station_fee_default
        
    tax_pct     = settings.market_tax_premium_pct if premium else settings.market_tax_non_premium_pct
    setup_fee   = round(sell_price * settings.market_setup_fee_pct)
    tax         = round(sell_price * tax_pct)
    station_fee = round(sell_price * crafting_station_fee)
    net         = sell_price - setup_fee - tax - station_fee

    return {
        "gross":             sell_price,
        "setup_fee":         setup_fee,
        "transaction_tax":   tax,
        "station_fee":       station_fee,
        "net_proceeds":      net,
        "effective_fee_pct": round((sell_price - net) / sell_price, 4) if sell_price > 0 else 0,
    }

def calculate_buy_cost(buy_price: int) -> dict:
    """
    Total cost of fulfilling a buy order at buy_price.
    Buy orders incur the 2.5% setup fee.
    """
    setup_fee  = round(buy_price * settings.market_setup_fee_pct)
    total_cost = buy_price + setup_fee

    return {
        "buy_price":  buy_price,
        "setup_fee":  setup_fee,
        "total_cost": total_cost,
    }

def calculate_black_market_margin(buy_price: int, bm_price: int) -> dict:
    """
    Round-trip margin for Black Market flips.
    - Buy: Buy Order Setup Fee (2.5%) applied.
    - Sell: ZERO fees on Black Market.
    """
    buy = calculate_buy_cost(buy_price)
    # BM has 0% tax, 0% setup fee, 0% station fee
    net_profit = bm_price - buy["total_cost"]
    
    return {
        "buy_details": buy,
        "sell_details": {"net_proceeds": bm_price},
        "net_profit": net_profit,
        "roi_pct": round(net_profit / buy["total_cost"] * 100, 2) if buy["total_cost"] > 0 else 0,
    }

def calculate_net_margin(
    buy_price:            int,
    sell_price:           int,
    is_black_market:      bool  = False,
    fast_sell:            bool  = False,
    premium:              bool  = True,
    tax_free:             bool  = False,
    crafting_station_fee: float = None,
) -> tuple[float, float]:
    """
    Full round-trip margin calculation.
    Returns (net_profit, roi_percentage).
    """
    if is_black_market:
        # BM has 0% tax, 0% setup fee, but we still pay the setup fee on the BUY side
        buy_setup = round(buy_price * settings.market_setup_fee_pct)
        total_cost = buy_price + buy_setup
        net_profit = sell_price - total_cost
    else:
        # Standard Market
        buy_setup = round(buy_price * settings.market_setup_fee_pct)
        total_cost = buy_price + buy_setup
        
        # Sell Side
        tax_pct = 0.0 if tax_free else (settings.market_tax_premium_pct if premium else settings.market_tax_non_premium_pct)
        # If fast selling (to a buy order), we don't pay the 2.5% setup fee
        sell_setup_pct = 0.0 if fast_sell else settings.market_setup_fee_pct
        
        sell_fee = round(sell_price * (tax_pct + sell_setup_pct))
        net_proceeds = sell_price - sell_fee
        net_profit = net_proceeds - total_cost

    roi_pct = (net_profit / total_cost * 100) if total_cost > 0 else 0
    return round(net_profit, 2), round(roi_pct, 2)

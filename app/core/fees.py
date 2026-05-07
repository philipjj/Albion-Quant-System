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
    premium:              bool  = True,
    crafting_station_fee: float = None,
) -> dict:
    """
    Full round-trip margin from buying and selling on regional markets.
    Applies all standard taxes and fees on both sides.
    """
    buy  = calculate_buy_cost(buy_price)
    sell = calculate_sell_proceeds(sell_price, premium, crafting_station_fee)
    net_profit = sell["net_proceeds"] - buy["total_cost"]

    return {
        "buy_details":  buy,
        "sell_details": sell,
        "net_profit":   net_profit,
        "roi_pct":      round(net_profit / buy["total_cost"] * 100, 2) if buy["total_cost"] > 0 else 0,
    }

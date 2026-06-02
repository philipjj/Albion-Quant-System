"""
Order book state management.
"""


def get_order_book(item_id: str, location: str) -> dict[str, list]:
    """
    Retrieves the current order book for an item at a location.
    Typically fetches from a database cache or the Albion Data Project API.
    """
    return {"bids": [], "asks": []}

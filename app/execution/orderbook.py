"""
Order book state management.
"""

def get_order_book(item_id: str, location: str) -> dict:
    """
    Retrieves the current order book for an item at a location.
    """
    # TODO: Implement retrieval from DB or API
    return {"bids": [], "asks": []}

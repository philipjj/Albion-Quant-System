"""
Manipulation Detector.
Detects spoofing or other manipulative behaviors in the order book.
"""
from typing import List, Dict, Any

def detect_manipulation(snapshots: List[Dict[str, Any]]) -> bool:
    """
    Detects manipulation (spoofing) in order book snapshots.
    Looks for large orders that appear and disappear quickly.
    """
    if len(snapshots) < 3:
        return False
        
    for i in range(1, len(snapshots) - 1):
        prev = snapshots[i-1]
        curr = snapshots[i]
        nxt = snapshots[i+1]
        
        # Calculate total bid volume at top level (or all levels)
        prev_bid_vol = sum(v for p, v in prev.get("bids", []))
        curr_bid_vol = sum(v for p, v in curr.get("bids", []))
        nxt_bid_vol = sum(v for p, v in nxt.get("bids", []))
        
        # Check for spike and drop (Spoofing)
        # If current volume is 5x previous and next is back to previous level
        if curr_bid_vol > prev_bid_vol * 5 and nxt_bid_vol < curr_bid_vol / 5:
            return True
            
        # Same for asks
        prev_ask_vol = sum(v for p, v in prev.get("asks", []))
        curr_ask_vol = sum(v for p, v in curr.get("asks", []))
        nxt_ask_vol = sum(v for p, v in nxt.get("asks", []))
        
        if curr_ask_vol > prev_ask_vol * 5 and nxt_ask_vol < curr_ask_vol / 5:
            return True
            
    return False

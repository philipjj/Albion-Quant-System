"""
Icon URL helpers.

Uses Albion's public render service to avoid shipping/hosting icon assets.
"""

from __future__ import annotations

from urllib.parse import quote


def item_icon_url(item_id: str | None, *, quality: int = 1, size: int = 128) -> str:
    """
    Build a render-service URL for an item icon.
    Handles missing/empty IDs, whitespace, enchantment variants (@1, @2, @3, @4),
    and normalizes quality/size bounds to prevent broken Discord thumbnail icons.
    """
    if not item_id or not isinstance(item_id, str):
        item_id = "T4_BAG"

    clean_id = item_id.strip()
    if not clean_id:
        clean_id = "T4_BAG"

    # Remove trailing .png if present
    if clean_id.lower().endswith(".png"):
        clean_id = clean_id[:-4]

    # Uppercase base item ID while preserving enchantment numbers after @
    if "@" in clean_id:
        base, enchant = clean_id.rsplit("@", 1)
        clean_id = f"{base.upper()}@{enchant}"
    else:
        clean_id = clean_id.upper()

    safe_identifier = quote(clean_id, safe="@_-.")
    q = max(1, min(5, int(quality or 1)))
    s = max(32, min(217, int(size or 128)))

    return f"https://render.albiononline.com/v1/item/{safe_identifier}.png?quality={q}&size={s}"

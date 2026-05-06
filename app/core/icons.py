"""
Icon URL helpers.

Uses Albion's public render service to avoid shipping/hosting icon assets.
"""

from __future__ import annotations

from urllib.parse import quote


def item_icon_url(item_id: str, *, quality: int = 1, size: int = 128) -> str:
    """
    Build a render-service URL for an item icon.

    Render service docs/examples:
    https://render.albiononline.com/v1/item/{identifier}.png?quality=1&size=128
    """
    safe_identifier = quote(item_id, safe="@_-.")
    q = int(quality) if quality else 1
    s = int(size) if size else 128
    if q < 1:
        q = 1
    if q > 5:
        q = 5
    if s < 16:
        s = 16
    if s > 217:
        s = 217
    return f"https://render.albiononline.com/v1/item/{safe_identifier}.png?quality={q}&size={s}"


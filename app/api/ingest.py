'''
FastAPI router for Private Ingestion from Albion Data Client.
'''

from fastapi import APIRouter, Request
from app.core.logging import log

router = APIRouter(prefix="/api/v1/ingest", tags=["Ingest"])

@router.post("/private")
async def private_ingest(request: Request):
    '''
    Private endpoint to receive market data directly from a local Albion Data Client.
    Command: albiondata-client.exe -i http://localhost:8000/api/v1/ingest/private
    '''
    try:
        data = await request.json()
    except Exception:
        return {"status": "error", "message": "Invalid JSON"}

    from app.core import state
    import httpx
    import asyncio

    if not getattr(state, "privacy_mode_enabled", False):
        async def forward_to_aodp(payload):
            try:
                async with httpx.AsyncClient() as client:
                    await client.post("https://www.albion-online-data.com/api/v2/stats/ingest", json=payload, timeout=5.0)
            except Exception as e:
                log.debug(f"[PROXY] Failed to forward to public AODP: {e}")
        
        asyncio.create_task(forward_to_aodp(data))

    orders = data.get("Orders")
    if not orders:
        if isinstance(data, list):
            orders = data
        else:
            return {"status": "ok", "message": "No orders found in payload"}

    from app.ingestion.nats_client import nats_client, LOCATION_MAPPING

    count = 0
    for order in orders:
        item_id = order.get("ItemTypeId")
        location_id = order.get("LocationId")
        quality = order.get("QualityLevel", 1)

        if item_id and location_id:
            city = LOCATION_MAPPING.get(location_id)
            if not city:
                continue

            # Route directly into the NATS live in-memory orderbook
            key = (item_id, city, quality)
            nats_client.order_buffer[key].append(order)
            nats_client._update_live_lob(item_id, city, quality, order)
            count += 1

    if count > 0:
        log.info(f"[PRIVATE INGEST] Ingested {count} live L2 orders directly from local client.")

    return {"status": "ok", "ingested": count}

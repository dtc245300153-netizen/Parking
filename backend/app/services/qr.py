from typing import Any


def ticket_qr_payload(ticket: Any) -> dict[str, Any]:
    """Return signed-transport-ready ticket data for a future QR renderer."""
    return {
        "ticket_id": ticket.id,
        "ticket_code": ticket.ticket_code,
        "status": ticket.status,
        "vehicle_id": ticket.vehicle_id,
        "slot_id": ticket.slot_id,
    }

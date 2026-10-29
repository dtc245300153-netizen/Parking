import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models import AILog, AIConversation, ParkingTicket, ParkingSlot, Vehicle, ParkingArea


SYSTEM_PROMPT = (
    "Bạn là trợ lý AI quản lý bãi đỗ xe. "
    "Trả lời ngắn gọn, chính xác, không tự bịa số liệu, chỉ dựa vào dữ liệu hệ thống/database được cung cấp."
)


def build_ai_context(db: Session) -> dict[str, Any]:
    tickets = db.query(ParkingTicket).all()
    slots = db.query(ParkingSlot).all()
    areas = db.query(ParkingArea).all()
    vehicles = db.query(Vehicle).all()

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "summary": {
            "total_slots": len(slots),
            "empty_slots": sum(1 for s in slots if s.status == "EMPTY"),
            "occupied_slots": sum(1 for s in slots if s.status == "OCCUPIED"),
            "active_tickets": sum(1 for t in tickets if t.status == "PARKING"),
            "vehicles": len(vehicles),
        },
        "areas": [
            {
                "area_code": area.area_code,
                "area_name": area.area_name,
                "vehicle_type": area.vehicle_type,
                "capacity": area.capacity,
                "status": area.status,
            }
            for area in areas
        ],
        "slots": [
            {
                "slot_code": slot.slot_code,
                "status": slot.status,
                "area_name": slot.area.area_name if slot.area else None,
                "floor": slot.floor,
                "row": slot.row_number,
                "column": slot.column_number,
            }
            for slot in slots
        ],
        "tickets": [
            {
                "ticket_code": ticket.ticket_code,
                "license_plate": ticket.vehicle.license_plate if ticket.vehicle else None,
                "status": ticket.status,
                "check_in": ticket.check_in.isoformat() if ticket.check_in else None,
                "check_out": ticket.check_out.isoformat() if ticket.check_out else None,
                "amount": float(ticket.amount or 0),
            }
            for ticket in tickets
        ],
    }


def save_ai_conversation(db: Session, user_id: int, question: str, answer: str):
    db.add(AIConversation(user_id=user_id, question=question, answer=answer))
    db.add(AILog(
        user_id=user_id,
        prompt=SYSTEM_PROMPT + "\nQuestion: " + question,
        input_data=json.dumps({"question": question}, ensure_ascii=False),
        output_data=json.dumps({"answer": answer}, ensure_ascii=False),
    ))
    db.commit()


def generate_answer_from_context(question: str, context: dict) -> str:
    q = question.lower().strip()
    summary = context.get("summary", {})
    slots = context.get("slots", [])

    if "trống" in q or "còn chỗ" in q or "vị trí" in q:
        empty_count = summary.get("empty_slots", 0)
        total = summary.get("total_slots", 0)
        return f"Hiện còn {empty_count}/{total} vị trí trống trong bãi."

    if "cao điểm" in q or "17" in q and "19" in q:
        return "Khung giờ 17:00-19:00 là thời điểm cao điểm. Nên ưu tiên phân bổ khu vực gần cổng và kiểm soát xe vào ra gấp."

    if "dự báo" in q or "công suất" in q:
        total = summary.get("total_slots", 1)
        occupied = summary.get("occupied_slots", 0)
        ratio = (occupied / total * 100) if total else 0
        return f"Công suất hiện tại khoảng {ratio:.1f}% (đang đỗ {occupied}/{total} vị trí)."

    if "gần cổng" in q or "đề xuất vị trí" in q:
        closest = next((s for s in slots if s.get("status") == "EMPTY"), None)
        if closest:
            return f"Đề xuất vị trí {closest['slot_code']} ở khu vực {closest.get('area_name')} vì đang trống và gần lối ra vào."
        return "Hiện không còn vị trí trống phù hợp gần cổng; hãy xem các khu vực còn lại trong bãi."

    return "Tôi chỉ có thể trả lời dựa trên dữ liệu hệ thống hiện có. Vui lòng cung cấp câu hỏi liên quan đến chỗ trống, doanh thu, lượng xe hoặc tình trạng bãi."

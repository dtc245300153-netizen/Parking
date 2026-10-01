from dataclasses import dataclass
from datetime import datetime
import json
import os
from typing import Any, Protocol

import httpx
from sqlalchemy.orm import Session

from ..models import ParkingSlot, ParkingTicket, Vehicle


@dataclass(frozen=True)
class AiCapability:
    name: str
    status: str
    provider: str | None = None
    reason: str | None = None


class AiProvider(Protocol):
    def answer(self, question: str, context: dict[str, Any]) -> str:
        ...


class NotConfiguredAiProvider:
    def answer(self, question: str, context: dict[str, Any]) -> str:
        raise RuntimeError(
            "AI provider chưa được cấu hình; không thể trả lời giả lập."
        )


class OpenAiCompatibleProvider:
    """Provider for OpenAI-compatible chat completion APIs."""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def answer(self, question: str, context: dict[str, Any]) -> str:
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Bạn là Parking AI. Chỉ trả lời bằng context JSON được cung cấp. "
                            "Không đoán, không bịa số liệu, nói rõ khi context không đủ."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Câu hỏi: {question}\nContext: {json.dumps(context, ensure_ascii=False)}",
                    },
                ],
            },
            timeout=20,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("AI provider trả về phản hồi rỗng")
        return content.strip()


def get_configured_provider() -> OpenAiCompatibleProvider | None:
    base_url = os.getenv("AI_BASE_URL", "").strip()
    api_key = os.getenv("AI_API_KEY", "").strip()
    model = os.getenv("AI_MODEL", "").strip()
    if not base_url or not api_key or not model:
        return None
    return OpenAiCompatibleProvider(base_url, api_key, model)


def build_database_context(db: Session) -> dict[str, Any]:
    slots = db.query(ParkingSlot).all()
    tickets = db.query(ParkingTicket).all()
    vehicles = db.query(Vehicle).all()
    return {
        "slots": [
            {
                "code": slot.slot_code,
                "area": slot.area.name if slot.area else "",
                "status": slot.status,
            }
            for slot in slots
        ],
        "vehicles": len(vehicles),
        "tickets": [
            {
                "code": ticket.ticket_code,
                "status": ticket.status,
                "vehicle_type": ticket.vehicle.vehicle_type if ticket.vehicle else "",
                "entry_time": ticket.entry_time.isoformat() if ticket.entry_time else None,
                "exit_time": ticket.exit_time.isoformat() if ticket.exit_time else None,
                "fee": float(ticket.fee or 0),
            }
            for ticket in tickets
        ],
    }


def answer_question(db: Session, question: str) -> dict[str, Any]:
    provider = get_configured_provider()
    if provider is None:
        return answer_parking_question(db, question)

    context = build_database_context(db)
    return {
        "intent": "model_analysis",
        "answer": provider.answer(question, context),
        "data": context,
        "source": "configured_ai_model",
    }


def _money(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".") + " ₫"


def _today_tickets(db: Session):
    today = datetime.now().date()
    return [
        ticket
        for ticket in db.query(ParkingTicket).all()
        if ticket.entry_time and ticket.entry_time.date() == today
    ]


def answer_parking_question(db: Session, question: str) -> dict[str, Any]:
    """Answer supported factual questions from current database state.

    This is deliberately deterministic. A generative provider can be plugged in
    later, but it must receive this database context and must not invent metrics.
    """
    normalized = " ".join(question.lower().strip().split())
    if not normalized:
        raise ValueError("Câu hỏi không được để trống")

    slots = db.query(ParkingSlot).all()
    vehicles = db.query(Vehicle).all()
    tickets = db.query(ParkingTicket).all()
    active_tickets = [ticket for ticket in tickets if ticket.status == "parking"]
    today_tickets = _today_tickets(db)
    completed = [ticket for ticket in tickets if ticket.status == "completed"]
    today = datetime.now().date()
    month = today.replace(day=1)

    def revenue_since(start_date):
        return sum(
            float(ticket.fee or 0)
            for ticket in completed
            if ticket.exit_time and ticket.exit_time.date() >= start_date
        )

    if any(term in normalized for term in ["còn bao nhiêu chỗ", "chỗ trống", "vị trí đang trống"]):
        available = sum(slot.status == "available" for slot in slots)
        return {
            "intent": "available_slots",
            "answer": f"Hiện bãi có {available} vị trí đang trống trên tổng số {len(slots)} vị trí.",
            "data": {"available": available, "total": len(slots)},
        }

    if "khu nào" in normalized and any(term in normalized for term in ["nhiều chỗ", "trống"]):
        areas: dict[str, int] = {}
        for slot in slots:
            if slot.status == "available":
                name = slot.area.name if slot.area else "Không xác định"
                areas[name] = areas.get(name, 0) + 1
        if not areas:
            return {"intent": "area_availability", "answer": "Hiện không có khu vực nào còn vị trí trống.", "data": {}}
        name, available = max(areas.items(), key=lambda item: item[1])
        return {
            "intent": "area_availability",
            "answer": f"{name} đang có nhiều vị trí trống nhất: {available} vị trí.",
            "data": {"area": name, "available": available},
        }

    if "bao nhiêu xe" in normalized or "tổng số xe" in normalized:
        return {
            "intent": "vehicle_count",
            "answer": f"Hệ thống hiện có {len(vehicles)} phương tiện đã đăng ký.",
            "data": {"vehicles": len(vehicles)},
        }

    if "hôm nay" in normalized and any(term in normalized for term in ["xe vào", "lượt xe"]):
        return {
            "intent": "today_entries",
            "answer": f"Hôm nay có {len(today_tickets)} lượt xe vào bãi.",
            "data": {"entries": len(today_tickets)},
        }

    if "doanh thu" in normalized and "tháng" in normalized:
        value = revenue_since(month)
        return {"intent": "monthly_revenue", "answer": f"Doanh thu tháng này là {_money(value)}.", "data": {"revenue": value}}

    if "doanh thu" in normalized and "hôm nay" in normalized:
        value = revenue_since(today)
        return {"intent": "today_revenue", "answer": f"Doanh thu hôm nay là {_money(value)}.", "data": {"revenue": value}}

    if "loại xe" in normalized and any(term in normalized for term in ["nhiều nhất", "gửi nhiều"]):
        counts: dict[str, int] = {}
        for ticket in tickets:
            name = ticket.vehicle.vehicle_type if ticket.vehicle else "Không xác định"
            counts[name] = counts.get(name, 0) + 1
        if not counts:
            return {"intent": "vehicle_type_usage", "answer": "Chưa có lượt gửi xe để phân tích.", "data": {}}
        name, count = max(counts.items(), key=lambda item: item[1])
        return {"intent": "vehicle_type_usage", "answer": f"{name} là loại xe có nhiều lượt gửi nhất với {count} lượt.", "data": {"vehicle_type": name, "trips": count}}

    if "khung giờ" in normalized or "giờ nào" in normalized:
        hours: dict[int, int] = {}
        for ticket in tickets:
            if ticket.entry_time:
                hour = ticket.entry_time.hour
                hours[hour] = hours.get(hour, 0) + 1
        if not hours:
            return {"intent": "peak_hour", "answer": "Chưa có dữ liệu lượt xe để xác định khung giờ đông nhất.", "data": {}}
        hour, count = max(hours.items(), key=lambda item: item[1])
        return {"intent": "peak_hour", "answer": f"Khung {hour:02d}:00-{hour + 1:02d}:00 có nhiều lượt xe nhất với {count} lượt.", "data": {"hour": hour, "trips": count}}

    if "a01" in normalized or "vị trí" in normalized and "xe gì" in normalized:
        code = "A01"
        for slot in slots:
            if code.lower() in normalized or slot.slot_code.lower() in normalized:
                if slot.status == "occupied":
                    ticket = next((item for item in slot.tickets if item.status == "parking"), None)
                    vehicle = ticket.vehicle if ticket else None
                    answer = f"Vị trí {slot.slot_code} đang có xe {vehicle.license_plate if vehicle else 'chưa xác định'}."
                else:
                    answer = f"Vị trí {slot.slot_code} hiện không có xe đang đỗ."
                return {"intent": "slot_status", "answer": answer, "data": {"slot_code": slot.slot_code, "status": slot.status}}

    if "công suất" in normalized or "phần trăm" in normalized:
        occupied = sum(slot.status in ["occupied", "reserved"] for slot in slots)
        utilization = round(occupied / len(slots) * 100, 2) if slots else 0
        return {"intent": "utilization", "answer": f"Công suất sử dụng hiện tại là {utilization}%.", "data": {"utilization": utilization}}

    raise LookupError(
        "Tôi chỉ trả lời các câu hỏi về chỗ trống, khu vực, phương tiện, vé, doanh thu, khung giờ và công suất bãi."
    )


def get_capabilities() -> list[dict[str, Any]]:
    provider = get_configured_provider()
    status = "configured" if provider else "not_configured"
    provider_name = "openai_compatible" if provider else None
    reason = None if provider else "Chưa có AI provider"
    return [
        AiCapability(name, status, provider_name, reason).__dict__
        for name in [
            "chatbot",
            "revenue_analysis",
            "occupancy_forecast",
            "license_plate_recognition",
        ]
    ]

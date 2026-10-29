from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import os
from math import ceil
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy.orm import Session

from ..models import ParkingSlot, ParkingTicket, Vehicle
from ..time_utils import VIETNAM_TIMEZONE, to_vietnam_datetime


COMPATIBLE_AI_PROVIDERS = {
    "openai_compatible",
    "openai",
    "ollama",
}

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)

GEMINI_SYSTEM_PROMPT = (
    "Bạn là Gemini, trợ lý nghiệp vụ của hệ thống Parking. "
    "Chỉ dùng dữ liệu được cung cấp; không bịa hoặc tự tính lại số liệu. "
    "Nếu có reference_answer, giữ nguyên các con số và ý nghĩa của câu trả lời đó, "
    "chỉ diễn giải cho dễ hiểu. Nếu dữ liệu không đủ, hãy nói rõ."
)


@dataclass(frozen=True)
class AiCapability:
    name: str
    status: str
    provider: str | None = None
    reason: str | None = None


class AiProvider(Protocol):
    def answer(self, question: str, context: dict[str, Any]) -> str:
        ...


class GeminiProvider:
    """Google Gemini generateContent API provider."""

    provider_name = "gemini"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def answer(self, question: str, context: dict[str, Any]) -> str:
        response = httpx.post(
            GEMINI_API_URL.format(model=quote(self.model, safe="")),
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json={
                "systemInstruction": {
                    "parts": [{"text": GEMINI_SYSTEM_PROMPT}],
                },
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": (
                                    f"Câu hỏi: {question}\n"
                                    f"Dữ liệu hệ thống: "
                                    f"{json.dumps(context, ensure_ascii=False)}"
                                ),
                            },
                        ],
                    },
                ],
                "generationConfig": {"temperature": 0},
            },
            timeout=20,
        )
        response.raise_for_status()
        try:
            candidates = response.json().get("candidates", [])
            parts = candidates[0]["content"]["parts"]
            content = "\n".join(
                part["text"] for part in parts if isinstance(part.get("text"), str)
            ).strip()
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
            raise RuntimeError("Gemini trả về phản hồi không đúng định dạng.") from error
        if not content:
            raise RuntimeError("Gemini trả về phản hồi rỗng.")
        return content


class NotConfiguredAiProvider:
    def answer(self, question: str, context: dict[str, Any]) -> str:
        raise RuntimeError(
            "AI provider chưa được cấu hình; không thể trả lời giả lập."
        )


class OpenAiCompatibleProvider:
    """Provider for OpenAI-compatible chat completion APIs."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        provider_name: str = "openai_compatible",
    ):
        parsed_url = urlsplit(base_url)
        is_local_http = (
            parsed_url.scheme == "http"
            and parsed_url.hostname in {"localhost", "127.0.0.1", "::1"}
        )
        if (
            not parsed_url.hostname
            or (parsed_url.scheme != "https" and not is_local_http)
            or parsed_url.username
            or parsed_url.password
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError(
                "AI_BASE_URL phải là HTTPS hợp lệ; chỉ cho phép HTTP với máy chủ loopback."
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.provider_name = provider_name

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
                            "Không đoán hoặc sửa số liệu. Với staffing_estimate, giữ nguyên "
                            "recommended_staff và nêu rõ đây là ước tính theo giả định. "
                            "Nói rõ khi context không đủ."
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


def get_configured_provider() -> OpenAiCompatibleProvider | GeminiProvider | None:
    provider_name = (
        os.getenv("AI_PROVIDER", "openai_compatible").strip().lower()
        or "openai_compatible"
    )
    api_key = os.getenv("AI_API_KEY", "").strip()
    if not api_key:
        return None
    if provider_name == "gemini":
        model = os.getenv("AI_MODEL", "").strip() or "gemini-3.8-flash"
        return GeminiProvider(api_key, model)
    if provider_name not in COMPATIBLE_AI_PROVIDERS:
        raise ValueError(
            "AI_PROVIDER phải là gemini, openai, openai_compatible hoặc ollama."
        )
    base_url = os.getenv("AI_BASE_URL", "").strip()
    model = os.getenv("AI_MODEL", "").strip()
    if not base_url or not model:
        return None
    return OpenAiCompatibleProvider(base_url, api_key, model, provider_name)


def build_database_context(db: Session) -> dict[str, Any]:
    slots = db.query(ParkingSlot).all()
    tickets = db.query(ParkingTicket).all()
    vehicles = db.query(Vehicle).all()
    return {
        "slots": [
            {
                "code": slot.slot_code,
                "area": slot.area.area_name if slot.area else "",
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
                "entry_time": ticket.check_in.isoformat() if ticket.check_in else None,
                "exit_time": ticket.exit_time.isoformat() if ticket.exit_time else None,
                "fee": float(ticket.amount or 0),
            }
            for ticket in tickets
        ],
    }


def answer_question(db: Session, question: str) -> dict[str, Any]:
    provider = get_configured_provider()
    try:
        result = answer_parking_question(db, question)
    except LookupError:
        if provider is None:
            raise
        context = build_database_context(db)
        try:
            answer = provider.answer(question, context)
        except (httpx.HTTPError, RuntimeError):
            return {
                "intent": "model_analysis",
                "answer": (
                    "Gemini không kết nối được hoặc trả về dữ liệu không hợp lệ. "
                    "Vui lòng thử lại sau."
                ),
                "data": context,
                "source": "deterministic_fallback",
            }
        return {
            "intent": "model_analysis",
            "answer": answer,
            "data": context,
            "source": provider.provider_name,
            "model": provider.model,
        }

    if provider is None:
        return {**result, "source": "database_rules"}

    if result["intent"] == "staffing_recommendation":
        context = {
            "staffing_estimate": result["data"],
            "reference_answer": result["answer"],
        }
    else:
        context = {
            "intent": result["intent"],
            "data": result["data"],
            "reference_answer": result["answer"],
        }
    try:
        model_answer = provider.answer(question, context)
    except (httpx.HTTPError, RuntimeError):
        return {
            **result,
            "answer": (
                f"{result['answer']} Gemini hiện không kết nối được; "
                "đây là kết quả tính từ dữ liệu hệ thống."
            ),
            "source": "deterministic_fallback",
        }
    return {
        **result,
        "answer": model_answer,
        "source": provider.provider_name,
        "model": provider.model,
    }


def _money(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".") + " ₫"


def traffic_metrics(tickets, period: str, now: datetime | None = None) -> dict[str, Any]:
    local_now = now or datetime.now(VIETNAM_TIMEZONE)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=VIETNAM_TIMEZONE)
    local_now = local_now.astimezone(VIETNAM_TIMEZONE)
    today = local_now.date()

    if period == "today":
        start_date = end_date = today
    elif period == "week":
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    elif period == "last_7_days":
        start_date = today - timedelta(days=6)
        end_date = today
    else:
        raise ValueError(f"Khoảng thời gian không được hỗ trợ: {period}")

    daily_counts = {
        (start_date + timedelta(days=offset)).isoformat(): 0
        for offset in range((end_date - start_date).days + 1)
    }
    hourly_counts: dict[tuple[str, int], int] = {}
    for ticket in tickets:
        if not ticket.check_in:
            continue
        entry_time = to_vietnam_datetime(ticket.check_in)
        entry_date = entry_time.date()
        if start_date <= entry_date <= end_date:
            daily_counts[entry_date.isoformat()] += 1
            hour_bucket = (entry_date.isoformat(), entry_time.hour)
            hourly_counts[hour_bucket] = hourly_counts.get(hour_bucket, 0) + 1

    peak = None
    if hourly_counts:
        peak_date, hour = max(sorted(hourly_counts), key=hourly_counts.get)
        peak = {
            "date": peak_date,
            "hour": hour,
            "trips": hourly_counts[(peak_date, hour)],
        }

    return {
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": [
            {"date": day, "trips": trips}
            for day, trips in daily_counts.items()
        ],
        "peak": peak,
    }


def estimate_staff_count(peak: dict[str, int] | None, arrivals_per_employee: int) -> int:
    if not peak or peak["trips"] <= 0:
        return 0
    return ceil(peak["trips"] / max(1, arrivals_per_employee))


def _period_from_question(question: str) -> str:
    if "tuần" in question:
        return "week"
    if "hôm nay" in question or "ngày hôm nay" in question:
        return "today"
    if "7 ngày" in question:
        return "last_7_days"
    return "last_7_days"


def _arrivals_per_employee() -> int:
    try:
        return max(1, int(os.getenv("AI_ARRIVALS_PER_EMPLOYEE_PER_HOUR", "10")))
    except ValueError:
        return 10


def _today_tickets(db: Session):
    today = datetime.now(VIETNAM_TIMEZONE).date()
    return [
        ticket
        for ticket in db.query(ParkingTicket).all()
        if ticket.check_in and to_vietnam_datetime(ticket.check_in).date() == today
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
    today_tickets = _today_tickets(db)
    completed = [
        ticket for ticket in tickets
        if str(ticket.status).upper() in {"PAID", "COMPLETED", "FINISHED"}
    ]
    today = datetime.now(VIETNAM_TIMEZONE).date()
    month = today.replace(day=1)

    def revenue_since(start_date):
        return sum(
            float(ticket.amount or 0)
            for ticket in completed
            if ticket.exit_time and to_vietnam_datetime(ticket.exit_time).date() >= start_date
        )

    if any(term in normalized for term in ["còn bao nhiêu chỗ", "chỗ trống", "vị trí đang trống"]):
        available = sum(str(slot.status).upper() in {"EMPTY", "AVAILABLE"} for slot in slots)
        return {
            "intent": "available_slots",
            "answer": f"Hiện bãi có {available} vị trí đang trống trên tổng số {len(slots)} vị trí.",
            "data": {"available": available, "total": len(slots)},
        }

    if "khu nào" in normalized and any(term in normalized for term in ["nhiều chỗ", "trống"]):
        areas: dict[str, int] = {}
        for slot in slots:
            if str(slot.status).upper() in {"EMPTY", "AVAILABLE"}:
                name = slot.area.area_name if slot.area else "Không xác định"
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

    if "nhân sự" in normalized or "nhân viên" in normalized or "bố trí ca" in normalized:
        period = _period_from_question(normalized)
        metrics = traffic_metrics(tickets, period)
        peak = metrics["peak"]
        capacity = _arrivals_per_employee()
        staff_count = estimate_staff_count(peak, capacity)
        if peak is None:
            answer = "Chưa có lượt xe trong khoảng thời gian này nên chưa thể ước tính nhân sự."
        else:
            end_hour = (peak["hour"] + 1) % 24
            answer = (
                f"Giờ cao điểm ngày {peak['date']} "
                f"{peak['hour']:02d}:00-{end_hour:02d}:00 có "
                f"{peak['trips']} lượt xe. Theo giả định 1 nhân viên xử lý "
                f"{capacity} lượt/giờ, nên bố trí khoảng {staff_count} nhân viên "
                "trong khung giờ này. Hãy đối chiếu với nhiệm vụ và quy định ca trực."
            )
        return {
            "intent": "staffing_recommendation",
            "answer": answer,
            "data": {
                "period": period,
                "peak": peak,
                "arrivals_per_employee_per_hour": capacity,
                "recommended_staff": staff_count,
            },
        }

    if "lưu lượng" in normalized or "theo ngày" in normalized or (
        "tuần" in normalized and any(term in normalized for term in ["lượt xe", "xe vào"])
    ):
        period = _period_from_question(normalized)
        metrics = traffic_metrics(tickets, period)
        rows = metrics["daily"]
        summary = "; ".join(f"{row['date']}: {row['trips']} lượt" for row in rows)
        return {
            "intent": "traffic_report",
            "answer": f"Lưu lượng xe ({metrics['start_date']} đến {metrics['end_date']}): {summary}.",
            "data": metrics,
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
        period = _period_from_question(normalized)
        metrics = traffic_metrics(tickets, period)
        peak = metrics["peak"]
        if peak is None:
            return {"intent": "peak_hour", "answer": "Chưa có dữ liệu lượt xe để xác định khung giờ đông nhất.", "data": {}}
        hour = peak["hour"]
        end_hour = (hour + 1) % 24
        return {
            "intent": "peak_hour",
            "answer": (
                f"Trong khoảng {metrics['start_date']} đến {metrics['end_date']}, "
                f"ngày {peak['date']} "
                f"khung {hour:02d}:00-{end_hour:02d}:00 đông nhất với {peak['trips']} lượt."
            ),
            "data": {**metrics, "hour": hour, "trips": peak["trips"]},
        }

    if "a01" in normalized or "vị trí" in normalized and "xe gì" in normalized:
        code = "A01"
        for slot in slots:
            if code.lower() in normalized or slot.slot_code.lower() in normalized:
                if str(slot.status).upper() == "OCCUPIED":
                    ticket = next(
                        (
                            item for item in slot.tickets
                            if str(item.status).upper() in {"PARKING", "ACTIVE"}
                        ),
                        None,
                    )
                    vehicle = ticket.vehicle if ticket else None
                    answer = f"Vị trí {slot.slot_code} đang có xe {vehicle.license_plate if vehicle else 'chưa xác định'}."
                else:
                    answer = f"Vị trí {slot.slot_code} hiện không có xe đang đỗ."
                return {"intent": "slot_status", "answer": answer, "data": {"slot_code": slot.slot_code, "status": slot.status}}

    if "công suất" in normalized or "phần trăm" in normalized:
        occupied = sum(
            str(slot.status).upper() in {"OCCUPIED", "RESERVED"}
            for slot in slots
        )
        utilization = round(occupied / len(slots) * 100, 2) if slots else 0
        return {"intent": "utilization", "answer": f"Công suất sử dụng hiện tại là {utilization}%.", "data": {"utilization": utilization}}

    raise LookupError(
        "Tôi hỗ trợ câu hỏi về chỗ trống, khu vực, phương tiện, vé, doanh thu, "
        "lưu lượng theo ngày/tuần, giờ cao điểm, gợi ý nhân sự và công suất bãi."
    )


def get_capabilities() -> list[dict[str, Any]]:
    provider = get_configured_provider()
    return [
        AiCapability(
            "chatbot",
            "configured" if provider else "deterministic",
            provider.provider_name if provider else "rules",
            None if provider else "Câu hỏi nghiệp vụ được xử lý bằng quy tắc và dữ liệu CSDL.",
        ).__dict__,
        AiCapability(
            "revenue_analysis",
            "deterministic",
            "rules",
            "Thống kê dựa trên vé và khoản thu trong CSDL.",
        ).__dict__,
        AiCapability(
            "staffing_recommendation",
            "configured_ai_with_rule_based_estimate" if provider else "deterministic",
            provider.provider_name if provider else "rules",
            "Model chỉ diễn giải đề xuất; số nhân sự được tính từ lưu lượng và giả định cấu hình.",
        ).__dict__,
        AiCapability(
            "occupancy_forecast",
            "not_implemented",
            reason="Chưa có mô hình hoặc thuật toán dự báo công suất.",
        ).__dict__,
        AiCapability(
            "license_plate_recognition",
            "not_implemented",
            reason="Chưa tích hợp mô hình nhận diện biển số.",
        ).__dict__,
    ]

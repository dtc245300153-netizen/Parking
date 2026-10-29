from datetime import datetime, timezone
from types import SimpleNamespace

from app.models import ParkingSlot, ParkingTicket, Vehicle
from app.services.ai import (
    answer_parking_question,
    answer_question,
    estimate_staff_count,
    get_capabilities,
    traffic_metrics,
)
from app.time_utils import VIETNAM_TIMEZONE


def _ticket(check_in):
    return SimpleNamespace(
        check_in=check_in,
        status="PARKING",
        amount=0,
        exit_time=None,
    )


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _FakeDb:
    def __init__(self, tickets):
        self.rows = {
            ParkingSlot: [],
            ParkingTicket: tickets,
            Vehicle: [],
        }

    def query(self, model):
        return _FakeQuery(self.rows.get(model, []))


def test_weekly_traffic_uses_vietnam_time_and_excludes_previous_week():
    now = datetime(2026, 10, 28, 12, 0, tzinfo=VIETNAM_TIMEZONE)
    tickets = [
        _ticket(datetime(2026, 10, 25, 16, 59)),
        _ticket(datetime(2026, 10, 26, 2, 15)),
        _ticket(datetime(2026, 10, 26, 10, 30)),
        _ticket(datetime(2026, 10, 26, 10, 45)),
        _ticket(datetime(2026, 10, 27, 10, 30)),
        _ticket(datetime(2026, 10, 27, 10, 45)),
        _ticket(datetime(2026, 10, 28, 2, 15)),
        _ticket(datetime(2026, 10, 28, 2, 30)),
        _ticket(datetime(2026, 10, 28, 2, 45)),
        _ticket(datetime(2026, 10, 28, 10, 30)),
        _ticket(datetime(2026, 10, 28, 10, 45)),
    ]

    result = traffic_metrics(tickets, "week", now)

    assert result["start_date"] == "2026-10-26"
    assert result["end_date"] == "2026-10-28"
    assert result["daily"] == [
        {"date": "2026-10-26", "trips": 3},
        {"date": "2026-10-27", "trips": 2},
        {"date": "2026-10-28", "trips": 5},
    ]
    assert result["peak"] == {"date": "2026-10-28", "hour": 9, "trips": 3}


def test_today_traffic_includes_utc_entries_on_vietnam_local_date():
    now = datetime(2026, 10, 28, 12, 0, tzinfo=VIETNAM_TIMEZONE)
    tickets = [
        _ticket(datetime(2026, 10, 27, 17, 5)),
        _ticket(datetime(2026, 10, 28, 16, 59)),
    ]

    result = traffic_metrics(tickets, "today", now)

    assert result["daily"] == [{"date": "2026-10-28", "trips": 2}]
    assert result["peak"] == {"date": "2026-10-28", "hour": 0, "trips": 1}


def test_staff_estimate_rounds_up_and_handles_no_traffic():
    assert estimate_staff_count({"hour": 17, "trips": 21}, 10) == 3
    assert estimate_staff_count(None, 10) == 0


def test_demo_traffic_question_returns_weekly_daily_breakdown():
    result = answer_parking_question(
        _FakeDb([]),
        "Báo cáo lưu lượng xe tuần này theo ngày",
    )

    assert result["intent"] == "traffic_report"
    assert result["data"]["period"] == "week"
    assert result["data"]["daily"]


def test_demo_staffing_question_uses_configured_arrival_ratio(monkeypatch):
    monkeypatch.setenv("AI_ARRIVALS_PER_EMPLOYEE_PER_HOUR", "10")
    check_in = datetime.now(timezone.utc).replace(minute=10, second=0, microsecond=0, tzinfo=None)
    tickets = [_ticket(check_in) for _ in range(21)]

    result = answer_parking_question(
        _FakeDb(tickets),
        "Gợi ý bố trí nhân sự tuần này",
    )

    assert result["intent"] == "staffing_recommendation"
    assert result["data"]["recommended_staff"] == 3


def test_capabilities_do_not_claim_forecast_or_plate_recognition(monkeypatch):
    monkeypatch.setenv("AI_BASE_URL", "https://ai.example")
    monkeypatch.setenv("AI_API_KEY", "configured-for-test")
    monkeypatch.setenv("AI_MODEL", "demo-model")

    capabilities = {item["name"]: item for item in get_capabilities()}

    assert capabilities["chatbot"]["status"] == "configured"
    assert capabilities["occupancy_forecast"]["status"] == "not_implemented"
    assert capabilities["license_plate_recognition"]["status"] == "not_implemented"


def test_staffing_uses_configured_provider_with_authoritative_estimate(monkeypatch):
    class _Provider:
        def answer(self, question, context):
            assert context["staffing_estimate"]["recommended_staff"] == 3
            return "Model diễn giải đề xuất 3 nhân viên theo dữ liệu được cung cấp."

    check_in = datetime.now(timezone.utc).replace(minute=10, second=0, microsecond=0, tzinfo=None)
    tickets = [_ticket(check_in) for _ in range(21)]
    monkeypatch.setattr("app.services.ai.get_configured_provider", lambda: _Provider())

    result = answer_question(_FakeDb(tickets), "Gợi ý bố trí nhân sự tuần này")

    assert result["source"] == "configured_ai_model_with_rule_based_estimate"
    assert "3 nhân viên" in result["answer"]
    assert result["data"]["recommended_staff"] == 3


def test_staffing_falls_back_when_configured_provider_fails(monkeypatch):
    class _UnavailableProvider:
        def answer(self, question, context):
            raise RuntimeError("provider unavailable")

    check_in = datetime.now(timezone.utc).replace(minute=10, second=0, microsecond=0, tzinfo=None)
    tickets = [_ticket(check_in) for _ in range(12)]
    monkeypatch.setattr(
        "app.services.ai.get_configured_provider",
        lambda: _UnavailableProvider(),
    )

    result = answer_question(_FakeDb(tickets), "Gợi ý bố trí nhân sự tuần này")

    assert result["source"] == "deterministic_fallback"
    assert result["data"]["recommended_staff"] == 2
    assert "không kết nối được" in result["answer"]

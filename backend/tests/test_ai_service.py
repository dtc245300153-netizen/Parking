from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models import ParkingSlot, ParkingTicket, Vehicle
from app.services.ai import (
    GeminiProvider,
    OpenAiCompatibleProvider,
    answer_parking_question,
    answer_question,
    estimate_staff_count,
    get_configured_provider,
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


def test_openai_compatible_provider_sends_key_and_parking_context_server_side(monkeypatch):
    api_key = "test-api-key-never-returned"
    monkeypatch.setenv("AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("AI_BASE_URL", "https://ai.example/v1/")
    monkeypatch.setenv("AI_API_KEY", api_key)
    monkeypatch.setenv("AI_MODEL", "parking-model")
    captured = {}

    class _Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "Còn 4 chỗ trống."}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.services.ai.httpx.post", fake_post)
    provider = get_configured_provider()

    assert provider is not None
    assert provider.provider_name == "openai_compatible"
    answer = provider.answer("Còn bao nhiêu chỗ?", {"empty_slots": 4})

    assert answer == "Còn 4 chỗ trống."
    assert captured["url"] == "https://ai.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == f"Bearer {api_key}"
    assert captured["json"]["model"] == "parking-model"
    assert captured["json"]["messages"][0]["role"] == "system"
    assert "empty_slots" in captured["json"]["messages"][1]["content"]
    assert api_key not in answer
    assert api_key not in repr(get_capabilities())
    capabilities = {item["name"]: item for item in get_capabilities()}
    assert capabilities["chatbot"]["provider"] == "openai_compatible"


def test_groq_provider_uses_default_endpoint_and_model(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "groq")
    monkeypatch.setenv("AI_API_KEY", "groq-test-key")
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)

    provider = get_configured_provider()

    assert provider is not None
    assert provider.provider_name == "groq"
    assert provider.base_url == "https://api.groq.com/openai/v1"
    assert provider.model == "openai/gpt-oss-120b"


def test_ollama_provider_uses_local_defaults_without_api_key(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)

    provider = get_configured_provider()

    assert provider is not None
    assert provider.provider_name == "ollama"
    assert provider.base_url == "http://127.0.0.1:11434/v1"
    assert provider.model == "qwen2.5:3b"
    assert provider.api_key == "ollama"


def test_ollama_general_question_is_sent_without_empty_context(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    captured = {}

    class _Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "Toyota."}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.services.ai.httpx.post", fake_post)
    provider = get_configured_provider()

    assert provider is not None
    assert provider.answer("Hãng xe nào nổi tiếng?", {}) == "Toyota."
    assert captured["json"]["messages"][1]["content"] == "Hãng xe nào nổi tiếng?"
    assert "Đừng nói rằng thiếu context" in captured["json"]["messages"][0]["content"]
    assert captured["json"]["temperature"] == 0.2
    assert captured["timeout"] == 120


def test_gemini_provider_uses_native_api_and_keeps_key_server_side(monkeypatch):
    api_key = "gemini-test-key"
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("AI_API_KEY", api_key)
    monkeypatch.setenv("AI_MODEL", "gemini-3.8-flash")
    captured = {}

    class _Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "Gemini đang hoạt động."}],
                        },
                    },
                ],
            }

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.services.ai.httpx.post", fake_post)
    provider = get_configured_provider()

    assert isinstance(provider, GeminiProvider)
    assert provider is not None
    assert provider.answer("Kiểm tra", {"slots": 4}) == "Gemini đang hoạt động."
    assert (
        captured["url"]
        == "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-3.8-flash:generateContent"
    )
    assert captured["headers"]["x-goog-api-key"] == api_key
    assert api_key not in captured["url"]
    assert captured["json"]["systemInstruction"]["parts"]
    assert captured["json"]["contents"][0]["role"] == "user"
    assert "slots" in captured["json"]["contents"][0]["parts"][0]["text"]


def test_gemini_provider_rejects_malformed_response(monkeypatch):
    class _Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": []}

    monkeypatch.setattr(
        "app.services.ai.httpx.post",
        lambda *args, **kwargs: _Response(),
    )

    with pytest.raises(RuntimeError, match="không đúng định dạng"):
        GeminiProvider("test-key", "gemini-2.5-flash").answer("hello", {})


def test_ai_provider_requires_https_except_for_loopback_ollama():
    with pytest.raises(ValueError, match="HTTPS"):
        OpenAiCompatibleProvider(
            "http://ai.example/v1",
            "test-key",
            "parking-model",
        )

    provider = OpenAiCompatibleProvider(
        "http://localhost:11434/v1",
        "ollama",
        "llama3",
    )

    assert provider.base_url == "http://localhost:11434/v1"


def test_unknown_ai_provider_configuration_is_rejected(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "unsupported-provider")
    monkeypatch.setenv("AI_BASE_URL", "https://ai.example/v1")
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_MODEL", "parking-model")

    with pytest.raises(ValueError, match="AI_PROVIDER"):
        get_configured_provider()


def test_staffing_uses_configured_provider_with_authoritative_estimate(monkeypatch):
    class _Provider:
        provider_name = "gemini"
        model = "gemini-test"

        def answer(self, question, context):
            assert context["staffing_estimate"]["recommended_staff"] == 3
            return "Model diễn giải đề xuất 3 nhân viên theo dữ liệu được cung cấp."

    check_in = datetime.now(timezone.utc).replace(minute=10, second=0, microsecond=0, tzinfo=None)
    tickets = [_ticket(check_in) for _ in range(21)]
    monkeypatch.setattr("app.services.ai.get_configured_provider", lambda: _Provider())

    result = answer_question(_FakeDb(tickets), "Gợi ý bố trí nhân sự tuần này")

    assert result["source"] == "gemini"
    assert result["model"] == "gemini-test"
    assert "3 nhân viên" in result["answer"]
    assert result["data"]["recommended_staff"] == 3


def test_configured_gemini_handles_supported_parking_questions(monkeypatch):
    class _Provider:
        provider_name = "gemini"
        model = "gemini-test"

        def answer(self, question, context):
            assert question == "Bãi còn bao nhiêu chỗ?"
            assert context["intent"] == "available_slots"
            assert context["data"] == {"available": 0, "total": 0}
            return "Gemini: bãi hiện chưa có vị trí."

    monkeypatch.setattr("app.services.ai.get_configured_provider", lambda: _Provider())

    result = answer_question(_FakeDb([]), "Bãi còn bao nhiêu chỗ?")

    assert result["answer"] == "Gemini: bãi hiện chưa có vị trí."
    assert result["source"] == "gemini"
    assert result["model"] == "gemini-test"


def test_general_question_uses_ai_without_sending_database_context(monkeypatch):
    class _Provider:
        provider_name = "groq"
        model = "groq-test"

        def answer(self, question, context):
            assert question == "Hãng xe nào nổi tiếng?"
            assert context == {}
            return "Toyota và Mercedes-Benz là những hãng xe nổi tiếng."

    monkeypatch.setattr("app.services.ai.get_configured_provider", lambda: _Provider())

    result = answer_question(_FakeDb([]), "Hãng xe nào nổi tiếng?")

    assert result["source"] == "groq"
    assert result["model"] == "groq-test"
    assert "Toyota" in result["answer"]


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

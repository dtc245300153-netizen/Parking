import httpx
from dotenv import load_dotenv

from app.services.ai import GeminiProvider, get_configured_provider


load_dotenv()
provider = get_configured_provider()
if not isinstance(provider, GeminiProvider):
    raise SystemExit(
        "Gemini chưa được cấu hình. Hãy đặt AI_PROVIDER=gemini và AI_API_KEY "
        "trong backend/.env."
    )

try:
    answer = provider.answer(
        "Trả lời ngắn gọn bằng tiếng Việt: Gemini đang kết nối.",
        {"purpose": "connection_check"},
    )
except (httpx.HTTPError, RuntimeError) as error:
    raise SystemExit(
        f"Kết nối Gemini thất bại ({type(error).__name__}). "
        "Kiểm tra API key, model và quyền truy cập mạng."
    ) from error

print("GEMINI_LIVE=OK")
print(f"MODEL={provider.model}")
print(f"RESPONSE={answer}")

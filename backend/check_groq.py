import httpx
from dotenv import load_dotenv

from app.services.ai import OpenAiCompatibleProvider, get_configured_provider


load_dotenv()
provider = get_configured_provider()
if not isinstance(provider, OpenAiCompatibleProvider) or provider.provider_name != "groq":
    raise SystemExit(
        "Groq chưa được cấu hình. Hãy đặt AI_PROVIDER=groq và AI_API_KEY "
        "trong backend/.env."
    )

try:
    answer = provider.answer(
        "Trả lời ngắn gọn bằng tiếng Việt: Groq đang kết nối.",
        {},
    )
except (httpx.HTTPError, RuntimeError) as error:
    raise SystemExit(
        f"Kết nối Groq thất bại ({type(error).__name__}). "
        "Kiểm tra API key, model, quota và quyền truy cập mạng."
    ) from error

print("GROQ_LIVE=OK")
print(f"MODEL={provider.model}")
print(f"RESPONSE={answer}")

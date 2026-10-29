import httpx
import sys
from dotenv import load_dotenv

from app.services.ai import OpenAiCompatibleProvider, get_configured_provider


load_dotenv()
provider = get_configured_provider()
if not isinstance(provider, OpenAiCompatibleProvider) or provider.provider_name != "ollama":
    raise SystemExit(
        "Ollama chưa được chọn. Đặt AI_PROVIDER=ollama trong backend/.env."
    )

try:
    answer = provider.answer(
        "Nêu tên một hãng ô tô nổi tiếng.",
        {},
    )
except (httpx.HTTPError, RuntimeError) as error:
    raise SystemExit(
        f"Kết nối Ollama thất bại ({type(error).__name__}). "
        "Kiểm tra ứng dụng Ollama và model đã được cài."
    ) from error

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

print("OLLAMA_LIVE=OK")
print(f"MODEL={provider.model}")
print(f"RESPONSE={answer}")

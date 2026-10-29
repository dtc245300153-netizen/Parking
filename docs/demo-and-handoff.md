# Demo and Handoff Checklist

## Local setup

Run commands from the `backend` directory:

```powershell
python -m pip install -r requirements.txt
Copy-Item ..\.env.example .env
python seed_data.py
python -m pytest -q tests
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080/login`. The local demo account created by `create_admin.py` is `admin` / `123456`; use it only in a local demo and change the password before deployment.

## Local AI configuration

Install Ollama, then download a Vietnamese-capable local model:

```powershell
ollama pull qwen2.5:3b
```

Set these values in `backend/.env`; no API key is required:

```dotenv
AI_PROVIDER=ollama
AI_BASE_URL=http://127.0.0.1:11434/v1
AI_MODEL=qwen2.5:3b
AI_ARRIVALS_PER_EMPLOYEE_PER_HOUR=10
```

Run `python check_ollama.py` from `backend` to verify a live local response. The assistant does not search the live web; model speed and answer quality depend on the computer. Local inference avoids hosted API quotas but is not guaranteed to be error-free. Gemini and Groq remain supported as alternatives.

On Windows systems with older GPU drivers, run Ollama CPU-only to avoid incompatible GPU backends. Set the user environment variables `OLLAMA_VULKAN=0` and `GGML_VK_VISIBLE_DEVICES=-1`, then restart Ollama. CPU-only responses may be slower.

## Demo flow

1. Sign in as the local admin. The default page is Overview, with live capacity, revenue, area usage, trends, and recent tickets.
2. Open the parking map and demonstrate a vehicle entry/exit. Confirm the slot status changes and the overview refreshes within 10 seconds.
3. Open Employees to create a staff account, update its position, and lock/unlock the account. This menu is admin-only.
4. Review unread notifications on Overview, mark one as read, then open the admin-only activity log.
5. Open Parking Assistant and ask `Báo cáo lưu lượng xe tuần này theo ngày`.
6. Ask `Khung giờ nào đông nhất tuần này?` and explain that peaks are grouped by Vietnam-local date and hour.
7. Ask `Gợi ý bố trí nhân sự tuần này`. State the configured arrivals-per-employee assumption and that the result is an estimate, not a shift schedule.
8. Start Ollama, configure the selected provider in `backend/.env`, restart the server, and confirm a chat answer is labeled with the configured provider and model.

## Automated test coverage

Run `python -m pytest -q tests`. Tests use a temporary SQLite database and cover:

- Weekly/day traffic aggregation, UTC-to-Vietnam time conversion, and daily peak-hour grouping.
- Staffing estimate rounding, configured-provider interpretation, provider failure fallback, and capability statuses.
- Valid/invalid login and admin-only revenue authorization.
- Admin-only employee listing, sanitized employee data, position updates, account locking, and employee-profile creation.
- Admin-only audit logs and notification listing/read state.
- Ticket check-in/check-out, slot state changes, fee calculation at the 60/61-minute boundary, and missing pricing rules.

The provider tests mock the HTTP response. They verify the chat-completions URL, model, context, server-side Bearer header, HTTPS requirement, and fallback logic, not the availability or quality of a third-party model.

There is no monthly-pass product in the current schema or pricing policy. Parking fees are charged from duration-based price rules; do not present recurring monthly billing as implemented.

## Submission evidence

Before submission, capture screenshots or a short recording of Overview, parking slot state, employee management, revenue view, and the three assistant questions. Keep the final test output and note the test date, Python version, database mode, and whether a real AI provider was configured. Include the project architecture, API summary, known limitations, and the AI prompt/test notes in the report or slides if required by the course rubric.

The project now has a project-scoped Git repository. Verify the root before staging any work:

```powershell
git rev-parse --show-toplevel
```

The project root should resolve to `C:/Users/Admin/Downloads/Parking-main/Parking-main`. The parent directory `C:/Users/Admin` contains unrelated personal files; do not stage or commit from that parent repository. No files have been staged or committed as part of this work.

# AI Development Log

This document records how AI assistance was used during development. It is evidence of assistance, not a claim that the application contains a generative AI model.

## Session 1: Runtime and data audit

**Prompt summary:** Inspect the Parking AI project, find hard-coded dashboard values, API mismatches and runtime errors.

**AI response used:** Identified the corrupted `<Questions>` tags in `parking.html`, mismatched form/JSON payloads, incorrect slot/ticket URLs, and dashboard response key mismatch.

**Student verification and edits:** Removed the corrupted tags, aligned frontend requests with FastAPI routes, compiled Python, parsed embedded JavaScript with Node, and exercised the application in a browser.

## Session 2: Data-driven dashboard

**Prompt summary:** Replace fake metrics with database-backed parking, ticket, revenue and utilization data.

**AI response used:** Proposed dashboard and revenue aggregations, slot detail responses, vehicle/ticket metadata and canonical vehicle-type mapping.

**Student verification and edits:** Confirmed values against `/api/dashboard/summary`, `/api/revenue`, area/slot endpoints and the SQLite database. Kept seed data separate from UI metrics.

## Session 3: Extensibility architecture

**Prompt summary:** Prepare audit logs, notifications, role hierarchy, QR payloads, backup/restore and an AI integration boundary without fake AI.

**AI response used:** Added additive SQLAlchemy models, role helpers, service interfaces, API endpoints and architecture documentation.

**Student verification and edits:** Confirmed OpenAPI routes, Python compilation, backup creation, authorization behavior and `501 Not Configured` for the unconfigured generative provider.

## Session 4: Parking AI data assistant

**Prompt summary:** Add a fixed Parking AI chat button that answers parking questions from real database/API data.

**AI response used:** Added `answer_parking_question()` and `/api/ai/assistant`, with deterministic intents for availability, areas, vehicles, tickets, revenue, vehicle types, peak hour, slot status and utilization.

**Student verification and edits:** Tested all requested questions against the running database, tested an unsupported question returns `422`, and verified the browser chat has no console/page errors. The assistant is explicitly a factual data assistant; no generative answer is claimed.

## Session 5: Traffic, staffing, and API verification

**Prompt summary:** Make the rubric demo answer daily/weekly traffic, identify date-specific peak hours, provide a transparent staffing suggestion, and add backend workflow tests.

**AI response used:** Added timezone-aware traffic aggregation grouped by local date and hour, a configurable arrivals-per-employee estimate, optional provider interpretation of that estimate, and a deterministic fallback. Seed data includes repeatable paid trips over the latest seven days. Added isolated SQLite API tests for login/authorization, ticket entry/exit, and pricing boundaries.

**Student verification and edits:** Tests cover weekly boundaries, UTC-to-Vietnam conversion, repeated hour buckets across dates, provider success/failure, capability reporting, login/authorization, ticket entry/exit, and 60/61-minute pricing boundaries. `python -m pytest -q tests` passes. The provider test is mocked; a real provider still requires local configuration and a manual smoke test. The estimate is documented as an operational estimate, not a predictive model or shift scheduler.

# FleetSignal

**Fleet Telemetry and Rental Operations** for a Caterpillar dealer: fleet visibility, explainable alert episodes, rental lifecycle tracking, and demand allocation recommendations, with retry-safe telemetry ingestion backed by file SQLite.

The application lives in [`caterpillar-smart-rental/`](caterpillar-smart-rental/README.md). Its [README](caterpillar-smart-rental/README.md) covers Python 3.11/uv and Node 22.19.0 setup, explicit demo mode, Docker persistence, and local verification. Read the [API contract](caterpillar-smart-rental/docs/API_CONTRACT.md), [reliability guarantees and limits](caterpillar-smart-rental/docs/RELIABILITY.md), and [completion evidence](caterpillar-smart-rental/docs/COMPLETION_REPORT.md).

The seven-asset story preserves the original SRTS hackathon demo: EQX1007 is an idle excavator that can be recovered for S003. Its dataset, forecasts, and fixed business clock (`2025-05-12`) are historical synthetic examples. The original [hackathon spec](caterpillar-smart-rental/docs/HACKATHON_SPEC.md) and [implementation plan](caterpillar-smart-rental/docs/IMPLEMENTATION_PLAN.md) remain available as historical context.

Default backend startup applies validated migrations without seed data or demo control routes. Demo mode is explicitly enabled for the local Compose demonstration. No hosted deployment, production scale, external APIs, authentication, or machine-learning claims are made.

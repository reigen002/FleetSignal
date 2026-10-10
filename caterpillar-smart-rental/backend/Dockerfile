FROM python:3.11-slim

WORKDIR /opt/fleetsignal/backend

RUN pip install uv==0.13.0 --no-cache-dir

# Build from the repository root so the same image includes configured demo data.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
COPY data/ /opt/fleetsignal/data/
RUN uv sync --frozen --no-dev

ENV PATH="/opt/fleetsignal/backend/.venv/bin:$PATH" \
    FLEETSIGNAL_DATA_DIR="/opt/fleetsignal/data" \
    FLEETSIGNAL_DATABASE_URL="sqlite:////var/lib/fleetsignal/fleetsignal.db" \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

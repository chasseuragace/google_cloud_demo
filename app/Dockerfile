FROM python:3.12-slim

WORKDIR /app

ENV PATH="/root/.local/bin:$PATH"
ENV PORT=8000

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen

COPY . /app

ENV PATH="/app/.venv/bin:$PATH"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

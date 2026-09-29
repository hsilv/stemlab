FROM ghcr.io/astral-sh/uv:0.8.22 AS uv
FROM python:3.11-slim-bookworm
ARG INFERENCE_EXTRA=inference
COPY --from=uv /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
WORKDIR /app
RUN useradd --create-home --uid 10001 stemlab && mkdir /data && chown stemlab:stemlab /data
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra ${INFERENCE_EXTRA}
COPY src ./src
RUN uv sync --frozen --no-dev --extra ${INFERENCE_EXTRA}
ENV PATH="/app/.venv/bin:$PATH" STEMLAB_DATA_DIR=/data TORCH_HOME=/data/models
USER stemlab
EXPOSE 8000
CMD ["uvicorn", "stemlab.main:app", "--host", "0.0.0.0", "--port", "8000"]

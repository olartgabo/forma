FROM ghcr.io/astral-sh/uv:0.11.16 AS uv

FROM python:3.12.6-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY apps/api/src apps/api/src
COPY packages/domain/src packages/domain/src
COPY packages/compiler/src packages/compiler/src
COPY packages/renderer/src packages/renderer/src
COPY packages/replanner/src packages/replanner/src
COPY packages/fabrication/src packages/fabrication/src
COPY packages/repair_search/src packages/repair_search/src
COPY packages/stability/src packages/stability/src
COPY packages/eval/src packages/eval/src
COPY packages/synthesizer/src packages/synthesizer/src
COPY packages/measurement/src packages/measurement/src
RUN uv sync --locked --no-dev --no-editable

RUN useradd --system --uid 10001 forma && mkdir /data && chown forma /data
USER forma
ENV PATH=/opt/venv/bin:$PATH \
    FORMA_DATA_DIR=/data
EXPOSE 8000
# One worker: the SQLite store and media directory are local to this container.
CMD ["uvicorn", "forma_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

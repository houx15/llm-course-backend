FROM python:3.12

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN python3 -m pip install -U uv -i https://mirrors.aliyun.com/pypi/simple --break-system-packages

COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

COPY app ./app
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

EXPOSE 10723

CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 10723"]

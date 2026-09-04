FROM python:3.10-slim

WORKDIR /app

ENV DENDROFLOW_ROOT=/app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY db ./db

RUN pip install --no-cache-dir .

CMD ["python", "-m", "dendroflow", "migrate"]

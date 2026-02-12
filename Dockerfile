# Reproducible evaluator image for data engineers.
# Python 3.12; git required for cloning repos.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY evaluator/ evaluator/
COPY config/ config/

ENV REPO_EVALUATOR_ROOT=/app
ENV PYTHONUNBUFFERED=1

# Default: show help. Override with docker run ... evaluate --file input/repos.xlsx
ENTRYPOINT ["python", "-m", "evaluator.cli"]
CMD ["--help"]

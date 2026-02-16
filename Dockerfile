# Reproducible evaluator image for data engineers.
# Python 3.12; git for cloning; Docker CLI (static binary) so the evaluator can run candidate pipelines in containers.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates git \
    && curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-27.3.1.tgz | tar xzv -C /tmp \
    && mv /tmp/docker/docker /usr/local/bin/docker \
    && chmod +x /usr/local/bin/docker \
    && rm -rf /tmp/docker \
    && apt-get purge -y curl \
    && apt-get autoremove -y -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY evaluator/ evaluator/
COPY config/ config/
COPY tests/ tests/
COPY .coveragerc .coveragerc

ENV REPO_EVALUATOR_ROOT=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Default: run evaluation (input/repos.xlsx -> output/repos_evaluated.xlsx)
ENTRYPOINT ["python", "main.py"]
CMD ["--file", "input/repos.xlsx", "--output", "repos_evaluated.xlsx"]

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_ROOT_USER_ACTION=ignore
WORKDIR /app

# Pinned deps first so code edits only rebuild the cheap --no-deps layer below.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml pipeline.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

COPY data ./data

# No root at runtime: the auditor reads untrusted traces, so it gets no more rights than it needs.
RUN useradd --create-home --uid 10001 auditor && mkdir -p /app/reviews && chown auditor /app/reviews
USER auditor

CMD ["python", "-m", "rosetta_flow"]

# WHA Membership Data Platform — console + nightly pull, one container.
# Target: Cloud Run (writable ephemeral FS; min-instances=1 keeps the
# in-process 2 AM scheduler alive). Build context excludes data/.env via
# .gcloudignore / .dockerignore.
FROM python:3.11-slim
# procps → pgrep, which the console uses to probe running pulls (its absence
# crashed the Control Panel on the first Cloud Run login, 8/8)
RUN apt-get update && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONPATH=/app
EXPOSE 8080
# scheduler daemon runs at PROCESS level (D2 finding 2: a session-started
# thread dies with the instance); WHA_SCHEDULER_DAEMON=1 in its env keeps
# the console's in-session ticker off.
CMD python console/scheduler_boot.py & \
    exec streamlit run console/app.py --server.port ${PORT:-8080} \
    --server.address 0.0.0.0 --server.headless true \
    --browser.gatherUsageStats false

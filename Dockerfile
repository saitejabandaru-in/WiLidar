FROM python:3.10-slim

# Install system dependencies (build-essential for compiling standard tools if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install python packages
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire server package
COPY server/ ./server/
COPY dashboard/ ./dashboard/
COPY tools/ ./tools/

# Expose ports:
# 5005: UDP CSI receiver
# 5006: UDP Heartbeat
# 8000: FastAPI HTTP and WebSocket
EXPOSE 5005/udp 5006/udp 8000

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "server.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

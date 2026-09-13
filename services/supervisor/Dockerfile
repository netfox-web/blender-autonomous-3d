FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY services/supervisor/requirements.txt /app/services/supervisor/requirements.txt
RUN pip install --no-cache-dir -r /app/services/supervisor/requirements.txt

COPY . /app

ENV PYTHONPATH="/app:/app/services"
ENV SUPERVISOR_PORT=8791

EXPOSE 8791

CMD ["python", "-m", "uvicorn", "services.supervisor.main:app", "--host", "0.0.0.0", "--port", "8791"]

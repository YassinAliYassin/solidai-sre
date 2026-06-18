FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir httpx fastapi uvicorn

COPY monitor.py .

CMD ["python", "monitor.py"]

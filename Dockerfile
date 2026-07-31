FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYLISTMUSE_DATA_DIR=/app/data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend backend
COPY frontend frontend
RUN mkdir -p data

EXPOSE 5780
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "5780"]

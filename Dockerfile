# Dockerfile
FROM python:3.11-slim

WORKDIR /app


COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV DB_NAME=scheduling-db
ENV DB_USER=scheduler
ENV DB_PASSWORD=V3riz0n-demo
ENV DB_HOST=postgres-db-container
ENV DB_PORT=5432

COPY . .

# Run the app. Use gunicorn for a more robust production server.
# We'll install it here.
RUN pip install gunicorn


CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000", "main:app"]

# Alternative to systemd: run the scanner in a container on any VPS.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# .env is mounted or passed via `docker run --env-file .env` at runtime —
# never baked into the image.
CMD ["python", "main.py"]

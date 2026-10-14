FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    TZ=Europe/Vienna

EXPOSE 8000

ENTRYPOINT ["sh", "docker-entrypoint.sh"]

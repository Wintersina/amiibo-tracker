# Start from official Python image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install dependencies
RUN apt-get update \
    && apt-get install -y build-essential libpq-dev curl \
    && apt-get clean


WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Pre-download rembg model to avoid startup timeout in Cloud Run
COPY scripts/download-rembg-models.py /tmp/
RUN python /tmp/download-rembg-models.py && rm /tmp/download-rembg-models.py

COPY . .


RUN python manage.py collectstatic --noinput

RUN chmod +x scripts/entrypoint.sh

EXPOSE 8080


ENTRYPOINT ["./scripts/entrypoint.sh"]

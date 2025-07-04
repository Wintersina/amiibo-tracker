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


COPY . .


RUN python manage.py collectstatic --noinput


EXPOSE 8080


CMD ["gunicorn", "amiibo_tracker.wsgi:application", "--bind", "0.0.0.0:8080"]

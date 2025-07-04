FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y build-essential libpq-dev curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt


COPY . .


RUN python manage.py collectstatic --noinput


EXPOSE 8080


CMD ["/bin/bash", "-c", "python manage.py migrate --noinput && exec gunicorn --bind :$PORT amiibo_tracker.wsgi:application"]
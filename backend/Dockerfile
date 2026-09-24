FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1     PORT=8000     WEB_CONCURRENCY=3

WORKDIR /app

RUN useradd --create-home --uid 1000 app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && chmod +x docker-entrypoint.sh \
    && mkdir -p /app/media \
    && chown -R app:app /app

USER app
EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
# gunicorn binds to 0.0.0.0:$PORT and starts $WEB_CONCURRENCY workers, so a host
# like Render can set its own port and a smaller worker count for 512 MB.
CMD ["gunicorn", "config.wsgi:application", "--timeout", "120", "--access-logfile", "-"]

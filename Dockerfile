FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 national
COPY --chown=national:national . ./
# collectstatic no se conecta a PostgreSQL ni requiere secretos del despliegue.
RUN DEBUG=true \
    SECRET_KEY=build-only-static-assets-key \
    JWT_SIGNING_KEY=build-only-independent-static-assets-key \
    DATABASE_URL=postgresql://unused@localhost/unused \
    python manage.py collectstatic --noinput \
    && chown -R national:national /app/staticfiles
USER national
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; host=os.getenv('ALLOWED_HOSTS','localhost').split(',')[0].strip().lstrip('.'); req=urllib.request.Request('http://127.0.0.1:'+os.getenv('PORT','8000')+'/health/ready/', headers={'Host':host}); urllib.request.urlopen(req, timeout=4)"
CMD ["gunicorn", "config.wsgi:application", "--config", "gunicorn.conf.py"]

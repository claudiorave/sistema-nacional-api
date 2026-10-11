import os

bind = "0.0.0.0:" + os.getenv("PORT", "8000")
workers = int(os.getenv("WEB_CONCURRENCY", "2"))
threads = int(os.getenv("GUNICORN_THREADS", "4"))
worker_class = "gthread"
timeout = 60
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
# El contenedor no acepta directamente tráfico de clientes en producción.
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1")

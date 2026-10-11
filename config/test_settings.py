from .settings import *  # noqa: F403

SECRET_KEY = "test-only-secret-key-for-national-api-never-use-in-production"
JWT_SIGNING_KEY = "test-only-independent-jwt-signing-key-never-use-in-production"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
SECURE_SSL_REDIRECT = False
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}  # noqa: F405
DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

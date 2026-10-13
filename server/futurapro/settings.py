"""Impostazioni del server FuturaPro. Tutto ciò che cambia tra installazioni arriva da variabili d'ambiente."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(nome, predefinito=None):
    return os.environ.get(f"FUTURAPRO_{nome}", predefinito)


DEBUG = _env("DEBUG", "0") == "1"
SECRET_KEY = _env("SECRET_KEY") or ("solo-sviluppo-non-usare-in-produzione" if DEBUG else None)
if not SECRET_KEY:
    raise RuntimeError("Impostare FUTURAPRO_SECRET_KEY.")
ALLOWED_HOSTS = [h for h in (_env("ALLOWED_HOSTS", "localhost,127.0.0.1")).split(",") if h]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "core",
    "clienti",
    "utenti",
    "dispositivi",
    "audit",
    "teleassistenza",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.AzzeraContestoMiddleware",
]

ROOT_URLCONF = "futurapro.urls"
WSGI_APPLICATION = "futurapro.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

# Solo PostgreSQL: l'isolamento tra clienti si appoggia alla sua Row-Level Security.
# L'utente del database NON deve essere superuser né avere BYPASSRLS.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _env("DB_NAME", "futurapro"),
        "USER": _env("DB_USER", "futurapro"),
        "PASSWORD": _env("DB_PASSWORD", "futurapro"),
        "HOST": _env("DB_HOST", "localhost"),
        "PORT": _env("DB_PORT", "5432"),
        # Ogni richiesta è una transazione: le variabili di contesto per la
        # Row-Level Security valgono fino al suo termine e poi spariscono.
        "ATOMIC_REQUESTS": True,
    }
}

AUTH_USER_MODEL = "utenti.Utente"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,
    "DEFAULT_THROTTLE_RATES": {"abbinamento": _env("THROTTLE_ABBINAMENTO", "20/hour")},
}

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

LANGUAGE_CODE = "it"
TIME_ZONE = "Europe/Rome"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

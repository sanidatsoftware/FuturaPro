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
# Indirizzi da cui arrivano i moduli del pannello, es. https://signage.miodominio.it
CSRF_TRUSTED_ORIGINS = [o for o in (_env("ORIGINI", "")).split(",") if o]
# Davanti c'è Caddy, che termina HTTPS e lo dice con X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

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
    "contenuti",
    "layout",
    "player",
    "eliminacode",
    "pannello",
    "plugin",
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
                "pannello.contesto.aspetto",
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
LOGIN_URL = "/accesso/"
LOGIN_REDIRECT_URL = "/pannello/"
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
    "DEFAULT_THROTTLE_RATES": {
        "abbinamento": _env("THROTTLE_ABBINAMENTO", "120/hour"), "biglietto": "40/min",
        # Il guardiano di ogni postazione chiede ogni 2 minuti; i PC di un negozio escono con lo stesso IP.
        "postazione": _env("THROTTLE_POSTAZIONE", "1200/hour"),
    },
}

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

LANGUAGE_CODE = "it"
TIME_ZONE = "Europe/Rome"
USE_I18N = True
USE_TZ = True

# I file dei clienti non sono mai serviti direttamente: passano dalle viste che
# controllano il cliente (contenuti.api), quindi niente MEDIA_URL pubblico.
MEDIA_ROOT = Path(_env("MEDIA_ROOT", BASE_DIR / "media"))
FUTURAPRO_MAX_UPLOAD_MB = int(_env("MAX_UPLOAD_MB", "2048"))
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# Email (allarmi degli schermi): un server SMTP qualsiasi. Senza FUTURAPRO_EMAIL_HOST le email
# non partono e il pannello lo dice.
EMAIL_HOST = _env("EMAIL_HOST", "")
EMAIL_PORT = int(_env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = _env("EMAIL_UTENTE", "")
EMAIL_HOST_PASSWORD = _env("EMAIL_PASSWORD", "")
EMAIL_USE_TLS = _env("EMAIL_TLS", "1") == "1" and EMAIL_PORT != 465
EMAIL_USE_SSL = EMAIL_PORT == 465
EMAIL_TIMEOUT = 20
DEFAULT_FROM_EMAIL = _env("EMAIL_MITTENTE", EMAIL_HOST_USER or "futurapro@localhost")
if not EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Facoltativo: l'indirizzo pubblico (da internet) per la coda sul telefono, es. https://coda.miodominio.it
FUTURAPRO_URL_PUBBLICO = _env("URL_PUBBLICO", "")
if FUTURAPRO_URL_PUBBLICO:
    from urllib.parse import urlsplit

    _host_pubblico = urlsplit(FUTURAPRO_URL_PUBBLICO).hostname
    if _host_pubblico and _host_pubblico not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_host_pubblico)

STATIC_URL = "static/"
STATIC_ROOT = Path(_env("STATIC_ROOT", BASE_DIR / "staticfiles"))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": _env("LOG_LEVEL", "WARNING")},
}

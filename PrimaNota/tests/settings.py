import sys
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI / "portale"))   # scansioni (copia reale) e incarichi (sostituto)
sys.path.insert(0, str(QUI.parent))        # primanota

BASE_DIR = QUI
SECRET_KEY = "prova-non-usare-in-produzione"
DEBUG = True
ALLOWED_HOSTS = ["*"]
USE_TZ = True
TIME_ZONE = "Europe/Rome"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "primanota",
]
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]
ROOT_URLCONF = "tests.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
}]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
BASEROW_PRIMANOTA_TABLE_ID = 999
BASEROW_UTENTE_MENU_PRIMANOTA_FIELD = "field_9000"

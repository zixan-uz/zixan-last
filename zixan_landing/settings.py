import os
from pathlib import Path
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Security / environment-sourced settings (fail loud in production) ---
SECRET_KEY = os.environ["SECRET_KEY"]
DEBUG = os.environ.get("DEBUG", "False").strip().lower() == "true"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "zixan-last.onrender.com").split(",") if h.strip()]  # можно указать конкретные хосты при необходимости

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'main',  # твоё приложение
    'rest_framework',
    'intake',
    'audit',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # для статики на проде
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'zixan_landing.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],  # путь к шаблонам
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'zixan_landing.wsgi.application'

# default is the production app DB (zixan-app-db, Oregon), wired ONLY via DATABASE_URL.
# Fail loud: a missing DATABASE_URL crashes at boot rather than silently using SQLite.
DATABASES = {
    "default": dj_database_url.parse(
        os.environ["DATABASE_URL"],
        conn_max_age=0,
        ssl_require=True,
    ),
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Статика
STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]  # для разработки
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')    # для Render и collectstatic
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'  # важно для Render

# Медиа (е

# === DIAMOR Phase 1A settings ===

# =====================================================================
# DIAMOR Phase 1A — settings snippet. ADD these to your existing settings.py.
# This NEVER replaces your existing DATABASES["default"]. The existing default
# database (which may be zixan_db) is left exactly as it is.
# =====================================================================
import os

# 1) INSTALLED_APPS — add the runtime app:
#       INSTALLED_APPS += ["diamor_runtime"]

# 2) DATABASES — ADD two NAMED aliases. Merge these WITHOUT overwriting "default".
#    (Define this after your existing DATABASES, then: DATABASES.update(DIAMOR_DATABASES))
DIAMOR_DATABASES = {
    # Django-managed app DB. Holds ONLY diamor_staff_identity_map.
    "diamor_app": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["DIAMOR_APP_DB_NAME"],          # diamor_app
        "USER": os.environ["DIAMOR_APP_DB_USER"],          # diamor_app_user
        "PASSWORD": os.environ.get("DIAMOR_APP_DB_PASSWORD", ""),
        "HOST": os.environ["DIAMOR_APP_DB_HOST"],
        "PORT": os.environ.get("DIAMOR_APP_DB_PORT", "5432"),
        "OPTIONS": {
            # TLS to Render PostgreSQL.
            "sslmode": os.environ.get("DIAMOR_APP_DB_SSLMODE", "require"),
            # diamor_app_user does not own the DB (Render-safe provisioning), so the
            # search_path is set here per-connection rather than via ALTER DATABASE.
            # This is where Django migrates / queries diamor_staff_identity_map.
            "options": "-c search_path=diamor_app_schema,public",
        },
    },
    # The DIAMOR database (e.g. diamor_staging). RAW SQL ONLY, via a DIAMOR app role.
    # Phase 1A uses the manager app role (app_manager_admin). NEVER zixan_user.
    "diamor": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["DIAMOR_DB_NAME"],              # e.g. diamor_staging
        "USER": os.environ["DIAMOR_DB_USER"],              # app_manager_admin
        "PASSWORD": os.environ.get("DIAMOR_DB_PASSWORD", ""),
        "HOST": os.environ["DIAMOR_DB_HOST"],
        "PORT": os.environ.get("DIAMOR_DB_PORT", "5432"),
        # We manage transactions explicitly (session_set_party is transaction-local):
        "ATOMIC_REQUESTS": False,
        "OPTIONS": {
            "sslmode": os.environ.get("DIAMOR_DB_SSLMODE", "require"),
        },
    },
}
#   DATABASES.update(DIAMOR_DATABASES)

# 3) DATABASE_ROUTERS — add the runtime router. It sends ONLY diamor_runtime models and
#    migrations to diamor_app, never routes ORM to the raw `diamor` alias, and leaves the
#    existing default DB for everything else:
#       DATABASE_ROUTERS = [
#           *globals().get("DATABASE_ROUTERS", []),
#           "diamor_runtime.routers.DiamorRuntimeRouter",
#       ]

# 4) CSRF — DO NOT disable. Phase 1A uses existing Django session auth, so
#    django.middleware.csrf.CsrfViewMiddleware MUST stay enabled and the staff endpoints
#    are NOT csrf_exempt. The staff client must send the CSRF token (X-CSRFToken header)
#    on POST /diamor/phase1/disclosure/decide.

# 5) URLs — include the runtime urls in your ROOT urlconf, e.g. in urls.py:
#       from django.urls import include, path
#       urlpatterns += [path("diamor/", include("diamor_runtime.urls"))]

# 6) Migrate ONLY the runtime app, ONLY against diamor_app (never a bare `migrate`):
#       python manage.py migrate diamor_runtime --database=diamor_app

# === DIAMOR Phase 1A activation ===
if "diamor_runtime" not in INSTALLED_APPS:
    INSTALLED_APPS = list(INSTALLED_APPS) + ["diamor_runtime"]

DATABASES.update(DIAMOR_DATABASES)

DATABASE_ROUTERS = list(globals().get("DATABASE_ROUTERS", [])) + [
    "diamor_runtime.routers.DiamorRuntimeRouter",
]

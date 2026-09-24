"""Django settings for the PC Builder project.

All environment-specific values come from environment variables so the same
settings module works locally, in Docker Compose, in CI and in production.
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

import dj_database_url
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines from a local .env (secrets for local runs).

    Real environment variables win, so Docker/CI configuration is never
    overridden by a stray file. Not a full dotenv implementation on purpose:
    no interpolation, no multi-line values.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export ").strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


load_env_file(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


INSECURE_DEFAULT_KEY = "dev-only-insecure-secret-key-change-me"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", INSECURE_DEFAULT_KEY)
DEBUG = env_bool("DJANGO_DEBUG", False)
TESTING = "pytest" in sys.modules
if not DEBUG and not TESTING and SECRET_KEY == INSECURE_DEFAULT_KEY:
    # A production server must never run with the key from the repository:
    # it signs sessions, password-reset links and JWTs.
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY (or DJANGO_DEBUG=1 for local development).")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,backend")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # third party
    "rest_framework",
    "rest_framework_simplejwt",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
    # local
    "apps.accounts",
    "apps.catalog",
    "apps.builds",
    "apps.orders",
    "apps.stats",
    "apps.advisor",
    "apps.alerts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        default="postgres://pcbuilder:pcbuilder@localhost:5432/pcbuilder",
        conn_max_age=60,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
# Chosen per request from Accept-Language (LocaleMiddleware): Django and DRF
# ship Ukrainian translations for their built-in validation messages.
LANGUAGES = [("en", "English"), ("uk", "Українська")]
TIME_ZONE = "Europe/Kyiv"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- REST framework -------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "config.pagination.DefaultPagination",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {
        "advisor": os.environ.get("ADVISOR_THROTTLE_RATE", "10/hour"),
        # Per client IP: slows down sign-up spam and password guessing.
        "register": os.environ.get("REGISTER_THROTTLE_RATE", "10/hour"),
        "login": os.environ.get("LOGIN_THROTTLE_RATE", "30/hour"),
    },
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "PC Builder API",
    "DESCRIPTION": (
        "PC configurator: component catalog, builds with compatibility checks, "
        "orders, statistics and an AI build advisor."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "CategoryKindEnum": "apps.catalog.models.CategoryKind",
        "OrderStatusEnum": "apps.orders.models.OrderStatus",
        "ListingStatusEnum": "apps.catalog.models.MarketListing.Status",
        "AdvisorLanguageEnum": ["en", "uk"],
        "AlertLanguageEnum": "apps.alerts.models.TelegramLink.Language",
        "CurrencyEnum": ["USD", "UAH"],
    },
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

# --- Celery -----------------------------------------------------------------

CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "update-exchange-rate": {
        "task": "apps.catalog.tasks.update_exchange_rate",
        "schedule": crontab(minute=15, hour="*/6"),
    },
    # Live prices and photos from product pages. Every 30 min it refreshes the
    # listings older than MARKET_STALE_HOURS, so the load is spread over the day.
    "refresh-market-listings": {
        "task": "apps.catalog.tasks.refresh_market_listings",
        "schedule": crontab(minute="*/30"),
        "kwargs": {"limit": 20},
    },
    # Also queued after every market refresh; the hourly run sends alerts that
    # quiet hours held back overnight.
    "check-price-watches": {
        "task": "apps.alerts.tasks.check_price_watches",
        "schedule": crontab(minute=5),
    },
    "expire-unpaid-orders": {
        "task": "apps.orders.tasks.expire_unpaid_orders",
        "schedule": crontab(minute="*/30"),
    },
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": CELERY_BROKER_URL,
    }
    if os.environ.get("REDIS_URL")
    else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}

# --- E-mail (comment notifications) ------------------------------------------

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "PC Builder <noreply@pcbuilder.local>")

# --- Domain / integrations ----------------------------------------------------

# Prices in the catalog are stored in USD; the NBU rate is used to show UAH.
NBU_EXCHANGE_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"

# Where the price sync task reads supplier prices from. "fixture" uses a bundled
# JSON feed; any http(s) URL is fetched and must return the same JSON shape.
PRICE_FEED_URL = os.environ.get("PRICE_FEED_URL", "fixture")

# Market data (prices, photos) from product pages; see apps/catalog/market.py.
MARKET_USER_AGENT = os.environ.get(
    "MARKET_USER_AGENT",
    "PCBuilderBot/1.0 (+https://github.com/; educational portfolio project)",
)
MARKET_MIN_INTERVAL = float(os.environ.get("MARKET_MIN_INTERVAL", "2.0"))  # seconds per host
MARKET_STALE_HOURS = int(os.environ.get("MARKET_STALE_HOURS", "20"))
# Master switch for every request to shop/aggregator sites (pages, photos, price
# history, catalog import). Off by default: hotline.ua's user agreement (p. 6.4)
# forbids automated collection without the administration's written permission.
# Turn on only with such permission, or for a source whose terms allow it.
MARKET_FETCH_ENABLED = env_bool("MARKET_FETCH_ENABLED", False)
# Parts sold by fewer shops are hidden from the catalog, pickers and the advisor
# (their "market price" is one shop's asking price). They reappear by themselves.
MARKET_MIN_SHOPS = int(os.environ.get("MARKET_MIN_SHOPS", "3"))
# Photos mirrored per product (each is a request to the source's CDN).
MARKET_MAX_PHOTOS = int(os.environ.get("MARKET_MAX_PHOTOS", "5"))

# Payment provider: "fake" (instant success, for dev/tests) or "stripe".
PAYMENT_PROVIDER = os.environ.get("PAYMENT_PROVIDER", "fake")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")

# Telegram price alerts (apps.alerts). The token comes from @BotFather; keep it
# in backend/.env or the environment, never in the repository.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "")  # else read via getMe

UNPAID_ORDER_TTL_HOURS = int(os.environ.get("UNPAID_ORDER_TTL_HOURS", "48"))

# AI advisor: without ANTHROPIC_API_KEY the rule-based planner is used.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ADVISOR_MODEL = os.environ.get("ADVISOR_MODEL", "claude-opus-5")
ADVISOR_MAX_TOOL_ROUNDS = int(os.environ.get("ADVISOR_MAX_TOOL_ROUNDS", "12"))
# Site-wide cap on Claude calls per day (each costs money and sign-up is open).
# Past it the rule-based planner answers, with a note. 0 = no AI calls at all.
ADVISOR_DAILY_LLM_LIMIT = int(os.environ.get("ADVISOR_DAILY_LLM_LIMIT", "100"))
# Interactive web request: medium effort keeps latency reasonable.
ADVISOR_EFFORT = os.environ.get("ADVISOR_EFFORT", "medium")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

if not DEBUG:
    # TLS ends at the reverse proxy (Caddy/nginx), which sets X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = env_bool("SECURE_COOKIES", True)
    CSRF_COOKIE_SECURE = env_bool("SECURE_COOKIES", True)
    # Enable only once HTTPS works: browsers remember it for the whole period.
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"

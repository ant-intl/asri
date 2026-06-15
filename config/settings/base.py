"""
Django settings for ASRI project.

Base settings shared across all environments.
"""
import os
from pathlib import Path

from dotenv import load_dotenv


def env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean environment variable."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in ('1', 'true', 'yes', 'on')


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
HOME_DIR = Path.home()

# Load .env file from project root (if exists)
load_dotenv(BASE_DIR / '.env')

# Skill storage root directory.
# Override via ASRI_SKILLS_DIR env var (e.g. ~/.asri for a home-dir layout).
# Default: <project_root>/data/tenant/
_skills_dir_env = os.environ.get('ASRI_SKILLS_DIR', '')
SKILLS_ROOT = (
    Path(os.path.expanduser(_skills_dir_env)).resolve()
    if _skills_dir_env
    else BASE_DIR / 'data' / 'tenant'
)

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-wv@c1u*_(!%62!kh(oqzm1l876cuaa1c^22jc25kgx^313g+3y'
)

ALLOWED_HOSTS = ["*"]  # Override in production settings

# CORS settings for cross-origin requests
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:5174"
]

# Regex patterns for dynamically matching allowed origins
CORS_ALLOWED_ORIGIN_REGEXES = [
]

# Allow credentials (cookies, authorization headers) in CORS requests
CORS_ALLOW_CREDENTIALS = True

# Additional CORS headers that can be exposed
CORS_EXPOSE_HEADERS = [
    "content-type",
    "authorization",
    "x-tenant-id"
]

# Headers allowed in CORS preflight requests
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "x-tenant-id"
]

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool('DJANGO_DEBUG', True)

# Application definition
INSTALLED_APPS = [
    'daphne',  # ASGI server for WebSocket support
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',  # Django Channels for WebSocket
    'health_check',
    'corsheaders',  # CORS support
    'apps',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # Must be first
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.tenant.middleware.TokenAuthMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'backend' / 'templates'],
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

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Django Channels configuration
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer'
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'

# Additional locations of static files
STATICFILES_DIRS = [
    BASE_DIR / 'static',  # Points to project root static/
]

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Database configuration
# Default: SQLite. For production MySQL, set DB_HOST/DB_NAME/DB_USER/DB_PASSWORD env vars.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# MySQL configuration example (uncomment and set env vars to use):
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.mysql',
#         'NAME': os.environ.get('DB_NAME', 'asri'),
#         'USER': os.environ.get('DB_USER', 'root'),
#         'PASSWORD': os.environ.get('DB_PASSWORD', ''),
#         'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
#         'PORT': os.environ.get('DB_PORT', '3306'),
#         'OPTIONS': {
#             'charset': 'utf8mb4',
#         },
#     }
# }

# Logging configuration
BASE_LOG_DIR = HOME_DIR / 'logs' / 'asri'
BASE_LOG_DIR.mkdir(parents=True, exist_ok=True)
APP_DEFAULT_LOG_FILE = BASE_LOG_DIR / 'app-default.log'
APP_ERROR_LOG_FILE = BASE_LOG_DIR / 'common-error.log'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s'
        },
        'simple': {
            'format': '%(asctime)s %(levelname)s %(name)s:%(lineno)d - %(message)s'
        },
    },
    'handlers': {
        'file': {
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': APP_DEFAULT_LOG_FILE,
            'formatter': 'verbose',
            'level': 'INFO',
            'when': 'midnight',
            'interval': 1,
            'backupCount': 5,
            'encoding': 'utf-8',
        },
        'error': {
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': APP_ERROR_LOG_FILE,
            'formatter': 'verbose',
            'level': 'ERROR',
            'when': 'midnight',
            'interval': 1,
            'backupCount': 5,
            'encoding': 'utf-8',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'apps': {
            'handlers': ['file', 'console', 'error'],
            'level': 'INFO',
            'propagate': True,
        },
        'config': {
            'handlers': ['file', 'console', 'error'],
            'level': 'INFO',
            'propagate': True,
        },
        'django': {
            'handlers': ['file', 'console', 'error'],
            'level': 'ERROR',
            'propagate': True,
        },
    },
}

# =============================================================================
# CHATBOT Configuration
# =============================================================================
CHATBOT = {
    # ReAct agent max iterations
    'REACT_MAX_ITERATIONS': int(os.environ.get('CHATBOT_MAX_ITERATIONS', '10')),

    # Agent mode: 'react' (ReAct loop) or 'pipeline' (pipecat Pipeline with function_calling)
    'AGENT_MODE': os.environ.get('CHATBOT_AGENT_MODE', 'react'),
    
    # Secret key for encrypting API keys
    'API_KEY_SECRET': os.environ.get('CHATBOT_API_KEY_SECRET', ''),
    
    # Session default TTL in seconds
    'SESSION_DEFAULT_TTL': int(os.environ.get('CHATBOT_SESSION_TTL', '3600')),
    
    # Max number of answers for one question
    'MULTI_ANSWER_MAX_COUNT': int(os.environ.get('CHATBOT_MULTI_ANSWER_MAX', '3')),
    
    # Timeout for grouping multiple questions (ms)
    'GROUP_WAIT_TIMEOUT': int(os.environ.get('CHATBOT_GROUP_TIMEOUT', '5000')),

    # AsriGateway configuration
    'ASRI_GATEWAY_API_BASE': os.environ.get('ASRI_GATEWAY_API_BASE', ''),
    'ASRI_GATEWAY_API_KEY': os.environ.get('ASRI_GATEWAY_API_KEY', ''),
    'ASRI_GATEWAY_MODEL': os.environ.get('ASRI_GATEWAY_MODEL', ''),

    # MCP Servers configuration (list of server configs for dynamic tool discovery)
    'MCP_SERVERS': [],  # Default: empty list, configure per-tenant
    
    # Tool interrupt strategy: 'immediate', 'semantic_complete', or 'none'
    'TOOL_INTERRUPT_STRATEGY': os.environ.get('TOOL_INTERRUPT_STRATEGY', 'none'),
}

# =============================================================================
# Tracing Configuration
# =============================================================================
# Backend: 'noop' (default), or name registered via entry_points('asri.tracers')
TRACING_BACKEND = os.environ.get('TRACING_BACKEND', 'noop')
TRACING_CONFIG = {
    'LOG_BASE_DIR': os.environ.get('TRACING_LOG_DIR', str(HOME_DIR / 'logs')),
}

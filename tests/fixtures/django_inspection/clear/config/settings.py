SECRET_KEY = 'disposable-fixture-only'
DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
ROOT_URLCONF = 'config.urls'
INSTALLED_APPS = []
MIDDLEWARE = []
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}

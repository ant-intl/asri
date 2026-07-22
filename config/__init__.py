# Django project configuration
try:
    import pymysql
    pymysql.install_as_MySQLdb()
except ImportError:
    pass  # pymysql not needed when using SQLite (default for local dev)

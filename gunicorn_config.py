"""Gunicorn configuration for production deployment on EC2."""

bind = "0.0.0.0:5000"
workers = 3
timeout = 120
accesslog = "-"
errorlog = "-"
loglevel = "info"

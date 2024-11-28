import os

user="ec2-user"
group="ec2-user"
wsgi_app = "app:app"
worker_class = "sync"
workers = int(os.environ.get('GUNICORN_PROCESSES', '4'))
threads = int(os.environ.get('GUNICORN_THREADS', '8'))
# timeout = int(os.environ.get('GUNICORN_TIMEOUT', '120'))
# bind = os.environ.get('GUNICORN_BIND', '0.0.0.0:8080')
bind = ['127.0.0.1:8080']
#forwarded_allow_ips = '*'
forwarded_allow_ips = '127.0.0.1'
proxy_allow_ips = '127.0.0.1'
secure_scheme_headers = { 'X-Forwarded-Proto': 'https' }
reload = True
errorlog = '/var/log/gunicorn/gunicorn-error.log'
accesslog = '/var/log/gunicorn/gunicorn-access.log'
capture_output=True

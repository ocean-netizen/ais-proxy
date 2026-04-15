import os
bind = f"0.0.0.0:{os.environ.get('PORT', 10000)}"
workers = 1
threads = 1
timeout = 60
preload_app = True
max_requests = 50
max_requests_jitter = 10

# Threaded workers: Excel/CSV exports stream for minutes and must not hit the
# 30 s sync-worker timeout; a hung request is still killed after `timeout`.
worker_class = 'gthread'
workers = 2
threads = 4
timeout = 600
graceful_timeout = 30


def on_starting(server):
    from storage import init
    init()

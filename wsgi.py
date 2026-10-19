import logging

from app import app

try:
    from app import init_db
    init_db()
except Exception as exc:  # never block startup on a DB hiccup
    logging.getLogger('taskmanager').error('init_db failed at boot: %s', exc)

if __name__ == '__main__':
    app.run()

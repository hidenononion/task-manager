from app import app, init_db, migrate_db

init_db()
migrate_db()

if __name__ == '__main__':
    app.run()

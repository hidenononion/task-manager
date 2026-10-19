import os
import csv
import hashlib
import hmac
import io
import logging
import math
import re
import secrets
import urllib.request
from functools import wraps
from urllib.parse import urlsplit

from flask import (  # pyright: ignore[reportMissingImports]
    Flask, request, jsonify, session, render_template, redirect, url_for, Response
)
from werkzeug.security import generate_password_hash, check_password_hash

from security import (
    ALLOWED_UPLOAD_EXTENSIONS, MAX_UPLOAD_BYTES, SlidingWindowLimiter,
    csv_safe, file_signature_ok, is_public_http_url, is_safe_link_url, safe_filename,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')

logger = logging.getLogger('taskmanager')
if not logger.handlers:
    logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO'),
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')


def _load_secret_key():
    """Lay SECRET_KEY tu env, hoac sinh file ngau nhien chi doc boi app.

    Khong con fallback hard-code: neu thieu key, moi session cu se bi vo hieu
    luc khoi dong lai, nhung ke tan cong khong the tu ky cookie.
    """
    env_key = (os.environ.get('SECRET_KEY') or '').strip()
    if len(env_key) >= 32:
        return env_key
    key_path = os.environ.get('SECRET_KEY_FILE') or os.path.join(INSTANCE_DIR, 'secret_key')
    try:
        with open(key_path, 'r', encoding='utf-8') as fh:
            saved = fh.read().strip()
        if len(saved) >= 32:
            return saved
    except OSError:
        pass
    new_key = secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(key_path), exist_ok=True)
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(new_key)
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        logger.warning('Khong ghi duoc SECRET_KEY_FILE (%s); dung key tam thoi trong bo nho', exc)
    return new_key


app = Flask(__name__)
app.secret_key = _load_secret_key()

# ─── Load environment variables ───────────────────────────────────────


# Fallback: if Google credentials not set, try gg.env
if not os.getenv('GOOGLE_CLIENT_ID'):
    gg_path = os.path.join(os.path.dirname(__file__), 'gg.env')
    if os.path.isfile(gg_path):
        with open(gg_path, encoding='utf-8') as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line or _line.startswith('#'):
                    continue
                _key, _, _val = _line.partition('=')
                _k = _key.strip()
                if _k in ('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET'):
                    os.environ.setdefault(_k, _val.strip())
# ─────────────────────────────────────────────────────────────────────────

_secure_flag = os.environ.get('SESSION_COOKIE_SECURE')
if _secure_flag is None:
    _cookie_secure = (os.environ.get('FLASK_ENV') == 'production'
                      or bool(os.environ.get('DATABASE_URL')))
else:
    _cookie_secure = _secure_flag.strip().lower() not in ('0', 'false', 'no', 'off')

app.config.update(
    SESSION_COOKIE_SECURE=_cookie_secure,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_NAME='taskmgr_session',
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 7,
    MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES + 1024 * 1024,
)

if os.environ.get('TRUST_PROXY', '').lower() in ('1', 'true', 'yes'):
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Gioi han thu dang nhap / dang ky (bo dem trong bo nho, moi worker rieng).
_login_limiter = SlidingWindowLimiter(5, 300)       # 5 lan sai / 5 phut / (ip+username)
_login_ip_limiter = SlidingWindowLimiter(20, 300)   # 20 lan sai / 5 phut / ip
_register_limiter = SlidingWindowLimiter(5, 3600)   # 5 tai khoan / gio / ip


def _static_version(filename):
    try:
        return int(os.path.getmtime(os.path.join(app.static_folder, filename)))
    except Exception:
        return 0


@app.context_processor
def inject_static_versions():
    return {
        'css_version': _static_version(os.path.join('css', 'style.css')),
        'appjs_version': _static_version(os.path.join('js', 'app.js')),
        'authjs_version': _static_version(os.path.join('js', 'auth.js')),
    }


UNSAFE_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
    "font-src 'self' data: https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
    "img-src 'self' data: https: blob:; "
    "connect-src 'self'; object-src 'self'; base-uri 'self'; frame-ancestors 'none'"
)


def is_admin():
    """So sanh role chinh xac (khong dung 'in' vi de nham substring)."""
    return session.get('role') == 'bithu'


def client_ip():
    return request.remote_addr or 'unknown'


def too_many_requests(retry_after, message='Quá nhiều lần thử, vui lòng đợi'):
    resp = jsonify({'error': message, 'retry_after': retry_after})
    resp.status_code = 429
    resp.headers['Retry-After'] = str(retry_after)
    return resp


def api_error(message, status=400):
    return jsonify({'error': message}), status


@app.before_request
def csrf_same_origin_guard():
    """Chan CSRF cho API ghi du lieu: cookie SameSite=Lax + kiem tra Origin."""
    if request.method not in UNSAFE_METHODS or not request.path.startswith('/api/'):
        return None
    if (request.headers.get('Sec-Fetch-Site') or '').lower() == 'cross-site':
        return api_error('Yêu cầu cross-site bị chặn', 403)
    origin = request.headers.get('Origin')
    if origin:
        try:
            origin_host = urlsplit(origin).netloc.lower()
        except ValueError:
            origin_host = ''
        if not origin_host or origin_host != (request.host or '').lower():
            return api_error('Origin không hợp lệ', 403)
    return None


@app.after_request
def security_headers(resp):
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('X-Frame-Options', 'DENY')
    resp.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    resp.headers.setdefault('Permissions-Policy', 'geolocation=(), microphone=(), camera=()')
    resp.headers.setdefault('Content-Security-Policy', CSP_POLICY)
    if app.config.get('SESSION_COOKIE_SECURE'):
        resp.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    return resp


@app.errorhandler(413)
def payload_too_large(_err):
    if request.path.startswith('/api/'):
        return api_error('File quá lớn (tối đa 20MB)', 413)
    return 'Payload too large', 413


@app.errorhandler(500)
def internal_error(err):
    logger.error('Loi khong xu ly %s %s: %s', request.method, request.path, err)
    if request.path.startswith('/api/'):
        return api_error('Lỗi máy chủ', 500)
    return 'Internal server error', 500


DATABASE_URL = os.environ.get('DATABASE_URL', '')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

LOCAL_DB = os.environ.get('TASKMGR_DB_PATH') or os.path.join(BASE_DIR, 'database.db')


def get_db():
    if DATABASE_URL:
        import psycopg
        conn = psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row)
        conn.autocommit = False
        return conn
    else:
        import sqlite3
        conn = sqlite3.connect(LOCAL_DB)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        return conn


def is_pg():
    return bool(DATABASE_URL)


def init_db():
    conn = get_db()
    cur = conn.cursor()

    if is_pg():
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                score INTEGER DEFAULT 0
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                priority TEXT DEFAULT 'medium',
                due_date TEXT,
                max_assignees INTEGER DEFAULT 3,
                points INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh'),
                created_by INTEGER REFERENCES users(id)
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS task_assignments (
                task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id),
                PRIMARY KEY (task_id, user_id)
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS points_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                points INTEGER NOT NULL,
                reason TEXT DEFAULT '',
                task_id INTEGER REFERENCES tasks(id),
                created_by INTEGER REFERENCES users(id),
                created_at TEXT DEFAULT (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS finance (
                id SERIAL PRIMARY KEY,
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                description TEXT DEFAULT '',
                category TEXT DEFAULT '',
                date TEXT DEFAULT (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh'),
                created_by INTEGER REFERENCES users(id)
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS fund (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL DEFAULT 'Quỹ chung',
                balance REAL DEFAULT 0,
                updated_at TEXT DEFAULT (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS login_history (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                ip TEXT DEFAULT '',
                user_agent TEXT DEFAULT '',
                created_at TEXT DEFAULT (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS automation_rules (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                trigger TEXT DEFAULT '',
                action TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                created_by INTEGER REFERENCES users(id)
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS webhooks (
                id SERIAL PRIMARY KEY,
                url TEXT NOT NULL,
                event TEXT DEFAULT 'task.done',
                enabled INTEGER DEFAULT 1,
                created_by INTEGER REFERENCES users(id)
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS attachments (
                id SERIAL PRIMARY KEY,
                task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
                filename TEXT DEFAULT '',
                size INTEGER DEFAULT 0,
                created_by INTEGER REFERENCES users(id),
                created_at TEXT DEFAULT (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS subtasks (
                id SERIAL PRIMARY KEY,
                task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                done INTEGER DEFAULT 0,
                created_by INTEGER REFERENCES users(id)
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS task_dependencies (
                task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
                depends_on_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
                PRIMARY KEY (task_id, depends_on_id)
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS comments (
                id SERIAL PRIMARY KEY,
                task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id),
                text TEXT DEFAULT '',
                created_at TEXT DEFAULT (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS time_logs (
                id SERIAL PRIMARY KEY,
                task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id),
                seconds INTEGER DEFAULT 0,
                note TEXT DEFAULT 'timer',
                created_at TEXT DEFAULT (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS shares (
                id SERIAL PRIMARY KEY,
                token TEXT UNIQUE NOT NULL,
                mode TEXT DEFAULT 'view',
                created_by INTEGER REFERENCES users(id),
                created_at TEXT DEFAULT (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                type TEXT DEFAULT 'assign',
                title TEXT DEFAULT '',
                body TEXT DEFAULT '',
                link TEXT DEFAULT '',
                is_read INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS ext_sql_config (
                id INTEGER PRIMARY KEY,
                dbtype TEXT DEFAULT 'mysql',
                host TEXT DEFAULT '',
                port INTEGER DEFAULT 3306,
                dbname TEXT DEFAULT '',
                username TEXT DEFAULT '',
                password TEXT DEFAULT '',
                table_prefix TEXT DEFAULT 'lamkhe_'
            )
        ''')
    else:
        cur.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                score INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                priority TEXT DEFAULT 'medium',
                due_date TEXT,
                max_assignees INTEGER DEFAULT 3,
                points INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                created_by INTEGER,
                FOREIGN KEY (created_by) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS task_assignments (
                task_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (task_id, user_id),
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS points_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                points INTEGER NOT NULL,
                reason TEXT DEFAULT '',
                task_id INTEGER,
                created_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (created_by) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS finance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                description TEXT DEFAULT '',
                category TEXT DEFAULT '',
                date TEXT DEFAULT CURRENT_TIMESTAMP,
                created_by INTEGER,
                FOREIGN KEY (created_by) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS fund (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT 'Quỹ chung',
                balance REAL DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS login_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                ip TEXT DEFAULT '',
                user_agent TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS automation_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                trigger TEXT DEFAULT '',
                action TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                created_by INTEGER,
                FOREIGN KEY (created_by) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS webhooks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                event TEXT DEFAULT 'task.done',
                enabled INTEGER DEFAULT 1,
                created_by INTEGER,
                FOREIGN KEY (created_by) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                filename TEXT DEFAULT '',
                size INTEGER DEFAULT 0,
                created_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (created_by) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS subtasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                title TEXT NOT NULL,
                done INTEGER DEFAULT 0,
                created_by INTEGER,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (created_by) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS task_dependencies (
                task_id INTEGER,
                depends_on_id INTEGER,
                PRIMARY KEY (task_id, depends_on_id),
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (depends_on_id) REFERENCES tasks(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                user_id INTEGER,
                text TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS time_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                user_id INTEGER,
                seconds INTEGER DEFAULT 0,
                note TEXT DEFAULT 'timer',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS shares (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                mode TEXT DEFAULT 'view',
                created_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT DEFAULT 'assign',
                title TEXT DEFAULT '',
                body TEXT DEFAULT '',
                link TEXT DEFAULT '',
                is_read INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS ext_sql_config (
                id INTEGER PRIMARY KEY,
                dbtype TEXT DEFAULT 'mysql',
                host TEXT DEFAULT '',
                port INTEGER DEFAULT 3306,
                dbname TEXT DEFAULT '',
                username TEXT DEFAULT '',
                password TEXT DEFAULT '',
                table_prefix TEXT DEFAULT 'lamkhe_'
            );
        ''')

    admin = cur.execute("SELECT id, password FROM users WHERE username = 'admin'").fetchone()
    if not admin:
        bootstrap_pw = (os.environ.get('ADMIN_PASSWORD') or '').strip()
        generated = len(bootstrap_pw) < 8
        if generated:
            bootstrap_pw = secrets.token_urlsafe(12)
        cur.execute(q("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                      "INSERT INTO users (username, password, role) VALUES (?, ?, ?)"),
                    ('admin', hash_password(bootstrap_pw), 'bithu'))
        if generated:
            pw_path = os.path.join(INSTANCE_DIR, 'admin_initial_password.txt')
            try:
                os.makedirs(INSTANCE_DIR, exist_ok=True)
                fd = os.open(pw_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                    fh.write('admin\n' + bootstrap_pw + '\n')
                logger.warning('Da tao tai khoan admin voi mat khau ngau nhien. Xem %s roi doi mat khau.', pw_path)
            except OSError as exc:
                logger.warning('Da tao admin voi mat khau ngau nhien nhung khong ghi duoc file: %s', exc)
    else:
        cur.execute(q("UPDATE users SET role = 'bithu' WHERE username = 'admin' AND role != 'bithu'",
                      "UPDATE users SET role = 'bithu' WHERE username = 'admin' AND role != 'bithu'"))
        if verify_password(dict(admin).get('password') or '', 'admin123'):
            logger.warning('CANH BAO: tai khoan admin van dung mat khau mac dinh admin123. Hay doi ngay.')

    if not is_pg():
        try:
            cur.execute('SELECT score FROM users LIMIT 1')
        except Exception:
            cur.execute('ALTER TABLE users ADD COLUMN score INTEGER DEFAULT 0')
        try:
            cur.execute('SELECT points FROM tasks LIMIT 1')
        except Exception:
            cur.execute('ALTER TABLE tasks ADD COLUMN points INTEGER DEFAULT 0')

    user_cols = [
        ('full_name', "TEXT DEFAULT ''"),
        ('avatar', "TEXT DEFAULT ''"),
        ('title', "TEXT DEFAULT ''"),
        ('department', "TEXT DEFAULT ''"),
        ('phone', "TEXT DEFAULT ''"),
        ('email', "TEXT DEFAULT ''"),
        ('twofa_enabled', 'INTEGER DEFAULT 0'),
        ('twofa_secret', "TEXT DEFAULT ''"),
        ('api_token', "TEXT DEFAULT ''"),
        ('theme', "TEXT DEFAULT 'dark'"),
        ('language', "TEXT DEFAULT 'vi'"),
        ('timezone', "TEXT DEFAULT 'Asia/Ho_Chi_Minh'"),
        ('date_format', "TEXT DEFAULT 'DD/MM/YYYY'"),
        ('time_format', "TEXT DEFAULT '24h'"),
        ('default_view', "TEXT DEFAULT 'kanban'"),
        ('cal_google', 'INTEGER DEFAULT 0'),
        ('cal_outlook', 'INTEGER DEFAULT 0'),
        ('store_drive', 'INTEGER DEFAULT 0'),
        ('store_onedrive', 'INTEGER DEFAULT 0'),
        ('store_dropbox', 'INTEGER DEFAULT 0'),
        ('auto_done_unfollow', 'INTEGER DEFAULT 0'),
        ('auto_overdue_warn', 'INTEGER DEFAULT 0'),
    ]
    for col, typ in user_cols:
        try:
            ensure_column(cur, 'users', col, typ)
        except Exception:
            pass
    try:
        ensure_column(cur, 'tasks', 'deleted_at', 'TEXT DEFAULT NULL')
    except Exception:
        pass
    for col, typ in [('estimate_hours', 'REAL DEFAULT 0'), ('actual_seconds', 'INTEGER DEFAULT 0'),
                     ('skills', "TEXT DEFAULT ''"), ('scope', "TEXT DEFAULT 'lang'")]:
        try:
            ensure_column(cur, 'tasks', col, typ)
        except Exception:
            pass
    for col, typ in [('slack_url', "TEXT DEFAULT ''"), ('teams_url', "TEXT DEFAULT ''"),
                     ('github_repo', "TEXT DEFAULT ''"), ('skills', "TEXT DEFAULT ''")]:
        try:
            ensure_column(cur, 'users', col, typ)
        except Exception:
            pass
    try:
        ensure_column(cur, 'attachments', 'note', "TEXT DEFAULT ''")
        ensure_column(cur, 'attachments', 'url', "TEXT DEFAULT ''")
        ensure_column(cur, 'attachments', 'file_data', q('BYTEA', 'BLOB'))
    except Exception:
        pass

    conn.commit()
    conn.close()


def hash_password(password):
    """Hash mat khau bang scrypt (werkzeug). Khong con SHA-256 tho."""
    try:
        return generate_password_hash(password)
    except (ValueError, RuntimeError):
        # Mot so ban Python khong co OpenSSL scrypt: lui ve PBKDF2.
        return generate_password_hash(password, method='pbkdf2:sha256:600000')


def _looks_like_legacy_hash(stored):
    """SHA-256 tran (64 hex) tu phien ban cu."""
    return bool(stored) and len(stored) == 64 and all(c in '0123456789abcdefABCDEF' for c in stored)


def verify_password(stored, password):
    """Kiem tra mat khau, ho tro hash SHA-256 cu de nang cap dan."""
    if not stored or password is None:
        return False
    if _looks_like_legacy_hash(stored):
        return hmac.compare_digest(stored.lower(), hashlib.sha256(password.encode()).hexdigest())
    try:
        return check_password_hash(stored, password)
    except (ValueError, TypeError):
        return False


def password_needs_rehash(stored):
    """True neu hash cu (SHA-256) hoac khong phai dinh dang werkzeug hien tai."""
    if not stored:
        return False
    return _looks_like_legacy_hash(stored) or not stored.startswith(('scrypt:', 'pbkdf2:'))


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Not authenticated'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin():
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Admin access required'}), 403
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


def q(sql_pg, sql_lite):
    return sql_pg if is_pg() else sql_lite


def ensure_column(cur, table, column, pg_type):
    if is_pg():
        cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {pg_type}")
    else:
        try:
            cur.execute(f'SELECT {column} FROM {table} LIMIT 1')
        except Exception:
            lite_type = pg_type.replace('SERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT')
            cur.execute(f'ALTER TABLE {table} ADD COLUMN {column} {lite_type}')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_json_best_effort(url, payload):
    """Gui webhook ra ngoai, chan SSRF (host noi bo / redirect)."""
    if not is_public_http_url(url):
        try:
            host = urlsplit(url).hostname
        except ValueError:
            host = 'invalid'
        logger.warning('Bo qua webhook khong an toan (host=%s)', host)
        return
    try:
        import json as _json
        opener = urllib.request.build_opener(_NoRedirect)
        req = urllib.request.Request(url, data=_json.dumps(payload).encode(),
                           headers={'Content-Type': 'application/json',
                                    'User-Agent': 'LamKhe-TaskManager/1.0'})
        opener.open(req, timeout=4).read()
    except Exception:
        pass


def run_automation(conn, event, task):
    try:
        cur = conn.cursor()
        rules = cur.execute("SELECT * FROM automation_rules WHERE enabled = 1").fetchall()
        me = cur.execute(q("SELECT slack_url, teams_url FROM users WHERE id = %s",
                           "SELECT slack_url, teams_url FROM users WHERE id = ?"),
                         (task.get('created_by') or 0,)).fetchone()
        slack = (dict(me).get('slack_url') or '') if me else ''
        teams = (dict(me).get('teams_url') or '') if me else ''
        for r in rules:
            rr = dict(r)
            trig = (rr.get('trigger') or '').strip()
            act = (rr.get('action') or '').strip()
            if trig and trig != event and trig != '*':
                continue
            if act.startswith('priority:'):
                cur.execute(q("UPDATE tasks SET priority = %s WHERE id = %s",
                              "UPDATE tasks SET priority = ? WHERE id = ?"),
                            (act.split(':', 1)[1], task['id']))
            elif act.startswith('notify:'):
                msg = {'text': f"[LamKhe] {event}: {task.get('title')} ({act.split(':', 1)[1]})"}
                if slack:
                    post_json_best_effort(slack, msg)
                if teams:
                    post_json_best_effort(teams, {'text': msg['text']})
        try:
            whs = cur.execute(q("SELECT * FROM webhooks WHERE enabled = 1 AND (event = %s OR event = '*')",
                                "SELECT * FROM webhooks WHERE enabled = 1 AND (event = ? OR event = '*')"),
                              (event,)).fetchall()
            for w in whs:
                post_json_best_effort(dict(w)['url'], {'event': event, 'task': {'id': task.get('id'), 'title': task.get('title')}})
        except Exception:
            pass
    except Exception:
        pass


# ==================== PAGE ROUTES ====================

@app.route('/health')
def health():
    return {'status': 'ok'}, 200

@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('images/favicon.png')

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login_page'))


@app.route('/login')
def login_page():
    return render_template('login.html')


@app.route('/register')
def register_page():
    return redirect(url_for('login_page') + '#signup')


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


# ==================== AUTH API ====================

USERNAME_RE = re.compile(r'^[A-Za-z0-9._-]{3,32}$')
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


def validate_new_password(password):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        return f'Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự'
    if len(password) > MAX_PASSWORD_LENGTH:
        return f'Mật khẩu tối đa {MAX_PASSWORD_LENGTH} ký tự'
    return None


@app.route('/api/register', methods=['POST'])
def api_register():
    retry = _register_limiter.hit(client_ip())
    if retry:
        return too_many_requests(retry, 'Bạn đã tạo quá nhiều tài khoản, thử lại sau')

    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return jsonify({'error': 'Username và password không được để trống'}), 400
    if not USERNAME_RE.match(username):
        return jsonify({'error': 'Username 3-32 ký tự, chỉ gồm chữ, số, dấu chấm, gạch dưới, gạch ngang'}), 400
    pw_error = validate_new_password(password)
    if pw_error:
        return jsonify({'error': pw_error}), 400

    conn = get_db()
    cur = conn.cursor()
    existing = cur.execute(q("SELECT id FROM users WHERE username = %s", "SELECT id FROM users WHERE username = ?"), (username,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'error': 'Username đã tồn tại'}), 400

    try:
        cur.execute(q("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                      "INSERT INTO users (username, password, role) VALUES (?, ?, ?)"),
                    (username, hash_password(password), 'user'))
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        return jsonify({'error': 'Username đã tồn tại'}), 400
    conn.close()
    return jsonify({'message': 'Đăng ký thành công'}), 201


_DUMMY_HASH = hash_password('freebuff-dummy-password')


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    ip = client_ip()
    limit_key = f'{ip}|{username.lower()}'

    retry = _login_ip_limiter.hit(ip)
    if retry:
        return too_many_requests(retry, 'Quá nhiều lần đăng nhập thất bại, thử lại sau')
    retry = _login_limiter.hit(limit_key)
    if retry:
        return too_many_requests(retry, 'Quá nhiều lần đăng nhập thất bại, thử lại sau')

    conn = get_db()
    cur = conn.cursor()
    user = cur.execute(q("SELECT * FROM users WHERE username = %s",
                         "SELECT * FROM users WHERE username = ?"), (username,)).fetchone()

    stored = dict(user).get('password') if user else ''
    # Luon chay mot phep hash de giam chenh lech thoi gian (user enumeration).
    password_ok = verify_password(stored or _DUMMY_HASH, password)
    if not user or not password_ok:
        conn.close()
        return jsonify({'error': 'Sai username hoặc password'}), 401

    u = dict(user)
    try:
        if password_needs_rehash(stored):
            cur.execute(q("UPDATE users SET password = %s WHERE id = %s",
                          "UPDATE users SET password = ? WHERE id = ?"),
                        (hash_password(password), u['id']))
    except Exception:
        pass
    session.clear()
    session.permanent = True
    session['user_id'] = u['id']
    session['username'] = u['username']
    session['role'] = u['role']
    try:
        cur.execute(q("INSERT INTO login_history (user_id, ip, user_agent) VALUES (%s, %s, %s)",
                      "INSERT INTO login_history (user_id, ip, user_agent) VALUES (?, ?, ?)"),
                    (u['id'], ip, (request.headers.get('User-Agent') or '')[:300]))
        conn.commit()
    except Exception:
        pass
    conn.close()
    _login_limiter.reset(limit_key)
    _login_ip_limiter.reset(ip)

    return jsonify({
        'message': 'Đăng nhập thành công',
        'user': {'id': u['id'], 'username': u['username'], 'role': u['role'], 'score': u['score']}
    })


@app.route('/api/logout')
def api_logout():
    session.clear()
    return jsonify({'message': 'Đã đăng xuất'})


@app.route('/api/me')
@login_required
def api_me():
    conn = get_db()
    cur = conn.cursor()
    user = cur.execute(q("SELECT * FROM users WHERE id = %s", "SELECT * FROM users WHERE id = ?"),
                       (session['user_id'],)).fetchone()
    conn.close()
    u = dict(user)
    u.pop('password', None)
    u.pop('twofa_secret', None)
    return jsonify(u)


# ==================== USERS API ====================

@app.route('/api/users')
@login_required
def api_users():
    conn = get_db()
    cur = conn.cursor()
    if session.get('role') == 'bithu':
        users = cur.execute(q("SELECT id, username, role, score, full_name, title FROM users ORDER BY username",
                              "SELECT id, username, role, score, full_name, title FROM users ORDER BY username")).fetchall()
    else:
        users = cur.execute(q("SELECT id, username, role, score FROM users WHERE id = %s",
                              "SELECT id, username, role, score FROM users WHERE id = ?"),
                            (session['user_id'],)).fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])


@app.route('/api/users/<int:user_id>/role', methods=['PUT'])
@login_required
@admin_required
def api_update_role(user_id):
    data = request.get_json(silent=True) or {}
    new_role = data.get('role')
    if new_role not in ('user', 'bithu'):
        return jsonify({'error': 'Role không hợp lệ'}), 400
    if user_id == session.get('user_id') and new_role != 'bithu':
        return jsonify({'error': 'Không thể tự hạ quyền chính mình'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q("UPDATE users SET role = %s WHERE id = %s", "UPDATE users SET role = ? WHERE id = ?"), (new_role, user_id))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã cập nhật role'})


@app.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required
@admin_required
def api_update_user(user_id):
    data = request.get_json() or {}
    updates = {f: (data.get(f) or '') for f in ADMIN_USER_FIELDS if f in data}
    if not updates:
        return jsonify({'error': 'Không có gì để cập nhật'}), 400
    conn = get_db()
    cur = conn.cursor()
    sets_pg = ', '.join([f"{k} = %s" for k in updates])
    sets_lite = ', '.join([f"{k} = ?" for k in updates])
    cur.execute(q(f"UPDATE users SET {sets_pg} WHERE id = %s", f"UPDATE users SET {sets_lite} WHERE id = ?"),
                list(updates.values()) + [user_id])
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã cập nhật'})


@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_user(user_id):
    if user_id == session['user_id']:
        return jsonify({'error': 'Không thể xóa chính mình'}), 400
    conn = get_db()
    cur = conn.cursor()
    target = cur.execute(q("SELECT id, username FROM users WHERE id = %s", "SELECT id, username FROM users WHERE id = ?"),
                         (user_id,)).fetchone()
    if not target:
        conn.close()
        return jsonify({'error': 'User không tồn tại'}), 404
    if dict(target).get('username') == 'admin':
        conn.close()
        return jsonify({'error': 'Không thể xóa tài khoản admin gốc'}), 400
    for tbl in ('task_assignments', 'points_log', 'comments', 'time_logs', 'login_history'):
        try:
            col = 'user_id'
            cur.execute(q(f"DELETE FROM {tbl} WHERE {col} = %s", f"DELETE FROM {tbl} WHERE {col} = ?"), (user_id,))
        except Exception:
            pass
    for tbl, col in (('tasks', 'created_by'), ('finance', 'created_by'), ('subtasks', 'created_by'),
                     ('attachments', 'created_by'), ('automation_rules', 'created_by'), ('webhooks', 'created_by'),
                     ('points_log', 'created_by')):
        try:
            cur.execute(q(f"UPDATE {tbl} SET {col} = NULL WHERE {col} = %s",
                          f"UPDATE {tbl} SET {col} = NULL WHERE {col} = ?"), (user_id,))
        except Exception:
            pass
    cur.execute(q("DELETE FROM users WHERE id = %s", "DELETE FROM users WHERE id = ?"), (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã xóa tài khoản'})


# ==================== SETTINGS API ====================

PROFILE_FIELDS = ['full_name', 'avatar', 'department', 'phone', 'email']
EXTRA_FIELDS = ['slack_url', 'teams_url', 'github_repo', 'skills']
ADMIN_USER_FIELDS = ['full_name', 'title', 'department']
PREF_FIELDS = ['theme', 'language', 'timezone', 'date_format', 'time_format', 'default_view',
               'cal_google', 'cal_outlook', 'store_drive', 'store_onedrive', 'store_dropbox',
               'auto_done_unfollow', 'auto_overdue_warn']
INT_FIELDS = {'cal_google', 'cal_outlook', 'store_drive', 'store_onedrive', 'store_dropbox',
              'auto_done_unfollow', 'auto_overdue_warn'}
ENUM_FIELDS = {
    'theme': {'dark', 'light', 'system'},
    'language': {'vi', 'en'},
    'timezone': {'Asia/Ho_Chi_Minh', 'Asia/Bangkok', 'UTC'},
    'date_format': {'DD/MM/YYYY', 'MM/DD/YYYY'},
    'time_format': {'24h', '12h'},
    'default_view': {'kanban', 'list', 'gantt', 'calendar', 'workload'},
}


@app.route('/api/profile', methods=['PUT'])
@login_required
def api_profile_update():
    data = request.get_json(silent=True) or {}
    updates = {}
    for f in PROFILE_FIELDS + PREF_FIELDS + EXTRA_FIELDS:
        if f in data:
            v = data[f]
            if f in INT_FIELDS:
                try:
                    v = 1 if str(v).lower() in ('1', 'true', 'on', 'yes') or v is True or v == 1 else 0
                except Exception:
                    v = 0
            else:
                v = '' if v is None else str(v).strip()
                if f in ('avatar', 'slack_url', 'teams_url') and v and not is_safe_link_url(v):
                    return jsonify({'error': f'{f} phải là URL http(s) hợp lệ'}), 400
                if f in ('slack_url', 'teams_url') and v and not is_public_http_url(v, resolve_dns=False):
                    return jsonify({'error': f'{f} không được trỏ tới địa chỉ nội bộ'}), 400
                if f in ENUM_FIELDS and v not in ENUM_FIELDS[f]:
                    return jsonify({'error': f'{f} không hợp lệ'}), 400
                v = v[:2048]
            updates[f] = v
    if not updates:
        return jsonify({'error': 'Không có gì để cập nhật'}), 400
    conn = get_db()
    cur = conn.cursor()
    sets_pg = ', '.join([f"{k} = %s" for k in updates])
    sets_lite = ', '.join([f"{k} = ?" for k in updates])
    vals = list(updates.values()) + [session['user_id']]
    cur.execute(q(f"UPDATE users SET {sets_pg} WHERE id = %s", f"UPDATE users SET {sets_lite} WHERE id = ?"), vals)
    conn.commit()
    user = cur.execute(q("SELECT * FROM users WHERE id = %s", "SELECT * FROM users WHERE id = ?"),
                       (session['user_id'],)).fetchone()
    conn.close()
    u = dict(user)
    u.pop('password', None)
    u.pop('twofa_secret', None)
    return jsonify(u)


@app.route('/api/change-password', methods=['POST'])
@login_required
def api_change_password():
    data = request.get_json() or {}
    old = data.get('old_password', '')
    new = data.get('new_password', '')
    pw_error = validate_new_password(new)
    if pw_error:
        return jsonify({'error': pw_error}), 400
    conn = get_db()
    cur = conn.cursor()
    user = cur.execute(q("SELECT * FROM users WHERE id = %s", "SELECT * FROM users WHERE id = ?"),
                       (session['user_id'],)).fetchone()
    if not user or not verify_password(dict(user)['password'], old):
        conn.close()
        return jsonify({'error': 'Mật khẩu cũ không đúng'}), 400
    cur.execute(q("UPDATE users SET password = %s WHERE id = %s", "UPDATE users SET password = ? WHERE id = ?"),
                (hash_password(new), session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã đổi mật khẩu'})


@app.route('/api/login-history')
@login_required
def api_login_history():
    conn = get_db()
    cur = conn.cursor()
    rows = cur.execute(q("SELECT * FROM login_history WHERE user_id = %s ORDER BY created_at DESC LIMIT 50",
                         "SELECT * FROM login_history WHERE user_id = ? ORDER BY created_at DESC LIMIT 50"),
                       (session['user_id'],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/login-history/<int:hid>', methods=['DELETE'])
@login_required
def api_login_history_delete(hid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q("DELETE FROM login_history WHERE id = %s AND user_id = %s",
                  "DELETE FROM login_history WHERE id = ? AND user_id = ?"), (hid, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã xóa phiên'})


@app.route('/api/api-token', methods=['POST'])
@login_required
def api_token_regen():
    token = 'lk_' + secrets.token_hex(24)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q("UPDATE users SET api_token = %s WHERE id = %s", "UPDATE users SET api_token = ? WHERE id = ?"),
                (token, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'api_token': token})


@app.route('/api/automation', methods=['GET', 'POST'])
@login_required
@admin_required
def api_automation():
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'GET':
        rows = cur.execute("SELECT * FROM automation_rules ORDER BY id DESC").fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        conn.close()
        return jsonify({'error': 'Thiếu tên rule'}), 400
    cur.execute(q("INSERT INTO automation_rules (name, trigger, action, enabled, created_by) VALUES (%s, %s, %s, %s, %s)",
                  "INSERT INTO automation_rules (name, trigger, action, enabled, created_by) VALUES (?, ?, ?, ?, ?)"),
                (name, data.get('trigger', ''), data.get('action', ''), 1 if data.get('enabled', True) else 0, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã tạo rule'}), 201


@app.route('/api/automation/<int:rid>', methods=['PUT', 'DELETE'])
@login_required
@admin_required
def api_automation_one(rid):
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'DELETE':
        cur.execute(q("DELETE FROM automation_rules WHERE id = %s", "DELETE FROM automation_rules WHERE id = ?"), (rid,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Đã xóa rule'})
    data = request.get_json() or {}
    cur.execute(q("UPDATE automation_rules SET name = %s, trigger = %s, action = %s, enabled = %s WHERE id = %s",
                  "UPDATE automation_rules SET name = ?, trigger = ?, action = ?, enabled = ? WHERE id = ?"),
                (data.get('name', ''), data.get('trigger', ''), data.get('action', ''),
                 1 if data.get('enabled', True) else 0, rid))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã cập nhật rule'})


@app.route('/api/webhooks', methods=['GET', 'POST'])
@login_required
@admin_required
def api_webhooks():
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'GET':
        rows = cur.execute("SELECT * FROM webhooks ORDER BY id DESC").fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    if not url:
        conn.close()
        return jsonify({'error': 'Thiếu URL'}), 400
    if not is_public_http_url(url):
        conn.close()
        return jsonify({'error': 'Webhook phải là URL http(s) công khai (không dùng localhost/IP nội bộ)'}), 400
    cur.execute(q("INSERT INTO webhooks (url, event, enabled, created_by) VALUES (%s, %s, %s, %s)",
                  "INSERT INTO webhooks (url, event, enabled, created_by) VALUES (?, ?, ?, ?)"),
                (url, data.get('event', 'task.done'), 1 if data.get('enabled', True) else 0, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã thêm webhook'}), 201


@app.route('/api/webhooks/<int:wid>', methods=['DELETE'])
@login_required
@admin_required
def api_webhook_delete(wid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q("DELETE FROM webhooks WHERE id = %s", "DELETE FROM webhooks WHERE id = ?"), (wid,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã xóa webhook'})


@app.route('/api/export/<kind>')
@login_required
def api_export(kind):
    conn = get_db()
    cur = conn.cursor()
    out = io.StringIO()
    w = csv.writer(out)
    if kind == 'tasks.csv':
        rows = cur.execute("SELECT id, title, description, status, priority, due_date, points, scope, created_at FROM tasks WHERE deleted_at IS NULL ORDER BY id").fetchall()
        w.writerow(['id', 'title', 'description', 'status', 'priority', 'due_date', 'points', 'scope', 'created_at'])
        for r in rows:
            d = dict(r)
            w.writerow([d.get('id'), csv_safe(d.get('title')), csv_safe(d.get('description')),
                        csv_safe(d.get('status')), csv_safe(d.get('priority')), d.get('due_date'),
                        d.get('points'), d.get('scope', 'lang'), d.get('created_at')])
    elif kind == 'finance.csv':
        rows = cur.execute("SELECT id, type, amount, description, category, date FROM finance ORDER BY id").fetchall()
        w.writerow(['id', 'type', 'amount', 'description', 'category', 'date'])
        for r in rows:
            d = dict(r)
            w.writerow([d.get('id'), d.get('type'), d.get('amount'), csv_safe(d.get('description')),
                        csv_safe(d.get('category')), d.get('date')])
    else:
        conn.close()
        return jsonify({'error': 'Loại không hỗ trợ'}), 400
    conn.close()
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={kind}'})


@app.route('/api/import/tasks', methods=['POST'])
@login_required
@admin_required
def api_import_tasks():
    data = request.get_json() or {}
    text = data.get('csv', '')
    if not text.strip():
        return jsonify({'error': 'Thiếu nội dung CSV'}), 400
    reader = csv.DictReader(io.StringIO(text))
    conn = get_db()
    cur = conn.cursor()
    count = 0
    for row in reader:
        title = (row.get('title') or '').strip()
        if not title:
            continue
        try:
            pts = int(float(row.get('points') or 0))
        except Exception:
            pts = 0
        cur.execute(q("INSERT INTO tasks (title, description, status, priority, due_date, points, scope, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                      "INSERT INTO tasks (title, description, status, priority, due_date, points, scope, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"),
                    (title, row.get('description', ''), row.get('status', 'pending') or 'pending',
                     row.get('priority', 'medium') or 'medium', row.get('due_date') or None, pts,
                     row.get('scope') if row.get('scope') in ('lang', 'xa') else 'lang', session['user_id']))
        count += 1
    conn.commit()
    conn.close()
    return jsonify({'message': f'Đã nhập {count} task'}), 201


@app.route('/api/trash')
@login_required
@admin_required
def api_trash():
    conn = get_db()
    cur = conn.cursor()
    rows = cur.execute("SELECT * FROM tasks WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/trash/<int:task_id>/restore', methods=['POST'])
@login_required
@admin_required
def api_trash_restore(task_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q("UPDATE tasks SET deleted_at = NULL WHERE id = %s", "UPDATE tasks SET deleted_at = NULL WHERE id = ?"), (task_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã khôi phục'})


@app.route('/api/trash/<int:task_id>/purge', methods=['DELETE'])
@login_required
@admin_required
def api_trash_purge(task_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q("DELETE FROM points_log WHERE task_id = %s", "DELETE FROM points_log WHERE task_id = ?"), (task_id,))
    cur.execute(q("DELETE FROM task_assignments WHERE task_id = %s", "DELETE FROM task_assignments WHERE task_id = ?"), (task_id,))
    cur.execute(q("DELETE FROM attachments WHERE task_id = %s", "DELETE FROM attachments WHERE task_id = ?"), (task_id,))
    cur.execute(q("DELETE FROM tasks WHERE id = %s", "DELETE FROM tasks WHERE id = ?"), (task_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã xóa vĩnh viễn'})


@app.route('/api/admin/reset', methods=['POST'])
@login_required
@admin_required
def api_admin_reset():
    data = request.get_json() or {}
    if data.get('confirm') != 'RESET':
        return jsonify({'error': 'Gõ RESET để xác nhận'}), 400
    conn = get_db()
    cur = conn.cursor()
    for tbl in ('task_assignments', 'task_dependencies', 'subtasks', 'comments', 'time_logs',
                'attachments', 'points_log', 'login_history', 'automation_rules', 'webhooks',
                'shares', 'finance', 'tasks'):
        try:
            cur.execute(f"DELETE FROM {tbl}")
        except Exception:
            pass
    cur.execute(q("UPDATE users SET score = 0 WHERE role = %s", "UPDATE users SET score = 0 WHERE role = ?"), ('bithu',))
    cur.execute(q("UPDATE fund SET balance = 0 WHERE id = %s", "UPDATE fund SET balance = 0 WHERE id = ?"),
                (get_fund(conn)['id'],))
    cur.execute(q("DELETE FROM users WHERE role != %s OR role IS NULL",
                  "DELETE FROM users WHERE role != ? OR role IS NULL"), ('bithu',))
    conn.commit()
    kept = cur.execute(q("SELECT username FROM users WHERE role = %s",
                         "SELECT username FROM users WHERE role = ?"), ('bithu',)).fetchall()
    conn.close()
    return jsonify({'message': 'Đã reset hệ thống', 'kept': [dict(u)['username'] for u in kept]})


@app.route('/api/storage')
@login_required
def api_storage():
    conn = get_db()
    cur = conn.cursor()
    try:
        rows = cur.execute("SELECT COUNT(*) AS n, COALESCE(SUM(size),0) AS s FROM attachments").fetchone()
        d = dict(rows)
    except Exception:
        d = {'n': 0, 's': 0}
    try:
        t = cur.execute("SELECT COUNT(*) AS c FROM tasks WHERE deleted_at IS NULL").fetchone()
        tasks_n = dict(t)['c']
    except Exception:
        tasks_n = 0
    conn.close()
    return jsonify({'files': d.get('n', 0), 'bytes': d.get('s', 0), 'tasks': tasks_n})


# ==================== TASKS API ====================

def get_task_assignees(conn, task_id):
    cur = conn.cursor()
    rows = cur.execute(q(
        "SELECT u.id, u.username FROM task_assignments ta JOIN users u ON ta.user_id = u.id WHERE ta.task_id = %s",
        "SELECT u.id, u.username FROM task_assignments ta JOIN users u ON ta.user_id = u.id WHERE ta.task_id = ?"),
        (task_id,)).fetchall()
    return [dict(r) for r in rows]


def _chunks(seq, size=500):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _lock_task(conn, task_id):
    """Khoa dong task de tranh race (2 nguoi cung nhan / cung danh dau done)."""
    cur = conn.cursor()
    if is_pg():
        return cur.execute("SELECT * FROM tasks WHERE id = %s FOR UPDATE", (task_id,)).fetchone()
    conn.execute("BEGIN IMMEDIATE")
    return cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def serialize_tasks(conn, tasks, user_id=None):
    """Serialize nhieu task bang 4 query batch thay vi 4 query moi task (N+1)."""
    rows = [dict(t) for t in tasks]
    if not rows:
        return []
    ids = [r['id'] for r in rows]
    cur = conn.cursor()
    assignments, subtasks, deps, comments = {}, {}, {}, {}
    for chunk in _chunks(ids):
        ph = ','.join(['%s'] * len(chunk)) if is_pg() else ','.join(['?'] * len(chunk))
        for r in cur.execute(q(
                f"SELECT ta.task_id, u.id, u.username FROM task_assignments ta JOIN users u ON ta.user_id = u.id WHERE ta.task_id IN ({ph})",
                f"SELECT ta.task_id, u.id, u.username FROM task_assignments ta JOIN users u ON ta.user_id = u.id WHERE ta.task_id IN ({ph})"),
                chunk).fetchall():
            d = dict(r)
            assignments.setdefault(d['task_id'], []).append({'id': d['id'], 'username': d['username']})
        for r in cur.execute(q(
                f"SELECT task_id, id, title, done FROM subtasks WHERE task_id IN ({ph}) ORDER BY id",
                f"SELECT task_id, id, title, done FROM subtasks WHERE task_id IN ({ph}) ORDER BY id"),
                chunk).fetchall():
            d = dict(r)
            subtasks.setdefault(d['task_id'], []).append({'id': d['id'], 'title': d['title'], 'done': d['done']})
        for r in cur.execute(q(
                f"SELECT task_id, depends_on_id FROM task_dependencies WHERE task_id IN ({ph})",
                f"SELECT task_id, depends_on_id FROM task_dependencies WHERE task_id IN ({ph})"),
                chunk).fetchall():
            d = dict(r)
            deps.setdefault(d['task_id'], []).append(d['depends_on_id'])
        for r in cur.execute(q(
                f"SELECT task_id, COUNT(*) AS c FROM comments WHERE task_id IN ({ph}) GROUP BY task_id",
                f"SELECT task_id, COUNT(*) AS c FROM comments WHERE task_id IN ({ph}) GROUP BY task_id"),
                chunk).fetchall():
            d = dict(r)
            comments[d['task_id']] = d['c']
    out = []
    for d in rows:
        tid = d['id']
        d['assigned_users'] = assignments.get(tid, [])
        d['assignee_count'] = len(d['assigned_users'])
        d['max_assignees'] = d.get('max_assignees') or 3
        d['slots_left'] = d['max_assignees'] - d['assignee_count']
        d['is_claimed_by_me'] = any(u['id'] == user_id for u in d['assigned_users']) if user_id else False
        d['points'] = d.get('points') or 0
        d['scope'] = d.get('scope') or 'lang'
        d['subtasks'] = subtasks.get(tid, [])
        d['depends_on'] = deps.get(tid, [])
        d['comment_count'] = comments.get(tid, 0)
        d['estimate_hours'] = d.get('estimate_hours') or 0
        d['actual_seconds'] = d.get('actual_seconds') or 0
        out.append(d)
    return out


def serialize_task(conn, task, user_id=None, role=None):
    d = dict(task)
    d['assigned_users'] = get_task_assignees(conn, task['id'])
    d['assignee_count'] = len(d['assigned_users'])
    d['max_assignees'] = task['max_assignees'] or 3
    d['slots_left'] = d['max_assignees'] - d['assignee_count']
    d['is_claimed_by_me'] = any(u['id'] == user_id for u in d['assigned_users']) if user_id else False
    d['points'] = task['points'] or 0
    try:
        d['scope'] = dict(task).get('scope') or 'lang'
    except Exception:
        d['scope'] = 'lang'
    try:
        cur = conn.cursor()
        subs = cur.execute(q("SELECT id, title, done FROM subtasks WHERE task_id = %s ORDER BY id",
                             "SELECT id, title, done FROM subtasks WHERE task_id = ? ORDER BY id"),
                           (task['id'],)).fetchall()
        d['subtasks'] = [dict(s) for s in subs]
        deps = cur.execute(q("SELECT depends_on_id FROM task_dependencies WHERE task_id = %s",
                             "SELECT depends_on_id FROM task_dependencies WHERE task_id = ?"),
                           (task['id'],)).fetchall()
        d['depends_on'] = [dict(x)['depends_on_id'] for x in deps]
        cc = cur.execute(q("SELECT COUNT(*) AS c FROM comments WHERE task_id = %s",
                           "SELECT COUNT(*) AS c FROM comments WHERE task_id = ?"),
                         (task['id'],)).fetchone()
        d['comment_count'] = dict(cc)['c'] if cc else 0
        d['estimate_hours'] = task['estimate_hours'] if 'estimate_hours' in dict(task) else 0
        d['actual_seconds'] = task['actual_seconds'] if 'actual_seconds' in dict(task) else 0
    except Exception:
        d['subtasks'] = []
        d['depends_on'] = []
        d['comment_count'] = 0
    return d


@app.route('/api/tasks')
@login_required
def api_tasks():
    conn = get_db()
    cur = conn.cursor()
    role = session.get('role')
    user_id = session['user_id']

    # Moi doan vien deu xem duoc bang viec chung de nhan task (claim).
    tasks = cur.execute("SELECT * FROM tasks WHERE deleted_at IS NULL ORDER BY created_at DESC").fetchall()

    scope = (request.args.get('scope') or '').strip()
    if scope in ('lang', 'xa'):
        tasks = [tk for tk in tasks if dict(tk).get('scope', 'lang') == scope]

    result = serialize_tasks(conn, tasks, user_id)
    conn.close()
    return jsonify(result)


@app.route('/api/tasks', methods=['POST'])
@login_required
@admin_required
def api_create_task():
    data = request.get_json(silent=True) or {}
    title = data.get('title', '').strip()
    if not title:
        return jsonify({'error': 'Tiêu đề không được để trống'}), 400

    max_assignees = min(max(int(data.get('max_assignees', 3) or 3), 1), 10)
    points = int(data.get('points', 0) or 0)

    assigned_ids = data.get('assigned_to', [])
    if not isinstance(assigned_ids, list):
        assigned_ids = [assigned_ids] if assigned_ids else []
    assigned_ids = [int(x) for x in assigned_ids if x]

    if len(assigned_ids) > max_assignees:
        return jsonify({'error': f'Tối đa giao cho {max_assignees} người'}), 400

    conn = get_db()
    cur = conn.cursor()
    due_date = data.get('due_date') or None
    try:
        est = float(data.get('estimate_hours', 0) or 0)
    except Exception:
        est = 0

    cur.execute(q(
        "INSERT INTO tasks (title, description, status, priority, due_date, max_assignees, points, estimate_hours, skills, scope, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        "INSERT INTO tasks (title, description, status, priority, due_date, max_assignees, points, estimate_hours, skills, scope, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"),
        (title, data.get('description', '') or '', data.get('status', 'pending'), data.get('priority', 'medium'),
         due_date, max_assignees, points, est, (data.get('skills') or ''),
         data.get('scope', 'lang') if data.get('scope') in ('lang', 'xa') else 'lang', session['user_id']))
    task_id = cur.fetchone()['id'] if is_pg() else cur.lastrowid

    for uid in assigned_ids:
        cur.execute(q("INSERT INTO task_assignments (task_id, user_id) VALUES (%s, %s)",
                      "INSERT INTO task_assignments (task_id, user_id) VALUES (?, ?)"), (task_id, uid))
    for uid in assigned_ids:
        if uid != session['user_id']:
            _notify_user(conn, uid, 'assign', f"Bạn được giao việc: {title}", f"#{task_id}", '')
    if assigned_ids:
        _push_assignment_chat(conn, task_id, title, assigned_ids, session['user_id'])

    for dep in (data.get('depends_on') or []):
        try:
            cur.execute(q("INSERT INTO task_dependencies (task_id, depends_on_id) VALUES (%s, %s)",
                          "INSERT INTO task_dependencies (task_id, depends_on_id) VALUES (?, ?)"),
                        (task_id, int(dep)))
        except Exception:
            pass
    for st in (data.get('subtasks') or []):
        ttl = (st.get('title') if isinstance(st, dict) else str(st)).strip() if st else ''
        if ttl:
            cur.execute(q("INSERT INTO subtasks (task_id, title, created_by) VALUES (%s, %s, %s)",
                          "INSERT INTO subtasks (task_id, title, created_by) VALUES (?, ?, ?)"),
                        (task_id, ttl, session['user_id']))

    conn.commit()
    task = cur.execute(q("SELECT * FROM tasks WHERE id = %s", "SELECT * FROM tasks WHERE id = ?"), (task_id,)).fetchone()
    result = serialize_task(conn, task, session['user_id'])
    conn.close()
    return jsonify(result), 201


def _save_attachment(cur, task_id, filename, url, size, raw, user_id):
    try:
        cur.execute("SAVEPOINT attach_file")
    except Exception:
        pass
    try:
        cur.execute(q("INSERT INTO attachments (task_id, filename, url, note, size, file_data, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                      "INSERT INTO attachments (task_id, filename, url, note, size, file_data, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)"),
                    (task_id, filename, url, '', size, raw, user_id))
    except Exception:
        try:
            cur.execute("ROLLBACK TO SAVEPOINT attach_file")
        except Exception:
            pass
        cur.execute(q("INSERT INTO attachments (task_id, filename, url, note, size, created_by) VALUES (%s, %s, %s, %s, %s, %s)",
                      "INSERT INTO attachments (task_id, filename, url, note, size, created_by) VALUES (?, ?, ?, ?, ?, ?)"),
                    (task_id, filename, url, '', size, user_id))
    try:
        cur.execute("RELEASE SAVEPOINT attach_file")
    except Exception:
        pass


def _notify_user(conn, user_id, ntype, title, body='', link=''):
    try:
        cur = conn.cursor()
        cur.execute(q("INSERT INTO notifications (user_id, type, title, body, link) VALUES (%s, %s, %s, %s, %s)",
                      "INSERT INTO notifications (user_id, type, title, body, link) VALUES (?, ?, ?, ?, ?)"),
                    (user_id, ntype, (title or '')[:200], (body or '')[:500], (link or '')[:300]))
    except Exception:
        pass


def _user_chat_urls(conn, user_id):
    try:
        cur = conn.cursor()
        r = cur.execute(q("SELECT slack_url, teams_url FROM users WHERE id = %s",
                          "SELECT slack_url, teams_url FROM users WHERE id = ?"), (user_id,)).fetchone()
        if not r:
            return []
        d = dict(r)
        return [u for u in [d.get('slack_url'), d.get('teams_url')] if u]
    except Exception:
        return []


def _push_assignment_chat(conn, task_id, title, assignee_ids, actor_id):
    try:
        text = f"[LamKhe] Bạn được giao việc: {title} (#{task_id})"
        urls = set()
        for uid in list(assignee_ids or []) + [actor_id]:
            for u in _user_chat_urls(conn, uid):
                urls.add(u)
        for u in urls:
            post_json_best_effort(u, {'text': text})
    except Exception:
        pass


@app.route('/api/notifications')
@login_required
def api_notifications():
    conn = get_db()
    cur = conn.cursor()
    rows = cur.execute(q("SELECT id, type, title, body, link, is_read, created_at FROM notifications WHERE user_id = %s ORDER BY id DESC LIMIT 30",
                         "SELECT id, type, title, body, link, is_read, created_at FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 30"),
                       (session['user_id'],)).fetchall()
    unread = cur.execute(q("SELECT COUNT(*) AS c FROM notifications WHERE user_id = %s AND is_read = 0",
                           "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0"),
                         (session['user_id'],)).fetchone()
    conn.close()
    return jsonify({'items': [dict(r) for r in rows], 'unread': dict(unread)['c'] if unread else 0})


@app.route('/api/notifications/read', methods=['POST'])
@login_required
def api_notifications_read():
    data = request.get_json() or {}
    ids = [int(x) for x in (data.get('ids') or []) if str(x).isdigit()]
    conn = get_db()
    cur = conn.cursor()
    if ids:
        ph = ','.join(['%s'] * len(ids)) if is_pg() else ','.join(['?'] * len(ids))
        cur.execute(q(f"UPDATE notifications SET is_read = 1 WHERE user_id = %s AND id IN ({ph})",
                      f"UPDATE notifications SET is_read = 1 WHERE user_id = ? AND id IN ({ph})"),
                    [session['user_id']] + ids)
    else:
        cur.execute(q("UPDATE notifications SET is_read = 1 WHERE user_id = %s",
                      "UPDATE notifications SET is_read = 1 WHERE user_id = ?"), (session['user_id'],))
    conn.commit()
    conn.close()
    return jsonify({'message': 'ok'})


def _ext_sql_connect(cfg):
    dbtype = (cfg.get('dbtype') or 'mysql')
    host = cfg.get('host') or 'localhost'
    port = int(cfg.get('port') or (3306 if dbtype == 'mysql' else 5432))
    if dbtype == 'mysql':
        import pymysql
        return pymysql.connect(host=host, port=port, user=cfg.get('username') or '',
                               password=cfg.get('password') or '', database=cfg.get('dbname') or '',
                               charset='utf8mb4', connect_timeout=8)
    import psycopg
    return psycopg.connect(host=host, port=port, dbname=cfg.get('dbname') or '',
                           user=cfg.get('username') or '', password=cfg.get('password') or '',
                           connect_timeout=8)


def _get_ext_sql_config(conn):
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT * FROM ext_sql_config WHERE id = 1").fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}


@app.route('/api/integrations/sql')
@login_required
@admin_required
def api_ext_sql_get():
    conn = get_db()
    cfg = _get_ext_sql_config(conn)
    conn.close()
    if cfg.get('password'):
        cfg['password'] = '••••••'
    return jsonify(cfg)


@app.route('/api/integrations/sql', methods=['PUT'])
@login_required
@admin_required
def api_ext_sql_save():
    data = request.get_json() or {}
    dbtype = data.get('dbtype') if data.get('dbtype') in ('mysql', 'postgres') else 'mysql'
    try:
        port = int(data.get('port') or (3306 if dbtype == 'mysql' else 5432))
    except Exception:
        port = 3306 if dbtype == 'mysql' else 5432
    conn = get_db()
    cur = conn.cursor()
    exists = cur.execute("SELECT id FROM ext_sql_config WHERE id = 1").fetchone()
    pw = (data.get('password') or '')
    if exists:
        if pw in ('', '••••••'):
            cur.execute(q("UPDATE ext_sql_config SET dbtype=%s, host=%s, port=%s, dbname=%s, username=%s, table_prefix=%s WHERE id=1",
                          "UPDATE ext_sql_config SET dbtype=?, host=?, port=?, dbname=?, username=?, table_prefix=? WHERE id=1"),
                        (dbtype, data.get('host') or '', port, data.get('dbname') or '',
                         data.get('username') or '', data.get('table_prefix') or 'lamkhe_'))
        else:
            cur.execute(q("UPDATE ext_sql_config SET dbtype=%s, host=%s, port=%s, dbname=%s, username=%s, password=%s, table_prefix=%s WHERE id=1",
                          "UPDATE ext_sql_config SET dbtype=?, host=?, port=?, dbname=?, username=?, password=?, table_prefix=? WHERE id=1"),
                        (dbtype, data.get('host') or '', port, data.get('dbname') or '',
                         data.get('username') or '', pw, data.get('table_prefix') or 'lamkhe_'))
    else:
        cur.execute(q("INSERT INTO ext_sql_config (id, dbtype, host, port, dbname, username, password, table_prefix) VALUES (1, %s, %s, %s, %s, %s, %s, %s)",
                      "INSERT INTO ext_sql_config (id, dbtype, host, port, dbname, username, password, table_prefix) VALUES (1, ?, ?, ?, ?, ?, ?, ?)"),
                    (dbtype, data.get('host') or '', port, data.get('dbname') or '',
                     data.get('username') or '', '' if pw in ('', '••••••') else pw, data.get('table_prefix') or 'lamkhe_'))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã lưu cấu hình SQL ngoài'})


@app.route('/api/integrations/sql/test', methods=['POST'])
@login_required
@admin_required
def api_ext_sql_test():
    data = request.get_json() or {}
    conn = get_db()
    cfg = _get_ext_sql_config(conn)
    conn.close()
    for k in ('dbtype', 'host', 'port', 'dbname', 'username', 'table_prefix'):
        if data.get(k) not in (None, ''):
            cfg[k] = data[k]
    if data.get('password') and data.get('password') != '••••••':
        cfg['password'] = data['password']
    try:
        c2 = _ext_sql_connect(cfg)
        cur2 = c2.cursor()
        cur2.execute("SELECT version()" if (cfg.get('dbtype') or 'mysql') == 'postgres' else "SELECT VERSION()")
        ver = cur2.fetchone()
        c2.close()
        try:
            vstr = ver[0] if ver else '?'
        except Exception:
            vstr = str(ver)
        return jsonify({'message': 'Kết nối thành công', 'version': str(vstr)[:200]})
    except Exception as e:
        return jsonify({'error': f'Kết nối thất bại: {e}'}), 400


@app.route('/api/integrations/sql/sync', methods=['POST'])
@login_required
@admin_required
def api_ext_sql_sync():
    conn = get_db()
    cfg = _get_ext_sql_config(conn)
    if not cfg.get('host') or not cfg.get('dbname'):
        conn.close()
        return jsonify({'error': 'Chưa cấu hình SQL ngoài'}), 400
    prefix = ''.join(ch for ch in (cfg.get('table_prefix') or 'lamkhe_') if ch.isalnum() or ch == '_') or 'lamkhe_'
    cur = conn.cursor()
    try:
        tasks = [dict(r) for r in cur.execute("SELECT id, title, description, status, priority, due_date, max_assignees, points, scope, created_by FROM tasks WHERE deleted_at IS NULL").fetchall()]
        users = [dict(r) for r in cur.execute("SELECT id, username, role, score FROM users").fetchall()]
        points = [dict(r) for r in cur.execute("SELECT id, user_id, points, reason, task_id, created_by FROM points_log").fetchall()]
        fins = [dict(r) for r in cur.execute("SELECT id, type, amount, description, category, date, created_by FROM finance").fetchall()]
    except Exception as e:
        conn.close()
        return jsonify({'error': f'Lỗi đọc dữ liệu nguồn: {e}'}), 500
    conn.close()
    try:
        c2 = _ext_sql_connect(cfg)
        cur2 = c2.cursor()
        cur2.execute(f"CREATE TABLE IF NOT EXISTS {prefix}tasks (id INTEGER PRIMARY KEY, title TEXT, description TEXT, status TEXT, priority TEXT, due_date TEXT, max_assignees INTEGER, points INTEGER, scope TEXT, created_by INTEGER)")
        cur2.execute(f"CREATE TABLE IF NOT EXISTS {prefix}users (id INTEGER PRIMARY KEY, username TEXT, role TEXT, score INTEGER)")
        cur2.execute(f"CREATE TABLE IF NOT EXISTS {prefix}points_log (id INTEGER PRIMARY KEY, user_id INTEGER, points INTEGER, reason TEXT, task_id INTEGER, created_by INTEGER)")
        cur2.execute(f"CREATE TABLE IF NOT EXISTS {prefix}finance (id INTEGER PRIMARY KEY, type TEXT, amount REAL, description TEXT, category TEXT, date TEXT, created_by INTEGER)")
        for tbl, rows, cols in [
            (f"{prefix}tasks", tasks, ['id', 'title', 'description', 'status', 'priority', 'due_date', 'max_assignees', 'points', 'scope', 'created_by']),
            (f"{prefix}users", users, ['id', 'username', 'role', 'score']),
            (f"{prefix}points_log", points, ['id', 'user_id', 'points', 'reason', 'task_id', 'created_by']),
            (f"{prefix}finance", fins, ['id', 'type', 'amount', 'description', 'category', 'date', 'created_by']),
        ]:
            cur2.execute(f"DELETE FROM {tbl}")
            ph = ','.join(['%s'] * len(cols))
            for r in rows:
                cur2.execute(f"INSERT INTO {tbl} ({','.join(cols)}) VALUES ({ph})", tuple(r.get(c) for c in cols))
        c2.commit()
        c2.close()
    except Exception as e:
        return jsonify({'error': f'Đồng bộ thất bại: {e}'}), 500
    return jsonify({'message': f"Đã đồng bộ: {len(tasks)} tasks, {len(users)} users, {len(points)} điểm, {len(fins)} giao dịch"})


def _uploads_dir():
    path = os.path.join(BASE_DIR, 'uploads')
    os.makedirs(path, exist_ok=True)
    return os.path.realpath(path)


def _uploads_path(stored_name):
    """Duong dan file upload, dam bao luon nam trong thu muc uploads/."""
    base = os.path.realpath(_uploads_dir())
    candidate = os.path.realpath(os.path.join(base, stored_name))
    try:
        inside = os.path.commonpath([base, candidate]) == base
    except ValueError:
        inside = False
    if not inside or candidate == base:
        raise ValueError('invalid upload path')
    return candidate


def _read_upload(file):
    """Doc upload co gioi han, kiem tra extension + magic bytes, lam sach ten."""
    if file is None or not getattr(file, 'filename', ''):
        return None, 'Chưa chọn file'
    original = file.filename
    ext = original.rsplit('.', 1)[-1].lower() if '.' in original else ''
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return None, 'Chỉ hỗ trợ file .pdf, .doc, .docx'
    raw = file.stream.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        return None, 'File quá lớn (tối đa 20MB)'
    if not raw:
        return None, 'File rỗng'
    if not file_signature_ok(ext, raw[:16]):
        return None, 'Nội dung file không khớp định dạng .pdf/.doc/.docx'
    return {'ext': ext, 'raw': raw, 'size': len(raw), 'display': safe_filename(original)}, None


@app.route('/api/tasks/import', methods=['POST'])
@login_required
@admin_required
def api_import_tasks_file():
    upload, upload_error = _read_upload(request.files.get('file'))
    if upload_error:
        return jsonify({'error': upload_error}), 400

    scope = request.form.get('scope', 'lang') if request.form.get('scope') in ('lang', 'xa') else 'lang'
    priority = request.form.get('priority', 'medium') if request.form.get('priority') in ('low', 'medium', 'high', 'urgent') else 'medium'

    raw = upload['raw']
    file_size = upload['size']
    stored_name = f"{secrets.token_hex(4)}_{upload['display']}"
    file_path = _uploads_path(stored_name)
    with open(file_path, 'wb') as _f:
        _f.write(raw)

    title = os.path.splitext(upload['display'])[0].strip() or upload['display']
    if len(title) > 500:
        title = title[:500]

    conn = get_db()
    cur = conn.cursor()
    cur.execute(q(
        "INSERT INTO tasks (title, description, status, priority, max_assignees, scope, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        "INSERT INTO tasks (title, description, status, priority, max_assignees, scope, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)"),
        (title, '', 'pending', priority, 3, scope, session['user_id']))
    tid = cur.fetchone()['id'] if is_pg() else cur.lastrowid

    att_url = f"/api/tasks/{tid}/file/{stored_name}"
    _save_attachment(cur, tid, upload['display'], att_url, file_size, raw, session['user_id'])
    conn.commit()
    conn.close()

    return jsonify({'message': f'Đã tạo task "{title}" với file đính kèm', 'tasks': [{'id': tid, 'title': title}]}), 201


@app.route('/api/tasks/<int:task_id>/file', methods=['POST'])
@login_required
@admin_required
def api_upload_task_file(task_id):
    conn = get_db()
    cur = conn.cursor()
    task = cur.execute(q("SELECT id FROM tasks WHERE id = %s", "SELECT id FROM tasks WHERE id = ?"), (task_id,)).fetchone()
    if not task:
        conn.close()
        return jsonify({'error': 'Task không tồn tại'}), 404

    upload, upload_error = _read_upload(request.files.get('file'))
    if upload_error:
        conn.close()
        return jsonify({'error': upload_error}), 400

    raw = upload['raw']
    file_size = upload['size']
    stored_name = f"{secrets.token_hex(4)}_{upload['display']}"
    file_path = _uploads_path(stored_name)
    with open(file_path, 'wb') as _f:
        _f.write(raw)

    att_url = f"/api/tasks/{task_id}/file/{stored_name}"
    _save_attachment(cur, task_id, upload['display'], att_url, file_size, raw, session['user_id'])
    conn.commit()
    conn.close()
    return jsonify({'message': f'Đã đính kèm file "{upload["display"]}"', 'url': att_url}), 201


@app.route('/api/tasks/<int:task_id>/file/<path:filename>')
@login_required
def api_serve_file(task_id, filename):
    import os as _os
    uploads_dir = _os.path.join(_os.path.dirname(__file__), 'uploads')
    safe = _os.path.basename(filename)
    ext = safe.rsplit('.', 1)[-1].lower() if '.' in safe else ''
    mime_map = {'pdf': 'application/pdf', 'doc': 'application/msword', 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
    mime = mime_map.get(ext, 'application/octet-stream')
    # 1) Serve from DB bytes (survives redeploys wiping uploads/)
    try:
        conn = get_db()
        cur = conn.cursor()
        row = cur.execute(q("SELECT filename, file_data FROM attachments WHERE url = %s",
                            "SELECT filename, file_data FROM attachments WHERE url = ?"),
                          (f"/api/tasks/{task_id}/file/{safe}",)).fetchone()
        conn.close()
    except Exception:
        row = None
    blob = None
    if row:
        try:
            blob = bytes(row['file_data']) if row['file_data'] is not None else None
        except Exception:
            blob = None
    if blob:
        from urllib.parse import quote as _quote
        try:
            orig = row['filename'] or safe
        except Exception:
            orig = safe
        ascii_name = (safe.encode('ascii', 'ignore').decode('ascii').strip() or 'file').replace('"', '')
        disp = f'inline; filename="{ascii_name}"; filename*=UTF-8\'\'{_quote(orig)}'
        return Response(blob, mimetype=mime, headers={
            'Content-Disposition': disp,
            'Cache-Control': 'private, no-store',
            'Cross-Origin-Resource-Policy': 'same-origin',
        })
    # 2) Disk fallback (older uploads still on disk)
    try:
        file_path = _uploads_path(safe)
    except ValueError:
        return jsonify({'error': 'Tên file không hợp lệ'}), 400
    if not _os.path.isfile(file_path):
        return jsonify({'error': 'File không tồn tại'}), 404

    from flask import send_file
    resp = send_file(file_path, mimetype=mime, as_attachment=False, download_name=safe)
    resp.headers['Cache-Control'] = 'private, no-store'
    resp.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    return resp


@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
@login_required
@admin_required
def api_update_task(task_id):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    cur = conn.cursor()
    task = cur.execute(q("SELECT * FROM tasks WHERE id = %s", "SELECT * FROM tasks WHERE id = ?"), (task_id,)).fetchone()
    if not task:
        conn.close()
        return jsonify({'error': 'Task không tồn tại'}), 404

    t = dict(task)
    max_assignees = min(max(int(data.get('max_assignees', t['max_assignees']) or 3), 1), 10)
    points = int(data.get('points', t['points'] or 0) or 0)
    due_date = data.get('due_date') or None
    try:
        est = float(data.get('estimate_hours', t.get('estimate_hours', 0) or 0) or 0)
    except Exception:
        est = 0

    assigned_ids = data.get('assigned_to', [])
    if not isinstance(assigned_ids, list):
        assigned_ids = [assigned_ids] if assigned_ids else []
    assigned_ids = [int(x) for x in assigned_ids if x]
    if len(assigned_ids) > max_assignees:
        conn.close()
        return jsonify({'error': f'Tối đa giao cho {max_assignees} người'}), 400

    cur.execute(q(
        "UPDATE tasks SET title=%s, description=%s, status=%s, priority=%s, due_date=%s, max_assignees=%s, points=%s, estimate_hours=%s, skills=%s, scope=%s WHERE id=%s",
        "UPDATE tasks SET title=?, description=?, status=?, priority=?, due_date=?, max_assignees=?, points=?, estimate_hours=?, skills=?, scope=? WHERE id=?"),
        (data.get('title', t['title']), data.get('description', t['description']) or '',
         data.get('status', t['status']), data.get('priority', t['priority']),
         due_date, max_assignees, points, est, data.get('skills', t.get('skills', '') or ''),
         data.get('scope', t.get('scope', 'lang') or 'lang') if (data.get('scope', t.get('scope', 'lang') or 'lang')) in ('lang', 'xa') else 'lang', task_id))

    prev_rows = cur.execute(q("SELECT user_id FROM task_assignments WHERE task_id = %s",
                              "SELECT user_id FROM task_assignments WHERE task_id = ?"), (task_id,)).fetchall()
    prev_ids = set(dict(r)['user_id'] for r in prev_rows)
    cur.execute(q("DELETE FROM task_assignments WHERE task_id = %s", "DELETE FROM task_assignments WHERE task_id = ?"), (task_id,))
    for uid in assigned_ids:
        cur.execute(q("INSERT INTO task_assignments (task_id, user_id) VALUES (%s, %s)",
                      "INSERT INTO task_assignments (task_id, user_id) VALUES (?, ?)"), (task_id, uid))
    new_title = data.get('title', t['title'])
    new_ids = [uid for uid in assigned_ids if uid not in prev_ids and uid != session['user_id']]
    for uid in new_ids:
        _notify_user(conn, uid, 'assign', f"Bạn được giao việc: {new_title}", f"#{task_id}", '')
    if new_ids:
        _push_assignment_chat(conn, task_id, new_title, new_ids, session['user_id'])

    if 'depends_on' in data:
        cur.execute(q("DELETE FROM task_dependencies WHERE task_id = %s", "DELETE FROM task_dependencies WHERE task_id = ?"), (task_id,))
        for dep in (data.get('depends_on') or []):
            try:
                if int(dep) == task_id:
                    continue
                cur.execute(q("INSERT INTO task_dependencies (task_id, depends_on_id) VALUES (%s, %s)",
                              "INSERT INTO task_dependencies (task_id, depends_on_id) VALUES (?, ?)"),
                            (task_id, int(dep)))
            except Exception:
                pass

    conn.commit()
    updated = cur.execute(q("SELECT * FROM tasks WHERE id = %s", "SELECT * FROM tasks WHERE id = ?"), (task_id,)).fetchone()
    result = serialize_task(conn, updated, session['user_id'])
    conn.close()
    return jsonify(result)


@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_task(task_id):
    conn = get_db()
    cur = conn.cursor()
    task = cur.execute(q("SELECT * FROM tasks WHERE id = %s", "SELECT * FROM tasks WHERE id = ?"), (task_id,)).fetchone()
    if not task:
        conn.close()
        return jsonify({'error': 'Task không tồn tại'}), 404
    cur.execute(q("UPDATE tasks SET deleted_at = NOW() WHERE id = %s",
                  "UPDATE tasks SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?"), (task_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã chuyển vào thùng rác'})


# ==================== AI & SMART ASSIGN ====================

def ai_split_goal(goal):
    goal = (goal or '').strip()
    if not goal:
        return []
    parts = [p.strip(' -•\t') for p in goal.replace(';', '\n').replace('。', '\n').split('\n')]
    parts = [p for p in parts if len(p) > 2]
    if len(parts) >= 2:
        return [{'title': p[:120]} for p in parts[:10]]
    words = goal.split()
    out = []
    verbs = ['Chuẩn bị', 'Lên kế hoạch', 'Triển khai', 'Kiểm tra', 'Tổng hợp báo cáo']
    base = ' '.join(words[:12])
    for i, v in enumerate(verbs):
        out.append({'title': f"{v}: {base[:80]}"})
        if i >= 3:
            break
    return out


@app.route('/api/ai/suggest', methods=['POST'])
@login_required
def api_ai_suggest():
    data = request.get_json() or {}
    goal = data.get('goal', '') or data.get('title', '')
    return jsonify({'suggestions': ai_split_goal(goal)})


@app.route('/api/smart-assign')
@login_required
def api_smart_assign():
    need_skills = (request.args.get('skills') or '').lower()
    conn = get_db()
    cur = conn.cursor()
    users = cur.execute(q("SELECT id, username, score, skills FROM users WHERE role = 'user'",
                          "SELECT id, username, score, skills FROM users WHERE role = 'user'")).fetchall()
    scored = []
    for u in users:
        uu = dict(u)
        act = cur.execute(q("SELECT COUNT(*) AS c FROM task_assignments ta JOIN tasks t ON ta.task_id = t.id WHERE ta.user_id = %s AND t.status != 'done' AND t.deleted_at IS NULL",
                            "SELECT COUNT(*) AS c FROM task_assignments ta JOIN tasks t ON ta.task_id = t.id WHERE ta.user_id = ? AND t.status != 'done' AND t.deleted_at IS NULL"),
                          (uu['id'],)).fetchone()
        workload = dict(act)['c'] if act else 0
        skill_hit = 0
        if need_skills:
            usk = (uu.get('skills') or '').lower()
            skill_hit = sum(1 for w in need_skills.replace(',', ' ').split() if w and w in usk)
        done_n = cur.execute(q("SELECT COUNT(*) AS c FROM points_log WHERE user_id = %s", "SELECT COUNT(*) AS c FROM points_log WHERE user_id = ?"),
                             (uu['id'],)).fetchone()
        done_n = dict(done_n)['c'] if done_n else 0
        score = skill_hit * 10 - workload * 3 + min(done_n, 10) * 0.2
        scored.append({'id': uu['id'], 'username': uu['username'], 'workload': workload,
                       'skill_match': skill_hit, 'score': round(score, 1)})
    scored.sort(key=lambda x: -x['score'])
    conn.close()
    return jsonify(scored[:5])


# ==================== SUBTASKS / DEPENDENCIES / COMMENTS / TIME ====================

@app.route('/api/tasks/<int:task_id>/subtasks', methods=['GET', 'POST'])
@login_required
def api_subtasks(task_id):
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'GET':
        rows = cur.execute(q("SELECT * FROM subtasks WHERE task_id = %s ORDER BY id",
                             "SELECT * FROM subtasks WHERE task_id = ? ORDER BY id"), (task_id,)).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    if not title:
        conn.close()
        return jsonify({'error': 'Thiếu tiêu đề'}), 400
    cur.execute(q("INSERT INTO subtasks (task_id, title, created_by) VALUES (%s, %s, %s)",
                  "INSERT INTO subtasks (task_id, title, created_by) VALUES (?, ?, ?)"),
                (task_id, title, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã thêm subtask'}), 201


@app.route('/api/subtasks/<int:sid>', methods=['PUT', 'DELETE'])
@login_required
def api_subtask_one(sid):
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'DELETE':
        cur.execute(q("DELETE FROM subtasks WHERE id = %s", "DELETE FROM subtasks WHERE id = ?"), (sid,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Đã xóa'})
    data = request.get_json() or {}
    if 'done' in data:
        cur.execute(q("UPDATE subtasks SET done = %s WHERE id = %s", "UPDATE subtasks SET done = ? WHERE id = ?"),
                    (1 if data['done'] else 0, sid))
    if 'title' in data and data['title']:
        cur.execute(q("UPDATE subtasks SET title = %s WHERE id = %s", "UPDATE subtasks SET title = ? WHERE id = ?"),
                    (data['title'], sid))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã cập nhật'})


@app.route('/api/tasks/<int:task_id>/dependencies', methods=['GET', 'POST', 'DELETE'])
@login_required
def api_dependencies(task_id):
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'GET':
        rows = cur.execute(q("SELECT d.depends_on_id AS id, t.title, t.status FROM task_dependencies d JOIN tasks t ON t.id = d.depends_on_id WHERE d.task_id = %s",
                             "SELECT d.depends_on_id AS id, t.title, t.status FROM task_dependencies d JOIN tasks t ON t.id = d.depends_on_id WHERE d.task_id = ?"),
                           (task_id,)).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    data = request.get_json() or {}
    dep = int(data.get('depends_on_id', 0) or 0)
    if request.method == 'DELETE':
        cur.execute(q("DELETE FROM task_dependencies WHERE task_id = %s AND depends_on_id = %s",
                      "DELETE FROM task_dependencies WHERE task_id = ? AND depends_on_id = ?"), (task_id, dep))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Đã gỡ phụ thuộc'})
    if not dep or dep == task_id:
        conn.close()
        return jsonify({'error': 'Phụ thuộc không hợp lệ'}), 400
    try:
        cur.execute(q("INSERT INTO task_dependencies (task_id, depends_on_id) VALUES (%s, %s)",
                      "INSERT INTO task_dependencies (task_id, depends_on_id) VALUES (?, ?)"), (task_id, dep))
        conn.commit()
    except Exception:
        pass
    conn.close()
    return jsonify({'message': 'Đã thêm phụ thuộc'}), 201


@app.route('/api/tasks/<int:task_id>/comments', methods=['GET', 'POST'])
@login_required
def api_comments(task_id):
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'GET':
        rows = cur.execute(q("SELECT c.*, u.username FROM comments c LEFT JOIN users u ON c.user_id = u.id WHERE c.task_id = %s ORDER BY c.created_at",
                             "SELECT c.*, u.username FROM comments c LEFT JOIN users u ON c.user_id = u.id WHERE c.task_id = ? ORDER BY c.created_at"),
                           (task_id,)).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    data = request.get_json() or {}
    text = (data.get('text') or '').strip()
    if not text:
        conn.close()
        return jsonify({'error': 'Thiếu nội dung'}), 400
    cur.execute(q("INSERT INTO comments (task_id, user_id, text) VALUES (%s, %s, %s)",
                  "INSERT INTO comments (task_id, user_id, text) VALUES (?, ?, ?)"),
                (task_id, session['user_id'], text[:2000]))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã bình luận'}), 201


@app.route('/api/tasks/<int:task_id>/time', methods=['POST'])
@login_required
def api_time_log(task_id):
    data = request.get_json() or {}
    try:
        secs = max(0, int(data.get('seconds', 0) or 0))
    except Exception:
        secs = 0
    if secs <= 0 or secs > 86400:
        return jsonify({'error': 'Số giây không hợp lệ (0-86400)'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q("INSERT INTO time_logs (task_id, user_id, seconds, note) VALUES (%s, %s, %s, %s)",
                  "INSERT INTO time_logs (task_id, user_id, seconds, note) VALUES (?, ?, ?, ?)"),
                (task_id, session['user_id'], secs, (data.get('note') or 'timer')[:50]))
    cur.execute(q("UPDATE tasks SET actual_seconds = COALESCE(actual_seconds,0) + %s WHERE id = %s",
                  "UPDATE tasks SET actual_seconds = COALESCE(actual_seconds,0) + ? WHERE id = ?"), (secs, task_id))
    conn.commit()
    conn.close()
    return jsonify({'message': f'Đã ghi {secs}s'}), 201


@app.route('/api/tasks/bulk', methods=['POST'])
@login_required
def api_tasks_bulk():
    data = request.get_json() or {}
    ids = [int(x) for x in (data.get('ids') or []) if str(x).isdigit()]
    if not ids:
        return jsonify({'error': 'Chưa chọn task'}), 400
    ph = ','.join(['%s'] * len(ids)) if is_pg() else ','.join(['?'] * len(ids))
    conn = get_db()
    cur = conn.cursor()
    if not is_admin():
        rows = cur.execute(f"SELECT task_id FROM task_assignments WHERE user_id = %s AND task_id IN ({ph})" if is_pg()
                           else f"SELECT task_id FROM task_assignments WHERE user_id = ? AND task_id IN ({ph})",
                           ([session['user_id']] + ids)).fetchall()
        ids = [dict(r)['task_id'] for r in rows]
        if not ids:
            conn.close()
            return jsonify({'error': 'Không có quyền'}), 403
        ph = ','.join(['%s'] * len(ids)) if is_pg() else ','.join(['?'] * len(ids))
    if data.get('status') in ('pending', 'in_progress', 'done'):
        cur.execute(f"UPDATE tasks SET status = %s WHERE id IN ({ph})" if is_pg()
                    else f"UPDATE tasks SET status = ? WHERE id IN ({ph})",
                    ([data['status']] + ids))
    if data.get('assign_to') is not None and is_admin():
        try:
            uid = int(data['assign_to'])
            for tid in ids:
                try:
                    cur.execute(q("INSERT INTO task_assignments (task_id, user_id) VALUES (%s, %s)",
                                  "INSERT INTO task_assignments (task_id, user_id) VALUES (?, ?)"), (tid, uid))
                except Exception:
                    pass
        except Exception:
            pass
    if data.get('claim_me'):
        for tid in ids:
            try:
                cur.execute(q("INSERT INTO task_assignments (task_id, user_id) VALUES (%s, %s)",
                              "INSERT INTO task_assignments (task_id, user_id) VALUES (?, ?)"), (tid, session['user_id']))
            except Exception:
                pass
    if data.get('delete') and is_admin():
        cur.execute(f"UPDATE tasks SET deleted_at = NOW() WHERE id IN ({ph})" if is_pg()
                    else f"UPDATE tasks SET deleted_at = CURRENT_TIMESTAMP WHERE id IN ({ph})", ids)
        conn.commit()
        conn.close()
        return jsonify({'message': f'Đã chuyển {len(ids)} task vào thùng rác'})
    conn.commit()
    conn.close()
    return jsonify({'message': f'Đã cập nhật {len(ids)} task'})


@app.route('/api/tasks', methods=['DELETE'])
@login_required
@admin_required
def api_delete_all_tasks():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q("UPDATE tasks SET deleted_at = NOW() WHERE deleted_at IS NULL",
                  "UPDATE tasks SET deleted_at = CURRENT_TIMESTAMP WHERE deleted_at IS NULL"))
    count = cur.rowcount
    conn.commit()
    conn.close()
    return jsonify({'message': f'Đã chuyển {count} task vào thùng rác'})


# ==================== WORKLOAD / GAMIFICATION ====================

@app.route('/api/workload')
@login_required
def api_workload():
    conn = get_db()
    cur = conn.cursor()
    users = cur.execute(q("SELECT id, username, full_name FROM users WHERE role = 'user'",
                          "SELECT id, username, full_name FROM users WHERE role = 'user'")).fetchall()
    out = []
    for u in users:
        uu = dict(u)
        act = cur.execute(q("SELECT COUNT(*) AS c FROM task_assignments ta JOIN tasks t ON ta.task_id = t.id WHERE ta.user_id = %s AND t.status != 'done' AND t.deleted_at IS NULL",
                            "SELECT COUNT(*) AS c FROM task_assignments ta JOIN tasks t ON ta.task_id = t.id WHERE ta.user_id = ? AND t.status != 'done' AND t.deleted_at IS NULL"),
                          (uu['id'],)).fetchone()
        over = cur.execute(q("SELECT COUNT(*) AS c FROM task_assignments ta JOIN tasks t ON ta.task_id = t.id WHERE ta.user_id = %s AND t.status != 'done' AND t.deleted_at IS NULL AND t.due_date IS NOT NULL AND t.due_date < CURRENT_DATE",
                             "SELECT COUNT(*) AS c FROM task_assignments ta JOIN tasks t ON ta.task_id = t.id WHERE ta.user_id = ? AND t.status != 'done' AND t.deleted_at IS NULL AND t.due_date IS NOT NULL AND date(t.due_date) < date('now')"),
                           (uu['id'],)).fetchone()
        done = cur.execute(q("SELECT COUNT(*) AS c FROM points_log WHERE user_id = %s", "SELECT COUNT(*) AS c FROM points_log WHERE user_id = ?"),
                           (uu['id'],)).fetchone()
        out.append({'id': uu['id'], 'username': uu['username'], 'full_name': uu.get('full_name') or '',
                    'active': dict(act)['c'] if act else 0, 'overdue': dict(over)['c'] if over else 0,
                    'done': dict(done)['c'] if done else 0})
    conn.close()
    return jsonify(out)


@app.route('/api/gamification')
@login_required
def api_gamification():
    conn = get_db()
    cur = conn.cursor()
    uid = session['user_id']
    rows = cur.execute(q("SELECT DATE(created_at) AS d FROM points_log WHERE user_id = %s AND points > 0 ORDER BY created_at DESC LIMIT 60",
                         "SELECT date(created_at) AS d FROM points_log WHERE user_id = ? AND points > 0 ORDER BY created_at DESC LIMIT 60"),
                       (uid,)).fetchall()
    days = []
    for r in rows:
        d = dict(r)['d']
        if d and (not days or days[-1] != str(d)):
            days.append(str(d))
    streak = 0
    try:
        from datetime import date, timedelta
        today = date.today()
        s = set(days)
        cursor = today if str(today) in s else today - timedelta(days=1)
        while str(cursor) in s:
            streak += 1
            cursor -= timedelta(days=1)
    except Exception:
        pass
    done_n = cur.execute(q("SELECT COUNT(*) AS c FROM points_log WHERE user_id = %s AND points > 0",
                           "SELECT COUNT(*) AS c FROM points_log WHERE user_id = ? AND points > 0"), (uid,)).fetchone()
    done_n = dict(done_n)['c'] if done_n else 0
    badges = []
    if done_n >= 1:
        badges.append({'icon': '🌱', 'name': 'Khởi đầu'})
    if done_n >= 5:
        badges.append({'icon': '🔥', 'name': 'Năng nổ (5 task)'})
    if done_n >= 20:
        badges.append({'icon': '⭐', 'name': 'Ngôi sao (20 task)'})
    if streak >= 3:
        badges.append({'icon': '📆', 'name': f'Streak {streak} ngày'})
    if streak >= 7:
        badges.append({'icon': '🏆', 'name': 'Bền bỉ 7 ngày'})
    conn.close()
    return jsonify({'streak': streak, 'done': done_n, 'badges': badges})


# ==================== GUEST SHARE ====================

@app.route('/api/share', methods=['GET', 'POST'])
@login_required
@admin_required
def api_share():
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'GET':
        rows = cur.execute("SELECT * FROM shares ORDER BY id DESC").fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    data = request.get_json() or {}
    token = secrets.token_urlsafe(10)
    cur.execute(q("INSERT INTO shares (token, mode, created_by) VALUES (%s, %s, %s)",
                  "INSERT INTO shares (token, mode, created_by) VALUES (?, ?, ?)"),
                (token, data.get('mode', 'view'), session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'token': token, 'url': f'/share/{token}'}), 201


@app.route('/api/share/<token>', methods=['DELETE'])
@login_required
@admin_required
def api_share_delete(token):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q("DELETE FROM shares WHERE token = %s", "DELETE FROM shares WHERE token = ?"), (token,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã xóa link'})


@app.route('/share/<token>')
def share_page(token):
    conn = get_db()
    cur = conn.cursor()
    sh = cur.execute(q("SELECT * FROM shares WHERE token = %s", "SELECT * FROM shares WHERE token = ?"),
                     (token,)).fetchone()
    if not sh:
        conn.close()
        return render_template('share_gone.html'), 404
    tasks = cur.execute("SELECT id, title, description, status, priority, due_date FROM tasks WHERE deleted_at IS NULL ORDER BY created_at DESC").fetchall()
    conn.close()
    mode = dict(sh).get('mode', 'view')
    resp = Response(render_template('share.html', tasks=[dict(t) for t in tasks], mode=mode))
    resp.headers['Cache-Control'] = 'private, no-store'
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return resp


@app.route('/api/tasks/<int:task_id>/attachments', methods=['GET', 'POST'])
@login_required
def api_attachments(task_id):
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'GET':
        try:
            rows = cur.execute(q("SELECT id, task_id, filename, url, note, size, created_by FROM attachments WHERE task_id = %s ORDER BY id",
                                 "SELECT id, task_id, filename, url, note, size, created_by FROM attachments WHERE task_id = ? ORDER BY id"), (task_id,)).fetchall()
            conn.close()
            return jsonify([dict(r) for r in rows])
        except Exception:
            conn.close()
            return jsonify([])
    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    note = (data.get('note') or '')[:500]
    name = (data.get('filename') or url or 'link')[:200]
    if not url:
        conn.close()
        return jsonify({'error': 'Thiếu link'}), 400
    if not is_safe_link_url(url):
        conn.close()
        return jsonify({'error': 'Link phải là http(s) hoặc đường dẫn nội bộ'}), 400
    cur.execute(q("INSERT INTO attachments (task_id, filename, url, note, size, created_by) VALUES (%s, %s, %s, %s, %s, %s)",
                  "INSERT INTO attachments (task_id, filename, url, note, size, created_by) VALUES (?, ?, ?, ?, ?, ?)"),
                (task_id, name, url, note, 0, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã đính kèm'}), 201


# ==================== CLAIM / UNCLAIM ====================

@app.route('/api/tasks/<int:task_id>/claim', methods=['POST'])
@login_required
def api_claim_task(task_id):
    conn = get_db()
    cur = conn.cursor()
    task = _lock_task(conn, task_id)
    if not task:
        conn.close()
        return jsonify({'error': 'Task không tồn tại'}), 404
    if task['status'] == 'done':
        conn.close()
        return jsonify({'error': 'Task đã hoàn thành'}), 400

    already = cur.execute(q("SELECT 1 FROM task_assignments WHERE task_id = %s AND user_id = %s",
                            "SELECT 1 FROM task_assignments WHERE task_id = ? AND user_id = ?"),
                          (task_id, session['user_id'])).fetchone()
    if already:
        conn.close()
        return jsonify({'error': 'Bạn đã nhận task này rồi'}), 400

    count = cur.execute(q("SELECT COUNT(*) as c FROM task_assignments WHERE task_id = %s",
                          "SELECT COUNT(*) as c FROM task_assignments WHERE task_id = ?"),
                        (task_id,)).fetchone()['c']

    max_a = task['max_assignees'] or 3
    if count >= max_a:
        conn.close()
        return jsonify({'error': 'Task đã đủ người nhận'}), 400

    cur.execute(q("INSERT INTO task_assignments (task_id, user_id) VALUES (%s, %s)",
                  "INSERT INTO task_assignments (task_id, user_id) VALUES (?, ?)"), (task_id, session['user_id']))

    if task['status'] == 'pending':
        cur.execute(q("UPDATE tasks SET status = 'in_progress' WHERE id = %s",
                      "UPDATE tasks SET status = 'in_progress' WHERE id = ?"), (task_id,))

    creator = task['created_by']
    if creator and creator != session['user_id']:
        claimer = session.get('username') or 'Đoàn viên'
        _notify_user(conn, creator, 'claim', f"{claimer} đã nhận task: {task['title']}", f"#{task_id}", '')

    conn.commit()
    updated = cur.execute(q("SELECT * FROM tasks WHERE id = %s", "SELECT * FROM tasks WHERE id = ?"), (task_id,)).fetchone()
    result = serialize_task(conn, updated, session['user_id'])
    conn.close()
    return jsonify(result)


@app.route('/api/tasks/<int:task_id>/claim', methods=['DELETE'])
@login_required
def api_unclaim_task(task_id):
    conn = get_db()
    cur = conn.cursor()
    task = cur.execute(q("SELECT * FROM tasks WHERE id = %s", "SELECT * FROM tasks WHERE id = ?"), (task_id,)).fetchone()
    if not task:
        conn.close()
        return jsonify({'error': 'Task không tồn tại'}), 404

    if not is_admin():
        own = cur.execute(q("SELECT 1 FROM task_assignments WHERE task_id = %s AND user_id = %s",
                            "SELECT 1 FROM task_assignments WHERE task_id = ? AND user_id = ?"),
                          (task_id, session['user_id'])).fetchone()
        if not own:
            conn.close()
            return jsonify({'error': 'Bạn chưa nhận task này'}), 400

    target_user = session['user_id']
    if is_admin() and request.is_json:
        target_user = (request.get_json(silent=True) or {}).get('user_id', session['user_id'])

    cur.execute(q("DELETE FROM task_assignments WHERE task_id = %s AND user_id = %s",
                  "DELETE FROM task_assignments WHERE task_id = ? AND user_id = ?"), (task_id, target_user))
    remaining = cur.execute(q("SELECT COUNT(*) as c FROM task_assignments WHERE task_id = %s",
                              "SELECT COUNT(*) as c FROM task_assignments WHERE task_id = ?"),
                            (task_id,)).fetchone()['c']
    if remaining == 0 and task['status'] == 'in_progress':
        cur.execute(q("UPDATE tasks SET status = 'pending' WHERE id = %s",
                      "UPDATE tasks SET status = 'pending' WHERE id = ?"), (task_id,))
    conn.commit()
    updated = cur.execute(q("SELECT * FROM tasks WHERE id = %s", "SELECT * FROM tasks WHERE id = ?"), (task_id,)).fetchone()
    result = serialize_task(conn, updated, session['user_id'])
    conn.close()
    return jsonify(result)


# ==================== STATUS ====================

@app.route('/api/tasks/<int:task_id>/status', methods=['PUT'])
@login_required
def api_update_status(task_id):
    data = request.get_json(silent=True) or {}
    new_status = data.get('status')
    if new_status not in ('pending', 'in_progress', 'done'):
        return jsonify({'error': 'Trạng thái không hợp lệ'}), 400

    conn = get_db()
    cur = conn.cursor()
    task = _lock_task(conn, task_id)
    if not task:
        conn.close()
        return jsonify({'error': 'Task không tồn tại'}), 404

    if not is_admin():
        assigned = cur.execute(q("SELECT 1 FROM task_assignments WHERE task_id = %s AND user_id = %s",
                                "SELECT 1 FROM task_assignments WHERE task_id = ? AND user_id = ?"),
                              (task_id, session['user_id'])).fetchone()
        if not assigned:
            conn.close()
            return jsonify({'error': 'Không có quyền cập nhật task này'}), 403

    old_status = task['status']
    if new_status == 'done' and old_status != 'done':
        try:
            deps = cur.execute(q("SELECT depends_on_id FROM task_dependencies WHERE task_id = %s",
                                 "SELECT depends_on_id FROM task_dependencies WHERE task_id = ?"),
                               (task_id,)).fetchall()
            dep_ids = [dict(x)['depends_on_id'] for x in deps]
            if dep_ids:
                ph = ','.join(['%s'] * len(dep_ids)) if is_pg() else ','.join(['?'] * len(dep_ids))
                open_deps = cur.execute(f"SELECT COUNT(*) AS c FROM tasks WHERE id IN ({ph}) AND status != 'done'",
                                        dep_ids).fetchone()
                if open_deps and dict(open_deps)['c'] > 0:
                    conn.close()
                    return jsonify({'error': f"Task phụ thuộc chưa xong ({dict(open_deps)['c']} task)"}), 400
        except Exception as e:
            if 'Task phụ thuộc' in str(e):
                raise e
    cur.execute(q("UPDATE tasks SET status = %s WHERE id = %s", "UPDATE tasks SET status = ? WHERE id = ?"), (new_status, task_id))

    if new_status == 'done' and old_status != 'done' and task['points'] and task['points'] > 0:
        assignees = cur.execute(q("SELECT user_id FROM task_assignments WHERE task_id = %s",
                                  "SELECT user_id FROM task_assignments WHERE task_id = ?"), (task_id,)).fetchall()
        num_assignees = len(assignees)
        if num_assignees > 0:
            total_points = task['points']
            points_per_person = total_points // num_assignees
            remainder = total_points - (points_per_person * num_assignees)

            for i, a in enumerate(assignees):
                uid = a['user_id']
                earned = points_per_person + (1 if i < remainder else 0)
                cur.execute(q("UPDATE users SET score = score + %s WHERE id = %s",
                              "UPDATE users SET score = score + ? WHERE id = ?"), (earned, uid))
                cur.execute(q("INSERT INTO points_log (user_id, points, reason, task_id, created_by) VALUES (%s, %s, %s, %s, %s)",
                              "INSERT INTO points_log (user_id, points, reason, task_id, created_by) VALUES (?, ?, ?, ?, ?)"),
                            (uid, earned, f"Hoàn thành task: {task['title']} (chia đều từ {total_points} điểm cho {num_assignees} người)", task_id, session['user_id']))

        fund = get_fund(conn)
        cur.execute(q("UPDATE fund SET balance = balance + %s, updated_at = NOW() WHERE id = %s",
                      "UPDATE fund SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"),
                    (task['points'], fund['id']))
        cur.execute(q("INSERT INTO finance (type, amount, description, category, created_by) VALUES (%s, %s, %s, %s, %s)",
                      "INSERT INTO finance (type, amount, description, category, created_by) VALUES (?, ?, ?, ?, ?)"),
                    ('income', task['points'], f"Thu từ task: {task['title']}", 'Task', session['user_id']))

    if new_status == 'done' and old_status != 'done':
        try:
            me = cur.execute(q("SELECT auto_done_unfollow FROM users WHERE id = %s",
                               "SELECT auto_done_unfollow FROM users WHERE id = ?"),
                             (session['user_id'],)).fetchone()
            if me and dict(me).get('auto_done_unfollow'):
                cur.execute(q("DELETE FROM task_assignments WHERE task_id = %s AND user_id = %s",
                              "DELETE FROM task_assignments WHERE task_id = ? AND user_id = ?"),
                            (task_id, session['user_id']))
        except Exception:
            pass
        run_automation(conn, f"status:{new_status}", dict(task))
    elif new_status != old_status:
        run_automation(conn, f"status:{new_status}", dict(task))

    conn.commit()
    updated = cur.execute(q("SELECT * FROM tasks WHERE id = %s", "SELECT * FROM tasks WHERE id = ?"), (task_id,)).fetchone()
    result = serialize_task(conn, updated, session['user_id'])
    conn.close()
    return jsonify(result)


# ==================== POINTS API ====================

@app.route('/api/points')
@login_required
@admin_required
def api_points_list():
    conn = get_db()
    cur = conn.cursor()
    users = cur.execute(q("SELECT id, username, score, role FROM users ORDER BY score DESC",
                          "SELECT id, username, score, role FROM users ORDER BY score DESC")).fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])


@app.route('/api/points/<int:user_id>')
@login_required
def api_points_detail(user_id):
    if not is_admin() and session['user_id'] != user_id:
        return jsonify({'error': 'Không có quyền'}), 403
    conn = get_db()
    cur = conn.cursor()
    user = cur.execute(q("SELECT id, username, score FROM users WHERE id = %s",
                        "SELECT id, username, score FROM users WHERE id = ?"), (user_id,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'User không tồn tại'}), 404
    logs = cur.execute(q(
        "SELECT pl.*, u.username as given_by_name FROM points_log pl LEFT JOIN users u ON pl.created_by = u.id WHERE pl.user_id = %s ORDER BY pl.created_at DESC",
        "SELECT pl.*, u.username as given_by_name FROM points_log pl LEFT JOIN users u ON pl.created_by = u.id WHERE pl.user_id = ? ORDER BY pl.created_at DESC"),
        (user_id,)).fetchall()
    conn.close()
    return jsonify({'user': dict(user), 'logs': [dict(l) for l in logs]})


@app.route('/api/points', methods=['POST'])
@login_required
@admin_required
def api_add_points():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    points = data.get('points', 0)
    reason = data.get('reason', '').strip()
    try:
        points = int(points)
    except (ValueError, TypeError):
        return jsonify({'error': 'Điểm không hợp lệ'}), 400
    if not user_id or not reason:
        return jsonify({'error': 'Thiếu thông tin'}), 400
    conn = get_db()
    cur = conn.cursor()
    user = cur.execute(q("SELECT id FROM users WHERE id = %s", "SELECT id FROM users WHERE id = ?"), (user_id,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'User không tồn tại'}), 404
    cur.execute(q("UPDATE users SET score = score + %s WHERE id = %s", "UPDATE users SET score = score + ? WHERE id = ?"), (points, user_id))
    cur.execute(q("INSERT INTO points_log (user_id, points, reason, created_by) VALUES (%s, %s, %s, %s)",
                  "INSERT INTO points_log (user_id, points, reason, created_by) VALUES (?, ?, ?, ?)"),
                (user_id, points, reason, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã cập nhật điểm'})


# ==================== FUND API ====================

def get_fund(conn):
    cur = conn.cursor()
    fund = cur.execute("SELECT * FROM fund LIMIT 1").fetchone()
    if not fund:
        cur.execute(q("INSERT INTO fund (name, balance) VALUES ('Quỹ chung', 0) RETURNING *",
                      "INSERT INTO fund (name, balance) VALUES ('Quỹ chung', 0)"))
        conn.commit()
        fund = cur.execute("SELECT * FROM fund LIMIT 1").fetchone()
    return dict(fund)


@app.route('/api/fund')
@login_required
@admin_required
def api_fund_get():
    conn = get_db()
    fund = get_fund(conn)
    conn.close()
    return jsonify(fund)


@app.route('/api/fund', methods=['PUT'])
@login_required
@admin_required
def api_fund_update():
    data = request.get_json(silent=True) or {}
    amount = data.get('amount', 0)
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return jsonify({'error': 'Số tiền không hợp lệ'}), 400
    if not math.isfinite(amount):
        return jsonify({'error': 'Số tiền không hợp lệ'}), 400
    conn = get_db()
    cur = conn.cursor()
    fund = get_fund(conn)
    new_balance = fund['balance'] + amount
    if new_balance < 0:
        conn.close()
        return jsonify({'error': 'Số dư quỹ không đủ'}), 400
    cur.execute(q("UPDATE fund SET balance = %s, updated_at = NOW() WHERE id = %s",
                  "UPDATE fund SET balance = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"), (new_balance, fund['id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã cập nhật quỹ', 'balance': new_balance})


@app.route('/api/fund/set', methods=['PUT'])
@login_required
@admin_required
def api_fund_set():
    data = request.get_json(silent=True) or {}
    amount = data.get('amount', 0)
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return jsonify({'error': 'Số tiền không hợp lệ'}), 400
    if not math.isfinite(amount) or amount < 0:
        return jsonify({'error': 'Số tiền phải >= 0'}), 400
    conn = get_db()
    cur = conn.cursor()
    fund = get_fund(conn)
    cur.execute(q("UPDATE fund SET balance = %s, updated_at = NOW() WHERE id = %s",
                  "UPDATE fund SET balance = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"), (amount, fund['id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã cập nhật quỹ', 'balance': amount})


# ==================== FINANCE API ====================

@app.route('/api/finance')
@login_required
@admin_required
def api_finance_list():
    conn = get_db()
    cur = conn.cursor()
    transactions = cur.execute(q(
        "SELECT f.*, u.username as created_by_name FROM finance f LEFT JOIN users u ON f.created_by = u.id ORDER BY f.date DESC",
        "SELECT f.*, u.username as created_by_name FROM finance f LEFT JOIN users u ON f.created_by = u.id ORDER BY f.date DESC")).fetchall()
    conn.close()
    return jsonify([dict(t) for t in transactions])


@app.route('/api/finance/summary')
@login_required
@admin_required
def api_finance_summary():
    conn = get_db()
    cur = conn.cursor()
    income = cur.execute(q("SELECT COALESCE(SUM(amount), 0) as total FROM finance WHERE type = 'income'",
                           "SELECT COALESCE(SUM(amount), 0) as total FROM finance WHERE type = 'income'")).fetchone()['total']
    expense = cur.execute(q("SELECT COALESCE(SUM(amount), 0) as total FROM finance WHERE type = 'expense'",
                            "SELECT COALESCE(SUM(amount), 0) as total FROM finance WHERE type = 'expense'")).fetchone()['total']
    fund = get_fund(conn)
    conn.close()
    return jsonify({'income': income, 'expense': expense, 'balance': income - expense, 'fund': fund['balance']})


@app.route('/api/finance', methods=['POST'])
@login_required
@admin_required
def api_finance_create():
    data = request.get_json(silent=True) or {}
    trans_type = data.get('type')
    amount = data.get('amount', 0)
    description = data.get('description', '').strip()
    category = data.get('category', '').strip()

    if trans_type not in ('income', 'expense'):
        return jsonify({'error': 'Loại giao dịch không hợp lệ'}), 400
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return jsonify({'error': 'Số tiền không hợp lệ'}), 400
    if not math.isfinite(amount) or amount <= 0:
        return jsonify({'error': 'Số tiền phải lớn hơn 0'}), 400

    conn = get_db()
    cur = conn.cursor()

    if trans_type == 'expense':
        fund = get_fund(conn)
        cur.execute(q("UPDATE fund SET balance = balance - %s, updated_at = NOW() WHERE id = %s AND balance >= %s",
                      "UPDATE fund SET balance = balance - ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND balance >= ?"),
                    (amount, fund['id'], amount))
        if cur.rowcount == 0:
            conn.rollback()
            conn.close()
            return jsonify({'error': f'Quỹ không đủ. Số dư quỹ: {int(fund["balance"]):,} VND'}), 400
    elif trans_type == 'income':
        fund = get_fund(conn)
        cur.execute(q("UPDATE fund SET balance = balance + %s, updated_at = NOW() WHERE id = %s",
                      "UPDATE fund SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"),
                    (amount, fund['id']))

    cur.execute(q("INSERT INTO finance (type, amount, description, category, created_by) VALUES (%s, %s, %s, %s, %s)",
                  "INSERT INTO finance (type, amount, description, category, created_by) VALUES (?, ?, ?, ?, ?)"),
                (trans_type, amount, description, category, session['user_id']))
    conn.commit()
    fund = get_fund(conn)
    conn.close()
    return jsonify({'message': 'Đã thêm giao dịch', 'fund': fund['balance']}), 201


@app.route('/api/finance/<int:finance_id>', methods=['DELETE'])
@login_required
@admin_required
def api_finance_delete(finance_id):
    conn = get_db()
    cur = conn.cursor()
    trans = cur.execute(q("SELECT * FROM finance WHERE id = %s", "SELECT * FROM finance WHERE id = ?"), (finance_id,)).fetchone()
    if trans and dict(trans)['type'] == 'expense':
        fund = get_fund(conn)
        cur.execute(q("UPDATE fund SET balance = balance + %s, updated_at = NOW() WHERE id = %s",
                      "UPDATE fund SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"),
                    (dict(trans)['amount'], fund['id']))
    cur.execute(q("DELETE FROM finance WHERE id = %s", "DELETE FROM finance WHERE id = ?"), (finance_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã xóa giao dịch'})


if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1', host='0.0.0.0', port=port)

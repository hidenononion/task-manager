import os
import base64
import csv
import hashlib
import hmac
import io
import secrets
import struct
import time
from datetime import datetime
from functools import wraps
from flask import (  # pyright: ignore[reportMissingImports]
    Flask, request, jsonify, session, render_template, redirect, url_for, Response
)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dtnlamkhe-secret-change-in-production')
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['SESSION_COOKIE_HTTPONLY'] = True

DATABASE_URL = os.environ.get('DATABASE_URL', '')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

LOCAL_DB = os.path.join(os.path.dirname(__file__), 'database.db')


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
        ''')

    admin = cur.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    if not admin:
        pw = hashlib.sha256('admin123'.encode()).hexdigest()
        cur.execute(q("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                      "INSERT INTO users (username, password, role) VALUES (?, ?, ?)"),
                     ('admin', pw, 'bithu'))
    else:
        cur.execute(q("UPDATE users SET role = 'bithu' WHERE username = 'admin' AND role != 'bithu'",
                      "UPDATE users SET role = 'bithu' WHERE username = 'admin' AND role != 'bithu'"))

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
    except Exception:
        pass

    conn.commit()
    conn.close()


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


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
        if session.get('role') != 'bithu':
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


def totp_verify(secret_b32, code, window=1):
    try:
        key = base64.b32decode(secret_b32, casefold=True)
        code = str(code).strip()
        t = int(time.time()) // 30
        for offset in range(-window, window + 1):
            msg = struct.pack('>Q', t + offset)
            h = hmac.new(key, msg, hashlib.sha1).digest()
            o = h[-1] & 0x0F
            token = (struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000
            if f'{token:06d}' == code:
                return True
        return False
    except Exception:
        return False


def post_json_best_effort(url, payload):
    try:
        import json as _json
        import urllib.request as _url
        req = _url.Request(url, data=_json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        _url.urlopen(req, timeout=4).read()
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
    return render_template('register.html')


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


# ==================== AUTH API ====================

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({'error': 'Username và password không được để trống'}), 400
    if len(password) < 4:
        return jsonify({'error': 'Password phải có ít nhất 4 ký tự'}), 400

    conn = get_db()
    cur = conn.cursor()
    existing = cur.execute(q("SELECT id FROM users WHERE username = %s", "SELECT id FROM users WHERE username = ?"), (username,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'error': 'Username đã tồn tại'}), 400

    cur.execute(q("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                  "INSERT INTO users (username, password, role) VALUES (?, ?, ?)"),
                (username, hash_password(password), 'user'))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đăng ký thành công'}), 201


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    code = str(data.get('code', '') or '').strip()

    conn = get_db()
    cur = conn.cursor()
    user = cur.execute(q("SELECT * FROM users WHERE username = %s AND password = %s",
                         "SELECT * FROM users WHERE username = ? AND password = ?"),
                       (username, hash_password(password))).fetchone()

    if not user:
        conn.close()
        return jsonify({'error': 'Sai username hoặc password'}), 401

    u = dict(user)
    if u.get('twofa_enabled'):
        pending = session.get('pending_2fa')
        if code and pending == u['id'] and totp_verify(u.get('twofa_secret') or '', code):
            pass
        elif code:
            conn.close()
            return jsonify({'error': 'Mã 2FA không đúng'}), 401
        else:
            session['pending_2fa'] = u['id']
            conn.close()
            return jsonify({'need_2fa': True, 'message': 'Nhập mã 2FA'}), 200

    session.pop('pending_2fa', None)
    session['user_id'] = u['id']
    session['username'] = u['username']
    session['role'] = u['role']
    try:
        cur.execute(q("INSERT INTO login_history (user_id, ip, user_agent) VALUES (%s, %s, %s)",
                      "INSERT INTO login_history (user_id, ip, user_agent) VALUES (?, ?, ?)"),
                    (u['id'], request.remote_addr or '', (request.headers.get('User-Agent') or '')[:300]))
        conn.commit()
    except Exception:
        pass
    conn.close()

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
    data = request.get_json()
    new_role = data.get('role')
    if new_role not in ('user', 'bithu'):
        return jsonify({'error': 'Role không hợp lệ'}), 400
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
              'auto_done_unfollow', 'auto_overdue_warn', 'twofa_enabled'}


@app.route('/api/profile', methods=['PUT'])
@login_required
def api_profile_update():
    data = request.get_json() or {}
    updates = {}
    for f in PROFILE_FIELDS + PREF_FIELDS + EXTRA_FIELDS:
        if f in data:
            v = data[f]
            if f in INT_FIELDS:
                try:
                    v = 1 if str(v).lower() in ('1', 'true', 'on', 'yes') or v is True or v == 1 else 0
                except Exception:
                    v = 0
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
    if len(new) < 4:
        return jsonify({'error': 'Mật khẩu mới ít nhất 4 ký tự'}), 400
    conn = get_db()
    cur = conn.cursor()
    user = cur.execute(q("SELECT * FROM users WHERE id = %s", "SELECT * FROM users WHERE id = ?"),
                       (session['user_id'],)).fetchone()
    if not user or dict(user)['password'] != hash_password(old):
        conn.close()
        return jsonify({'error': 'Mật khẩu cũ không đúng'}), 400
    cur.execute(q("UPDATE users SET password = %s WHERE id = %s", "UPDATE users SET password = ? WHERE id = ?"),
                (hash_password(new), session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã đổi mật khẩu'})


@app.route('/api/2fa/setup', methods=['POST'])
@login_required
def api_2fa_setup():
    secret = base64.b32encode(secrets.token_bytes(20)).decode().replace('=', '')
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q("UPDATE users SET twofa_secret = %s WHERE id = %s",
                  "UPDATE users SET twofa_secret = ? WHERE id = ?"), (secret, session['user_id']))
    conn.commit()
    conn.close()
    conn2 = get_db()
    user = conn2.cursor().execute(q("SELECT username FROM users WHERE id = %s", "SELECT username FROM users WHERE id = ?"),
                                  (session['user_id'],)).fetchone()
    conn2.close()
    label = dict(user)['username'] if user else 'user'
    otpauth = f"otpauth://totp/LamKhe:{label}?secret={secret}&issuer=LamKhe"
    return jsonify({'secret': secret, 'otpauth_url': otpauth})


@app.route('/api/2fa/enable', methods=['POST'])
@login_required
def api_2fa_enable():
    data = request.get_json() or {}
    code = str(data.get('code', ''))
    conn = get_db()
    cur = conn.cursor()
    user = cur.execute(q("SELECT * FROM users WHERE id = %s", "SELECT * FROM users WHERE id = ?"),
                       (session['user_id'],)).fetchone()
    u = dict(user)
    if not totp_verify(u.get('twofa_secret') or '', code):
        conn.close()
        return jsonify({'error': 'Mã xác thực không đúng'}), 400
    cur.execute(q("UPDATE users SET twofa_enabled = 1 WHERE id = %s", "UPDATE users SET twofa_enabled = 1 WHERE id = ?"),
                (session['user_id'],))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã bật 2FA'})


@app.route('/api/2fa/disable', methods=['POST'])
@login_required
def api_2fa_disable():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q("UPDATE users SET twofa_enabled = 0, twofa_secret = '' WHERE id = %s",
                  "UPDATE users SET twofa_enabled = 0, twofa_secret = '' WHERE id = ?"), (session['user_id'],))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã tắt 2FA'})


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
    data = request.get_json() or {}
    url = (data.get('url') or '').strip()
    if not url:
        conn.close()
        return jsonify({'error': 'Thiếu URL'}), 400
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
            w.writerow([d.get('id'), d.get('title'), d.get('description'), d.get('status'), d.get('priority'), d.get('due_date'), d.get('points'), d.get('scope', 'lang'), d.get('created_at')])
    elif kind == 'finance.csv':
        rows = cur.execute("SELECT id, type, amount, description, category, date FROM finance ORDER BY id").fetchall()
        w.writerow(['id', 'type', 'amount', 'description', 'category', 'date'])
        for r in rows:
            d = dict(r)
            w.writerow([d.get('id'), d.get('type'), d.get('amount'), d.get('description'), d.get('category'), d.get('date')])
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

    if role in 'bithu':
        tasks = cur.execute("SELECT * FROM tasks WHERE deleted_at IS NULL ORDER BY created_at DESC").fetchall()
    else:
        tasks = cur.execute("SELECT * FROM tasks WHERE deleted_at IS NULL ORDER BY created_at DESC").fetchall()

    scope = (request.args.get('scope') or '').strip()
    if scope in ('lang', 'xa'):
        tasks = [tk for tk in tasks if dict(tk).get('scope', 'lang') == scope]

    result = [serialize_task(conn, t, user_id, role) for t in tasks]
    conn.close()
    return jsonify(result)


@app.route('/api/tasks', methods=['POST'])
@login_required
@admin_required
def api_create_task():
    data = request.get_json()
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


@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
@login_required
@admin_required
def api_update_task(task_id):
    data = request.get_json()
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

    cur.execute(q("DELETE FROM task_assignments WHERE task_id = %s", "DELETE FROM task_assignments WHERE task_id = ?"), (task_id,))
    for uid in assigned_ids:
        cur.execute(q("INSERT INTO task_assignments (task_id, user_id) VALUES (%s, %s)",
                      "INSERT INTO task_assignments (task_id, user_id) VALUES (?, ?)"), (task_id, uid))

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
    if secs <= 0:
        return jsonify({'error': 'Số giây không hợp lệ'}), 400
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
    if session.get('role') != 'bithu':
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
    if data.get('assign_to') is not None:
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
    conn.commit()
    conn.close()
    return jsonify({'message': f'Đã cập nhật {len(ids)} task'})


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
    sh = cur.execute(q("SELECT * FROM shares WHERE token = %s", "SELECT * FROM shares WHERE token = ?"), (token,)).fetchone()
    if not sh:
        conn.close()
        return 'Link không tồn tại', 404
    tasks = cur.execute("SELECT id, title, description, status, priority, due_date FROM tasks WHERE deleted_at IS NULL ORDER BY created_at DESC").fetchall()
    conn.close()
    rows = ''.join([f"<tr><td>{dict(t).get('title','')}</td><td>{dict(t).get('status','')}</td><td>{dict(t).get('due_date') or ''}</td></tr>" for t in tasks])
    mode = dict(sh).get('mode', 'view')
    comment_box = ''
    if mode == 'comment':
        comment_box = '<p style="color:#888">Link này cho phép bình luận (liên hệ Bí thư để gửi nhận xét).</p>'
    return f"""<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tiến độ - Đoàn TN thôn Lam Khê</title>
<style>body{{font-family:system-ui;background:#0a0a0f;color:#eee;margin:0;padding:24px}}table{{width:100%;border-collapse:collapse}}td,th{{border:1px solid #333;padding:8px;text-align:left}}th{{background:#1a1a24}}</style></head>
<body><h2>Tiến độ công việc - Đoàn TN thôn Lam Khê</h2>{comment_box}<table><tr><th>Nhiệm vụ</th><th>Trạng thái</th><th>Hạn</th></tr>{rows}</table></body></html>"""


@app.route('/api/tasks/<int:task_id>/attachments', methods=['GET', 'POST'])
@login_required
def api_attachments(task_id):
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'GET':
        try:
            rows = cur.execute(q("SELECT * FROM attachments WHERE task_id = %s ORDER BY id",
                                 "SELECT * FROM attachments WHERE task_id = ? ORDER BY id"), (task_id,)).fetchall()
            conn.close()
            return jsonify([dict(r) for r in rows])
        except Exception:
            conn.close()
            return jsonify([])
    data = request.get_json() or {}
    url = (data.get('url') or '').strip()
    note = (data.get('note') or '')[:500]
    name = (data.get('filename') or url or 'link')[:200]
    if not url:
        conn.close()
        return jsonify({'error': 'Thiếu link'}), 400
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
    task = cur.execute(q("SELECT * FROM tasks WHERE id = %s", "SELECT * FROM tasks WHERE id = ?"), (task_id,)).fetchone()
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

    if session['role'] not in 'bithu':
        own = cur.execute(q("SELECT 1 FROM task_assignments WHERE task_id = %s AND user_id = %s",
                            "SELECT 1 FROM task_assignments WHERE task_id = ? AND user_id = ?"),
                          (task_id, session['user_id'])).fetchone()
        if not own:
            conn.close()
            return jsonify({'error': 'Bạn chưa nhận task này'}), 400

    target_user = session['user_id']
    if session['role'] in 'bithu' and request.is_json:
        target_user = request.get_json().get('user_id', session['user_id'])

    cur.execute(q("DELETE FROM task_assignments WHERE task_id = %s AND user_id = %s",
                  "DELETE FROM task_assignments WHERE task_id = ? AND user_id = ?"), (task_id, target_user))
    conn.commit()
    updated = cur.execute(q("SELECT * FROM tasks WHERE id = %s", "SELECT * FROM tasks WHERE id = ?"), (task_id,)).fetchone()
    result = serialize_task(conn, updated, session['user_id'])
    conn.close()
    return jsonify(result)


# ==================== STATUS ====================

@app.route('/api/tasks/<int:task_id>/status', methods=['PUT'])
@login_required
def api_update_status(task_id):
    data = request.get_json()
    new_status = data.get('status')
    if new_status not in ('pending', 'in_progress', 'done'):
        return jsonify({'error': 'Trạng thái không hợp lệ'}), 400

    conn = get_db()
    cur = conn.cursor()
    task = cur.execute(q("SELECT * FROM tasks WHERE id = %s", "SELECT * FROM tasks WHERE id = ?"), (task_id,)).fetchone()
    if not task:
        conn.close()
        return jsonify({'error': 'Task không tồn tại'}), 404

    if session['role'] not in 'bithu':
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
    users = cur.execute(q("SELECT id, username, score, role FROM users WHERE role = 'user' ORDER BY score DESC",
                          "SELECT id, username, score, role FROM users WHERE role = 'user' ORDER BY score DESC")).fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])


@app.route('/api/points/<int:user_id>')
@login_required
def api_points_detail(user_id):
    if session['role'] not in 'bithu' and session['user_id'] != user_id:
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
    data = request.get_json()
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
    data = request.get_json()
    amount = data.get('amount', 0)
    try:
        amount = float(amount)
    except (ValueError, TypeError):
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
    data = request.get_json()
    amount = data.get('amount', 0)
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return jsonify({'error': 'Số tiền không hợp lệ'}), 400
    if amount < 0:
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
    data = request.get_json()
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
    if amount <= 0:
        return jsonify({'error': 'Số tiền phải lớn hơn 0'}), 400

    conn = get_db()
    cur = conn.cursor()

    if trans_type == 'expense':
        fund = get_fund(conn)
        if fund['balance'] < amount:
            conn.close()
            return jsonify({'error': f'Quỹ không đủ. Số dư quỹ: {int(fund["balance"]):,} VND'}), 400
        cur.execute(q("UPDATE fund SET balance = balance - %s, updated_at = NOW() WHERE id = %s",
                      "UPDATE fund SET balance = balance - ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"),
                    (amount, fund['id']))
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

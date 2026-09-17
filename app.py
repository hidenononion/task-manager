import os
import sqlite3
import hashlib
import secrets
from datetime import datetime
from functools import wraps
from flask import (  # pyright: ignore[reportMissingImports]
    Flask, request, jsonify, session, render_template, redirect, url_for
)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dtnlamkhe-secret-change-in-production')
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['SESSION_COOKIE_HTTPONLY'] = True
DATABASE = os.path.join(os.path.dirname(__file__), 'database.db')


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
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
            FOREIGN KEY (task_id) REFERENCES tasks(id),
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
    ''')
    admin = conn.execute('SELECT id FROM users WHERE username = ?', ('admin',)).fetchone()
    if not admin:
        pw = hashlib.sha256('admin123'.encode()).hexdigest()
        conn.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                     ('admin', pw, 'admin'))
    try:
        conn.execute('SELECT max_assignees FROM tasks LIMIT 1')
    except Exception:
        conn.execute('ALTER TABLE tasks ADD COLUMN max_assignees INTEGER DEFAULT 3')
    try:
        conn.execute('SELECT score FROM users LIMIT 1')
    except Exception:
        conn.execute('ALTER TABLE users ADD COLUMN score INTEGER DEFAULT 0')
    try:
        conn.execute('SELECT points FROM tasks LIMIT 1')
    except Exception:
        conn.execute('ALTER TABLE tasks ADD COLUMN points INTEGER DEFAULT 0')
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
        if session.get('role') not in ('admin', 'bithu'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Admin access required'}), 403
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


def migrate_db():
    conn = get_db()
    try:
        conn.execute('SELECT assigned_to FROM tasks LIMIT 1')
        tasks = conn.execute('SELECT id, assigned_to FROM tasks WHERE assigned_to IS NOT NULL').fetchall()
        for t in tasks:
            conn.execute('INSERT OR IGNORE INTO task_assignments (task_id, user_id) VALUES (?, ?)',
                         (t['id'], t['assigned_to']))
        conn.execute('ALTER TABLE tasks DROP COLUMN assigned_to')
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute('SELECT max_assignees FROM tasks LIMIT 1')
    except Exception:
        conn.execute('ALTER TABLE tasks ADD COLUMN max_assignees INTEGER DEFAULT 3')
    try:
        conn.execute('SELECT score FROM users LIMIT 1')
    except Exception:
        conn.execute('ALTER TABLE users ADD COLUMN score INTEGER DEFAULT 0')
    try:
        conn.execute('SELECT points FROM tasks LIMIT 1')
    except Exception:
        conn.execute('ALTER TABLE tasks ADD COLUMN points INTEGER DEFAULT 0')
    conn.commit()
    conn.close()


# ==================== PAGE ROUTES ====================

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
    existing = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'error': 'Username đã tồn tại'}), 400

    conn.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                 (username, hash_password(password), 'user'))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đăng ký thành công'}), 201


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?',
                        (username, hash_password(password))).fetchone()
    conn.close()

    if not user:
        return jsonify({'error': 'Sai username hoặc password'}), 401

    session['user_id'] = user['id']
    session['username'] = user['username']
    session['role'] = user['role']

    return jsonify({
        'message': 'Đăng nhập thành công',
        'user': {'id': user['id'], 'username': user['username'], 'role': user['role'], 'score': user['score']}
    })


@app.route('/api/logout')
def api_logout():
    session.clear()
    return jsonify({'message': 'Đã đăng xuất'})


@app.route('/api/me')
@login_required
def api_me():
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    return jsonify({
        'id': user['id'],
        'username': user['username'],
        'role': user['role'],
        'score': user['score']
    })


# ==================== USERS API ====================

@app.route('/api/users')
@login_required
def api_users():
    conn = get_db()
    if session.get('role') in ('admin', 'bithu'):
        users = conn.execute('SELECT id, username, role, score FROM users WHERE role = ? ORDER BY username', ('user',)).fetchall()
    else:
        users = conn.execute('SELECT id, username, role, score FROM users WHERE id = ?', (session['user_id'],)).fetchall()
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
    conn.execute('UPDATE users SET role = ? WHERE id = ?', (new_role, user_id))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã cập nhật role'})


# ==================== TASKS API ====================

def get_task_assignees(conn, task_id):
    rows = conn.execute('''
        SELECT u.id, u.username FROM task_assignments ta
        JOIN users u ON ta.user_id = u.id
        WHERE ta.task_id = ?
    ''', (task_id,)).fetchall()
    return [dict(r) for r in rows]


def serialize_task(conn, task, user_id=None, role=None):
    d = dict(task)
    d['assigned_users'] = get_task_assignees(conn, task['id'])
    d['assignee_count'] = len(d['assigned_users'])
    d['max_assignees'] = task['max_assignees'] or 3
    d['slots_left'] = d['max_assignees'] - d['assignee_count']
    d['is_claimed_by_me'] = any(u['id'] == user_id for u in d['assigned_users']) if user_id else False
    d['points'] = task['points'] or 0
    return d


@app.route('/api/tasks')
@login_required
def api_tasks():
    conn = get_db()
    role = session.get('role')
    user_id = session['user_id']

    if role in ('admin', 'bithu'):
        tasks = conn.execute('SELECT * FROM tasks ORDER BY created_at DESC').fetchall()
        result = [serialize_task(conn, t, user_id, role) for t in tasks]
    else:
        assigned = conn.execute('SELECT task_id FROM task_assignments WHERE user_id = ?', (user_id,)).fetchall()
        task_ids = [a['task_id'] for a in assigned]
        if task_ids:
            placeholders = ','.join('?' * len(task_ids))
            tasks = conn.execute(f'SELECT * FROM tasks WHERE id IN ({placeholders}) ORDER BY created_at DESC', task_ids).fetchall()
        else:
            tasks = []
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

    max_assignees = data.get('max_assignees', 3)
    try:
        max_assignees = int(max_assignees)
    except (ValueError, TypeError):
        max_assignees = 3
    if max_assignees < 1:
        max_assignees = 1
    if max_assignees > 10:
        max_assignees = 10

    points = data.get('points', 0)
    try:
        points = int(points)
    except (ValueError, TypeError):
        points = 0

    assigned_ids = data.get('assigned_to', [])
    if not isinstance(assigned_ids, list):
        assigned_ids = [assigned_ids] if assigned_ids else []
    assigned_ids = [int(x) for x in assigned_ids if x]

    if len(assigned_ids) > max_assignees:
        return jsonify({'error': f'Tối đa giao cho {max_assignees} người'}), 400

    conn = get_db()
    due_date = data.get('due_date') or None

    cursor = conn.execute('''
        INSERT INTO tasks (title, description, status, priority, due_date, max_assignees, points, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        title,
        data.get('description', '') or '',
        data.get('status', 'pending'),
        data.get('priority', 'medium'),
        due_date,
        max_assignees,
        points,
        session['user_id']
    ))
    task_id = cursor.lastrowid

    for uid in assigned_ids:
        conn.execute('INSERT INTO task_assignments (task_id, user_id) VALUES (?, ?)', (task_id, uid))

    conn.commit()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    result = serialize_task(conn, task, session['user_id'])
    conn.close()
    return jsonify(result), 201


@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
@login_required
@admin_required
def api_update_task(task_id):
    data = request.get_json()
    conn = get_db()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task:
        conn.close()
        return jsonify({'error': 'Task không tồn tại'}), 404

    max_assignees = data.get('max_assignees', task['max_assignees'])
    try:
        max_assignees = int(max_assignees)
    except (ValueError, TypeError):
        max_assignees = task['max_assignees'] or 3
    if max_assignees < 1:
        max_assignees = 1
    if max_assignees > 10:
        max_assignees = 10

    points = data.get('points', task['points'] or 0)
    try:
        points = int(points)
    except (ValueError, TypeError):
        points = 0

    assigned_ids = data.get('assigned_to', [])
    if not isinstance(assigned_ids, list):
        assigned_ids = [assigned_ids] if assigned_ids else []
    assigned_ids = [int(x) for x in assigned_ids if x]

    if len(assigned_ids) > max_assignees:
        conn.close()
        return jsonify({'error': f'Tối đa giao cho {max_assignees} người'}), 400

    due_date = data.get('due_date') or None

    conn.execute('''
        UPDATE tasks SET title=?, description=?, status=?, priority=?, due_date=?, max_assignees=?, points=?
        WHERE id=?
    ''', (
        data.get('title', task['title']),
        data.get('description', task['description']) or '',
        data.get('status', task['status']),
        data.get('priority', task['priority']),
        due_date,
        max_assignees,
        points,
        task_id
    ))

    conn.execute('DELETE FROM task_assignments WHERE task_id = ?', (task_id,))
    for uid in assigned_ids:
        conn.execute('INSERT INTO task_assignments (task_id, user_id) VALUES (?, ?)', (task_id, uid))

    conn.commit()
    updated = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    result = serialize_task(conn, updated, session['user_id'])
    conn.close()
    return jsonify(result)


@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_task(task_id):
    conn = get_db()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task:
        conn.close()
        return jsonify({'error': 'Task không tồn tại'}), 404

    conn.execute('DELETE FROM task_assignments WHERE task_id = ?', (task_id,))
    conn.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã xóa task'})


# ==================== CLAIM / UNCLAIM ====================

@app.route('/api/tasks/<int:task_id>/claim', methods=['POST'])
@login_required
def api_claim_task(task_id):
    conn = get_db()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task:
        conn.close()
        return jsonify({'error': 'Task không tồn tại'}), 404

    if task['status'] == 'done':
        conn.close()
        return jsonify({'error': 'Task đã hoàn thành'}), 400

    already = conn.execute(
        'SELECT 1 FROM task_assignments WHERE task_id = ? AND user_id = ?',
        (task_id, session['user_id'])
    ).fetchone()
    if already:
        conn.close()
        return jsonify({'error': 'Bạn đã nhận task này rồi'}), 400

    count = conn.execute(
        'SELECT COUNT(*) as c FROM task_assignments WHERE task_id = ?', (task_id,)
    ).fetchone()['c']

    max_assignees = task['max_assignees'] or 3
    if count >= max_assignees:
        conn.close()
        return jsonify({'error': 'Task đã đủ người nhận'}), 400

    conn.execute('INSERT INTO task_assignments (task_id, user_id) VALUES (?, ?)',
                 (task_id, session['user_id']))
    conn.commit()
    updated = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    result = serialize_task(conn, updated, session['user_id'])
    conn.close()
    return jsonify(result)


@app.route('/api/tasks/<int:task_id>/claim', methods=['DELETE'])
@login_required
def api_unclaim_task(task_id):
    conn = get_db()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task:
        conn.close()
        return jsonify({'error': 'Task không tồn tại'}), 404

    if session['role'] not in ('admin', 'bithu'):
        own = conn.execute(
            'SELECT 1 FROM task_assignments WHERE task_id = ? AND user_id = ?',
            (task_id, session['user_id'])
        ).fetchone()
        if not own:
            conn.close()
            return jsonify({'error': 'Bạn chưa nhận task này'}), 400

    target_user = request.get_json().get('user_id', session['user_id']) if request.is_json else session['user_id']
    if session['role'] not in ('admin', 'bithu'):
        target_user = session['user_id']

    conn.execute('DELETE FROM task_assignments WHERE task_id = ? AND user_id = ?',
                 (task_id, target_user))
    conn.commit()
    updated = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
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
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task:
        conn.close()
        return jsonify({'error': 'Task không tồn tại'}), 404

    if session['role'] not in ('admin', 'bithu'):
        assigned = conn.execute(
            'SELECT 1 FROM task_assignments WHERE task_id = ? AND user_id = ?',
            (task_id, session['user_id'])
        ).fetchone()
        if not assigned:
            conn.close()
            return jsonify({'error': 'Không có quyền cập nhật task này'}), 403

    old_status = task['status']
    conn.execute('UPDATE tasks SET status = ? WHERE id = ?', (new_status, task_id))

    if new_status == 'done' and old_status != 'done' and task['points'] and task['points'] > 0:
        assignees = conn.execute('SELECT user_id FROM task_assignments WHERE task_id = ?', (task_id,)).fetchall()
        for a in assignees:
            uid = a['user_id']
            conn.execute('UPDATE users SET score = score + ? WHERE id = ?', (task['points'], uid))
            conn.execute('INSERT INTO points_log (user_id, points, reason, task_id, created_by) VALUES (?, ?, ?, ?, ?)',
                         (uid, task['points'], f'Hoàn thành task: {task["title"]}', task_id, session['user_id']))

    conn.commit()
    updated = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    result = serialize_task(conn, updated, session['user_id'])
    conn.close()
    return jsonify(result)


# ==================== POINTS API ====================

@app.route('/api/points')
@login_required
@admin_required
def api_points_list():
    conn = get_db()
    users = conn.execute('SELECT id, username, score, role FROM users WHERE role = ? ORDER BY score DESC', ('user',)).fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])


@app.route('/api/points/<int:user_id>')
@login_required
def api_points_detail(user_id):
    if session['role'] not in ('admin', 'bithu') and session['user_id'] != user_id:
        return jsonify({'error': 'Không có quyền'}), 403

    conn = get_db()
    user = conn.execute('SELECT id, username, score FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'User không tồn tại'}), 404

    logs = conn.execute('''
        SELECT pl.*, u.username as given_by_name
        FROM points_log pl
        LEFT JOIN users u ON pl.created_by = u.id
        WHERE pl.user_id = ?
        ORDER BY pl.created_at DESC
    ''', (user_id,)).fetchall()
    conn.close()
    return jsonify({
        'user': dict(user),
        'logs': [dict(l) for l in logs]
    })


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
    user = conn.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'User không tồn tại'}), 404

    conn.execute('UPDATE users SET score = score + ? WHERE id = ?', (points, user_id))
    conn.execute('INSERT INTO points_log (user_id, points, reason, created_by) VALUES (?, ?, ?, ?)',
                 (user_id, points, reason, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã cập nhật điểm'})


# ==================== FINANCE API ====================

@app.route('/api/finance')
@login_required
@admin_required
def api_finance_list():
    conn = get_db()
    transactions = conn.execute('''
        SELECT f.*, u.username as created_by_name
        FROM finance f
        LEFT JOIN users u ON f.created_by = u.id
        ORDER BY f.date DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(t) for t in transactions])


@app.route('/api/finance/summary')
@login_required
@admin_required
def api_finance_summary():
    conn = get_db()
    income = conn.execute('SELECT COALESCE(SUM(amount), 0) as total FROM finance WHERE type = ?').fetchone()['total']
    expense = conn.execute('SELECT COALESCE(SUM(amount), 0) as total FROM finance WHERE type = ?').fetchone()['total']
    conn.close()
    return jsonify({
        'income': income,
        'expense': expense,
        'balance': income - expense
    })


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
    conn.execute('INSERT INTO finance (type, amount, description, category, created_by) VALUES (?, ?, ?, ?, ?)',
                 (trans_type, amount, description, category, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã thêm giao dịch'}), 201


@app.route('/api/finance/<int:finance_id>', methods=['DELETE'])
@login_required
@admin_required
def api_finance_delete(finance_id):
    conn = get_db()
    conn.execute('DELETE FROM finance WHERE id = ?', (finance_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Đã xóa giao dịch'})


if __name__ == '__main__':
    init_db()
    migrate_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1', host='0.0.0.0', port=port)

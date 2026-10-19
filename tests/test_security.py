"""Regression tests cho cac loi bao mat da sua.

Chay: python -m unittest discover -s tests -v
"""

import hashlib
import io
import os
import secrets
import shutil
import tempfile
import unittest

# Phai set env truoc khi import app (LOCAL_DB duoc tinh luc import).
_TMP_DB = tempfile.NamedTemporaryFile(prefix='taskmgr_test_', suffix='.db', delete=False)
_TMP_DB.close()
os.environ['TASKMGR_DB_PATH'] = _TMP_DB.name
os.environ['SECRET_KEY'] = secrets.token_hex(32)
os.environ['ADMIN_PASSWORD'] = 'AdminPass123!'
os.environ.pop('DATABASE_URL', None)

import app as appmod  # noqa: E402
from security import (  # noqa: E402
    SlidingWindowLimiter, csv_safe, file_signature_ok, is_public_http_url,
    is_safe_link_url, safe_filename,
)

ADMIN_PASSWORD = 'AdminPass123!'
_UPLOAD_TMP = tempfile.mkdtemp(prefix='taskmgr_uploads_')


def _unique(prefix='user'):
    return f'{prefix}_{secrets.token_hex(4)}'


class SecurityTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        appmod.app.config.update(TESTING=True)
        appmod.init_db()
        appmod._uploads_dir = lambda: _UPLOAD_TMP

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_UPLOAD_TMP, ignore_errors=True)
        try:
            os.unlink(_TMP_DB.name)
        except OSError:
            pass

    def setUp(self):
        appmod._login_limiter.clear()
        appmod._login_ip_limiter.clear()
        appmod._register_limiter.clear()
        self.client = appmod.app.test_client()

    # ---------- helpers ----------
    def login(self, username, password, client=None):
        client = client or self.client
        return client.post('/api/login', json={'username': username, 'password': password})

    def login_admin(self):
        res = self.login('admin', ADMIN_PASSWORD)
        self.assertEqual(res.status_code, 200, res.get_json())
        return self.client

    def register(self, client=None):
        client = client or self.client
        username = _unique()
        res = client.post('/api/register', json={'username': username, 'password': 'UserPass123!'})
        self.assertEqual(res.status_code, 201, res.get_json())
        return username

    def create_task(self, **extra):
        payload = {'title': 'Task ' + secrets.token_hex(3)}
        payload.update(extra)
        res = self.client.post('/api/tasks', json=payload)
        self.assertEqual(res.status_code, 201, res.get_json())
        return res.get_json()

    # ---------- auth ----------
    def test_passwords_use_slow_hash_and_legacy_migrates(self):
        hashed = appmod.hash_password('Secret123!')
        self.assertFalse(appmod._looks_like_legacy_hash(hashed))
        self.assertTrue(hashed.startswith(('scrypt:', 'pbkdf2:')), hashed)

        username = _unique('legacy')
        legacy = hashlib.sha256(b'LegacyPass123!').hexdigest()
        conn = appmod.get_db()
        conn.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                     (username, legacy, 'user'))
        conn.commit()
        conn.close()

        res = self.login(username, 'LegacyPass123!')
        self.assertEqual(res.status_code, 200, res.get_json())

        conn = appmod.get_db()
        row = conn.execute('SELECT password FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        self.assertFalse(appmod._looks_like_legacy_hash(row['password']))

    def test_login_is_rate_limited(self):
        username = _unique('lim')
        for _ in range(5):
            res = self.login(username, 'wrong-password')
            self.assertEqual(res.status_code, 401)
        res = self.login(username, 'wrong-password')
        self.assertEqual(res.status_code, 429)
        self.assertIn('Retry-After', res.headers)

    def test_register_enforces_policy(self):
        res = self.client.post('/api/register', json={'username': 'ab', 'password': 'UserPass123!'})
        self.assertEqual(res.status_code, 400)
        res = self.client.post('/api/register', json={'username': _unique(), 'password': '1234567'})
        self.assertEqual(res.status_code, 400)
        res = self.client.post('/api/register', json={'username': _unique(), 'password': 'abcdefgh'})
        self.assertIn(res.status_code, (201, 400))  # 400 neu username trung, van la policy hop le

    def test_regular_user_cannot_use_admin_endpoints(self):
        username = self.register()
        self.assertEqual(self.login(username, 'UserPass123!').status_code, 200)
        self.assertEqual(self.client.post('/api/tasks', json={'title': 'x'}).status_code, 403)
        self.assertEqual(self.client.get('/api/points').status_code, 403)
        self.assertEqual(self.client.put('/api/users/1/role', json={'role': 'bithu'}).status_code, 403)

    def test_session_fixation_is_cleared_on_login(self):
        username = self.register()
        with self.client.session_transaction() as sess:
            sess['user_id'] = 999999
            sess['role'] = 'bithu'
        self.assertEqual(self.login(username, 'UserPass123!').status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertNotEqual(sess.get('user_id'), 999999)
            self.assertEqual(sess.get('role'), 'user')

    # ---------- request forgery / headers ----------
    def test_cross_site_origin_is_rejected(self):
        self.login_admin()
        res = self.client.post('/api/tasks', json={'title': 'csrf'},
                               headers={'Origin': 'https://evil.example'})
        self.assertEqual(res.status_code, 403)

    def test_security_headers_are_set(self):
        res = self.client.get('/health')
        self.assertEqual(res.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(res.headers.get('X-Frame-Options'), 'DENY')
        self.assertIn("default-src 'self'", res.headers.get('Content-Security-Policy', ''))
        self.assertTrue(res.headers.get('Referrer-Policy'))

    # ---------- XSS / HTML escaping ----------
    def test_share_page_escapes_task_title(self):
        self.login_admin()
        self.create_task(title='<script>alert(1)</script>')
        res = self.client.post('/api/share', json={'mode': 'view'})
        self.assertEqual(res.status_code, 201, res.get_json())
        token = res.get_json()['token']
        page = self.client.get(f'/share/{token}')
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        self.assertNotIn('<script>alert(1)</script>', body)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', body)

    def test_attachment_rejects_javascript_url(self):
        self.login_admin()
        task = self.create_task()
        res = self.client.post(f"/api/tasks/{task['id']}/attachments",
                               json={'url': 'javascript:alert(1)'})
        self.assertEqual(res.status_code, 400)

    # ---------- uploads ----------
    def test_upload_rejects_disguised_content_and_traversal(self):
        self.login_admin()
        task = self.create_task()
        bad = self.client.post(
            f"/api/tasks/{task['id']}/file",
            data={'file': (io.BytesIO(b'<html>not a pdf</html>'), 'evil.pdf')},
            content_type='multipart/form-data')
        self.assertEqual(bad.status_code, 400)

        good = self.client.post(
            f"/api/tasks/{task['id']}/file",
            data={'file': (io.BytesIO(b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n'), '../../escape.pdf')},
            content_type='multipart/form-data')
        self.assertEqual(good.status_code, 201, good.get_json())
        self.assertNotIn('..', good.get_json()['url'])

        # Khong co file nao bi ghi ra ngoai uploads/
        self.assertFalse(os.path.exists(os.path.join(appmod.BASE_DIR, 'escape.pdf')))
        self.assertTrue(any('escape.pdf' in name for name in os.listdir(_UPLOAD_TMP)))

    def test_download_requires_login(self):
        self.login_admin()
        task = self.create_task()
        up = self.client.post(
            f"/api/tasks/{task['id']}/file",
            data={'file': (io.BytesIO(b'%PDF-1.4\n'), 'doc.pdf')},
            content_type='multipart/form-data')
        url = up.get_json()['url']
        self.client.get('/api/logout')
        self.assertEqual(self.client.get(url).status_code, 401)

    # ---------- SSRF / links ----------
    def test_webhook_rejects_private_targets(self):
        self.login_admin()
        for url in ('http://127.0.0.1:8080/hook', 'http://localhost/hook',
                    'http://169.254.169.254/latest/meta-data', 'file:///etc/passwd'):
            res = self.client.post('/api/webhooks', json={'url': url})
            self.assertEqual(res.status_code, 400, url)

    # ---------- CSV injection ----------
    def test_csv_export_neutralises_formulas(self):
        self.login_admin()
        self.create_task(title='=cmd|calc')
        res = self.client.get('/api/export/tasks.csv')
        self.assertEqual(res.status_code, 200)
        self.assertIn("'=cmd|calc", res.get_data(as_text=True))

    # ---------- bulk serialization / claim limit ----------
    def test_tasks_payload_includes_batch_relations(self):
        self.login_admin()
        task = self.create_task()
        self.client.post(f"/api/tasks/{task['id']}/subtasks", json={'title': 'sub'})
        self.client.post(f"/api/tasks/{task['id']}/comments", json={'text': 'hello'})
        rows = self.client.get('/api/tasks').get_json()
        row = next(r for r in rows if r['id'] == task['id'])
        self.assertEqual(row['subtasks'][0]['title'], 'sub')
        self.assertEqual(row['comment_count'], 1)
        self.assertIn('assigned_users', row)

    def test_claim_respects_max_assignees(self):
        self.login_admin()
        task = self.create_task(max_assignees=1)

        first = appmod.app.test_client()
        u1 = _unique('claim1')
        self.assertEqual(first.post('/api/register', json={'username': u1, 'password': 'UserPass123!'}).status_code, 201)
        self.assertEqual(first.post('/api/login', json={'username': u1, 'password': 'UserPass123!'}).status_code, 200)
        self.assertEqual(first.post(f"/api/tasks/{task['id']}/claim").status_code, 200)

        second = appmod.app.test_client()
        u2 = _unique('claim2')
        self.assertEqual(second.post('/api/register', json={'username': u2, 'password': 'UserPass123!'}).status_code, 201)
        self.assertEqual(second.post('/api/login', json={'username': u2, 'password': 'UserPass123!'}).status_code, 200)
        self.assertEqual(second.post(f"/api/tasks/{task['id']}/claim").status_code, 400)


class SecurityHelperTestCase(unittest.TestCase):
    def test_safe_filename_strips_paths(self):
        self.assertEqual(safe_filename('../../etc/passwd'), 'passwd')
        self.assertEqual(safe_filename('..\\..\\evil.pdf'), 'evil.pdf')
        self.assertNotIn('/', safe_filename('/tmp/../x.pdf'))

    def test_magic_bytes(self):
        self.assertTrue(file_signature_ok('pdf', b'%PDF-1.7'))
        self.assertTrue(file_signature_ok('docx', b'PK\x03\x04rest'))
        self.assertFalse(file_signature_ok('pdf', b'<html>'))

    def test_link_schemes(self):
        self.assertTrue(is_safe_link_url('https://example.com/x'))
        self.assertTrue(is_safe_link_url('/api/tasks/1/file/x.pdf'))
        self.assertFalse(is_safe_link_url('javascript:alert(1)'))
        self.assertFalse(is_safe_link_url('data:text/html,<script>alert(1)</script>'))
        self.assertFalse(is_safe_link_url('//evil.example'))

    def test_ssrf_guard(self):
        self.assertFalse(is_public_http_url('http://127.0.0.1/', resolve_dns=False))
        self.assertFalse(is_public_http_url('http://10.0.0.5/', resolve_dns=False))
        self.assertFalse(is_public_http_url('http://169.254.169.254/', resolve_dns=False))
        self.assertFalse(is_public_http_url('ftp://example.com/', resolve_dns=False))
        self.assertTrue(is_public_http_url('https://1.1.1.1/hook', resolve_dns=False))

    def test_csv_safe_keeps_numbers(self):
        self.assertEqual(csv_safe('=1+1'), "'=1+1")
        self.assertEqual(csv_safe('safe'), 'safe')
        self.assertEqual(csv_safe(-5), -5)

    def test_limiter_window(self):
        limiter = SlidingWindowLimiter(2, 60)
        self.assertEqual(limiter.hit('k'), 0)
        self.assertEqual(limiter.hit('k'), 0)
        self.assertGreater(limiter.hit('k'), 0)
        limiter.reset('k')
        self.assertEqual(limiter.hit('k'), 0)


if __name__ == '__main__':
    unittest.main()

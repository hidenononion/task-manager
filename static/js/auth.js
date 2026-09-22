document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');

    if (loginForm) loginForm.addEventListener('submit', handleLogin);
    if (registerForm) registerForm.addEventListener('submit', handleRegister);

    fetch('/api/me').then(r => { if (r.ok) window.location.href = '/dashboard'; }).catch(() => {});
});

async function handleLogin(e) {
    e.preventDefault();
    const errorEl = document.getElementById('loginError');
    errorEl.textContent = '';
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value.trim();
    const codeEl = document.getElementById('twofaCode');
    const code = codeEl ? codeEl.value.trim() : '';
    if (!username || !password) { errorEl.textContent = 'Vui lòng nhập đầy đủ thông tin'; return; }
    try {
        const res = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password, code }) });
        const data = await res.json();
        if (!res.ok) { errorEl.textContent = data.error || 'Đăng nhập thất bại'; return; }
        if (data.need_2fa) {
            document.getElementById('twofaGroup').style.display = 'block';
            if (codeEl) codeEl.focus();
            errorEl.textContent = 'Tài khoản bật 2FA — nhập mã 6 số rồi bấm Đăng nhập lại';
            return;
        }
        window.location.href = '/dashboard';
    } catch (err) { errorEl.textContent = 'Lỗi kết nối server'; }
}

async function handleRegister(e) {
    e.preventDefault();
    const errorEl = document.getElementById('registerError');
    errorEl.textContent = '';
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value.trim();
    const confirmPassword = document.getElementById('confirmPassword').value.trim();
    if (!username || !password) { errorEl.textContent = 'Vui lòng nhập đầy đủ thông tin'; return; }
    if (password !== confirmPassword) { errorEl.textContent = 'Password xác nhận không khớp'; return; }
    if (password.length < 4) { errorEl.textContent = 'Password phải có ít nhất 4 ký tự'; return; }
    try {
        const res = await fetch('/api/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) });
        const data = await res.json();
        if (!res.ok) { errorEl.textContent = data.error || 'Đăng ký thất bại'; return; }
        window.location.href = '/login';
    } catch (err) { errorEl.textContent = 'Lỗi kết nối server'; }
}

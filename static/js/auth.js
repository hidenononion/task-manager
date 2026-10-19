(function initLoginTheme() {
    const v = localStorage.getItem('theme') || 'dark';
    const resolved = v === 'system'
        ? (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
        : v;
    document.documentElement.setAttribute('data-theme', resolved);
})();

document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');

    if (loginForm) loginForm.addEventListener('submit', handleLogin);
    if (registerForm) registerForm.addEventListener('submit', handleRegister);
    if (window.location.hash === '#signup') flipCard();

    fetch('/api/me').then(r => { if (r.ok) window.location.href = '/dashboard'; }).catch(() => {});
});

function flipCard() {
    document.getElementById('authCard').classList.toggle('flipped');
}

function togglePassword(btn) {
    const input = btn.parentElement.querySelector('input');
    const icon = btn.querySelector('i');
    if (input.type === 'password') {
        input.type = 'text';
        icon.classList.replace('fa-eye', 'fa-eye-slash');
    } else {
        input.type = 'password';
        icon.classList.replace('fa-eye-slash', 'fa-eye');
    }
}

function shakeCard() {
    const card = document.getElementById('authCard');
    const panel = card.classList.contains('flipped') ? card.querySelector('.signup-panel') : card.querySelector('.login-panel');
    panel.classList.remove('shake');
    void panel.offsetWidth;
    panel.classList.add('shake');
}

function setBtnLoading(btn, loading, text) {
    if (loading) {
        btn.disabled = true;
        btn.dataset.oldText = btn.textContent;
        btn.textContent = text;
    } else {
        btn.disabled = false;
        btn.textContent = btn.dataset.oldText || btn.textContent;
    }
}

async function handleLogin(e) {
    e.preventDefault();
    const errorEl = document.getElementById('loginError');
    const btn = e.target.querySelector('.main-btn');
    errorEl.textContent = '';
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value.trim();
    if (!username || !password) { errorEl.textContent = 'Vui lòng nhập đầy đủ thông tin'; shakeCard(); return; }
    setBtnLoading(btn, true, 'Đang đăng nhập...');
    try {
        const res = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) });
        const data = await res.json();
        if (!res.ok) {
            setBtnLoading(btn, false);
            errorEl.textContent = data.error || 'Đăng nhập thất bại';
            shakeCard();
            return;
        }
        btn.textContent = '✓ Thành công';
        setTimeout(() => { window.location.href = '/dashboard'; }, 700);
    } catch (err) {
        setBtnLoading(btn, false);
        errorEl.textContent = 'Lỗi kết nối server';
        shakeCard();
    }
}

async function handleRegister(e) {
    e.preventDefault();
    const errorEl = document.getElementById('registerError');
    const btn = e.target.querySelector('.main-btn');
    errorEl.textContent = '';
    const username = document.getElementById('regUsername').value.trim();
    const password = document.getElementById('regPassword').value.trim();
    const confirmPassword = document.getElementById('confirmPassword').value.trim();
    if (!username || !password || !confirmPassword) { errorEl.textContent = 'Vui lòng nhập đầy đủ thông tin'; shakeCard(); return; }
    if (password !== confirmPassword) { errorEl.textContent = 'Password xác nhận không khớp'; shakeCard(); return; }
    if (password.length < 4) { errorEl.textContent = 'Password phải có ít nhất 4 ký tự'; shakeCard(); return; }
    setBtnLoading(btn, true, 'Đang tạo...');
    try {
        const res = await fetch('/api/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) });
        const data = await res.json();
        if (!res.ok) {
            setBtnLoading(btn, false);
            errorEl.textContent = data.error || 'Đăng ký thất bại';
            shakeCard();
            return;
        }
        btn.textContent = '✓ Thành công';
        setTimeout(() => { window.location.href = '/login'; }, 700);
    } catch (err) {
        setBtnLoading(btn, false);
        errorEl.textContent = 'Lỗi kết nối server';
        shakeCard();
    }
}

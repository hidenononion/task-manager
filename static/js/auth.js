document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');

    if (loginForm) loginForm.addEventListener('submit', handleLogin);
    if (registerForm) registerForm.addEventListener('submit', handleRegister);

    fetch('/api/me').then(r => { if (r.ok) window.location.href = '/dashboard'; }).catch(() => {});
});

function setLoginState(state) {
    const boxes = [document.getElementById('userBox'), document.getElementById('passBox')];
    const icons = [document.getElementById('userIconWrap'), document.getElementById('passIconWrap')];
    const spinner = document.getElementById('loginSpinner');
    const btn = document.getElementById('loginBtn');
    const btnText = document.getElementById('loginBtnText');
    const scan = document.getElementById('loginScan');
    const inputs = document.querySelectorAll('.login-box input');

    if (state === 'loading') {
        boxes.forEach(b => b.classList.add('searching'));
        icons.forEach(i => i.classList.add('icon-searching'));
        inputs.forEach(i => i.disabled = true);
        btn.disabled = true;
        spinner.classList.remove('hidden');
        btnText.textContent = 'Đang đăng nhập...';
        scan.classList.remove('hidden');
    } else if (state === 'success') {
        boxes.forEach(b => b.classList.remove('searching'));
        icons.forEach(i => {
            i.classList.remove('icon-searching');
            const field = i.querySelector('.field-icon');
            const success = i.querySelector('.success-icon');
            if (field) field.classList.add('hidden');
            if (success) {
                success.classList.remove('hidden');
                success.classList.remove('success-pop');
                void success.offsetWidth;
                success.classList.add('success-pop');
            }
        });
        spinner.classList.add('hidden');
        scan.classList.add('hidden');
        btn.disabled = false;
        btnText.textContent = 'Thành công ✓';
    } else {
        boxes.forEach(b => b.classList.remove('searching'));
        icons.forEach(i => i.classList.remove('icon-searching'));
        inputs.forEach(i => i.disabled = false);
        btn.disabled = false;
        spinner.classList.add('hidden');
        scan.classList.add('hidden');
        btnText.textContent = 'Đăng nhập';
        const card = document.querySelector('.auth-card');
        card.classList.remove('shake');
        void card.offsetWidth;
        card.classList.add('shake');
    }
}

async function handleLogin(e) {
    e.preventDefault();
    const errorEl = document.getElementById('loginError');
    errorEl.textContent = '';
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value.trim();
    if (!username || !password) {
        errorEl.textContent = 'Vui lòng nhập đầy đủ thông tin';
        const card = document.querySelector('.auth-card');
        card.classList.remove('shake'); void card.offsetWidth; card.classList.add('shake');
        return;
    }
    setLoginState('loading');
    try {
        const res = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) });
        const data = await res.json();
        if (!res.ok) {
            setLoginState('error');
            errorEl.textContent = data.error || 'Đăng nhập thất bại';
            return;
        }
        setLoginState('success');
        setTimeout(() => { window.location.href = '/dashboard'; }, 800);
    } catch (err) {
        setLoginState('error');
        errorEl.textContent = 'Lỗi kết nối server';
    }
}

async function handleRegister(e) {
    e.preventDefault();
    const errorEl = document.getElementById('registerError');
    errorEl.textContent = '';
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value.trim();
    const confirmPassword = document.getElementById('confirmPassword').value.trim();
    if (!username || !password || !confirmPassword) { errorEl.textContent = 'Vui lòng nhập đầy đủ thông tin'; return; }
    if (password !== confirmPassword) { errorEl.textContent = 'Password xác nhận không khớp'; return; }
    if (password.length < 4) { errorEl.textContent = 'Password phải có ít nhất 4 ký tự'; return; }
    try {
        const res = await fetch('/api/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) });
        const data = await res.json();
        if (!res.ok) { errorEl.textContent = data.error || 'Đăng ký thất bại'; return; }
        window.location.href = '/login';
    } catch (err) { errorEl.textContent = 'Lỗi kết nối server'; }
}

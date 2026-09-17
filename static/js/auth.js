document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');

    if (loginForm) {
        loginForm.addEventListener('submit', handleLogin);
    }

    if (registerForm) {
        registerForm.addEventListener('submit', handleRegister);
    }

    fetch('/api/me').then(r => {
        if (r.ok) window.location.href = '/dashboard';
    }).catch(() => {});
});

async function handleLogin(e) {
    e.preventDefault();
    const errorEl = document.getElementById('loginError');
    errorEl.textContent = '';

    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value.trim();

    if (!username || !password) {
        errorEl.textContent = 'Vui long nhap day du thong tin';
        return;
    }

    try {
        const res = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await res.json();

        if (!res.ok) {
            errorEl.textContent = data.error || 'Dang nhap that bai';
            return;
        }

        window.location.href = '/dashboard';
    } catch (err) {
        errorEl.textContent = 'Loi ket noi server';
    }
}

async function handleRegister(e) {
    e.preventDefault();
    const errorEl = document.getElementById('registerError');
    errorEl.textContent = '';

    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value.trim();
    const confirmPassword = document.getElementById('confirmPassword').value.trim();

    if (!username || !password) {
        errorEl.textContent = 'Vui long nhap day du thong tin';
        return;
    }

    if (password !== confirmPassword) {
        errorEl.textContent = 'Password xac nhan khong khop';
        return;
    }

    if (password.length < 4) {
        errorEl.textContent = 'Password phai co it nhat 4 ky tu';
        return;
    }

    try {
        const res = await fetch('/api/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await res.json();

        if (!res.ok) {
            errorEl.textContent = data.error || 'Dang ky that bai';
            return;
        }

        window.location.href = '/login';
    } catch (err) {
        errorEl.textContent = 'Loi ket noi server';
    }
}

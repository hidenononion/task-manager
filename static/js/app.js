let currentUser = null;
let allTasks = [];
let allUsers = [];
let allPoints = [];
let currentView = 'kanban';
let deleteTaskId = null;

// ==================== INIT ====================
document.addEventListener('DOMContentLoaded', async () => {
    loadTheme();
    await loadUser();
    setupNav();
    await loadTasks();
    await loadUsers();
});

async function loadUser() {
    try {
        const res = await fetch('/api/me');
        if (!res.ok) { window.location.href = '/login'; return; }
        currentUser = await res.json();
        document.getElementById('userName').textContent = currentUser.username;
        document.getElementById('userAvatar').textContent = currentUser.username[0].toUpperCase();
        const roleEl = document.getElementById('userRole');
        roleEl.textContent = currentUser.role === 'bithu' ? t('role_bithu') : t('role_user');
        if (currentUser.role === 'bithu') roleEl.classList.add('badge-admin');

        const isAdminOrBithu = currentUser.role === 'bithu';
        document.querySelectorAll('.admin-only').forEach(el => el.style.display = isAdminOrBithu ? '' : 'none');
        document.querySelectorAll('.user-only').forEach(el => el.style.display = !isAdminOrBithu ? '' : 'none');
        if (document.getElementById('addTaskBtn')) {
            document.getElementById('addTaskBtn').style.display = isAdminOrBithu ? 'inline-flex' : 'none';
        }
        fillSettings();
        applyLang(localStorage.getItem('lang') || currentUser.language || 'vi');
        if (currentUser.default_view && (currentView === 'kanban')) {
            const target = document.querySelector(`.nav-item[data-view="${currentUser.default_view}"]`);
            if (target && currentUser.default_view !== 'kanban') target.click();
        }
    } catch (err) { window.location.href = '/login'; }
}

// ==================== SIDEBAR ====================
function toggleSidebar() {
    document.querySelector('.sidebar').classList.toggle('open');
    document.querySelector('.sidebar-overlay').classList.toggle('active');
}

// ==================== THEME ====================
function resolveTheme(v) {
    if (v === 'system') return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    return v || 'dark';
}
function loadTheme() {
    const theme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', resolveTheme(theme));
    updateThemeUI(theme);
}

function toggleTheme() {
    const current = localStorage.getItem('theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    localStorage.setItem('theme', next);
    document.documentElement.setAttribute('data-theme', resolveTheme(next));
    updateThemeUI(next);
    if (currentUser) savePrefs(true);
}

function updateThemeUI(theme) {
    document.getElementById('themeIcon').innerHTML = theme === 'dark' ? '&#9790;' : '&#9728;';
    document.getElementById('themeLabel').textContent = theme === 'dark' ? 'Chế độ sáng' : 'Chế độ tối';
}

// ==================== NAV ====================
function setupNav() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            item.classList.add('active');
            currentView = item.dataset.view;

            const views = ['kanbanView', 'listView', 'pointsView', 'myPointsView', 'financeView', 'usersView', 'settingsView'];
            views.forEach(v => { const el = document.getElementById(v); if (el) el.style.display = 'none'; });

            const titles = { kanban: t('title_kanban'), list: t('title_list'), points: t('title_points'), 'my-points': t('title_mine'), finance: t('title_finance'), users: t('title_users'), settings: t('title_settings') };
            document.getElementById('viewTitle').textContent = titles[currentView] || '';
            document.getElementById('statsGrid').style.display = ['kanban', 'list'].includes(currentView) ? '' : 'none';

            if (currentView === 'kanban') document.getElementById('kanbanView').style.display = 'flex';
            else if (currentView === 'list') { document.getElementById('listView').style.display = 'block'; renderTasks(); }
            else if (currentView === 'points') { document.getElementById('pointsView').style.display = 'block'; loadPoints(); }
            else if (currentView === 'my-points') { document.getElementById('myPointsView').style.display = 'block'; loadMyPoints(); }
            else if (currentView === 'finance') { document.getElementById('financeView').style.display = 'block'; loadFinance(); }
            else if (currentView === 'users') { document.getElementById('usersView').style.display = 'block'; loadUsersList(); }
            else if (currentView === 'settings') { document.getElementById('settingsView').style.display = 'block'; loadSettings(); }
        });
    });
}

// ==================== FILTERS ====================
function getFilteredTasks() {
    const priority = document.getElementById('filterPriority').value;
    const status = document.getElementById('filterStatus').value;
    const search = document.getElementById('searchInput').value.toLowerCase().trim();
    return allTasks.filter(t => {
        if (priority && t.priority !== priority) return false;
        if (status && t.status !== status) return false;
        if (search) {
            if (!t.title.toLowerCase().includes(search) && !(t.description || '').toLowerCase().includes(search) &&
                !t.assigned_users.some(u => u.username.toLowerCase().includes(search))) return false;
        }
        return true;
    });
}

// ==================== LOAD DATA ====================
async function loadTasks() {
    try {
        const res = await fetch('/api/tasks');
        allTasks = await res.json();
        renderTasks();
    } catch (err) { showToast('Lỗi tải dữ liệu', 'error'); }
}

async function loadUsers() {
    try {
        const res = await fetch('/api/users');
        allUsers = await res.json();
        populateAssigneeCheckboxes();
    } catch (err) {}
}

function populateAssigneeCheckboxes() {
    document.getElementById('taskAssignees').innerHTML = allUsers.map(u =>
        `<label class="checkbox-label"><input type="checkbox" name="assignee" value="${u.id}"><span>${escapeHtml(u.username)}</span></label>`
    ).join('');
}

function getSelectedAssignees() {
    return Array.from(document.querySelectorAll('input[name="assignee"]:checked')).map(cb => parseInt(cb.value));
}

function setSelectedAssignees(ids) {
    document.querySelectorAll('input[name="assignee"]').forEach(cb => cb.checked = ids.includes(parseInt(cb.value)));
}

// ==================== STATS ====================
function updateStats() {
    const total = allTasks.length;
    const pending = allTasks.filter(t => t.status === 'pending').length;
    const inProgress = allTasks.filter(t => t.status === 'in_progress').length;
    const done = allTasks.filter(t => t.status === 'done').length;
    animateCounter('statTotal', total);
    animateCounter('statPending', pending);
    animateCounter('statInProgress', inProgress);
    animateCounter('statDone', done);
    if (currentUser) document.getElementById('statMyScore').textContent = currentUser.score || 0;
}

function animateCounter(id, target) {
    const el = document.getElementById(id);
    if (!el) return;
    const current = parseInt(el.textContent) || 0;
    if (current === target) return;
    const step = target > current ? 1 : -1;
    const diff = Math.abs(target - current);
    const duration = Math.min(300, diff * 50);
    const interval = duration / diff || 1;
    let count = current;
    const timer = setInterval(() => { count += step; el.textContent = count; if (count === target) clearInterval(timer); }, interval);
}

// ==================== RENDER ====================
function renderTasks() {
    const tasks = getFilteredTasks();
    document.getElementById('taskCount').textContent = `${tasks.length} ${t('tasks_suffix')}`;
    updateStats();
    if (currentView === 'kanban') renderKanban(tasks);
    else if (currentView === 'list') renderList(tasks);
}

function renderKanban(tasks) {
    const pending = tasks.filter(t => t.status === 'pending');
    const inProgress = tasks.filter(t => t.status === 'in_progress');
    const done = tasks.filter(t => t.status === 'done');
    document.getElementById('pendingCount').textContent = pending.length;
    document.getElementById('inProgressCount').textContent = inProgress.length;
    document.getElementById('doneCount').textContent = done.length;
    document.getElementById('pendingTasks').innerHTML = pending.length ? pending.map(createTaskCard).join('') : `<div class="empty-state"><p>${t('empty_tasks')}</p></div>`;
    document.getElementById('inProgressTasks').innerHTML = inProgress.length ? inProgress.map(createTaskCard).join('') : `<div class="empty-state"><p>${t('empty_tasks')}</p></div>`;
    document.getElementById('doneTasks').innerHTML = done.length ? done.map(createTaskCard).join('') : `<div class="empty-state"><p>${t('empty_tasks')}</p></div>`;
}

function createTaskCard(task) {
    const isAdmin = currentUser.role === 'bithu';
    const isClaimed = task.is_claimed_by_me;
    const isOverdue = task.due_date && new Date(task.due_date) < new Date() && task.status !== 'done';
    const canClaim = !isAdmin && !isClaimed && task.slots_left > 0 && task.status !== 'done';

    let adminActions = '';
    if (isAdmin) {
        adminActions = `<button class="btn-icon" onclick="openEditModal(${task.id})" title="Sửa">&#9998;</button><button class="btn-icon" onclick="openDeleteModal(${task.id}, '${escapeHtml(task.title)}')" title="Xóa">&#10005;</button>`;
    }

    const assigneeTags = task.assigned_users.map(u => `<span class="assignee-tag">@${escapeHtml(u.username)}</span>`).join('');
    const slotInfo = `<span class="slot-info">${task.assignee_count}/${task.max_assignees}</span>`;
    const pointsTag = task.points > 0 ? `<span class="priority-tag low">+${task.points}</span>` : '';

    let claimBtn = '';
    if (canClaim) claimBtn = `<button class="btn btn-claim" onclick="claimTask(${task.id})">${t('claim')}</button>`;
    else if (isClaimed && !isAdmin) claimBtn = `<button class="btn btn-unclaim" onclick="unclaimTask(${task.id})">${t('unclaim')}</button>`;

    let statusSelect = '';
    if (isClaimed || isAdmin) {
        statusSelect = `<select class="status-select" onchange="changeStatus(${task.id}, this.value)">
            <option value="pending" ${task.status === 'pending' ? 'selected' : ''}>${getStatusLabel('pending')}</option>
            <option value="in_progress" ${task.status === 'in_progress' ? 'selected' : ''}>${getStatusLabel('in_progress')}</option>
            <option value="done" ${task.status === 'done' ? 'selected' : ''}>${getStatusLabel('done')}</option>
        </select>`;
    }

    return `<div class="task-card" data-id="${task.id}">
        <div class="task-card-header">
            <div class="task-card-title">${escapeHtml(task.title)}</div>
            <div class="task-card-actions">${adminActions}</div>
        </div>
        ${task.description ? `<div class="task-card-desc">${escapeHtml(task.description)}</div>` : ''}
        <div class="task-card-footer">
            <div class="task-card-meta">
                <span class="priority-tag ${task.priority}">${getPriorityLabel(task.priority)}</span>
                ${assigneeTags || `<span class="assignee-tag" style="color:var(--text-muted)">${t('no_one')}</span>`}
                ${slotInfo} ${pointsTag}
                ${task.due_date ? `<span class="due-date ${isOverdue ? 'overdue' : ''}">${formatDate(task.due_date)}</span>` : ''}
            </div>
            <div class="task-card-actions-row">${statusSelect} ${claimBtn}</div>
        </div>
    </div>`;
}

function renderList(tasks) {
    const tbody = document.getElementById('taskTableBody');
    if (!tasks.length) { tbody.innerHTML = `<tr><td colspan="8" class="empty-state"><p>${t('empty_tasks')}</p></td></tr>`; return; }
    tbody.innerHTML = tasks.map(task => {
        const isAdmin = currentUser.role === 'bithu';
        const isClaimed = task.is_claimed_by_me;
        const isOverdue = task.due_date && new Date(task.due_date) < new Date() && task.status !== 'done';
        const canClaim = !isAdmin && !isClaimed && task.slots_left > 0 && task.status !== 'done';
        let adminActions = isAdmin ? `<button class="btn-icon" onclick="openEditModal(${task.id})">&#9998;</button><button class="btn-icon" onclick="openDeleteModal(${task.id}, '${escapeHtml(task.title)}')">&#10005;</button>` : '';
        const assigneeNames = task.assigned_users.map(u => escapeHtml(u.username)).join(', ');
        let statusCell = (isClaimed || isAdmin) ? `<select class="status-select" onchange="changeStatus(${task.id}, this.value)"><option value="pending" ${task.status === 'pending' ? 'selected' : ''}>${getStatusLabel('pending')}</option><option value="in_progress" ${task.status === 'in_progress' ? 'selected' : ''}>${getStatusLabel('in_progress')}</option><option value="done" ${task.status === 'done' ? 'selected' : ''}>${getStatusLabel('done')}</option></select>` : `<span class="status-label">${getStatusLabel(task.status)}</span>`;
        let claimBtn = canClaim ? `<button class="btn btn-claim btn-sm" onclick="claimTask(${task.id})">${t('claim_sm')}</button>` : isClaimed && !isAdmin ? `<button class="btn btn-unclaim btn-sm" onclick="unclaimTask(${task.id})">${t('unclaim')}</button>` : '';
        return `<tr><td><div class="task-title-cell">${escapeHtml(task.title)}${task.description ? `<small>${escapeHtml(task.description.substring(0, 60))}${task.description.length > 60 ? '...' : ''}</small>` : ''}</div></td><td>${statusCell}</td><td><span class="priority-tag ${task.priority}">${getPriorityLabel(task.priority)}</span></td><td>${assigneeNames || `<span style="color:var(--text-muted)">${t('no_one')}</span>`}</td><td><span class="slot-info">${task.assignee_count}/${task.max_assignees}</span></td><td>${task.points > 0 ? `<span class="priority-tag low">+${task.points}</span>` : '-'}</td><td>${task.due_date ? `<span class="due-date ${isOverdue ? 'overdue' : ''}">${formatDate(task.due_date)}</span>` : '-'}</td><td>${adminActions}${claimBtn}</td></tr>`;
    }).join('');
}

// ==================== POINTS ====================
async function loadPoints() {
    try {
        const res = await fetch('/api/points');
        allPoints = await res.json();
        renderPoints();
    } catch (err) { showToast('Lỗi tải điểm', 'error'); }
}

function renderPoints() {
    const tbody = document.getElementById('pointsTableBody');
    if (!allPoints.length) { tbody.innerHTML = `<tr><td colspan="4" class="empty-state"><p>${t('no_data')}</p></td></tr>`; return; }
    tbody.innerHTML = allPoints.map((u, i) => `<tr><td>${i + 1}</td><td><strong>${escapeHtml(u.username)}</strong></td><td><span class="priority-tag low" style="font-size:14px;">${u.score}</span></td><td><button class="btn btn-sm btn-secondary" onclick="openPointsDetail(${u.id}, '${escapeHtml(u.username)}')">${curLang() === 'en' ? 'View detail' : 'Xem chi tiết'}</button></td></tr>`).join('');
}

async function openPointsDetail(userId, username) {
    try {
        const res = await fetch(`/api/points/${userId}`);
        const data = await res.json();
        document.getElementById('pointsDetailTitle').textContent = `${curLang() === 'en' ? 'Points' : 'Điểm'} - ${username}`;
        document.getElementById('pointsDetailScore').textContent = data.user.score;
        const tbody = document.getElementById('pointsDetailLogBody');
        if (!data.logs.length) { tbody.innerHTML = `<tr><td colspan="3" class="empty-state"><p>${t('no_hist')}</p></td></tr>`; }
        else { tbody.innerHTML = data.logs.map(l => `<tr><td>${formatDate(l.created_at)}</td><td><span class="priority-tag ${l.points >= 0 ? 'low' : 'high'}">${l.points >= 0 ? '+' : ''}${l.points}</span></td><td>${escapeHtml(l.reason)}</td></tr>`).join(''); }
        document.getElementById('pointsDetailModal').classList.add('active');
    } catch (err) { showToast('Lỗi tải dữ liệu', 'error'); }
}

function closePointsDetailModal() { document.getElementById('pointsDetailModal').classList.remove('active'); }

function openAddPointsModal() {
    document.getElementById('pointsUserId').innerHTML = allUsers.map(u => `<option value="${u.id}">${escapeHtml(u.username)}</option>`).join('');
    document.getElementById('pointsValue').value = '';
    document.getElementById('pointsReason').value = '';
    document.getElementById('pointsError').textContent = '';
    document.getElementById('addPointsModal').classList.add('active');
}

function closeAddPointsModal() { document.getElementById('addPointsModal').classList.remove('active'); }

async function submitPoints() {
    const userId = document.getElementById('pointsUserId').value;
    const points = document.getElementById('pointsValue').value;
    const reason = document.getElementById('pointsReason').value.trim();
    const errorEl = document.getElementById('pointsError');
    if (!userId || !points || !reason) { errorEl.textContent = 'Đầy đủ thông tin'; return; }
    try {
        const res = await fetch('/api/points', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: parseInt(userId), points: parseInt(points), reason }) });
        const data = await res.json();
        if (!res.ok) { errorEl.textContent = data.error; return; }
        closeAddPointsModal();
        await loadPoints();
        showToast('Đã cập nhật điểm', 'success');
    } catch (err) { errorEl.textContent = 'Lỗi kết nối'; }
}

async function loadMyPoints() {
    try {
        const res = await fetch(`/api/points/${currentUser.id}`);
        const data = await res.json();
        document.getElementById('myScore').textContent = data.user.score;
        const tbody = document.getElementById('myPointsLogBody');
        if (!data.logs.length) { tbody.innerHTML = `<tr><td colspan="3" class="empty-state"><p>${t('no_points')}</p></td></tr>`; }
        else { tbody.innerHTML = data.logs.map(l => `<tr><td>${formatDate(l.created_at)}</td><td><span class="priority-tag ${l.points >= 0 ? 'low' : 'high'}">${l.points >= 0 ? '+' : ''}${l.points}</span></td><td>${escapeHtml(l.reason)}</td></tr>`).join(''); }
    } catch (err) { showToast('Lỗi tải dữ liệu', 'error'); }
}

// ==================== FINANCE ====================
async function loadFinance() {
    try {
        const [listRes, summaryRes] = await Promise.all([fetch('/api/finance'), fetch('/api/finance/summary')]);
        const transactions = await listRes.json();
        const summary = await summaryRes.json();
        document.getElementById('financeIncome').textContent = formatMoney(summary.income);
        document.getElementById('financeExpense').textContent = formatMoney(summary.expense);
        document.getElementById('financeFund').textContent = formatMoney(summary.fund);
        const tbody = document.getElementById('financeTableBody');
        if (!transactions.length) { tbody.innerHTML = `<tr><td colspan="6" class="empty-state"><p>${t('no_hist')}</p></td></tr>`; return; }
        tbody.innerHTML = transactions.map(t => `<tr><td>${formatDate(t.date)}</td><td><span class="priority-tag ${t.type === 'income' ? 'low' : 'high'}">${t.type === 'income' ? t('income') : t('expense').split(' ')[0]}</span></td><td><strong>${formatMoney(t.amount)}</strong></td><td>${escapeHtml(t.description) || '-'}</td><td>${escapeHtml(t.category) || '-'}</td><td><button class="btn-icon" onclick="deleteFinance(${t.id})">&#10005;</button></td></tr>`).join('');
    } catch (err) { showToast('Lỗi tải dữ liệu', 'error'); }
}

function openAddFinanceModal() {
    document.getElementById('financeType').value = 'income';
    document.getElementById('financeAmount').value = '';
    document.getElementById('financeDesc').value = '';
    document.getElementById('financeCategory').value = '';
    document.getElementById('financeError').textContent = '';
    document.getElementById('addFinanceModal').classList.add('active');
}

function closeAddFinanceModal() { document.getElementById('addFinanceModal').classList.remove('active'); }

async function submitFinance() {
    const type = document.getElementById('financeType').value;
    const amount = document.getElementById('financeAmount').value;
    const description = document.getElementById('financeDesc').value.trim();
    const category = document.getElementById('financeCategory').value.trim();
    const errorEl = document.getElementById('financeError');
    if (!amount) { errorEl.textContent = 'Nhập số tiền'; return; }
    try {
        const res = await fetch('/api/finance', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type, amount: parseFloat(amount), description, category }) });
        const data = await res.json();
        if (!res.ok) { errorEl.textContent = data.error; return; }
        closeAddFinanceModal();
        await loadFinance();
        showToast('Đã thêm giao dịch', 'success');
    } catch (err) { errorEl.textContent = 'Lỗi kết nối'; }
}

async function deleteFinance(id) {
    if (!confirm('Xóa giao dịch này?')) return;
    try {
        await fetch(`/api/finance/${id}`, { method: 'DELETE' });
        await loadFinance();
        showToast('Đã xóa giao dịch', 'success');
    } catch (err) { showToast('Lỗi', 'error'); }
}

// ==================== CLAIM ====================
async function claimTask(taskId) {
    try {
        const res = await fetch(`/api/tasks/${taskId}/claim`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) { showToast(data.error, 'error'); return; }
        await loadTasks();
        showToast('Đã nhận task', 'success');
    } catch (err) { showToast('Lỗi kết nối', 'error'); }
}

async function unclaimTask(taskId) {
    try {
        const res = await fetch(`/api/tasks/${taskId}/claim`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: currentUser.id }) });
        const data = await res.json();
        if (!res.ok) { showToast(data.error, 'error'); return; }
        await loadTasks();
        showToast('Đã bỏ nhận', 'success');
    } catch (err) { showToast('Lỗi kết nối', 'error'); }
}

async function changeStatus(taskId, newStatus) {
    try {
        const res = await fetch(`/api/tasks/${taskId}/status`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: newStatus }) });
        if (!res.ok) { const data = await res.json(); showToast(data.error, 'error'); return; }
        await loadTasks();
        showToast('Đã cập nhật', 'success');
    } catch (err) { showToast('Lỗi kết nối', 'error'); }
}

// ==================== MODALS ====================
function openTaskModal(taskId = null) {
    document.getElementById('taskFormError').textContent = '';
    if (taskId) {
        const task = allTasks.find(t => t.id === taskId);
        if (!task) return;
        document.getElementById('modalTitle').textContent = t('edit_task');
        document.getElementById('taskId').value = task.id;
        document.getElementById('taskTitle').value = task.title;
        document.getElementById('taskDesc').value = task.description || '';
        document.getElementById('taskStatus').value = task.status;
        document.getElementById('taskPriority').value = task.priority;
        document.getElementById('taskMaxAssignees').value = task.max_assignees;
        document.getElementById('taskDueDate').value = task.due_date || '';
        document.getElementById('taskPoints').value = task.points || 0;
        setSelectedAssignees(task.assigned_users.map(u => u.id));
    } else {
        document.getElementById('modalTitle').textContent = t('new_task');
        document.getElementById('taskForm').reset();
        document.getElementById('taskId').value = '';
        document.getElementById('taskPriority').value = 'medium';
        document.getElementById('taskMaxAssignees').value = 3;
        document.getElementById('taskPoints').value = 0;
        setSelectedAssignees([]);
    }
    document.getElementById('taskModal').classList.add('active');
}

function closeTaskModal() { document.getElementById('taskModal').classList.remove('active'); }
function openEditModal(taskId) { openTaskModal(taskId); }
function openDeleteModal(taskId, title) { deleteTaskId = taskId; document.getElementById('deleteTaskName').textContent = title; document.getElementById('deleteModal').classList.add('active'); }
function closeDeleteModal() { document.getElementById('deleteModal').classList.remove('active'); deleteTaskId = null; }

async function saveTask() {
    const errorEl = document.getElementById('taskFormError');
    errorEl.textContent = '';
    const title = document.getElementById('taskTitle').value.trim();
    if (!title) { errorEl.textContent = 'Tiêu đề không được để trống'; return; }
    const maxAssignees = parseInt(document.getElementById('taskMaxAssignees').value) || 3;
    const assignedTo = getSelectedAssignees();
    if (assignedTo.length > maxAssignees) { errorEl.textContent = `Tối đa giao cho ${maxAssignees} người`; return; }
    const taskId = document.getElementById('taskId').value;
    const payload = {
        title, description: document.getElementById('taskDesc').value.trim(),
        status: document.getElementById('taskStatus').value, priority: document.getElementById('taskPriority').value,
        max_assignees: maxAssignees, assigned_to: assignedTo,
        due_date: document.getElementById('taskDueDate').value || null,
        points: parseInt(document.getElementById('taskPoints').value) || 0
    };
    try {
        const url = taskId ? `/api/tasks/${taskId}` : '/api/tasks';
        const method = taskId ? 'PUT' : 'POST';
        const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const data = await res.json();
        if (!res.ok) { errorEl.textContent = data.error; return; }
        closeTaskModal();
        await loadTasks();
        showToast(taskId ? 'Đã cập nhật task' : 'Đã tạo task', 'success');
    } catch (err) { errorEl.textContent = 'Lỗi kết nối'; }
}

async function confirmDelete() {
    if (!deleteTaskId) return;
    try {
        const res = await fetch(`/api/tasks/${deleteTaskId}`, { method: 'DELETE' });
        if (!res.ok) { showToast('Lỗi xóa', 'error'); return; }
        closeDeleteModal();
        await loadTasks();
        showToast('Đã xóa task', 'success');
    } catch (err) { showToast('Lỗi kết nối', 'error'); }
}

// ==================== USERS MANAGEMENT ====================
async function loadUsersList() {
    try {
        const res = await fetch('/api/users');
        const users = await res.json();
        const tbody = document.getElementById('usersTableBody');
        if (!users.length) { tbody.innerHTML = `<tr><td colspan="5" class="empty-state"><p>${t('no_data')}</p></td></tr>`; return; }
        tbody.innerHTML = users.map(u => {
            const roleOptions = ['user', 'bithu'].map(r =>
                `<option value="${r}" ${u.role === r ? 'selected' : ''}>${r === 'bithu' ? t('role_bithu') : t('role_user')}</option>`
            ).join('');
            return `<tr>
                <td><strong>${escapeHtml(u.username)}</strong>${u.full_name ? `<br><small style="color:var(--text-muted)">${escapeHtml(u.full_name)}</small>` : ''}</td>
                <td><div style="display:flex;gap:4px;"><input type="text" value="${escapeHtml(u.title || '')}" id="title-${u.id}" placeholder="${t('th_title_col')}" style="width:120px;"><button class="btn btn-sm btn-secondary" onclick="updateUserTitle(${u.id})">${t('save')}</button></div></td>
                <td><select class="status-select" onchange="updateUserRole(${u.id}, this.value)">${roleOptions}</select></td>
                <td>${u.score || 0}</td>
                <td></td>
            </tr>`;
        }).join('');
    } catch (err) { showToast('Lỗi tải danh sách user', 'error'); }
}

async function updateUserTitle(userId) {
    const el = document.getElementById('title-' + userId);
    const title = el ? el.value : '';
    try {
        const res = await fetch(`/api/users/${userId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title })
        });
        const data = await res.json();
        if (!res.ok) { showToast(data.error || 'Lỗi cập nhật', 'error'); return; }
        showToast('Đã cập nhật chức danh', 'success');
    } catch (err) { showToast('Lỗi kết nối', 'error'); }
}

async function updateUserRole(userId, newRole) {
    try {
        const res = await fetch(`/api/users/${userId}/role`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role: newRole })
        });
        const data = await res.json();
        if (!res.ok) { showToast(data.error || 'Lỗi cập nhật', 'error'); loadUsersList(); return; }
        showToast('Đã cập nhật role', 'success');
    } catch (err) { showToast('Lỗi kết nối', 'error'); }
}

// ==================== UTILS ====================
function logout() { fetch('/api/logout').then(() => window.location.href = '/login'); }

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type} show`;
    setTimeout(() => toast.classList.remove('show'), 3000);
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ==================== I18N ====================
const I18N = {
vi: {
    nav_kanban: 'Kanban Board', nav_list: 'Danh sách', nav_points: 'Điểm tổng hợp', nav_finance: 'Tài chính',
    nav_users: 'Quản lý user', nav_mine: 'Điểm của tôi', nav_settings: 'Cài đặt', logout: 'Đăng xuất',
    role_bithu: 'Bí thư', role_user: 'Đoàn viên',
    stat_total: 'Tổng nhiệm vụ', stat_pending: 'Chờ xử lý', stat_inprog: 'Đang thực hiện', stat_done: 'Hoàn thành', stat_mine: 'Điểm của bạn',
    tasks_suffix: 'nhiệm vụ', search_ph: 'Tìm nhiệm vụ...', f_all_prio: 'Tất cả ưu tiên', f_all_status: 'Tất cả trạng thái', add_task: '+ Thêm nhiệm vụ',
    empty_tasks: 'Không có task nào', no_data: 'Chưa có dữ liệu', no_points: 'Chưa có điểm', no_hist: 'Chưa có lịch sử',
    th_task: 'Nhiệm vụ', th_status: 'Trạng thái', th_priority: 'Ưu tiên', th_assignee: 'Người thực hiện', th_slot: 'Slot',
    th_points: 'Điểm', th_due: 'Hạn chót', th_action: 'Thao tác', th_no: 'STT', th_member: 'Đoàn viên', th_total: 'Tổng điểm',
    th_date: 'Ngày', th_point: 'Điểm', th_reason: 'Lý do', th_type: 'Loại', th_amount: 'Số tiền', th_desc: 'Mô tả',
    th_category: 'Loại chi', th_username: 'Username', th_title_col: 'Chức danh', th_role: 'Role', th_score: 'Điểm',
    th_time: 'Thời gian', th_ip: 'IP', th_device: 'Thiết bị', th_trigger: 'Trigger', th_event: 'Event', th_url: 'URL', th_deleted: 'Xóa lúc', th_name: 'Tên',
    points_title: 'Bảng điểm tổng hợp', add_points: '+ Cộng điểm', my_total: 'Tổng điểm của bạn', points_hist: 'Lịch sử điểm',
    fin_fund: 'Quỹ hiện tại', fin_in: 'Tổng thu', fin_out: 'Tổng chi', fin_hist: 'Lịch sử giao dịch', add_trans: '+ Thêm giao dịch', update_fund: 'Cập nhật quỹ',
    users_title: 'Quản lý người dùng', save: 'Lưu', cancel: 'Hủy', confirm: 'Xác nhận', close: 'Đóng',
    claim: 'Nhận task', claim_sm: 'Nhận', unclaim: 'Bỏ nhận', no_one: 'Chưa ai nhận',
    title_kanban: 'Kanban Board', title_list: 'Danh sách', title_points: 'Điểm tổng hợp', title_mine: 'Điểm của tôi',
    title_finance: 'Tài chính', title_users: 'Quản lý user', title_settings: 'Cài đặt',
    tab_profile: 'Hồ sơ', tab_security: 'Bảo mật', tab_display: 'Giao diện', tab_int: 'Tích hợp', tab_data: 'Dữ liệu',
    profile_h: 'Thông tin cá nhân', lbl_name: 'Họ tên', lbl_dept: 'Phòng ban', lbl_phone: 'Số điện thoại', lbl_email: 'Email liên hệ',
    lbl_avatar: 'Avatar (URL)', lbl_title_ro: 'Chức danh (chỉ Bí thư đổi)', save_profile: 'Lưu hồ sơ',
    sec_pass: 'Đổi mật khẩu', old_pass: 'Mật khẩu cũ', new_pass: 'Mật khẩu mới', change_pass_btn: 'Đổi mật khẩu',
    tfa: 'Xác thực 2 yếu tố (2FA)', tfa_status: 'Trạng thái:', on: 'Bật', off: 'Tắt',
    tfa_code_lbl: 'Nhập mã 6 số từ app Authenticator', tfa_confirm: 'Xác nhận bật 2FA', tfa_gen: 'Tạo mã 2FA', tfa_off: 'Tắt 2FA',
    login_hist: 'Lịch sử đăng nhập / Thiết bị',
    disp_h: 'Chế độ hiển thị', lbl_theme: 'Theme', theme_dark: 'Tối', theme_light: 'Sáng', theme_sys: 'Theo hệ thống',
    lbl_default_view: 'Giao diện công việc mặc định', lbl_lang: 'Ngôn ngữ', lbl_tz: 'Múi giờ',
    lbl_datefmt: 'Định dạng ngày', lbl_timefmt: 'Định dạng giờ', save_display: 'Lưu giao diện',
    int_cal: 'Lịch cá nhân', int_google: 'Đồng bộ deadline sang Google Calendar', int_outlook: 'Đồng bộ deadline sang Outlook Calendar',
    ics_btn: 'Tải file lịch (.ics)', int_files: 'Lưu trữ tệp', int_auto: 'Quy tắc tự động hóa',
    auto_unfollow: 'Hoàn thành → tự bỏ theo dõi', auto_warn: 'Quá hạn → cảnh báo', add_rule: '+ Thêm rule',
    save_int: 'Lưu tích hợp', api_wh: 'API & Webhook', api_token: 'API Token', regen: 'Tạo mới', add_wh: '+ Thêm webhook',
    data_io: 'Nhập / Xuất dữ liệu', export_tasks: 'Xuất tasks CSV', export_fin: 'Xuất tài chính CSV',
    import_lbl: 'Dán CSV để nhập tasks (cột: title,description,status,priority,due_date,points)', import_btn: 'Nhập tasks',
    trash_h: 'Thùng rác (giữ 30 ngày)', trash_empty: 'Thùng rác trống', restore: 'Khôi phục', purge: 'Xóa vĩnh viễn',
    storage_h: 'Dung lượng',
    new_task: 'Thêm nhiệm vụ mới', edit_task: 'Sửa nhiệm vụ', lbl_task_title: 'Tiêu đề *', lbl_task_desc: 'Mô tả',
    lbl_task_status: 'Trạng thái', lbl_task_prio: 'Ưu tiên', assign_to: 'Giao cho (tối đa 3 người)', max_claim: 'Số người tối đa nhận task',
    due: 'Hạn chót', pts_done: 'Điểm khi hoàn thành',
    confirm_del: 'Xác nhận xóa', del_q: 'Bạn có chắc muốn xóa nhiệm vụ này?', del_btn: 'Xóa',
    addsub: 'Cộng/trừ điểm', member: 'Đoàn viên', pts_lbl: 'Điểm (cộng +, trừ -)', reason: 'Lý do', points_total: 'Tổng điểm',
    add_fin_trans: 'Thêm giao dịch', trans_type: 'Loại giao dịch', income: 'Thu', expense: 'Chi (tự trừ quỹ)',
    amount: 'Số tiền', desc: 'Mô tả', category: 'Loại chi / Nhóm',
    update_fund_h: 'Cập nhật quỹ', fund_balance: 'Số dư quỹ hiện tại', op: 'Thao tác',
    op_set: 'Đặt lại số dư', op_add: 'Cộng thêm', op_sub: 'Trừ bớt'
},
en: {
    nav_kanban: 'Kanban Board', nav_list: 'List', nav_points: 'Points overview', nav_finance: 'Finance',
    nav_users: 'Users', nav_mine: 'My points', nav_settings: 'Settings', logout: 'Logout',
    role_bithu: 'Secretary', role_user: 'Member',
    stat_total: 'Total tasks', stat_pending: 'Pending', stat_inprog: 'In progress', stat_done: 'Done', stat_mine: 'Your points',
    tasks_suffix: 'tasks', search_ph: 'Search tasks...', f_all_prio: 'All priorities', f_all_status: 'All statuses', add_task: '+ Add task',
    empty_tasks: 'No tasks', no_data: 'No data', no_points: 'No points yet', no_hist: 'No history',
    th_task: 'Task', th_status: 'Status', th_priority: 'Priority', th_assignee: 'Assignees', th_slot: 'Slot',
    th_points: 'Points', th_due: 'Due date', th_action: 'Actions', th_no: '#', th_member: 'Member', th_total: 'Total',
    th_date: 'Date', th_point: 'Points', th_reason: 'Reason', th_type: 'Type', th_amount: 'Amount', th_desc: 'Description',
    th_category: 'Category', th_username: 'Username', th_title_col: 'Title', th_role: 'Role', th_score: 'Points',
    th_time: 'Time', th_ip: 'IP', th_device: 'Device', th_trigger: 'Trigger', th_event: 'Event', th_url: 'URL', th_deleted: 'Deleted at', th_name: 'Name',
    points_title: 'Points leaderboard', add_points: '+ Add points', my_total: 'Your total points', points_hist: 'Points history',
    fin_fund: 'Current fund', fin_in: 'Total income', fin_out: 'Total expense', fin_hist: 'Transactions', add_trans: '+ Add transaction', update_fund: 'Update fund',
    users_title: 'User management', save: 'Save', cancel: 'Cancel', confirm: 'Confirm', close: 'Close',
    claim: 'Claim task', claim_sm: 'Claim', unclaim: 'Unclaim', no_one: 'Unclaimed',
    title_kanban: 'Kanban Board', title_list: 'List', title_points: 'Points overview', title_mine: 'My points',
    title_finance: 'Finance', title_users: 'Users', title_settings: 'Settings',
    tab_profile: 'Profile', tab_security: 'Security', tab_display: 'Display', tab_int: 'Integrations', tab_data: 'Data',
    profile_h: 'Personal info', lbl_name: 'Full name', lbl_dept: 'Department', lbl_phone: 'Phone', lbl_email: 'Contact email',
    lbl_avatar: 'Avatar (URL)', lbl_title_ro: 'Title (Secretary only)', save_profile: 'Save profile',
    sec_pass: 'Change password', old_pass: 'Old password', new_pass: 'New password', change_pass_btn: 'Change password',
    tfa: 'Two-factor auth (2FA)', tfa_status: 'Status:', on: 'On', off: 'Off',
    tfa_code_lbl: 'Enter 6-digit code from Authenticator app', tfa_confirm: 'Confirm enable 2FA', tfa_gen: 'Generate 2FA', tfa_off: 'Disable 2FA',
    login_hist: 'Login history / Devices',
    disp_h: 'Display mode', lbl_theme: 'Theme', theme_dark: 'Dark', theme_light: 'Light', theme_sys: 'System',
    lbl_default_view: 'Default task view', lbl_lang: 'Language', lbl_tz: 'Timezone',
    lbl_datefmt: 'Date format', lbl_timefmt: 'Time format', save_display: 'Save display',
    int_cal: 'Personal calendar', int_google: 'Sync deadlines to Google Calendar', int_outlook: 'Sync deadlines to Outlook Calendar',
    ics_btn: 'Download calendar (.ics)', int_files: 'File storage', int_auto: 'Automation rules',
    auto_unfollow: 'On complete → auto unclaim', auto_warn: 'On overdue → warn', add_rule: '+ Add rule',
    save_int: 'Save integrations', api_wh: 'API & Webhook', api_token: 'API Token', regen: 'Regenerate', add_wh: '+ Add webhook',
    data_io: 'Import / Export', export_tasks: 'Export tasks CSV', export_fin: 'Export finance CSV',
    import_lbl: 'Paste CSV to import tasks (columns: title,description,status,priority,due_date,points)', import_btn: 'Import tasks',
    trash_h: 'Trash (kept 30 days)', trash_empty: 'Trash is empty', restore: 'Restore', purge: 'Delete forever',
    storage_h: 'Storage',
    new_task: 'Add new task', edit_task: 'Edit task', lbl_task_title: 'Title *', lbl_task_desc: 'Description',
    lbl_task_status: 'Status', lbl_task_prio: 'Priority', assign_to: 'Assign to (max 3)', max_claim: 'Max claimants',
    due: 'Due date', pts_done: 'Points on completion',
    confirm_del: 'Confirm delete', del_q: 'Are you sure you want to delete this task?', del_btn: 'Delete',
    addsub: 'Add/deduct points', member: 'Member', pts_lbl: 'Points (+ add, - deduct)', reason: 'Reason', points_total: 'Total points',
    add_fin_trans: 'Add transaction', trans_type: 'Transaction type', income: 'Income', expense: 'Expense (from fund)',
    amount: 'Amount', desc: 'Description', category: 'Category',
    update_fund_h: 'Update fund', fund_balance: 'Current balance', op: 'Operation',
    op_set: 'Reset balance', op_add: 'Add', op_sub: 'Subtract'
}
};
function curLang() { return localStorage.getItem('lang') || (currentUser && currentUser.language) || 'vi'; }
function t(k) { const L = curLang(); return (I18N[L] && I18N[L][k]) || I18N.vi[k] || k; }
function getPriorityLabel(p) { const L = curLang() === 'en' ? { low: 'Low', medium: 'Med', high: 'High' } : { low: 'Thấp', medium: 'TB', high: 'Cao' }; return L[p] || p; }
function getStatusLabel(s) { const L = curLang() === 'en' ? { pending: 'Pending', in_progress: 'In progress', done: 'Done' } : { pending: 'Chờ xử lý', in_progress: 'Đang thực hiện', done: 'Hoàn thành' }; return L[s] || s; }
function formatDate(d) {
    if (!d) return '';
    const dt = new Date(d);
    const fmt = localStorage.getItem('date_format') || (currentUser && currentUser.date_format) || 'DD/MM/YYYY';
    const tf = localStorage.getItem('time_format') || (currentUser && currentUser.time_format) || '24h';
    const dd = String(dt.getDate()).padStart(2, '0');
    const mm = String(dt.getMonth() + 1).padStart(2, '0');
    const yyyy = dt.getFullYear();
    let s = fmt === 'MM/DD/YYYY' ? `${mm}/${dd}/${yyyy}` : `${dd}/${mm}/${yyyy}`;
    if (String(d).length > 10) {
        let h = dt.getHours(); const mi = String(dt.getMinutes()).padStart(2, '0');
        if (tf === '12h') { const ap = h >= 12 ? 'PM' : 'AM'; h = h % 12 || 12; s += ` ${h}:${mi} ${ap}`; }
        else s += ` ${String(h).padStart(2, '0')}:${mi}`;
    }
    return s;
}
function formatMoney(n) { return new Intl.NumberFormat('vi-VN').format(n) + ' VND'; }

// ==================== FUND ====================
async function openEditFundModal() {
    try {
        const res = await fetch('/api/fund');
        const fund = await res.json();
        document.getElementById('fundCurrentBalance').textContent = formatMoney(fund.balance);
        document.getElementById('fundAmount').value = '';
        document.getElementById('fundError').textContent = '';
        document.getElementById('editFundModal').classList.add('active');
    } catch (err) { showToast('Lỗi tải dữ liệu', 'error'); }
}

function closeEditFundModal() { document.getElementById('editFundModal').classList.remove('active'); }

async function submitFund() {
    const action = document.getElementById('fundAction').value;
    const amount = document.getElementById('fundAmount').value;
    const errorEl = document.getElementById('fundError');
    if (!amount) { errorEl.textContent = 'Nhập số tiền'; return; }
    try {
        let res;
        if (action === 'set') {
            res = await fetch('/api/fund/set', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ amount: parseFloat(amount) }) });
        } else if (action === 'add') {
            res = await fetch('/api/fund', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ amount: parseFloat(amount) }) });
        } else {
            res = await fetch('/api/fund', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ amount: -parseFloat(amount) }) });
        }
        const data = await res.json();
        if (!res.ok) { errorEl.textContent = data.error; return; }
        closeEditFundModal();
        await loadFinance();
        showToast('Đã cập nhật quỹ', 'success');
    } catch (err) { errorEl.textContent = 'Lỗi kết nối'; }
}

document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeTaskModal(); closeDeleteModal(); closeAddPointsModal(); closeAddFinanceModal(); closePointsDetailModal(); closeEditFundModal(); } });

// ==================== SETTINGS ====================
function switchSettingsTab(tab) {
    document.querySelectorAll('.settings-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    ['profile', 'security', 'display', 'integrations', 'data'].forEach(t => {
        const el = document.getElementById('settings-' + t);
        if (el) el.style.display = t === tab ? 'block' : 'none';
    });
}

function fillSettings() {
    if (!currentUser) return;
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v || ''; };
    set('setFullName', currentUser.full_name);
    set('setDept', currentUser.department); set('setPhone', currentUser.phone);
    set('setEmail', currentUser.email); set('setAvatar', currentUser.avatar);
    set('setTitleRO', currentUser.title);
    set('setTheme', currentUser.theme || localStorage.getItem('theme') || 'dark');
    set('setDefaultView', currentUser.default_view || 'kanban');
    set('setLang', currentUser.language || 'vi'); set('setTz', currentUser.timezone || 'Asia/Ho_Chi_Minh');
    set('setDateFmt', currentUser.date_format || 'DD/MM/YYYY'); set('setTimeFmt', currentUser.time_format || '24h');
    const chk = (id, v) => { const el = document.getElementById(id); if (el) el.checked = !!v; };
    chk('intGoogle', currentUser.cal_google); chk('intOutlook', currentUser.cal_outlook);
    chk('intDrive', currentUser.store_drive); chk('intOneDrive', currentUser.store_onedrive);
    chk('intDropbox', currentUser.store_dropbox);
    chk('autoUnfollow', currentUser.auto_done_unfollow); chk('autoWarn', currentUser.auto_overdue_warn);
    const tok = document.getElementById('apiToken'); if (tok) tok.value = currentUser.api_token || '';
    const st = document.getElementById('twofaStatus'); if (st) st.textContent = currentUser.twofa_enabled ? t('on') : t('off');
    if (currentUser.avatar) document.getElementById('userAvatar').textContent = (currentUser.full_name || currentUser.username)[0].toUpperCase();
    localStorage.setItem('date_format', currentUser.date_format || 'DD/MM/YYYY');
    localStorage.setItem('time_format', currentUser.time_format || '24h');
    if (!localStorage.getItem('theme') && currentUser.theme) {
        localStorage.setItem('theme', currentUser.theme);
        document.documentElement.setAttribute('data-theme', resolveTheme(currentUser.theme));
        updateThemeUI(currentUser.theme);
    }
}

async function loadSettings() {
    fillSettings();
    loadLoginHistory(); loadRules(); loadWebhooks(); loadTrash(); loadStorage();
    if (currentUser && currentUser.role === 'bithu') { loadRules(); loadWebhooks(); loadTrash(); }
}

async function saveProfile() {
    const body = {
        full_name: document.getElementById('setFullName').value,
        department: document.getElementById('setDept').value,
        phone: document.getElementById('setPhone').value,
        email: document.getElementById('setEmail').value,
        avatar: document.getElementById('setAvatar').value
    };
    const res = await fetch('/api/profile', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await res.json();
    if (!res.ok) { showToast(data.error || 'Lỗi lưu', 'error'); return; }
    currentUser = data; fillSettings();
    document.getElementById('userName').textContent = currentUser.full_name || currentUser.username;
    showToast('Đã lưu hồ sơ', 'success');
}

async function savePrefs(silent) {
    const body = {
        theme: document.getElementById('setTheme') ? document.getElementById('setTheme').value : (localStorage.getItem('theme') || 'dark'),
        default_view: document.getElementById('setDefaultView') ? document.getElementById('setDefaultView').value : 'kanban',
        language: document.getElementById('setLang') ? document.getElementById('setLang').value : 'vi',
        timezone: document.getElementById('setTz') ? document.getElementById('setTz').value : 'Asia/Ho_Chi_Minh',
        date_format: document.getElementById('setDateFmt') ? document.getElementById('setDateFmt').value : 'DD/MM/YYYY',
        time_format: document.getElementById('setTimeFmt') ? document.getElementById('setTimeFmt').value : '24h'
    };
    localStorage.setItem('theme', body.theme);
    localStorage.setItem('date_format', body.date_format);
    localStorage.setItem('time_format', body.time_format);
    document.documentElement.setAttribute('data-theme', resolveTheme(body.theme));
    updateThemeUI(body.theme);
    applyLang(body.language);
    const res = await fetch('/api/profile', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) { if (!silent) showToast('Lỗi lưu giao diện', 'error'); return; }
    currentUser = await res.json();
    if (!silent) showToast('Đã lưu giao diện', 'success');
}

function applyLang(lang) {
    if (lang) localStorage.setItem('lang', lang);
    document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-ph]').forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
    const icons = { kanban: '&#9638;', list: '&#9776;', points: '&#11088;', finance: '&#128176;', users: '&#128101;', 'my-points': '&#11088;', settings: '&#9881;' };
    const navKeys = { kanban: 'nav_kanban', list: 'nav_list', points: 'nav_points', finance: 'nav_finance', users: 'nav_users', 'my-points': 'nav_mine', settings: 'nav_settings' };
    document.querySelectorAll('.nav-item').forEach(n => {
        const k = navKeys[n.dataset.view];
        if (k) n.innerHTML = `<span class="nav-icon">${icons[n.dataset.view] || ''}</span> ${t(k)}`;
    });
    const titles = { kanban: t('title_kanban'), list: t('title_list'), points: t('title_points'), 'my-points': t('title_mine'), finance: t('title_finance'), users: t('title_users'), settings: t('title_settings') };
    const vt = document.getElementById('viewTitle');
    if (vt && titles[currentView]) vt.textContent = titles[currentView];
    const fp = document.getElementById('filterPriority');
    if (fp && fp.options.length >= 4) {
        fp.options[0].textContent = t('f_all_prio');
        fp.options[1].textContent = getPriorityLabel('low'); fp.options[2].textContent = getPriorityLabel('medium'); fp.options[3].textContent = getPriorityLabel('high');
    }
    const fs = document.getElementById('filterStatus');
    if (fs && fs.options.length >= 4) {
        fs.options[0].textContent = t('f_all_status');
        fs.options[1].textContent = getStatusLabel('pending'); fs.options[2].textContent = getStatusLabel('in_progress'); fs.options[3].textContent = getStatusLabel('done');
    }
    const roleEl = document.getElementById('userRole');
    if (roleEl && currentUser) roleEl.textContent = currentUser.role === 'bithu' ? t('role_bithu') : t('role_user');
    const setOpts = (id, map) => {
        const sel = document.getElementById(id);
        if (!sel) return;
        Array.from(sel.options).forEach(o => { if (map[o.value]) o.textContent = map[o.value]; });
    };
    setOpts('taskStatus', { pending: getStatusLabel('pending'), in_progress: getStatusLabel('in_progress'), done: getStatusLabel('done') });
    setOpts('taskPriority', { low: getPriorityLabel('low'), medium: getPriorityLabel('medium'), high: getPriorityLabel('high') });
    setOpts('financeType', { income: t('income'), expense: t('expense') });
    setOpts('fundAction', { set: t('op_set'), add: t('op_add'), subtract: t('op_sub') });
    setOpts('setTheme', { dark: t('theme_dark'), light: t('theme_light'), system: t('theme_sys') });
    setOpts('setDefaultView', { kanban: 'Kanban', list: t('nav_list') });
    renderTasks();
}

async function changePassword() {
    const res = await fetch('/api/change-password', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_password: document.getElementById('oldPass').value, new_password: document.getElementById('newPass').value }) });
    const data = await res.json();
    if (!res.ok) { showToast(data.error || 'Lỗi', 'error'); return; }
    showToast('Đã đổi mật khẩu', 'success');
    document.getElementById('oldPass').value = ''; document.getElementById('newPass').value = '';
}

async function setup2FA() {
    const res = await fetch('/api/2fa/setup', { method: 'POST' });
    const data = await res.json();
    document.getElementById('twofaSetupBox').style.display = 'block';
    document.getElementById('twofaSecret').textContent = data.secret;
    showToast('Quét secret vào app Authenticator', 'info');
}
async function enable2FA() {
    const res = await fetch('/api/2fa/enable', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: document.getElementById('twofaCode').value }) });
    const data = await res.json();
    if (!res.ok) { showToast(data.error || 'Lỗi', 'error'); return; }
    currentUser.twofa_enabled = 1; fillSettings(); showToast('Đã bật 2FA', 'success');
}
async function disable2FA() {
    const res = await fetch('/api/2fa/disable', { method: 'POST' });
    await res.json(); currentUser.twofa_enabled = 0; fillSettings(); showToast('Đã tắt 2FA', 'success');
}
async function loadLoginHistory() {
    try {
        const res = await fetch('/api/login-history');
        const rows = await res.json();
        const tb = document.getElementById('loginHistoryBody');
        if (!tb) return;
        tb.innerHTML = rows.length ? rows.map(r => `<tr><td>${formatDate(r.created_at)}</td><td>${escapeHtml(r.ip || '-')}</td><td><small>${escapeHtml((r.user_agent || '').substring(0, 60))}</small></td><td><button class="btn-icon" onclick="delSession(${r.id})">&#10005;</button></td></tr>`).join('')
            : `<tr><td colspan="4" class="empty-state"><p>${t('no_hist')}</p></td></tr>`;
    } catch (e) {}
}
async function delSession(id) {
    await fetch(`/api/login-history/${id}`, { method: 'DELETE' });
    loadLoginHistory(); showToast('Đã xóa phiên', 'success');
}
async function saveIntegrations() {
    const body = {
        cal_google: document.getElementById('intGoogle').checked ? 1 : 0,
        cal_outlook: document.getElementById('intOutlook').checked ? 1 : 0,
        store_drive: document.getElementById('intDrive').checked ? 1 : 0,
        store_onedrive: document.getElementById('intOneDrive').checked ? 1 : 0,
        store_dropbox: document.getElementById('intDropbox').checked ? 1 : 0,
        auto_done_unfollow: document.getElementById('autoUnfollow').checked ? 1 : 0,
        auto_overdue_warn: document.getElementById('autoWarn').checked ? 1 : 0
    };
    const res = await fetch('/api/profile', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) { showToast('Lỗi lưu', 'error'); return; }
    currentUser = await res.json(); fillSettings(); showToast('Đã lưu tích hợp', 'success');
}
function exportICS() {
    const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//LamKhe//Tasks//VN'];
    allTasks.filter(t => t.due_date).forEach(t => {
        const dt = t.due_date.replace(/-/g, '');
        lines.push('BEGIN:VEVENT', `UID:${t.id}@lamkhe`, `DTSTAMP:${dt}T000000`, `DTSTART:${dt}T000000`, `SUMMARY:${t.title}`, 'END:VEVENT');
    });
    lines.push('END:VCALENDAR');
    const blob = new Blob([lines.join('\r\n')], { type: 'text/calendar' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'tasks.ics'; a.click();
}
async function loadRules() {
    try {
        const res = await fetch('/api/automation');
        if (!res.ok) return;
        const rows = await res.json();
        document.getElementById('rulesBody').innerHTML = rows.length ? rows.map(r => `<tr><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.trigger || '')}</td><td>${escapeHtml(r.action || '')}</td><td><button class="btn-icon" onclick="delRule(${r.id})">&#10005;</button></td></tr>`).join('')
            : `<tr><td colspan="4" class="empty-state"><p>${t('no_data')}</p></td></tr>`;
    } catch (e) {}
}
async function addRule() {
    const res = await fetch('/api/automation', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: document.getElementById('ruleName').value, trigger: document.getElementById('ruleTrigger').value, action: document.getElementById('ruleAction').value }) });
    const data = await res.json();
    if (!res.ok) { showToast(data.error || 'Lỗi', 'error'); return; }
    loadRules(); showToast('Đã thêm rule', 'success');
}
async function delRule(id) { await fetch(`/api/automation/${id}`, { method: 'DELETE' }); loadRules(); }
async function regenToken() {
    const res = await fetch('/api/api-token', { method: 'POST' });
    const data = await res.json();
    document.getElementById('apiToken').value = data.api_token || '';
    currentUser.api_token = data.api_token; showToast('Đã tạo token mới', 'success');
}
async function loadWebhooks() {
    try {
        const res = await fetch('/api/webhooks');
        if (!res.ok) return;
        const rows = await res.json();
        document.getElementById('webhooksBody').innerHTML = rows.length ? rows.map(w => `<tr><td><small>${escapeHtml(w.url)}</small></td><td>${escapeHtml(w.event || '')}</td><td><button class="btn-icon" onclick="delWebhook(${w.id})">&#10005;</button></td></tr>`).join('')
            : `<tr><td colspan="3" class="empty-state"><p>${t('no_data')}</p></td></tr>`;
    } catch (e) {}
}
async function addWebhook() {
    const res = await fetch('/api/webhooks', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: document.getElementById('whUrl').value, event: document.getElementById('whEvent').value }) });
    const data = await res.json();
    if (!res.ok) { showToast(data.error || 'Lỗi', 'error'); return; }
    loadWebhooks(); showToast('Đã thêm webhook', 'success');
}
async function delWebhook(id) { await fetch(`/api/webhooks/${id}`, { method: 'DELETE' }); loadWebhooks(); }
function exportCSV(kind) { window.location.href = `/api/export/${kind}`; }
async function importTasks() {
    const res = await fetch('/api/import/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csv: document.getElementById('importCsv').value }) });
    const data = await res.json();
    if (!res.ok) { showToast(data.error || 'Lỗi', 'error'); return; }
    showToast(data.message, 'success'); loadTasks();
}
async function loadTrash() {
    try {
        const res = await fetch('/api/trash');
        if (!res.ok) return;
        const rows = await res.json();
        document.getElementById('trashBody').innerHTML = rows.length ? rows.map(t => `<tr><td>${escapeHtml(t.title)}</td><td>${formatDate(t.deleted_at)}</td><td style="white-space:nowrap;"><button class="btn btn-sm btn-secondary" onclick="restoreTrash(${t.id})">${t('restore')}</button> <button class="btn btn-sm btn-secondary" onclick="purgeTrash(${t.id})">${t('purge')}</button></td></tr>`).join('')
            : `<tr><td colspan="3" class="empty-state"><p>${t('trash_empty')}</p></td></tr>`;
    } catch (e) {}
}
async function restoreTrash(id) { await fetch(`/api/trash/${id}/restore`, { method: 'POST' }); loadTrash(); loadTasks(); showToast('Đã khôi phục', 'success'); }
async function purgeTrash(id) { if (!confirm('Xóa vĩnh viễn?')) return; await fetch(`/api/trash/${id}/purge`, { method: 'DELETE' }); loadTrash(); showToast('Đã xóa vĩnh viễn', 'success'); }
async function loadStorage() {
    try {
        const res = await fetch('/api/storage');
        const d = await res.json();
        const el = document.getElementById('storageInfo');
        if (el) el.textContent = `${d.files} tệp đính kèm • ${(d.bytes / 1024).toFixed(1)} KB • ${d.tasks} task đang hoạt động`;
    } catch (e) {}
}

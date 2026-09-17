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
        roleEl.textContent = currentUser.role === 'bithu' ? 'Bí thư' : currentUser.role;
        if (currentUser.role === 'admin') roleEl.classList.add('badge-admin');

        const isAdminOrBithu = currentUser.role === 'admin' || currentUser.role === 'bithu';
        document.querySelectorAll('.admin-only').forEach(el => el.style.display = isAdminOrBithu ? '' : 'none');
        document.querySelectorAll('.user-only').forEach(el => el.style.display = !isAdminOrBithu ? '' : 'none');
        if (document.getElementById('addTaskBtn')) {
            document.getElementById('addTaskBtn').style.display = isAdminOrBithu ? 'inline-flex' : 'none';
        }
    } catch (err) { window.location.href = '/login'; }
}

// ==================== SIDEBAR ====================
function toggleSidebar() {
    document.querySelector('.sidebar').classList.toggle('open');
    document.querySelector('.sidebar-overlay').classList.toggle('active');
}

// ==================== THEME ====================
function loadTheme() {
    const theme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', theme);
    updateThemeUI(theme);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    updateThemeUI(next);
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

            const views = ['kanbanView', 'listView', 'pointsView', 'myPointsView', 'financeView'];
            views.forEach(v => { const el = document.getElementById(v); if (el) el.style.display = 'none'; });

            const titles = { kanban: 'Kanban Board', list: 'Danh sách', points: 'Điểm tổng hợp', 'my-points': 'Điểm của tôi', finance: 'Tài chính' };
            document.getElementById('viewTitle').textContent = titles[currentView] || '';
            document.getElementById('statsGrid').style.display = ['kanban', 'list'].includes(currentView) ? '' : 'none';

            if (currentView === 'kanban') document.getElementById('kanbanView').style.display = 'flex';
            else if (currentView === 'list') document.getElementById('listView').style.display = 'block';
            else if (currentView === 'points') loadPoints();
            else if (currentView === 'my-points') loadMyPoints();
            else if (currentView === 'finance') loadFinance();
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
    document.getElementById('taskCount').textContent = `${tasks.length} nhiệm vụ`;
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
    document.getElementById('pendingTasks').innerHTML = pending.length ? pending.map(createTaskCard).join('') : '<div class="empty-state"><p>Không có task nào</p></div>';
    document.getElementById('inProgressTasks').innerHTML = inProgress.length ? inProgress.map(createTaskCard).join('') : '<div class="empty-state"><p>Không có task nào</p></div>';
    document.getElementById('doneTasks').innerHTML = done.length ? done.map(createTaskCard).join('') : '<div class="empty-state"><p>Không có task nào</p></div>';
}

function createTaskCard(task) {
    const isAdmin = currentUser.role === 'admin' || currentUser.role === 'bithu';
    const isClaimed = task.is_claimed_by_me;
    const isOverdue = task.due_date && new Date(task.due_date) < new Date() && task.status !== 'done';
    const canClaim = !isAdmin && !isClaimed && task.slots_left > 0 && task.status !== 'done';

    let adminActions = '';
    if (isAdmin) {
        adminActions = `<button class="btn-icon" onclick="openEditModal(${task.id})" title="Sửa">&#9998;</button><button class="btn-icon" onclick="openDeleteModal(${task.id}, '${escapeHtml(task.title)}')" title="Xóa">&#10005;</button>`;
    }

    const assigneeTags = task.assigned_users.map(u => `<span class="assignee-tag">@${escapeHtml(u.username)}</span>`).join('');
    const slotInfo = `<span class="slot-info">${task.assignee_count}/${task.max_assignees}</span>`;
    const pointsTag = task.points > 0 ? `<span class="priority-tag low">+${task.points} điểm</span>` : '';

    let claimBtn = '';
    if (canClaim) claimBtn = `<button class="btn btn-claim" onclick="claimTask(${task.id})">Nhận task</button>`;
    else if (isClaimed && !isAdmin) claimBtn = `<button class="btn btn-unclaim" onclick="unclaimTask(${task.id})">Bỏ nhận</button>`;

    let statusSelect = '';
    if (isClaimed || isAdmin) {
        statusSelect = `<select class="status-select" onchange="changeStatus(${task.id}, this.value)">
            <option value="pending" ${task.status === 'pending' ? 'selected' : ''}>Chờ xử lý</option>
            <option value="in_progress" ${task.status === 'in_progress' ? 'selected' : ''}>Đang thực hiện</option>
            <option value="done" ${task.status === 'done' ? 'selected' : ''}>Hoàn thành</option>
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
                ${assigneeTags || '<span class="assignee-tag" style="color:var(--text-muted)">Chưa ai nhận</span>'}
                ${slotInfo} ${pointsTag}
                ${task.due_date ? `<span class="due-date ${isOverdue ? 'overdue' : ''}">${formatDate(task.due_date)}</span>` : ''}
            </div>
            <div class="task-card-actions-row">${statusSelect} ${claimBtn}</div>
        </div>
    </div>`;
}

function renderList(tasks) {
    const tbody = document.getElementById('taskTableBody');
    if (!tasks.length) { tbody.innerHTML = '<tr><td colspan="8" class="empty-state"><p>Không có task nào</p></td></tr>'; return; }
    tbody.innerHTML = tasks.map(task => {
        const isAdmin = currentUser.role === 'admin' || currentUser.role === 'bithu';
        const isClaimed = task.is_claimed_by_me;
        const isOverdue = task.due_date && new Date(task.due_date) < new Date() && task.status !== 'done';
        const canClaim = !isAdmin && !isClaimed && task.slots_left > 0 && task.status !== 'done';
        let adminActions = isAdmin ? `<button class="btn-icon" onclick="openEditModal(${task.id})">&#9998;</button><button class="btn-icon" onclick="openDeleteModal(${task.id}, '${escapeHtml(task.title)}')">&#10005;</button>` : '';
        const assigneeNames = task.assigned_users.map(u => escapeHtml(u.username)).join(', ');
        let statusCell = (isClaimed || isAdmin) ? `<select class="status-select" onchange="changeStatus(${task.id}, this.value)"><option value="pending" ${task.status === 'pending' ? 'selected' : ''}>Chờ xử lý</option><option value="in_progress" ${task.status === 'in_progress' ? 'selected' : ''}>Đang thực hiện</option><option value="done" ${task.status === 'done' ? 'selected' : ''}>Hoàn thành</option></select>` : `<span class="status-label">${getStatusLabel(task.status)}</span>`;
        let claimBtn = canClaim ? `<button class="btn btn-claim btn-sm" onclick="claimTask(${task.id})">Nhận</button>` : isClaimed && !isAdmin ? `<button class="btn btn-unclaim btn-sm" onclick="unclaimTask(${task.id})">Bỏ nhận</button>` : '';
        return `<tr><td><div class="task-title-cell">${escapeHtml(task.title)}${task.description ? `<small>${escapeHtml(task.description.substring(0, 60))}${task.description.length > 60 ? '...' : ''}</small>` : ''}</div></td><td>${statusCell}</td><td><span class="priority-tag ${task.priority}">${getPriorityLabel(task.priority)}</span></td><td>${assigneeNames || '<span style="color:var(--text-muted)">Chưa ai nhận</span>'}</td><td><span class="slot-info">${task.assignee_count}/${task.max_assignees}</span></td><td>${task.points > 0 ? `<span class="priority-tag low">+${task.points}</span>` : '-'}</td><td>${task.due_date ? `<span class="due-date ${isOverdue ? 'overdue' : ''}">${formatDate(task.due_date)}</span>` : '-'}</td><td>${adminActions}${claimBtn}</td></tr>`;
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
    if (!allPoints.length) { tbody.innerHTML = '<tr><td colspan="4" class="empty-state"><p>Chưa có dữ liệu</p></td></tr>'; return; }
    tbody.innerHTML = allPoints.map((u, i) => `<tr><td>${i + 1}</td><td><strong>${escapeHtml(u.username)}</strong></td><td><span class="priority-tag low" style="font-size:14px;">${u.score} điểm</span></td><td><button class="btn btn-sm btn-secondary" onclick="openPointsDetail(${u.id}, '${escapeHtml(u.username)}')">Xem chi tiết</button></td></tr>`).join('');
}

async function openPointsDetail(userId, username) {
    try {
        const res = await fetch(`/api/points/${userId}`);
        const data = await res.json();
        document.getElementById('pointsDetailTitle').textContent = `Điểm - ${username}`;
        document.getElementById('pointsDetailScore').textContent = data.user.score;
        const tbody = document.getElementById('pointsDetailLogBody');
        if (!data.logs.length) { tbody.innerHTML = '<tr><td colspan="3" class="empty-state"><p>Chưa có lịch sử</p></td></tr>'; }
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
        if (!data.logs.length) { tbody.innerHTML = '<tr><td colspan="3" class="empty-state"><p>Chưa có điểm</p></td></tr>'; }
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
        document.getElementById('financeBalance').textContent = formatMoney(summary.balance);
        const tbody = document.getElementById('financeTableBody');
        if (!transactions.length) { tbody.innerHTML = '<tr><td colspan="6" class="empty-state"><p>Chưa có giao dịch</p></td></tr>'; return; }
        tbody.innerHTML = transactions.map(t => `<tr><td>${formatDate(t.date)}</td><td><span class="priority-tag ${t.type === 'income' ? 'low' : 'high'}">${t.type === 'income' ? 'Thu' : 'Chi'}</span></td><td><strong>${formatMoney(t.amount)}</strong></td><td>${escapeHtml(t.description) || '-'}</td><td>${escapeHtml(t.category) || '-'}</td><td><button class="btn-icon" onclick="deleteFinance(${t.id})">&#10005;</button></td></tr>`).join('');
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
        document.getElementById('modalTitle').textContent = 'Sửa nhiệm vụ';
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
        document.getElementById('modalTitle').textContent = 'Thêm nhiệm vụ mới';
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

function getPriorityLabel(p) { return { low: 'Thấp', medium: 'TB', high: 'Cao' }[p] || p; }
function getStatusLabel(s) { return { pending: 'Chờ xử lý', in_progress: 'Đang thực hiện', done: 'Hoàn thành' }[s] || s; }
function formatDate(d) { return d ? new Date(d).toLocaleDateString('vi-VN') : ''; }
function formatMoney(n) { return new Intl.NumberFormat('vi-VN').format(n) + ' VND'; }

document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeTaskModal(); closeDeleteModal(); closeAddPointsModal(); closeAddFinanceModal(); closePointsDetailModal(); } });

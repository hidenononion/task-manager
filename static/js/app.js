let currentUser = null;
let allTasks = [];
let allUsers = [];
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
        if (!res.ok) {
            window.location.href = '/login';
            return;
        }
        currentUser = await res.json();
        document.getElementById('userName').textContent = currentUser.username;
        document.getElementById('userAvatar').textContent = currentUser.username[0].toUpperCase();
        const roleEl = document.getElementById('userRole');
        roleEl.textContent = currentUser.role;
        if (currentUser.role === 'admin') {
            roleEl.classList.add('badge-admin');
            document.getElementById('addTaskBtn').style.display = 'inline-flex';
        } else {
            document.getElementById('addTaskBtn').style.display = 'none';
        }
    } catch (err) {
        window.location.href = '/login';
    }
}

// ==================== SIDEBAR TOGGLE ====================
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
    const icon = document.getElementById('themeIcon');
    const label = document.getElementById('themeLabel');
    if (theme === 'dark') {
        icon.innerHTML = '&#9790;';
        label.textContent = 'Chế độ sáng';
    } else {
        icon.innerHTML = '&#9728;';
        label.textContent = 'Chế độ tối';
    }
}

// ==================== NAV ====================
function setupNav() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            item.classList.add('active');
            currentView = item.dataset.view;
            document.getElementById('viewTitle').textContent =
                currentView === 'kanban' ? 'Kanban Board' : 'Danh sách';
            document.getElementById('kanbanView').style.display = currentView === 'kanban' ? 'flex' : 'none';
            document.getElementById('listView').style.display = currentView === 'list' ? 'block' : 'none';
        });
    });
}

// ==================== FILTERS & SEARCH ====================
function getFilteredTasks() {
    const priority = document.getElementById('filterPriority').value;
    const status = document.getElementById('filterStatus').value;
    const search = document.getElementById('searchInput').value.toLowerCase().trim();

    return allTasks.filter(t => {
        if (priority && t.priority !== priority) return false;
        if (status && t.status !== status) return false;
        if (search) {
            const matchTitle = t.title.toLowerCase().includes(search);
            const matchDesc = (t.description || '').toLowerCase().includes(search);
            const matchUser = t.assigned_users.some(u => u.username.toLowerCase().includes(search));
            if (!matchTitle && !matchDesc && !matchUser) return false;
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
    } catch (err) {
        showToast('Lỗi tải dữ liệu', 'error');
    }
}

async function loadUsers() {
    try {
        const res = await fetch('/api/users');
        allUsers = await res.json();
        populateAssigneeCheckboxes();
    } catch (err) {}
}

function populateAssigneeCheckboxes() {
    const container = document.getElementById('taskAssignees');
    container.innerHTML = allUsers.map(u => `
        <label class="checkbox-label">
            <input type="checkbox" name="assignee" value="${u.id}">
            <span>${escapeHtml(u.username)}</span>
        </label>
    `).join('');
}

function getSelectedAssignees() {
    return Array.from(document.querySelectorAll('input[name="assignee"]:checked'))
        .map(cb => parseInt(cb.value));
}

function setSelectedAssignees(userIds) {
    document.querySelectorAll('input[name="assignee"]').forEach(cb => {
        cb.checked = userIds.includes(parseInt(cb.value));
    });
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
    const current = parseInt(el.textContent) || 0;
    if (current === target) return;

    const step = target > current ? 1 : -1;
    const diff = Math.abs(target - current);
    const duration = Math.min(300, diff * 50);
    const interval = duration / diff;

    let count = current;
    const timer = setInterval(() => {
        count += step;
        el.textContent = count;
        if (count === target) clearInterval(timer);
    }, interval);
}

// ==================== RENDER ====================
function renderTasks() {
    const tasks = getFilteredTasks();
    document.getElementById('taskCount').textContent = `${tasks.length} nhiệm vụ`;
    updateStats();

    if (currentView === 'kanban') {
        renderKanban(tasks);
    } else {
        renderList(tasks);
    }
}

function renderKanban(tasks) {
    const pending = tasks.filter(t => t.status === 'pending');
    const inProgress = tasks.filter(t => t.status === 'in_progress');
    const done = tasks.filter(t => t.status === 'done');

    document.getElementById('pendingCount').textContent = pending.length;
    document.getElementById('inProgressCount').textContent = inProgress.length;
    document.getElementById('doneCount').textContent = done.length;

    document.getElementById('pendingTasks').innerHTML = pending.length ?
        pending.map(t => createTaskCard(t)).join('') :
        '<div class="empty-state"><p>Không có task nào</p></div>';

    document.getElementById('inProgressTasks').innerHTML = inProgress.length ?
        inProgress.map(t => createTaskCard(t)).join('') :
        '<div class="empty-state"><p>Không có task nào</p></div>';

    document.getElementById('doneTasks').innerHTML = done.length ?
        done.map(t => createTaskCard(t)).join('') :
        '<div class="empty-state"><p>Không có task nào</p></div>';
}

function createTaskCard(task) {
    const isAdmin = currentUser.role === 'admin';
    const isClaimed = task.is_claimed_by_me;
    const isOverdue = task.due_date && new Date(task.due_date) < new Date() && task.status !== 'done';
    const slotsLeft = task.slots_left;
    const canClaim = !isAdmin && !isClaimed && slotsLeft > 0 && task.status !== 'done';

    let adminActions = '';
    if (isAdmin) {
        adminActions = `
            <button class="btn-icon" onclick="openEditModal(${task.id})" title="Sua">&#9998;</button>
            <button class="btn-icon" onclick="openDeleteModal(${task.id}, '${escapeHtml(task.title)}')" title="Xoa">&#10005;</button>
        `;
    }

    const assigneeTags = task.assigned_users.map(u =>
        `<span class="assignee-tag">@${escapeHtml(u.username)}</span>`
    ).join('');

    const slotInfo = `<span class="slot-info">${task.assignee_count}/${task.max_assignees}</span>`;

    let claimBtn = '';
    if (canClaim) {
        claimBtn = `<button class="btn btn-claim" onclick="claimTask(${task.id})">Nhan task</button>`;
    } else if (isClaimed && !isAdmin) {
        claimBtn = `<button class="btn btn-unclaim" onclick="unclaimTask(${task.id})">Bo nhan</button>`;
    }

    let statusSelect = '';
    if (isClaimed || isAdmin) {
        statusSelect = `
            <select class="status-select" onchange="changeStatus(${task.id}, this.value)">
                <option value="pending" ${task.status === 'pending' ? 'selected' : ''}>Cho xu ly</option>
                <option value="in_progress" ${task.status === 'in_progress' ? 'selected' : ''}>Dang thuc hien</option>
                <option value="done" ${task.status === 'done' ? 'selected' : ''}>Hoan thanh</option>
            </select>
        `;
    }

    return `
        <div class="task-card" data-id="${task.id}">
            <div class="task-card-header">
                <div class="task-card-title">${escapeHtml(task.title)}</div>
                <div class="task-card-actions">${adminActions}</div>
            </div>
            ${task.description ? `<div class="task-card-desc">${escapeHtml(task.description)}</div>` : ''}
            <div class="task-card-footer">
                <div class="task-card-meta">
                    <span class="priority-tag ${task.priority}">${getPriorityLabel(task.priority)}</span>
                    ${assigneeTags || '<span class="assignee-tag" style="color:var(--text-muted)">Chua ai nhan</span>'}
                    ${slotInfo}
                    ${task.due_date ? `<span class="due-date ${isOverdue ? 'overdue' : ''}">${formatDate(task.due_date)}</span>` : ''}
                </div>
                <div class="task-card-actions-row">
                    ${statusSelect}
                    ${claimBtn}
                </div>
            </div>
        </div>
    `;
}

function renderList(tasks) {
    const tbody = document.getElementById('taskTableBody');

    if (!tasks.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-state"><p>Khong co task nao</p></td></tr>';
        return;
    }

    tbody.innerHTML = tasks.map(task => {
        const isAdmin = currentUser.role === 'admin';
        const isClaimed = task.is_claimed_by_me;
        const isOverdue = task.due_date && new Date(task.due_date) < new Date() && task.status !== 'done';
        const canClaim = !isAdmin && !isClaimed && task.slots_left > 0 && task.status !== 'done';

        let adminActions = '';
        if (isAdmin) {
            adminActions = `
                <button class="btn-icon" onclick="openEditModal(${task.id})" title="Sua">&#9998;</button>
                <button class="btn-icon" onclick="openDeleteModal(${task.id}, '${escapeHtml(task.title)}')" title="Xoa">&#10005;</button>
            `;
        }

        const assigneeNames = task.assigned_users.map(u => escapeHtml(u.username)).join(', ');

        let statusCell = '';
        if (isClaimed || isAdmin) {
            statusCell = `
                <select class="status-select" onchange="changeStatus(${task.id}, this.value)">
                    <option value="pending" ${task.status === 'pending' ? 'selected' : ''}>Cho xu ly</option>
                    <option value="in_progress" ${task.status === 'in_progress' ? 'selected' : ''}>Dang thuc hien</option>
                    <option value="done" ${task.status === 'done' ? 'selected' : ''}>Hoan thanh</option>
                </select>
            `;
        } else {
            statusCell = `<span class="status-label">${getStatusLabel(task.status)}</span>`;
        }

        let claimBtn = '';
        if (canClaim) {
            claimBtn = `<button class="btn btn-claim btn-sm" onclick="claimTask(${task.id})">Nhan</button>`;
        } else if (isClaimed && !isAdmin) {
            claimBtn = `<button class="btn btn-unclaim btn-sm" onclick="unclaimTask(${task.id})">Bo nhan</button>`;
        }

        return `
            <tr>
                <td>
                    <div class="task-title-cell">
                        ${escapeHtml(task.title)}
                        ${task.description ? `<small>${escapeHtml(task.description.substring(0, 60))}${task.description.length > 60 ? '...' : ''}</small>` : ''}
                    </div>
                </td>
                <td>${statusCell}</td>
                <td><span class="priority-tag ${task.priority}">${getPriorityLabel(task.priority)}</span></td>
                <td>${assigneeNames || '<span style="color:var(--text-muted)">Chua ai nhan</span>'}</td>
                <td><span class="slot-info">${task.assignee_count}/${task.max_assignees}</span></td>
                <td>${task.due_date ? `<span class="due-date ${isOverdue ? 'overdue' : ''}">${formatDate(task.due_date)}</span>` : '-'}</td>
                <td>${adminActions}${claimBtn}</td>
            </tr>
        `;
    }).join('');
}

// ==================== CLAIM / UNCLAIM ====================
async function claimTask(taskId) {
    try {
        const res = await fetch(`/api/tasks/${taskId}/claim`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.error || 'Loi nhan task', 'error');
            return;
        }
        await loadTasks();
        showToast('Da nhan task thanh cong', 'success');
    } catch (err) {
        showToast('Loi ket noi', 'error');
    }
}

async function unclaimTask(taskId) {
    try {
        const res = await fetch(`/api/tasks/${taskId}/claim`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: currentUser.id })
        });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.error || 'Loi bo nhan task', 'error');
            return;
        }
        await loadTasks();
        showToast('Da bo nhan task', 'success');
    } catch (err) {
        showToast('Loi ket noi', 'error');
    }
}

// ==================== STATUS CHANGE ====================
async function changeStatus(taskId, newStatus) {
    try {
        const res = await fetch(`/api/tasks/${taskId}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });
        if (!res.ok) {
            const data = await res.json();
            showToast(data.error || 'Loi cap nhat', 'error');
            return;
        }
        await loadTasks();
        showToast('Da cap nhat trang thai', 'success');
    } catch (err) {
        showToast('Loi ket noi', 'error');
    }
}

// ==================== MODALS ====================
function openTaskModal(taskId = null) {
    document.getElementById('taskFormError').textContent = '';
    if (taskId) {
        const task = allTasks.find(t => t.id === taskId);
        if (!task) return;
        document.getElementById('modalTitle').textContent = 'Sua nhiem vu';
        document.getElementById('taskId').value = task.id;
        document.getElementById('taskTitle').value = task.title;
        document.getElementById('taskDesc').value = task.description || '';
        document.getElementById('taskStatus').value = task.status;
        document.getElementById('taskPriority').value = task.priority;
        document.getElementById('taskMaxAssignees').value = task.max_assignees;
        document.getElementById('taskDueDate').value = task.due_date || '';
        setSelectedAssignees(task.assigned_users.map(u => u.id));
    } else {
        document.getElementById('modalTitle').textContent = 'Them nhiem vu moi';
        document.getElementById('taskForm').reset();
        document.getElementById('taskId').value = '';
        document.getElementById('taskPriority').value = 'medium';
        document.getElementById('taskMaxAssignees').value = 3;
        setSelectedAssignees([]);
    }
    document.getElementById('taskModal').classList.add('active');
}

function closeTaskModal() {
    document.getElementById('taskModal').classList.remove('active');
}

function openEditModal(taskId) {
    openTaskModal(taskId);
}

function openDeleteModal(taskId, taskTitle) {
    deleteTaskId = taskId;
    document.getElementById('deleteTaskName').textContent = taskTitle;
    document.getElementById('deleteModal').classList.add('active');
}

function closeDeleteModal() {
    document.getElementById('deleteModal').classList.remove('active');
    deleteTaskId = null;
}

async function saveTask() {
    const errorEl = document.getElementById('taskFormError');
    errorEl.textContent = '';

    const title = document.getElementById('taskTitle').value.trim();
    if (!title) {
        errorEl.textContent = 'Tieu de khong duoc de trong';
        return;
    }

    const maxAssignees = parseInt(document.getElementById('taskMaxAssignees').value) || 3;
    const assignedTo = getSelectedAssignees();
    if (assignedTo.length > maxAssignees) {
        errorEl.textContent = `Toi da giao cho ${maxAssignees} nguoi`;
        return;
    }

    const taskId = document.getElementById('taskId').value;
    const payload = {
        title,
        description: document.getElementById('taskDesc').value.trim(),
        status: document.getElementById('taskStatus').value,
        priority: document.getElementById('taskPriority').value,
        max_assignees: maxAssignees,
        assigned_to: assignedTo,
        due_date: document.getElementById('taskDueDate').value || null
    };

    try {
        const url = taskId ? `/api/tasks/${taskId}` : '/api/tasks';
        const method = taskId ? 'PUT' : 'POST';
        const res = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();

        if (!res.ok) {
            errorEl.textContent = data.error || 'Loi luu task';
            return;
        }

        closeTaskModal();
        await loadTasks();
        showToast(taskId ? 'Da cap nhat task' : 'Da tao task moi', 'success');
    } catch (err) {
        errorEl.textContent = 'Loi ket noi server';
    }
}

async function confirmDelete() {
    if (!deleteTaskId) return;

    try {
        const res = await fetch(`/api/tasks/${deleteTaskId}`, { method: 'DELETE' });
        if (!res.ok) {
            showToast('Loi xoa task', 'error');
            return;
        }
        closeDeleteModal();
        await loadTasks();
        showToast('Da xoa task', 'success');
    } catch (err) {
        showToast('Loi ket noi', 'error');
    }
}

// ==================== UTILS ====================
function logout() {
    fetch('/api/logout').then(() => {
        window.location.href = '/login';
    });
}

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

function getPriorityLabel(priority) {
    const labels = { low: 'Thap', medium: 'TB', high: 'Cao' };
    return labels[priority] || priority;
}

function getStatusLabel(status) {
    const labels = { pending: 'Cho xu ly', in_progress: 'Dang thuc hien', done: 'Hoan thanh' };
    return labels[status] || status;
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleDateString('vi-VN');
}

// Close modals on Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeTaskModal();
        closeDeleteModal();
    }
});

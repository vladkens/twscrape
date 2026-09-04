const tokenMeta = document.querySelector('meta[name="twscrape-token"]');
const token = tokenMeta ? tokenMeta.content : "";

const POLL_MS = 10000;
const STATUS_LABELS = {
  ready: "可用",
  cooling: "冷却中",
  attention: "需处理",
  disabled: "已停用",
};

const state = {
  accounts: [],
  summary: null,
  expanded: null,
  editing: null,
  pendingDelete: null,
  openDeleteOnEditClose: false,
  loadError: "",
};

const els = {
  loadError: document.querySelector("#loadError"),
  viewAttention: document.querySelector("#viewAttention"),
  statReady: document.querySelector("#statReady"),
  statCooling: document.querySelector("#statCooling"),
  statAttention: document.querySelector("#statAttention"),
  statDisabled: document.querySelector("#statDisabled"),
  rows: document.querySelector("#accountRows"),
  empty: document.querySelector("#emptyState"),
  emptyTitle: document.querySelector("#emptyTitle"),
  emptyHint: document.querySelector("#emptyHint"),
  search: document.querySelector("#searchInput"),
  filter: document.querySelector("#statusFilter"),
  updated: document.querySelector("#updatedAt"),
  sessionUser: document.querySelector("#sessionUser"),
  logout: document.querySelector("#logoutButton"),
  addButton: document.querySelector("#addButton"),
  dialog: document.querySelector("#addDialog"),
  form: document.querySelector("#addForm"),
  username: document.querySelector("#cookieUsername"),
  cookies: document.querySelector("#cookieValue"),
  formError: document.querySelector("#formError"),
  submit: document.querySelector("#submitAccount"),
  closeDialog: document.querySelector("#closeDialog"),
  cancelDialog: document.querySelector("#cancelDialog"),
  editDialog: document.querySelector("#editDialog"),
  editForm: document.querySelector("#editForm"),
  editUsernameDisplay: document.querySelector("#editUsernameDisplay"),
  editActive: document.querySelector("#editActive"),
  editCookies: document.querySelector("#editCookies"),
  editProxyStatus: document.querySelector("#editProxyStatus"),
  editProxyKeep: document.querySelector("#editProxyKeep"),
  editProxySet: document.querySelector("#editProxySet"),
  editProxyClear: document.querySelector("#editProxyClear"),
  editProxyLabel: document.querySelector("#editProxyLabel"),
  editProxy: document.querySelector("#editProxy"),
  editFormError: document.querySelector("#editFormError"),
  editSubmit: document.querySelector("#submitEdit"),
  closeEditDialog: document.querySelector("#closeEditDialog"),
  cancelEditDialog: document.querySelector("#cancelEditDialog"),
  deleteAccountButton: document.querySelector("#deleteAccountButton"),
  deleteDialog: document.querySelector("#deleteDialog"),
  deleteForm: document.querySelector("#deleteForm"),
  deleteSummary: document.querySelector("#deleteSummary"),
  deleteConfirm: document.querySelector("#deleteConfirmUsername"),
  deleteFormError: document.querySelector("#deleteFormError"),
  deleteSubmit: document.querySelector("#submitDelete"),
  closeDeleteDialog: document.querySelector("#closeDeleteDialog"),
  cancelDeleteDialog: document.querySelector("#cancelDeleteDialog"),
  accountsHeading: document.querySelector("#accountsHeading"),
  toast: document.querySelector("#toast"),
};

for (const [name, node] of Object.entries(els)) {
  if (!node) throw new Error(`DOM 节点缺失: ${name}`);
}

function apiHeaders(withJson = false) {
  const headers = { "X-Twscrape-Token": token };
  if (withJson) headers["Content-Type"] = "application/json";
  return headers;
}

async function api(path, options = {}) {
  const withJson = options.body !== undefined;
  const response = await fetch(path, {
    ...options,
    headers: {
      ...apiHeaders(withJson),
      ...(options.headers || {}),
    },
  });
  const raw = await response.text();
  let body = {};
  if (raw) {
    try {
      body = JSON.parse(raw);
    } catch {
      body = { error: raw };
    }
  }
  if (response.status === 401) {
    location.replace("/login");
  }
  if (!response.ok) {
    throw new Error(body.error || `请求失败 (${response.status})`);
  }
  return body;
}

function showToast(message, isError = false) {
  els.toast.textContent = message;
  els.toast.classList.toggle("error", Boolean(isError));
  els.toast.classList.toggle("ok", !isError);
  els.toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => els.toast.classList.remove("show"), 2600);
}

function loginLabel(method) {
  if (method === "cookies") return "Cookie";
  if (method === "password") return "密码";
  return method || "—";
}

function relativeTime(value) {
  if (!value) return "从未";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return "—";
  const seconds = Math.round((parsed - Date.now()) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 45) return "刚刚";
  if (abs < 3600) return `${Math.round(abs / 60)} 分钟前`;
  if (abs < 86400) return `${Math.round(abs / 3600)} 小时前`;
  return `${Math.round(abs / 86400)} 天前`;
}

function formatDuration(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return "";
  if (value < 60) return `${value} 秒后`;
  if (value < 3600) return `${Math.ceil(value / 60)} 分钟后`;
  return `${Math.ceil(value / 3600)} 小时后`;
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", { hour12: false });
}

function primaryAction(account) {
  if (account.next_action === "add_cookie") {
    return { action: "add_cookie", label: "添加 Cookie", className: "action-add" };
  }
  if (account.next_action === "enable") {
    return { action: "enable", label: "启用", className: "action-enable" };
  }
  if (Number(account.lock_count) > 0) {
    return { action: "reset", label: "清锁", className: "action-reset" };
  }
  if (account.active) {
    return { action: "disable", label: "停用", className: "action-disable" };
  }
  return null;
}

function lockRecovery(account) {
  const count = Number(account.lock_count) || 0;
  if (!count) return { text: "—", title: "" };
  const wait = formatDuration(account.next_unlock_in_seconds);
  const queues = Array.isArray(account.locked_queues)
    ? account.locked_queues.join(", ")
    : "";
  const when = account.next_unlock_at ? formatDateTime(account.next_unlock_at) : "";
  const text = wait ? `${count} 个队列 · ${wait}` : `${count} 个队列`;
  const title = [queues && `队列: ${queues}`, when && `最早恢复: ${when}`]
    .filter(Boolean)
    .join(" · ");
  return { text, title };
}

function filteredAccounts() {
  const query = els.search.value.trim().toLowerCase();
  const filter = els.filter.value;
  return state.accounts.filter((account) => {
    const username = String(account.username || "").toLowerCase();
    const matchQuery = !query || username.includes(query);
    const matchFilter =
      filter === "all" ||
      account.status === filter ||
      (filter === "attention" && account.needs_attention);
    return matchQuery && matchFilter;
  });
}

function appendText(parent, tag, text, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  parent.appendChild(node);
  return node;
}

function labeledCell(label, className) {
  const td = document.createElement("td");
  td.dataset.label = label;
  if (className) td.className = className;
  return td;
}

function renderDetailCard(title, items, emptyText) {
  const card = document.createElement("div");
  card.className = "detail-card";
  appendText(card, "h3", title);
  if (!items.length) {
    appendText(card, "p", emptyText, "detail-empty");
    return card;
  }
  const list = document.createElement("ul");
  for (const item of items) {
    const li = document.createElement("li");
    appendText(li, "span", item.label);
    appendText(li, "span", item.value);
    list.appendChild(li);
  }
  card.appendChild(list);
  return card;
}

function renderDetailRow(account) {
  const tr = document.createElement("tr");
  tr.className = "detail-row";
  const td = document.createElement("td");
  td.colSpan = 7;
  const grid = document.createElement("div");
  grid.className = "detail-grid";

  const queues = Array.isArray(account.requests_by_queue)
    ? account.requests_by_queue.map((item) => ({
        label: String(item.queue || "—"),
        value: Number(item.count || 0).toLocaleString("zh-CN"),
      }))
    : [];
  const locks = Array.isArray(account.active_locks)
    ? account.active_locks.map((item) => ({
        label: String(item.queue || "—"),
        value: formatDateTime(item.unlock_at),
      }))
    : [];

  const errorCard = document.createElement("div");
  errorCard.className = "detail-card";
  appendText(errorCard, "h3", "错误信息");
  appendText(
    errorCard,
    "p",
    account.error_message || "没有错误信息",
    account.error_message ? "detail-error" : "detail-empty"
  );

  grid.append(
    renderDetailCard("各队列请求", queues, "还没有请求记录"),
    renderDetailCard("本地锁", locks, "当前没有本地锁"),
    errorCard
  );
  td.appendChild(grid);
  tr.appendChild(td);
  return tr;
}

function syncAttentionFilter() {
  els.viewAttention.setAttribute(
    "aria-pressed",
    els.filter.value === "attention" ? "true" : "false"
  );
}

function renderAccounts() {
  const accounts = filteredAccounts();
  els.rows.replaceChildren();
  syncAttentionFilter();

  if (!accounts.length) {
    els.empty.hidden = false;
    const hasAny = state.accounts.length > 0;
    els.emptyTitle.textContent = hasAny ? "没有匹配的账号" : "还没有账号";
    els.emptyHint.textContent = hasAny
      ? "试试其他筛选或搜索"
      : "添加 Cookie 后才会出现在列表中";
    return;
  }

  els.empty.hidden = true;
  const fragment = document.createDocumentFragment();

  for (const account of accounts) {
    const username = String(account.username || "");
    const tr = document.createElement("tr");
    tr.className = "account-row";
    tr.dataset.username = username;
    tr.tabIndex = 0;
    tr.setAttribute("aria-expanded", account.username === state.expanded ? "true" : "false");
    if (account.status === "attention" || account.needs_attention) {
      tr.classList.add("row-attention");
    } else if (account.status === "cooling") {
      tr.classList.add("row-cooling");
    }
    if (state.expanded === username) tr.classList.add("is-expanded");

    const nameTd = labeledCell("账号", "cell-account");
    const cell = document.createElement("div");
    cell.className = "account-cell";
    appendText(cell, "span", state.expanded === username ? "▾" : "▸", "chevron");
    const avatar = appendText(cell, "span", username.slice(0, 1) || "?", "avatar");
    avatar.setAttribute("aria-hidden", "true");
    appendText(cell, "span", `@${username}`, "account-name");
    nameTd.appendChild(cell);

    const statusTd = labeledCell("状态", "cell-status");
    const statusBlock = document.createElement("div");
    statusBlock.className = "status-block";
    const statusKey = STATUS_LABELS[account.status] ? account.status : "disabled";
    appendText(
      statusBlock,
      "span",
      account.status_label || STATUS_LABELS[statusKey] || account.status,
      `status status-${statusKey}`
    );
    if (account.status_detail) {
      appendText(statusBlock, "span", String(account.status_detail), "status-detail");
    }
    statusTd.appendChild(statusBlock);

    const loginTd = labeledCell("登录方式");
    loginTd.textContent = loginLabel(account.login_method);

    const reqTd = labeledCell("总请求");
    reqTd.textContent = Number(account.total_requests || 0).toLocaleString("zh-CN");

    const usedTd = labeledCell("最后使用", "cell-meta");
    usedTd.textContent = relativeTime(account.last_used);
    if (account.last_used) usedTd.title = formatDateTime(account.last_used);

    const lockTd = labeledCell("锁恢复");
    const recovery = lockRecovery(account);
    lockTd.textContent = recovery.text;
    if (recovery.title) lockTd.title = recovery.title;
    if (recovery.text === "—") lockTd.classList.add("cell-meta");

    const actionTd = labeledCell("操作", "cell-actions");
    const actions = document.createElement("div");
    actions.className = "row-actions";
    const action = primaryAction(account);
    if (action) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.action = action.action;
      button.dataset.user = username;
      button.className = action.className;
      button.textContent = action.label;
      actions.appendChild(button);
    }
    const manage = document.createElement("button");
    manage.type = "button";
    manage.dataset.action = "manage";
    manage.dataset.user = username;
    manage.className = "action-manage";
    manage.textContent = "管理";
    manage.setAttribute("aria-haspopup", "dialog");
    manage.setAttribute("aria-label", `管理 @${username}`);
    actions.appendChild(manage);
    actionTd.appendChild(actions);

    tr.append(nameTd, statusTd, loginTd, reqTd, usedTd, lockTd, actionTd);
    fragment.appendChild(tr);
    if (state.expanded === username) {
      fragment.appendChild(renderDetailRow(account));
    }
  }

  els.rows.appendChild(fragment);
}

function renderSummary() {
  const summary = state.summary;
  const ready = Number(summary?.ready || 0);
  const attention = Number(summary?.attention || 0);
  const cooling = Number(summary?.cooling || 0);
  const disabled = Number(summary?.disabled || 0);

  els.statReady.textContent = summary ? String(ready) : "—";
  els.statAttention.textContent = summary ? String(attention) : "—";
  els.statCooling.textContent = summary ? String(cooling) : "—";
  els.statDisabled.textContent = summary ? String(disabled) : "—";

  els.statReady.classList.toggle("is-ok", ready > 0);
  els.statAttention.classList.toggle("is-bad", attention > 0);
  els.statCooling.classList.toggle("is-warn", cooling > 0);

  els.loadError.hidden = !state.loadError;
  els.loadError.textContent = state.loadError || "";
  syncAttentionFilter();
}

function clearCookieForm() {
  els.form.reset();
  els.cookies.value = "";
  els.username.value = "";
  els.formError.hidden = true;
  els.formError.textContent = "";
}

function openCookieDialog(username = "") {
  clearCookieForm();
  if (username) els.username.value = username;
  if (typeof els.dialog.showModal === "function") {
    els.dialog.showModal();
  }
  (username ? els.cookies : els.username).focus();
}

function closeCookieDialog() {
  clearCookieForm();
  if (els.dialog.open) els.dialog.close();
}

function selectedProxyMode() {
  if (els.editProxySet.checked) return "set";
  if (els.editProxyClear.checked) return "clear";
  return "keep";
}

function syncProxyInputVisibility() {
  const isSet = selectedProxyMode() === "set";
  els.editProxyLabel.hidden = !isSet;
  els.editProxy.disabled = !isSet;
  if (!isSet) els.editProxy.value = "";
}

function setEditFormError(message) {
  els.editFormError.textContent = message || "";
  els.editFormError.hidden = !message;
}

function setDeleteFormError(message) {
  els.deleteFormError.textContent = message || "";
  els.deleteFormError.hidden = !message;
}

function clearEditSecrets() {
  els.editCookies.value = "";
  els.editProxy.value = "";
}

function resetEditForm() {
  els.editForm.reset();
  els.editUsernameDisplay.textContent = "";
  els.editProxyStatus.textContent = "未配置";
  els.editProxyStatus.classList.remove("is-configured");
  els.editProxyKeep.checked = true;
  els.editSubmit.disabled = false;
  els.editSubmit.textContent = "保存更改";
  els.deleteAccountButton.disabled = false;
  clearEditSecrets();
  setEditFormError("");
  syncProxyInputVisibility();
}

function onEditDialogClosed() {
  const shouldOpenDelete = state.openDeleteOnEditClose;
  const openingDelete = state.pendingDelete;
  state.openDeleteOnEditClose = false;
  resetEditForm();
  state.editing = null;
  if (shouldOpenDelete && openingDelete && openingDelete.username) {
    window.setTimeout(() => {
      if (!els.deleteDialog.open) openDeleteDialog(openingDelete);
    }, 0);
  }
}

function closeEditDialog() {
  if (els.editDialog.open) {
    els.editDialog.close();
  } else {
    onEditDialogClosed();
  }
}

function openEditDialog(username) {
  const account = state.accounts.find((item) => item.username === username);
  if (!account) return;
  resetEditForm();
  state.editing = String(account.username || "");
  els.editUsernameDisplay.textContent = `@${state.editing}`;
  els.editActive.checked = Boolean(account.active);
  const hasProxy = Boolean(account.has_proxy);
  els.editProxyStatus.textContent = hasProxy ? "已配置" : "未配置";
  els.editProxyStatus.classList.toggle("is-configured", hasProxy);
  els.editProxyKeep.checked = true;
  syncProxyInputVisibility();
  if (typeof els.editDialog.showModal === "function") {
    els.editDialog.showModal();
  }
  els.editActive.focus();
}

function updateDeleteSubmitState() {
  const expected = state.pendingDelete ? state.pendingDelete.username : "";
  const typed = String(els.deleteConfirm.value || "");
  els.deleteSubmit.disabled = !expected || typed !== expected;
}

function resetDeleteForm() {
  els.deleteForm.reset();
  els.deleteSummary.textContent = "";
  els.deleteConfirm.value = "";
  els.deleteSubmit.textContent = "确认删除";
  setDeleteFormError("");
  updateDeleteSubmitState();
}

function onDeleteDialogClosed() {
  resetDeleteForm();
  state.pendingDelete = null;
}

function closeDeleteDialog() {
  if (els.deleteDialog.open) {
    els.deleteDialog.close();
  } else {
    onDeleteDialogClosed();
  }
}

function openDeleteDialog(account) {
  const username = String(account.username || "");
  if (!username) return;
  resetDeleteForm();
  state.pendingDelete = {
    username,
    total_requests: Number(account.total_requests || 0),
  };
  const count = state.pendingDelete.total_requests.toLocaleString("zh-CN");
  els.deleteSummary.textContent = `将永久删除 @${username}，该账号累计 ${count} 次请求。此操作无法撤销。`;
  updateDeleteSubmitState();
  if (typeof els.deleteDialog.showModal === "function") {
    els.deleteDialog.showModal();
  }
  els.deleteConfirm.focus();
}

function startDeleteFromEdit() {
  const username = state.editing;
  if (!username) return;
  const account = state.accounts.find((item) => item.username === username);
  state.pendingDelete = {
    username: String((account && account.username) || username),
    total_requests: Number((account && account.total_requests) || 0),
  };
  if (els.editDialog.open) {
    state.openDeleteOnEditClose = true;
    els.editDialog.close();
  } else {
    state.openDeleteOnEditClose = false;
    openDeleteDialog(state.pendingDelete);
  }
}

function clearSensitiveInputs() {
  els.cookies.value = "";
  clearEditSecrets();
}

function setSync(text) {
  els.updated.textContent = text;
}

async function loadAccounts() {
  setSync("正在刷新");
  try {
    const data = await api("/admin/accounts");
    state.accounts = Array.isArray(data.accounts) ? data.accounts : [];
    state.summary = data.summary || null;
    state.loadError = "";
    if (state.expanded && !state.accounts.some((item) => item.username === state.expanded)) {
      state.expanded = null;
    }
    renderSummary();
    renderAccounts();
    const stamp = data.updated_at ? new Date(data.updated_at) : new Date();
    setSync(
      `已更新 ${stamp.toLocaleTimeString("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })}`
    );
  } catch (error) {
    state.loadError = error.message || "无法读取账号池";
    renderSummary();
    setSync("刷新失败");
    showToast(state.loadError, true);
  }
}

async function runAccountAction(action, username, button) {
  if (!username) return;
  if (action === "manage") {
    openEditDialog(username);
    return;
  }
  if (action === "add_cookie") {
    openCookieDialog(username);
    return;
  }
  if (action === "reset") {
    const ok = window.confirm(
      "只会清除这个账号在本机的限流锁，不能绕过 X 侧的真实限流。确定继续？"
    );
    if (!ok) return;
  }
  if (button) button.disabled = true;
  try {
    if (action === "enable" || action === "disable") {
      await api(`/admin/accounts/${encodeURIComponent(username)}`, {
        method: "PATCH",
        body: JSON.stringify({ active: action === "enable" }),
      });
      showToast(action === "enable" ? "账号已启用" : "账号已停用");
    } else if (action === "reset") {
      await api(`/admin/accounts/${encodeURIComponent(username)}/reset-locks`, {
        method: "POST",
        body: "{}",
      });
      showToast("本地锁已清除");
    }
    await loadAccounts();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

function toggleExpanded(username) {
  state.expanded = state.expanded === username ? null : username;
  renderAccounts();
  for (const row of els.rows.querySelectorAll("tr.account-row")) {
    if (row.dataset.username === username) {
      row.focus();
      break;
    }
  }
}

els.search.addEventListener("input", renderAccounts);
els.filter.addEventListener("change", () => {
  renderSummary();
  renderAccounts();
});
els.addButton.addEventListener("click", () => openCookieDialog());
els.closeDialog.addEventListener("click", closeCookieDialog);
els.cancelDialog.addEventListener("click", closeCookieDialog);
els.dialog.addEventListener("close", clearCookieForm);
els.dialog.addEventListener("cancel", clearCookieForm);

els.closeEditDialog.addEventListener("click", closeEditDialog);
els.cancelEditDialog.addEventListener("click", closeEditDialog);
els.editDialog.addEventListener("close", onEditDialogClosed);
els.editDialog.addEventListener("cancel", resetEditForm);
els.deleteAccountButton.addEventListener("click", startDeleteFromEdit);

els.editForm.addEventListener("change", (event) => {
  if (event.target && event.target.name === "editProxyMode") {
    const wasSet = !els.editProxyLabel.hidden;
    syncProxyInputVisibility();
    if (!wasSet && selectedProxyMode() === "set") {
      els.editProxy.focus();
    }
  }
});

els.editForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = state.editing;
  if (!username) return;
  setEditFormError("");
  const proxyMode = selectedProxyMode();
  const cookies = String(els.editCookies.value || "").trim();
  const proxy = String(els.editProxy.value || "").trim();
  if (proxyMode === "set" && !proxy) {
    setEditFormError("请输入代理地址");
    els.editProxy.focus();
    return;
  }
  const payload = {
    active: Boolean(els.editActive.checked),
    proxy_mode: proxyMode,
  };
  if (cookies) payload.cookies = cookies;
  if (proxyMode === "set") payload.proxy = proxy;
  els.editSubmit.disabled = true;
  els.deleteAccountButton.disabled = true;
  const original = els.editSubmit.textContent;
  els.editSubmit.textContent = "保存中…";
  try {
    await api(`/admin/accounts/${encodeURIComponent(username)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    closeEditDialog();
    showToast("账号已更新");
    await loadAccounts();
  } catch (error) {
    setEditFormError(error.message || "保存失败");
  } finally {
    clearEditSecrets();
    els.editSubmit.disabled = false;
    els.deleteAccountButton.disabled = false;
    els.editSubmit.textContent = original;
  }
});

els.closeDeleteDialog.addEventListener("click", closeDeleteDialog);
els.cancelDeleteDialog.addEventListener("click", closeDeleteDialog);
els.deleteDialog.addEventListener("close", onDeleteDialogClosed);
els.deleteDialog.addEventListener("cancel", resetDeleteForm);
els.deleteConfirm.addEventListener("input", updateDeleteSubmitState);

els.deleteForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = state.pendingDelete ? state.pendingDelete.username : "";
  const confirmUsername = String(els.deleteConfirm.value || "");
  if (!username) return;
  if (confirmUsername !== username) {
    setDeleteFormError("请输入完整账号名称确认删除");
    updateDeleteSubmitState();
    els.deleteConfirm.focus();
    return;
  }
  setDeleteFormError("");
  els.deleteSubmit.disabled = true;
  const original = els.deleteSubmit.textContent;
  els.deleteSubmit.textContent = "删除中…";
  try {
    await api(`/admin/accounts/${encodeURIComponent(username)}`, {
      method: "DELETE",
      body: JSON.stringify({ confirm_username: confirmUsername }),
    });
    if (state.expanded === username) state.expanded = null;
    if (state.editing === username) state.editing = null;
    closeDeleteDialog();
    showToast("账号已删除");
    await loadAccounts();
  } catch (error) {
    setDeleteFormError(error.message || "删除失败");
    updateDeleteSubmitState();
  } finally {
    els.deleteSubmit.textContent = original;
    updateDeleteSubmitState();
  }
});

els.viewAttention.addEventListener("click", () => {
  els.filter.value = "attention";
  renderAccounts();
  els.accountsHeading.scrollIntoView({ behavior: "smooth", block: "start" });
});

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  els.formError.hidden = true;
  els.formError.textContent = "";
  els.submit.disabled = true;
  const original = els.submit.textContent;
  els.submit.textContent = "提交中…";
  const username = String(els.username.value || "").trim();
  const cookies = String(els.cookies.value || "").trim();
  try {
    await api("/admin/accounts", {
      method: "POST",
      body: JSON.stringify({ username, cookies }),
    });
    clearCookieForm();
    if (els.dialog.open) els.dialog.close();
    showToast("账号已添加");
    await loadAccounts();
  } catch (error) {
    els.formError.textContent = error.message;
    els.formError.hidden = false;
  } finally {
    els.cookies.value = "";
    els.submit.disabled = false;
    els.submit.textContent = original;
  }
});

els.rows.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (button) {
    event.preventDefault();
    event.stopPropagation();
    runAccountAction(button.dataset.action, button.dataset.user, button);
    return;
  }
  if (event.target.closest(".row-actions")) {
    event.preventDefault();
    event.stopPropagation();
    return;
  }
  const row = event.target.closest("tr.account-row");
  if (row) toggleExpanded(row.dataset.username);
});

els.rows.addEventListener("keydown", (event) => {
  if (event.target.closest("button")) return;
  const row = event.target.closest("tr.account-row");
  if (!row) return;
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    toggleExpanded(row.dataset.username);
  }
});

async function loadSession() {
  try {
    const data = await api("/auth/session");
    const username = String(data.username || "");
    if (!username) {
      els.sessionUser.hidden = true;
      els.sessionUser.textContent = "";
      return;
    }
    els.sessionUser.textContent = username;
    els.sessionUser.hidden = false;
  } catch {
    els.sessionUser.hidden = true;
    els.sessionUser.textContent = "";
  }
}

els.logout.addEventListener("click", async () => {
  els.logout.disabled = true;
  const original = els.logout.textContent;
  els.logout.textContent = "退出中…";
  try {
    await api("/auth/logout", {
      method: "POST",
      body: "{}",
    });
    location.replace("/login");
  } catch (error) {
    if (error.message === "Authentication required") {
      location.replace("/login");
      return;
    }
    showToast(error.message || "退出失败", true);
    els.logout.disabled = false;
    els.logout.textContent = original;
  }
});

window.addEventListener("pagehide", clearSensitiveInputs);
window.addEventListener("pageshow", (event) => {
  if (event.persisted) clearSensitiveInputs();
});

loadSession();
loadAccounts();
setInterval(loadAccounts, POLL_MS);

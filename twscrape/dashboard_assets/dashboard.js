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
  endpoints: [],
  selectedEndpoint: null,
  loadError: "",
};

const els = {
  health: document.querySelector("#healthBanner"),
  headline: document.querySelector("#headline"),
  healthError: document.querySelector("#healthError"),
  viewAttention: document.querySelector("#viewAttention"),
  statTotal: document.querySelector("#statTotal"),
  statRunning: document.querySelector("#statRunning"),
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
  syncDot: document.querySelector("#syncDot"),
  sessionUser: document.querySelector("#sessionUser"),
  logout: document.querySelector("#logoutButton"),
  dialog: document.querySelector("#addDialog"),
  form: document.querySelector("#addForm"),
  username: document.querySelector("#cookieUsername"),
  cookies: document.querySelector("#cookieValue"),
  formError: document.querySelector("#formError"),
  submit: document.querySelector("#submitAccount"),
  toast: document.querySelector("#toast"),
  endpointSelect: document.querySelector("#endpointSelect"),
  endpointDesc: document.querySelector("#endpointDesc"),
  paramFields: document.querySelector("#paramFields"),
  apiForm: document.querySelector("#apiForm"),
  apiError: document.querySelector("#apiError"),
  apiOutput: document.querySelector("#apiOutput"),
  apiStatus: document.querySelector("#apiStatus"),
  tryApi: document.querySelector("#tryApi"),
};

function apiHeaders() {
  return {
    "Content-Type": "application/json",
    "X-Twscrape-Token": token,
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...apiHeaders(),
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

function healthState(summary) {
  if (!summary) return "loading";
  if (summary.attention > 0) return "attention";
  if (summary.total === 0) return "empty";
  if (summary.running === 0) return "down";
  if (summary.ready === 0) return "cooling";
  return "ok";
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

function renderAccounts() {
  const accounts = filteredAccounts();
  els.rows.replaceChildren();

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

    const nameTd = document.createElement("td");
    const cell = document.createElement("div");
    cell.className = "account-cell";
    appendText(cell, "span", state.expanded === username ? "▾" : "▸", "chevron");
    const avatar = appendText(cell, "span", username.slice(0, 1) || "?", "avatar");
    avatar.setAttribute("aria-hidden", "true");
    appendText(cell, "span", `@${username}`, "account-name");
    nameTd.appendChild(cell);

    const statusTd = document.createElement("td");
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

    const loginTd = document.createElement("td");
    loginTd.textContent = loginLabel(account.login_method);

    const reqTd = document.createElement("td");
    reqTd.textContent = Number(account.total_requests || 0).toLocaleString("zh-CN");

    const usedTd = document.createElement("td");
    usedTd.className = "muted";
    usedTd.textContent = relativeTime(account.last_used);
    if (account.last_used) usedTd.title = formatDateTime(account.last_used);

    const lockTd = document.createElement("td");
    const recovery = lockRecovery(account);
    lockTd.textContent = recovery.text;
    if (recovery.title) lockTd.title = recovery.title;
    if (recovery.text === "—") lockTd.className = "muted";

    const actionTd = document.createElement("td");
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
  els.health.dataset.state = state.loadError ? "down" : healthState(summary);
  els.headline.textContent =
    state.loadError || summary?.headline || "正在读取账号池…";
  els.healthError.hidden = !state.loadError;
  els.healthError.textContent = state.loadError;

  const attention = Number(summary?.attention || 0);
  els.statTotal.textContent = summary ? String(summary.total ?? 0) : "—";
  els.statRunning.textContent = summary ? String(summary.running ?? 0) : "—";
  els.statCooling.textContent = summary ? String(summary.cooling ?? 0) : "—";
  els.statAttention.textContent = summary ? String(attention) : "—";
  els.statDisabled.textContent = summary ? String(summary.disabled ?? 0) : "—";
  els.statAttention.classList.toggle("has-attention", attention > 0);
  els.viewAttention.hidden = attention <= 0;
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

function setSync(status, text) {
  els.syncDot.classList.toggle("busy", status === "busy");
  els.syncDot.classList.toggle("error", status === "error");
  els.updated.textContent = text;
}

async function loadAccounts() {
  setSync("busy", "正在刷新");
  try {
    const data = await api("/api/accounts");
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
      "ok",
      `已更新 ${stamp.toLocaleTimeString("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })}`
    );
  } catch (error) {
    state.loadError = error.message || "无法读取账号池";
    renderSummary();
    setSync("error", "刷新失败");
    showToast(state.loadError, true);
  }
}

function currentEndpoint() {
  const index = Number(els.endpointSelect.value);
  if (!Number.isInteger(index) || !state.endpoints[index]) return null;
  return state.endpoints[index];
}

function paramValues() {
  const values = {};
  for (const input of els.paramFields.querySelectorAll("[data-param]")) {
    values[input.dataset.param] = String(input.value || "").trim();
  }
  return values;
}

function buildEndpointUrl(endpoint, values) {
  let path = String(endpoint.path || "");
  const query = new URLSearchParams();
  for (const param of endpoint.params || []) {
    const value = values[param.name] || "";
    if (param.required && !value) {
      throw new Error(`请填写 ${param.name}`);
    }
    if (!value) continue;
    if (param.in === "path") {
      path = path.replaceAll(`{${param.name}}`, encodeURIComponent(value));
    } else if (param.in === "query") {
      query.set(param.name, value);
    }
  }
  if (path.includes("{")) {
    throw new Error("路径参数不完整");
  }
  const qs = query.toString();
  return qs ? `${path}?${qs}` : path;
}

function renderParamFields(endpoint) {
  els.paramFields.replaceChildren();
  if (!endpoint) return;
  for (const param of endpoint.params || []) {
    const label = document.createElement("label");
    const title = document.createElement("span");
    title.textContent = param.name;
    if (param.required) {
      const mark = document.createElement("span");
      mark.className = "req-mark";
      mark.textContent = " *";
      title.appendChild(mark);
    }
    const where = document.createElement("span");
    where.className = "muted";
    where.textContent = `  · ${param.in}${param.required ? " · 必填" : ""}`;
    title.appendChild(where);
    const input = document.createElement("input");
    input.type = "text";
    input.dataset.param = param.name;
    input.required = Boolean(param.required);
    input.autocomplete = "off";
    input.spellcheck = false;
    input.placeholder = param.example ? String(param.example) : "";
    input.setAttribute("aria-label", `${param.name} (${param.in})`);
    label.append(title, input);
    els.paramFields.appendChild(label);
  }
}

function onEndpointChange() {
  const endpoint = currentEndpoint();
  state.selectedEndpoint = endpoint;
  els.endpointDesc.textContent = endpoint
    ? `${endpoint.method || "GET"} ${endpoint.path} — ${endpoint.description || ""}`
    : "选择一个端点以填写参数。";
  renderParamFields(endpoint);
  els.apiError.hidden = true;
  els.apiError.textContent = "";
}

function setApiOutput(text, statusText) {
  els.apiOutput.textContent = text;
  if (statusText) els.apiStatus.textContent = statusText;
}

async function loadEndpoints() {
  try {
    const data = await api("/api/_endpoints");
    state.endpoints = Array.isArray(data.endpoints) ? data.endpoints : [];
    els.endpointSelect.replaceChildren();
    if (!state.endpoints.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "没有可用端点";
      els.endpointSelect.appendChild(option);
      return;
    }
    state.endpoints.forEach((endpoint, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = `${endpoint.name}  ${endpoint.method || "GET"} ${endpoint.path}`;
      els.endpointSelect.appendChild(option);
    });
    els.endpointSelect.value = "0";
    onEndpointChange();
  } catch (error) {
    els.endpointSelect.replaceChildren();
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "端点加载失败";
    els.endpointSelect.appendChild(option);
    els.endpointDesc.textContent = error.message || "无法读取 /api/_endpoints";
  }
}

async function runAccountAction(action, username, button) {
  if (!username) return;
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
      await api(`/api/accounts/${encodeURIComponent(username)}`, {
        method: "PATCH",
        body: JSON.stringify({ active: action === "enable" }),
      });
      showToast(action === "enable" ? "账号已启用" : "账号已停用");
    } else if (action === "reset") {
      await api(`/api/accounts/${encodeURIComponent(username)}/reset-locks`, {
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
els.filter.addEventListener("change", renderAccounts);
document.querySelector("#addButton").addEventListener("click", () => openCookieDialog());
document.querySelector("#closeDialog").addEventListener("click", closeCookieDialog);
document.querySelector("#cancelDialog").addEventListener("click", closeCookieDialog);
els.dialog.addEventListener("close", clearCookieForm);
els.dialog.addEventListener("cancel", clearCookieForm);

els.viewAttention.addEventListener("click", () => {
  els.filter.value = "attention";
  renderAccounts();
  document.querySelector("#accountsHeading").scrollIntoView({ behavior: "smooth", block: "start" });
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
    await api("/api/accounts", {
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

els.endpointSelect.addEventListener("change", onEndpointChange);

els.apiForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  els.apiError.hidden = true;
  els.apiError.textContent = "";
  const endpoint = currentEndpoint();
  if (!endpoint) {
    els.apiError.textContent = "请先选择端点";
    els.apiError.hidden = false;
    return;
  }
  let url;
  try {
    url = buildEndpointUrl(endpoint, paramValues());
  } catch (error) {
    els.apiError.textContent = error.message;
    els.apiError.hidden = false;
    return;
  }
  els.tryApi.disabled = true;
  const original = els.tryApi.textContent;
  els.tryApi.textContent = "请求中…";
  setApiOutput("请求中…", "请求中");
  try {
    const response = await fetch(url, { headers: apiHeaders() });
    if (response.status === 401) {
      location.replace("/login");
      return;
    }
    const raw = await response.text();
    let text = raw;
    try {
      text = JSON.stringify(JSON.parse(raw), null, 2);
    } catch {
      text = raw || "(空响应)";
    }
    setApiOutput(text, `${response.status} ${response.statusText || ""}`.trim());
    if (!response.ok) {
      els.apiError.textContent = `请求返回 ${response.status}`;
      els.apiError.hidden = false;
    }
  } catch (error) {
    const message = error.message || "请求失败";
    setApiOutput(message, "失败");
    els.apiError.textContent = message;
    els.apiError.hidden = false;
  } finally {
    els.tryApi.disabled = false;
    els.tryApi.textContent = original;
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

loadSession();
loadAccounts();
loadEndpoints();
setInterval(loadAccounts, POLL_MS);

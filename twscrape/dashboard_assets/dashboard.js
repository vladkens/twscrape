const token = document.querySelector('meta[name="twscrape-token"]').content;
const state = { accounts: [] };
const labels = {
  ready: "就绪",
  locked: "限流中",
  inactive: "已停用",
  session: "会话缺失",
  error: "异常",
};

const els = {
  rows: document.querySelector("#accountRows"),
  empty: document.querySelector("#emptyState"),
  total: document.querySelector("#totalCount"),
  running: document.querySelector("#runningCount"),
  attention: document.querySelector("#attentionCount"),
  updated: document.querySelector("#updatedAt"),
  search: document.querySelector("#searchInput"),
  filter: document.querySelector("#statusFilter"),
  dialog: document.querySelector("#addDialog"),
  form: document.querySelector("#addForm"),
  error: document.querySelector("#formError"),
  submit: document.querySelector("#submitAccount"),
  toast: document.querySelector("#toast"),
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  }[char]));
}

function relativeTime(value) {
  if (!value) return "从未";
  const seconds = Math.round((Date.parse(value) - Date.now()) / 1000);
  const units = [
    [86400, "天"],
    [3600, "小时"],
    [60, "分钟"],
  ];
  for (const [size, label] of units) {
    if (Math.abs(seconds) >= size) {
      return `${Math.abs(Math.round(seconds / size))} ${label}前`;
    }
  }
  return "刚刚";
}

function loginLabel(method) {
  return method === "cookies" ? "Cookie" : "密码";
}

function render() {
  const query = els.search.value.trim().toLowerCase();
  const filter = els.filter.value;
  const accounts = state.accounts.filter((account) => {
    const matchQuery = String(account.username || "").toLowerCase().includes(query);
    const matchFilter =
      filter === "all" ||
      account.status === filter ||
      (filter === "attention" && account.needs_attention);
    return matchQuery && matchFilter;
  });

  els.empty.hidden = accounts.length > 0;
  els.rows.replaceChildren();

  for (const account of accounts) {
    const tr = document.createElement("tr");
    const username = String(account.username || "");
    const errorTitle = account.error_message ? escapeHtml(account.error_message) : "";
    const queues = Array.isArray(account.locked_queues) ? account.locked_queues.join(", ") : "";
    const lockHtml = account.lock_count
      ? `<span class="status locked" title="${escapeHtml(queues)}">${escapeHtml(account.lock_count)} 个队列</span>`
      : '<span class="muted">—</span>';
    const resetBtn = account.lock_count
      ? `<button type="button" data-action="reset" data-user="${escapeHtml(username)}">清锁</button>`
      : "";

    tr.innerHTML = `
      <td>
        <div class="account-cell">
          <span class="avatar">${escapeHtml(username.slice(0, 1))}</span>
          <span class="account-name">@${escapeHtml(username)}</span>
        </div>
      </td>
      <td>
        <span class="status ${escapeHtml(account.status)}" title="${errorTitle}">
          ${escapeHtml(labels[account.status] || account.status)}
        </span>
      </td>
      <td>${escapeHtml(loginLabel(account.login_method))}</td>
      <td>${escapeHtml(Number(account.total_requests || 0).toLocaleString("zh-CN"))}</td>
      <td class="muted">${escapeHtml(relativeTime(account.last_used))}</td>
      <td>${lockHtml}</td>
      <td>
        <div class="row-actions">
          ${resetBtn}
          <button type="button" data-action="toggle" data-user="${escapeHtml(username)}" data-active="${account.active ? "true" : "false"}">
            ${account.active ? "停用" : "启用"}
          </button>
        </div>
      </td>
    `;
    els.rows.appendChild(tr);
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Twscrape-Token": token,
      ...(options.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error || "请求失败");
  }
  return body;
}

async function load() {
  try {
    const data = await api("/api/accounts");
    state.accounts = Array.isArray(data.accounts) ? data.accounts : [];
    els.total.textContent = data.summary?.total ?? 0;
    els.running.textContent = data.summary?.running ?? 0;
    els.attention.textContent = data.summary?.attention ?? 0;
    const stamp = data.updated_at ? new Date(data.updated_at) : new Date();
    els.updated.textContent = `已更新 ${stamp.toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })}`;
    render();
  } catch (error) {
    showToast(error.message, true);
  }
}

function showToast(message, isError = false) {
  els.toast.textContent = message;
  els.toast.classList.toggle("error", Boolean(isError));
  els.toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => els.toast.classList.remove("show"), 2400);
}

function closeAddDialog() {
  els.form.reset();
  els.error.hidden = true;
  els.error.textContent = "";
  els.dialog.close();
}

document.querySelector("#addButton").addEventListener("click", () => {
  els.error.hidden = true;
  els.dialog.showModal();
});
document.querySelector("#closeDialog").addEventListener("click", closeAddDialog);
document.querySelector("#cancelDialog").addEventListener("click", closeAddDialog);
els.search.addEventListener("input", render);
els.filter.addEventListener("change", render);

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  els.error.hidden = true;
  els.submit.disabled = true;
  els.submit.textContent = "添加中…";
  const form = new FormData(els.form);
  const username = String(form.get("username") || "").trim();
  const cookies = String(form.get("cookies") || "").trim();
  try {
    await api("/api/accounts", {
      method: "POST",
      body: JSON.stringify({ username, cookies }),
    });
    form.set("cookies", "");
    els.form.reset();
    els.dialog.close();
    showToast("账号已添加");
    await load();
  } catch (error) {
    els.error.textContent = error.message;
    els.error.hidden = false;
  } finally {
    els.submit.disabled = false;
    els.submit.textContent = "添加账号";
  }
});

els.rows.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const username = button.dataset.user;
  button.disabled = true;
  try {
    if (button.dataset.action === "toggle") {
      const nextActive = button.dataset.active !== "true";
      await api(`/api/accounts/${encodeURIComponent(username)}`, {
        method: "PATCH",
        body: JSON.stringify({ active: nextActive }),
      });
      showToast(nextActive ? "账号已启用" : "账号已停用");
    } else if (button.dataset.action === "reset") {
      if (!confirm("只清除这个账号的本地锁。X 侧的真实限流可能仍然存在，继续吗？")) {
        return;
      }
      await api(`/api/accounts/${encodeURIComponent(username)}/reset-locks`, {
        method: "POST",
        body: "{}",
      });
      showToast("本地锁已清除");
    }
    await load();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
});

load();
setInterval(load, 30000);

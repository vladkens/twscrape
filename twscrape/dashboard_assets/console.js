const tokenMeta = document.querySelector('meta[name="twscrape-token"]');
const token = tokenMeta ? tokenMeta.content : "";

const BEARER_PLACEHOLDER = "tws_your_key_here";

const state = {
  endpoints: [],
  selectedEndpoint: null,
  keys: [],
  hasSent: false,
  createdToken: "",
  tokenCanClose: false,
  pendingRevoke: null,
};

const els = {
  sessionUser: document.querySelector("#sessionUser"),
  logout: document.querySelector("#logoutButton"),
  endpointSelect: document.querySelector("#endpointSelect"),
  endpointDesc: document.querySelector("#endpointDesc"),
  paramFields: document.querySelector("#paramFields"),
  apiForm: document.querySelector("#apiForm"),
  apiError: document.querySelector("#apiError"),
  apiOutput: document.querySelector("#apiOutput"),
  apiStatus: document.querySelector("#apiStatus"),
  resultMeta: document.querySelector("#resultMeta"),
  tryApi: document.querySelector("#tryApi"),
  keyRows: document.querySelector("#keyRows"),
  keysEmpty: document.querySelector("#keysEmpty"),
  keysEmptyTitle: document.querySelector("#keysEmptyTitle"),
  keysEmptyHint: document.querySelector("#keysEmptyHint"),
  keysError: document.querySelector("#keysError"),
  createKeyButton: document.querySelector("#createKeyButton"),
  createKeyDialog: document.querySelector("#createKeyDialog"),
  createKeyForm: document.querySelector("#createKeyForm"),
  createKeyTitle: document.querySelector("#createKeyTitle"),
  createKeyLead: document.querySelector("#createKeyLead"),
  createKeySetup: document.querySelector("#createKeySetup"),
  createKeyReveal: document.querySelector("#createKeyReveal"),
  closeCreateKey: document.querySelector("#closeCreateKey"),
  cancelCreateKey: document.querySelector("#cancelCreateKey"),
  keyName: document.querySelector("#keyName"),
  createKeyError: document.querySelector("#createKeyError"),
  submitCreateKey: document.querySelector("#submitCreateKey"),
  keyToken: document.querySelector("#keyToken"),
  copyHint: document.querySelector("#copyHint"),
  copyKey: document.querySelector("#copyKey"),
  confirmSaved: document.querySelector("#confirmSaved"),
  manualCopyRow: document.querySelector("#manualCopyRow"),
  manualCopyConfirm: document.querySelector("#manualCopyConfirm"),
  revokeDialog: document.querySelector("#revokeDialog"),
  revokeForm: document.querySelector("#revokeForm"),
  revokeSummary: document.querySelector("#revokeSummary"),
  revokeConfirm: document.querySelector("#revokeConfirmName"),
  revokeFormError: document.querySelector("#revokeFormError"),
  closeRevoke: document.querySelector("#closeRevoke"),
  cancelRevoke: document.querySelector("#cancelRevoke"),
  submitRevoke: document.querySelector("#submitRevoke"),
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

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", { hour12: false });
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

function isActiveKey(key) {
  return Boolean(key && key.active) && !key.revoked_at;
}

function keyPrefix(key) {
  return String(key.prefix || key.key_prefix || "—");
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

function buildEndpointUrl(endpoint, values, { requireRequired = true } = {}) {
  let path = String(endpoint.path || "");
  const query = new URLSearchParams();
  for (const param of endpoint.params || []) {
    const value = values[param.name] || "";
    if (param.required && !value && requireRequired) {
      throw new Error(`请填写 ${param.name}`);
    }
    if (!value) continue;
    if (param.in === "path") {
      path = path.replaceAll(`{${param.name}}`, encodeURIComponent(value));
    } else if (param.in === "query") {
      query.set(param.name, value);
    }
  }
  if (requireRequired && path.includes("{")) {
    throw new Error("路径参数不完整");
  }
  const qs = query.toString();
  return qs ? `${path}?${qs}` : path;
}

function buildCurlExample(endpoint, values) {
  const path = endpoint
    ? buildEndpointUrl(endpoint, values, { requireRequired: false })
    : "/api";
  const url = `${location.origin}${path}`;
  return [
    "curl -sS \\",
    `  -H "Authorization: Bearer ${BEARER_PLACEHOLDER}" \\`,
    `  "${url}"`,
  ].join("\n");
}

function showCurlPreview() {
  setApiOutput(buildCurlExample(currentEndpoint(), paramValues()), "curl 示例", "");
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
  if (!state.hasSent) showCurlPreview();
}

function setApiOutput(text, statusText, tone) {
  els.apiOutput.textContent = text;
  if (statusText) els.apiStatus.textContent = statusText;
  els.resultMeta.classList.toggle("is-ok", tone === "ok");
  els.resultMeta.classList.toggle("is-bad", tone === "bad");
}

function setEndpointPlaceholder(label) {
  els.endpointSelect.replaceChildren();
  const option = document.createElement("option");
  option.value = "";
  option.textContent = label;
  els.endpointSelect.appendChild(option);
}

async function loadEndpoints() {
  try {
    const data = await api("/api/_endpoints");
    state.endpoints = Array.isArray(data.endpoints) ? data.endpoints : [];
    els.endpointSelect.replaceChildren();
    if (!state.endpoints.length) {
      setEndpointPlaceholder("没有可用端点");
      showCurlPreview();
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
    setEndpointPlaceholder("端点加载失败");
    els.endpointDesc.textContent = error.message || "无法读取 /api/_endpoints";
    showCurlPreview();
  }
}

function renderKeys() {
  els.keyRows.replaceChildren();
  if (!state.keys.length) {
    els.keysEmpty.hidden = false;
    els.keysEmptyTitle.textContent = "还没有 API 密钥";
    els.keysEmptyHint.textContent = "新建密钥后即可在 curl 中使用";
    return;
  }

  els.keysEmpty.hidden = true;
  const fragment = document.createDocumentFragment();

  for (const key of state.keys) {
    const active = isActiveKey(key);
    const name = String(key.name || "");
    const tr = document.createElement("tr");
    tr.className = "key-row";
    if (!active) tr.classList.add("row-revoked");

    const nameTd = labeledCell("名称", "cell-name");
    appendText(nameTd, "span", name, "key-name");

    const prefixTd = labeledCell("前缀", "key-prefix");
    prefixTd.textContent = keyPrefix(key);

    const createdTd = labeledCell("创建时间", "cell-meta");
    createdTd.textContent = formatDateTime(key.created_at);
    if (key.created_at) createdTd.title = formatDateTime(key.created_at);

    const usedTd = labeledCell("最后使用", "key-used");
    usedTd.textContent = relativeTime(key.last_used_at);
    if (key.last_used_at) usedTd.title = formatDateTime(key.last_used_at);

    const statusTd = labeledCell("状态");
    appendText(
      statusTd,
      "span",
      active ? "有效" : "已撤销",
      active ? "status status-ready" : "status status-revoked"
    );

    const actionTd = labeledCell("操作", "cell-actions");
    const actions = document.createElement("div");
    actions.className = "row-actions";
    if (active) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "action-revoke";
      button.dataset.action = "revoke";
      button.dataset.keyId = String(key.id || "");
      button.textContent = "撤销";
      button.setAttribute("aria-haspopup", "dialog");
      button.setAttribute("aria-label", `撤销密钥 ${name}`);
      actions.appendChild(button);
    } else {
      appendText(actions, "span", "—", "muted");
    }
    actionTd.appendChild(actions);

    tr.append(nameTd, prefixTd, createdTd, usedTd, statusTd, actionTd);
    fragment.appendChild(tr);
  }

  els.keyRows.appendChild(fragment);
}

async function loadKeys() {
  try {
    const data = await api("/admin/keys");
    const keys = Array.isArray(data.keys) ? data.keys.slice() : [];
    keys.sort((a, b) => Number(isActiveKey(b)) - Number(isActiveKey(a)));
    state.keys = keys;
    els.keysError.hidden = true;
    els.keysError.textContent = "";
    renderKeys();
  } catch (error) {
    const message = error.message || "无法读取密钥列表";
    els.keysError.textContent = message;
    els.keysError.hidden = false;
    showToast(message, true);
  }
}

function setCreateKeyError(message) {
  els.createKeyError.textContent = message || "";
  els.createKeyError.hidden = !message;
}

function setCopyHint(message) {
  els.copyHint.textContent = message || "";
  els.copyHint.hidden = !message;
}

function revealLocked() {
  return Boolean(state.createdToken) && !state.tokenCanClose;
}

function syncRevealLock() {
  const locked = revealLocked();
  els.closeCreateKey.hidden = locked;
  if (locked) {
    els.createKeyDialog.setAttribute("closedby", "none");
  } else {
    els.createKeyDialog.removeAttribute("closedby");
  }
}

function showCreateSetup() {
  els.createKeySetup.hidden = false;
  els.createKeyReveal.hidden = true;
  els.createKeyTitle.textContent = "新建密钥";
  els.createKeyLead.textContent = "名称仅用于识别，不会写入密钥本身。";
  els.submitCreateKey.disabled = false;
  els.submitCreateKey.textContent = "创建";
  setCreateKeyError("");
  syncRevealLock();
}

function clearCreatedToken() {
  state.createdToken = "";
  state.tokenCanClose = false;
  els.keyToken.value = "";
  setCopyHint("");
  els.copyKey.disabled = false;
  els.copyKey.textContent = "复制";
  els.confirmSaved.disabled = true;
  els.confirmSaved.textContent = "我已保存";
  els.manualCopyRow.hidden = true;
  els.manualCopyConfirm.checked = false;
  syncRevealLock();
}

function resetCreateKeyForm() {
  els.createKeyForm.reset();
  els.keyName.value = "";
  clearCreatedToken();
  showCreateSetup();
}

function openCreateKeyDialog() {
  resetCreateKeyForm();
  if (typeof els.createKeyDialog.showModal === "function") {
    els.createKeyDialog.showModal();
  }
  els.keyName.focus();
}

function closeCreateKeyDialog(force = false) {
  if (revealLocked() && !force) return;
  state.tokenCanClose = true;
  syncRevealLock();
  if (els.createKeyDialog.open) {
    els.createKeyDialog.close();
  } else {
    resetCreateKeyForm();
  }
}

function showCreatedToken(plainToken) {
  const value = String(plainToken || "");
  if (!value) {
    showToast("密钥已创建，但未返回明文", true);
    return;
  }
  state.createdToken = value;
  state.tokenCanClose = false;
  els.createKeySetup.hidden = true;
  els.createKeyReveal.hidden = false;
  els.submitCreateKey.disabled = true;
  els.createKeyTitle.textContent = "保存 API 密钥";
  els.createKeyLead.textContent = "明文只显示这一次。请复制并放到安全的地方。";
  els.keyToken.value = value;
  els.copyKey.disabled = false;
  els.copyKey.textContent = "复制";
  els.confirmSaved.disabled = true;
  els.confirmSaved.textContent = "我已保存";
  els.manualCopyRow.hidden = true;
  els.manualCopyConfirm.checked = false;
  setCopyHint("");
  syncRevealLock();
  els.copyKey.focus();
}

function allowTokenClose() {
  state.tokenCanClose = true;
  els.confirmSaved.disabled = false;
  syncRevealLock();
}

function selectTokenText() {
  els.keyToken.focus();
  if (typeof els.keyToken.select === "function") {
    els.keyToken.select();
  }
}

async function copyCreatedToken() {
  const value = state.createdToken;
  if (!value) return;
  try {
    if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
      throw new Error("clipboard unavailable");
    }
    await navigator.clipboard.writeText(value);
    els.copyKey.textContent = "已复制";
    setCopyHint("已复制到剪贴板");
    els.confirmSaved.textContent = "我已保存";
    els.manualCopyRow.hidden = true;
    allowTokenClose();
    els.confirmSaved.focus();
  } catch {
    selectTokenText();
    els.confirmSaved.textContent = "我已手动保存";
    els.confirmSaved.disabled = false;
    els.manualCopyRow.hidden = true;
    els.manualCopyConfirm.checked = false;
    setCopyHint("无法自动复制，请手动选择并复制上方密钥");
    els.confirmSaved.focus();
  }
}

function setRevokeFormError(message) {
  els.revokeFormError.textContent = message || "";
  els.revokeFormError.hidden = !message;
}

function updateRevokeSubmitState() {
  const expected = state.pendingRevoke ? state.pendingRevoke.name : "";
  const typed = String(els.revokeConfirm.value || "");
  els.submitRevoke.disabled = !expected || typed !== expected;
}

function resetRevokeForm() {
  els.revokeForm.reset();
  els.revokeSummary.textContent = "";
  els.revokeConfirm.value = "";
  els.submitRevoke.textContent = "确认撤销";
  setRevokeFormError("");
  updateRevokeSubmitState();
}

function onRevokeDialogClosed() {
  resetRevokeForm();
  state.pendingRevoke = null;
}

function closeRevokeDialog() {
  if (els.revokeDialog.open) {
    els.revokeDialog.close();
  } else {
    onRevokeDialogClosed();
  }
}

function openRevokeDialog(key) {
  const id = String(key.id || "");
  const name = String(key.name || "");
  if (!id || !name) return;
  resetRevokeForm();
  state.pendingRevoke = { id, name };
  els.revokeSummary.textContent = `将撤销「${name}」。已发出的请求不会被收回，此操作无法恢复明文。`;
  updateRevokeSubmitState();
  if (typeof els.revokeDialog.showModal === "function") {
    els.revokeDialog.showModal();
  }
  els.revokeConfirm.focus();
}

els.endpointSelect.addEventListener("change", onEndpointChange);
els.paramFields.addEventListener("input", () => {
  if (!state.hasSent) showCurlPreview();
});

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
  const method = String(endpoint.method || "GET").toUpperCase();
  if (method !== "GET") {
    els.apiError.textContent = "试用台仅支持只读 GET";
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
    state.hasSent = true;
    const statusText = `${response.status} ${response.statusText || ""}`.trim();
    setApiOutput(text, statusText, response.ok ? "ok" : "bad");
    if (!response.ok) {
      els.apiError.textContent = `请求返回 ${response.status}`;
      els.apiError.hidden = false;
    }
  } catch (error) {
    const message = error.message || "请求失败";
    state.hasSent = true;
    setApiOutput(message, "失败", "bad");
    els.apiError.textContent = message;
    els.apiError.hidden = false;
  } finally {
    els.tryApi.disabled = false;
    els.tryApi.textContent = original;
  }
});

els.createKeyButton.addEventListener("click", openCreateKeyDialog);
els.closeCreateKey.addEventListener("click", () => closeCreateKeyDialog());
els.cancelCreateKey.addEventListener("click", () => closeCreateKeyDialog());
els.confirmSaved.addEventListener("click", () => closeCreateKeyDialog(true));
els.createKeyDialog.addEventListener("close", () => {
  if (revealLocked()) {
    window.setTimeout(() => {
      if (revealLocked() && !els.createKeyDialog.open) {
        if (typeof els.createKeyDialog.showModal === "function") {
          els.createKeyDialog.showModal();
        }
        syncRevealLock();
      }
    }, 0);
    return;
  }
  resetCreateKeyForm();
});

els.createKeyDialog.addEventListener("cancel", (event) => {
  if (revealLocked()) event.preventDefault();
});

els.createKeyDialog.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && revealLocked()) {
    event.preventDefault();
    event.stopPropagation();
  }
});

els.createKeyDialog.addEventListener("click", (event) => {
  if (event.target === els.createKeyDialog && revealLocked()) {
    event.preventDefault();
    event.stopPropagation();
  }
});

els.createKeyForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.createdToken) return;
  setCreateKeyError("");
  const name = String(els.keyName.value || "").trim();
  if (!name) {
    setCreateKeyError("请输入密钥名称");
    els.keyName.focus();
    return;
  }
  els.submitCreateKey.disabled = true;
  const original = els.submitCreateKey.textContent;
  els.submitCreateKey.textContent = "创建中…";
  try {
    const data = await api("/admin/keys", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    const plainToken = typeof data.token === "string" ? data.token : "";
    showToast("密钥已创建，请立即保存");
    await loadKeys();
    showCreatedToken(plainToken);
  } catch (error) {
    setCreateKeyError(error.message || "创建失败");
  } finally {
    if (!state.createdToken) {
      els.submitCreateKey.disabled = false;
      els.submitCreateKey.textContent = original;
    }
  }
});

els.copyKey.addEventListener("click", copyCreatedToken);
els.manualCopyConfirm.addEventListener("change", () => {
  if (els.manualCopyConfirm.checked) {
    els.confirmSaved.textContent = "我已手动保存";
    allowTokenClose();
    return;
  }
  if (!state.tokenCanClose) return;
  const copied = els.copyKey.textContent === "已复制";
  if (copied) return;
  state.tokenCanClose = false;
  els.confirmSaved.disabled = true;
  syncRevealLock();
});

els.keyRows.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action='revoke']");
  if (!button) return;
  event.preventDefault();
  const keyId = String(button.dataset.keyId || "");
  const key = state.keys.find((item) => String(item.id || "") === keyId);
  if (key) openRevokeDialog(key);
});

els.closeRevoke.addEventListener("click", closeRevokeDialog);
els.cancelRevoke.addEventListener("click", closeRevokeDialog);
els.revokeDialog.addEventListener("close", onRevokeDialogClosed);
els.revokeConfirm.addEventListener("input", updateRevokeSubmitState);

els.revokeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const pending = state.pendingRevoke;
  const confirmName = String(els.revokeConfirm.value || "");
  if (!pending || !pending.id) return;
  if (confirmName !== pending.name) {
    setRevokeFormError("请输入完整密钥名称确认撤销");
    updateRevokeSubmitState();
    els.revokeConfirm.focus();
    return;
  }
  setRevokeFormError("");
  els.submitRevoke.disabled = true;
  const original = els.submitRevoke.textContent;
  els.submitRevoke.textContent = "撤销中…";
  try {
    await api(`/admin/keys/${encodeURIComponent(pending.id)}`, {
      method: "DELETE",
      body: JSON.stringify({ confirm_name: confirmName }),
    });
    closeRevokeDialog();
    showToast("密钥已撤销");
    await loadKeys();
  } catch (error) {
    setRevokeFormError(error.message || "撤销失败");
    updateRevokeSubmitState();
  } finally {
    els.submitRevoke.textContent = original;
    updateRevokeSubmitState();
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

window.addEventListener("pagehide", clearCreatedToken);
window.addEventListener("pageshow", (event) => {
  if (event.persisted) clearCreatedToken();
});

showCurlPreview();
loadSession();
loadEndpoints();
loadKeys();

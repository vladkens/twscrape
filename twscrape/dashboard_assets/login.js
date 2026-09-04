const tokenMeta = document.querySelector('meta[name="twscrape-token"]');
const token = tokenMeta ? tokenMeta.content : "";

const els = {
  form: document.querySelector("#loginForm"),
  username: document.querySelector("#loginUsername"),
  password: document.querySelector("#loginPassword"),
  error: document.querySelector("#loginError"),
  submit: document.querySelector("#loginSubmit"),
};

for (const [name, node] of Object.entries(els)) {
  if (!node) throw new Error(`DOM 节点缺失: ${name}`);
}

function clearPassword() {
  els.password.value = "";
}

function showError(message) {
  els.error.textContent = message;
  els.error.hidden = false;
}

function hideError() {
  els.error.textContent = "";
  els.error.hidden = true;
}

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideError();
  els.submit.disabled = true;
  const original = els.submit.textContent;
  els.submit.textContent = "登录中…";
  const username = String(els.username.value || "").trim();
  const password = String(els.password.value || "");
  try {
    const response = await fetch("/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Twscrape-Token": token,
      },
      body: JSON.stringify({ username, password }),
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
    if (response.ok) {
      clearPassword();
      location.replace("/accounts");
      return;
    }
    clearPassword();
    if (response.status === 401) {
      showError("用户名或密码错误");
    } else if (response.status === 429) {
      showError(body.error || "登录尝试过多，请稍后重试");
    } else {
      showError(body.error || `请求失败 (${response.status})`);
    }
  } catch (error) {
    clearPassword();
    showError(error.message || "无法连接");
  } finally {
    els.submit.disabled = false;
    els.submit.textContent = original;
  }
});

window.addEventListener("pagehide", clearPassword);
window.addEventListener("pageshow", (event) => {
  if (event.persisted) clearPassword();
});

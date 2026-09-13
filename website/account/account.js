"use strict";
// 身份由 HttpOnly Cookie 保存；IndexedDB 仅保存本地曲谱与继承进度。
const API = "../account-api";
const $ = id => document.getElementById(id);
let user = null, mode = "login", running = false, cooldownUntil = 0;
const dbReady = new Promise((resolve, reject) => {
  const request = indexedDB.open("melodica-library", 1);
  request.onupgradeneeded = () => {
    request.result.createObjectStore("songs", {keyPath: "id"});
    request.result.createObjectStore("state");
  };
  request.onsuccess = () => resolve(request.result);
  request.onerror = () => reject(new Error("无法打开本地曲库，请检查浏览器存储设置"));
});
function result(request) { return new Promise((resolve, reject) => {request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);}); }
async function transaction(names, action) {
  const db = await dbReady, tx = db.transaction(names, "readwrite");
  const done = new Promise((resolve, reject) => {tx.oncomplete = resolve; tx.onabort = tx.onerror = () => reject(tx.error || new Error("本地曲库保存失败"));});
  try { const value = await action(tx); await done; return value; }
  catch (error) { try {tx.abort();} catch {} await done.catch(() => {}); throw error; }
}
async function records() { const db = await dbReady; return result(db.transaction("songs").objectStore("songs").getAll()); }
function status(text, error = false) { $("status").textContent = text; $("status").dataset.error = String(error); }
async function api(path, data, method) {
  const response = await fetch(API + path, {method: method || (data === undefined ? "GET" : "POST"), credentials: "same-origin", redirect: "error",
    headers: {"Content-Type": "application/json"}, body: data === undefined ? undefined : JSON.stringify(data), signal: AbortSignal.timeout(20000)});
  let payload; try {payload = await response.json();} catch {throw new Error("账号服务暂时不可用，请稍后重试");}
  if (!response.ok) {const error = new Error(typeof payload.detail === "string" ? payload.detail : "输入格式不正确，请检查邮箱、密码和验证码"); error.status = response.status; throw error;}
  return payload;
}
function setMode(next) {
  mode = next;
  document.querySelectorAll("[data-mode]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.mode === mode)));
  $("code-fields").hidden = mode === "login"; $("code").required = mode !== "login";
  $("register-note").hidden = mode !== "register";
  $("password").autocomplete = mode === "login" ? "current-password" : "new-password";
  $("password-label").textContent = mode === "reset" ? "新密码" : "密码";
  $("submit-auth").textContent = {login: "登录", register: "验证邮箱并注册", reset: "验证邮箱并重置密码"}[mode];
}
async function render() {
  $("guest-auth").hidden = !!user; $("signed-in").hidden = !user; $("merge").hidden = !user;
  $("account-email").textContent = user ? user.email : "";
  $("library-title").textContent = user ? "我的曲库" : "游客曲库";
  const local = (await records()).filter(item => item.owner === (user ? user.id : "guest"));
  $("song-list").replaceChildren(); $("empty-library").hidden = !!local.length;
  for (const item of local) {
    const li = document.createElement("li"), title = document.createElement("span"), download = document.createElement("button");
    title.textContent = item.score.title; download.textContent = "下载备份"; download.type = "button";
    download.onclick = () => {
      const url = URL.createObjectURL(new Blob([JSON.stringify(item.score)], {type: "application/json"}));
      const link = document.createElement("a"); link.href = url; link.download = item.score.title.replace(/[<>:"/\\|?*]/g, "_") + ".json";
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    li.append(title, download); $("song-list").append(li);
  }
}
async function run(action) {
  if (running) return;
  running = true; status("正在处理…");
  document.querySelectorAll("button,input").forEach(item => item.disabled = true);
  try {await action();} catch (error) {
    if (error.status === 401) {user = null; setMode("login");}
    status(error.message || "网络不可用，请稍后重试", true);
  }
  finally {
    running = false;
    document.querySelectorAll("button,input").forEach(item => item.disabled = false);
    try {await render();} catch (error) {status(error.message, true);}
    updateCooldown();
  }
}
async function claimGuest() {
  const pending = await transaction(["songs", "state"], async tx => {
    const state = tx.objectStore("state"), previous = await result(state.get("pending"));
    if (previous) {if (previous.user !== user.id) throw new Error("另一账号的游客继承尚未完成，请先登录原账号"); return previous;}
    const songs = (await result(tx.objectStore("songs").getAll())).filter(item => item.owner === "guest");
    if (!songs.length) return null;
    const value = {user: user.id, token: crypto.randomUUID().replaceAll("-", ""), ids: songs.map(item => item.id)};
    state.put(value, "pending"); return value;
  });
  if (!pending) return;
  await api("/library/claim", {guest_token: pending.token});
  await transaction(["songs", "state"], async tx => {
    const songs = tx.objectStore("songs");
    for (const id of pending.ids) {const item = await result(songs.get(id)); if (item && item.owner === "guest") {item.owner = user.id; songs.put(item);}}
    tx.objectStore("state").delete("pending");
  });
}
async function sync() {
  if (!user) {setMode("login"); $("email").focus(); throw new Error("云端同步需要登录；游客曲库和客户端本地演奏仍可使用");}
  let remote = (await api("/library/songs")).songs;
  const remoteIds = new Set(remote.map(item => item.id));
  const local = (await records()).filter(item => item.owner === user.id);
  let uploaded = 0, downloaded = 0;
  for (const item of local) {
    if (!item.cloudId || !remoteIds.has(item.cloudId)) {
      const saved = await api("/library/songs", item.score); item.cloudId = saved.id;
      await transaction(["songs"], tx => tx.objectStore("songs").put(item)); uploaded++;
    }
  }
  const known = new Set(local.map(item => item.cloudId));
  remote = (await api("/library/songs")).songs;
  for (const item of remote) {
    if (known.has(item.id)) continue;
    if (!/^[a-f0-9]{64}$/.test(item.id)) throw new Error("云端曲目标识无效");
    const score = validateScore(await api("/library/songs/" + item.id));
    await transaction(["songs"], tx => tx.objectStore("songs").put({id: user.id + ":" + item.id, owner: user.id, cloudId: item.id, score})); downloaded++;
  }
  status(`同步完成：上传 ${uploaded} 首，下载 ${downloaded} 首。`);
}
function validateScore(score) {
  if (!score || score.version !== 1 || typeof score.title !== "string" || !score.title.trim() || score.title.length > 100 || /[\x00-\x1f]/.test(score.title)
      || !Number.isInteger(score.duration) || score.duration < 1 || score.duration > 1800000 || !Array.isArray(score.notes) || !score.notes.length || score.notes.length > 30000)
    throw new Error("曲谱备份格式无效，请使用从曲库下载的 JSON 备份");
  for (const n of score.notes) if (!Array.isArray(n) || n.length !== 4 || !n.every(Number.isInteger) || n[0] < 0 || n[1] <= n[0] || n[1] > score.duration || n[2] < 0 || n[2] > 127 || n[3] < 0 || n[3] > 65535) throw new Error("曲谱音符格式无效");
  return {version: 1, title: score.title.trim(), duration: score.duration, notes: score.notes};
}
function updateCooldown() {
  const remaining = Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000));
  $("send-code").disabled = running || remaining > 0;
  $("send-code").textContent = remaining ? `${remaining} 秒后重发` : "发送验证码";
}
document.querySelectorAll("[data-mode]").forEach(button => button.onclick = () => setMode(button.dataset.mode));
$("send-code").onclick = () => run(async () => {
  if (!$("email").checkValidity()) {$("email").reportValidity(); throw new Error("请先填写有效邮箱");}
  const response = await api("/auth/request-code", {email: $("email").value.trim(), purpose: mode});
  cooldownUntil = Date.now() + 60000; status(response.message);
});
$("auth-form").onsubmit = event => {
  event.preventDefault(); const selected = mode;
  const data = {email: $("email").value.trim(), password: $("password").value};
  if (selected !== "login") data.code = $("code").value;
  if (selected !== "reset") data.client = "web";
  $("password").value = "";
  run(async () => {
    const response = await api("/auth/" + (selected === "reset" ? "reset-password" : selected), data);
    if (selected === "reset") {setMode("login"); status(response.message); return;}
    user = response.user;
    if (selected === "register") {await claimGuest(); await sync();}
    else {status("已登录。可同步云端曲库，或点击合并此浏览器的游客曲谱。");}
  });
};
$("sync").onclick = () => run(sync);
$("merge").onclick = () => {
  if (confirm("将此浏览器的游客曲谱归入当前账号，并上传至私有云端？")) run(async () => {await claimGuest(); await sync();});
};
$("logout").onclick = () => run(async () => {
  await api("/auth/logout", {}); user = null; status("已退出，游客模式可继续使用。");
});
$("import-score").onchange = event => {
  const file = event.target.files[0]; if (!file) return;
  run(async () => {
    if (file.size > 2 * 1024 * 1024) throw new Error("曲谱备份不能超过 2 MB");
    const score = validateScore(JSON.parse(await file.text()));
    await transaction(["songs"], tx => tx.objectStore("songs").put({id: crypto.randomUUID(), owner: user ? user.id : "guest", score}));
    status("已保存到本机曲库。" + (user ? "点击同步将其保存至云端。" : "注册后可自动继承。"));
  });
  event.target.value = "";
};
setInterval(updateCooldown, 1000);
run(async () => {
  try {user = (await api("/auth/me")).user; status("已登录，点击同步读取云端曲库。");}
  catch (error) {if (error.status === 401) status("当前为游客模式，可登录或注册以使用云端同步。"); else status("账号服务暂不可用，仍可使用本机曲库。", true);}
});

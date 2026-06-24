from flask import Flask, request, redirect, jsonify, render_template_string
import json
import os
import random
import string
from datetime import datetime

app = Flask(__name__)

DATA_FILE = "/data/links.json"

def load_links():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_links(links):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(links, f, indent=2, ensure_ascii=False)

def gen_code(length=6):
    chars = string.ascii_letters + string.digits
    links = load_links()
    while True:
        code = "".join(random.choices(chars, k=length))
        if code not in links:
            return code

HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>URL Short</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0f1115;
    color: #eee;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 40px 16px;
  }
  h1 {
    font-size: 2rem;
    font-weight: 700;
    margin-bottom: 8px;
    background: linear-gradient(90deg, #3D6BFF, #B43DFF);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  .subtitle { color: #6c727f; margin-bottom: 40px; font-size: 0.95rem; }
  .card {
    background: #1a1d24;
    border: 1px solid #2a2d36;
    border-radius: 16px;
    padding: 32px;
    width: 100%;
    max-width: 680px;
    margin-bottom: 24px;
  }
  .input-row { display: flex; gap: 10px; }
  input[type="text"] {
    flex: 1;
    background: #0f1115;
    border: 1px solid #2a2d36;
    border-radius: 8px;
    color: #fff;
    font-size: 14px;
    padding: 10px 14px;
    outline: none;
    transition: border-color 0.2s;
  }
  input[type="text"]:focus { border-color: #3D6BFF; }
  button {
    background: linear-gradient(90deg, #3D6BFF, #B43DFF);
    border: none;
    border-radius: 8px;
    color: #fff;
    cursor: pointer;
    font-size: 14px;
    font-weight: 600;
    padding: 10px 20px;
    transition: opacity 0.2s;
    white-space: nowrap;
  }
  button:hover { opacity: 0.8; }
  #result {
    margin-top: 16px;
    background: #0f1115;
    border: 1px solid #2a2d36;
    border-radius: 8px;
    padding: 12px 16px;
    display: none;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  #result.show { display: flex; }
  #short-url { color: #3D6BFF; font-size: 14px; word-break: break-all; }
  .copy-btn {
    background: #2a2d36;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
    flex-shrink: 0;
  }
  .copy-btn:hover { background: #3a3d46; opacity: 1; }
  .error { margin-top: 12px; color: #ff3d77; font-size: 13px; display: none; }
  .error.show { display: block; }
  h2 { font-size: 16px; font-weight: 600; margin-bottom: 20px; color: #fff; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { color: #6c727f; font-weight: 600; padding: 12px 16px; border-bottom: 1px solid #2a2d36; text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px; }
  td { padding: 14px 16px; border-bottom: 1px solid #1e2128; color: #ccc; }
  tr:last-child td { border-bottom: none; }
  td:first-child { color: #3D6BFF; font-weight: 600; }
  .long-url { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .date { color: #6c727f; font-size: 12px; white-space: nowrap; }
  .del-btn { background: rgba(255,61,119,0.1); color: #ff3d77; border-radius: 6px; padding: 5px 12px; font-size: 12px; font-weight: 600; }
  .del-btn:hover { background: rgba(255,61,119,0.2); opacity: 1; }
  .empty { color: #6c727f; text-align: center; padding: 32px; }
</style>
</head>
<body>
<h1>🔗 URL Short</h1>
<p class="subtitle">Вставьте длинную ссылку — получите короткую</p>

<div class="card">
  <div class="input-row">
    <input type="text" id="long-url" placeholder="https://example.com/very/long/url..." />
    <button onclick="shorten()">Сократить</button>
  </div>
  <div id="error" class="error"></div>
  <div id="result">
    <span id="short-url"></span>
    <button class="copy-btn" onclick="copy()">Копировать</button>
  </div>
</div>

<div class="card">
  <h2>Все ссылки</h2>
  <table id="links-table">
    <thead>
      <tr>
        <th>Короткая</th>
        <th>Оригинал</th>
        <th>Создана</th>
        <th></th>
      </tr>
    </thead>
    <tbody id="links-body">
      <tr><td colspan="4" class="empty">Загрузка...</td></tr>
    </tbody>
  </table>
</div>

<script>
const base = window.location.origin;

async function shorten() {
  const url = document.getElementById('long-url').value.trim();
  const err = document.getElementById('error');
  const res = document.getElementById('result');
  err.className = 'error';
  res.className = '';

  if (!url) { err.textContent = 'Введите ссылку'; err.className = 'error show'; return; }

  try {
    const r = await fetch('/api/shorten', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url})
    });
    const data = await r.json();
    if (!r.ok) { err.textContent = data.error || 'Ошибка'; err.className = 'error show'; return; }
    document.getElementById('short-url').textContent = base + '/' + data.code;
    res.className = 'show';
    loadLinks();
  } catch(e) {
    err.textContent = 'Ошибка соединения'; err.className = 'error show';
  }
}

async function copy() {
  const text = document.getElementById('short-url').textContent;
  await navigator.clipboard.writeText(text);
  const btn = document.querySelector('.copy-btn');
  btn.textContent = 'Скопировано!';
  setTimeout(() => btn.textContent = 'Копировать', 1500);
}

async function loadLinks() {
  const r = await fetch('/api/links');
  const data = await r.json();
  const body = document.getElementById('links-body');
  if (!data.links || data.links.length === 0) {
    body.innerHTML = '<tr><td colspan="4" class="empty">Ссылок пока нет</td></tr>';
    return;
  }
  body.innerHTML = data.links.map(l => `
    <tr>
      <td><a href="/${l.code}" target="_blank" style="color:#3D6BFF;text-decoration:none">${l.code}</a></td>
      <td><span class="long-url" title="${l.url}">${l.url}</span></td>
      <td class="date">${l.created}</td>
      <td><button class="del-btn" onclick="del('${l.code}')">✕</button></td>
    </tr>
  `).join('');
}

async function del(code) {
  await fetch('/api/links/' + code, {method: 'DELETE'});
  loadLinks();
}

document.getElementById('long-url').addEventListener('keydown', e => {
  if (e.key === 'Enter') shorten();
});

loadLinks();
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/api/shorten", methods=["POST"])
def shorten():
    data = request.get_json()
    url = (data or {}).get("url", "").strip()
    if not url:
        return jsonify({"error": "URL не указан"}), 400
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "URL должен начинаться с http:// или https://"}), 400

    links = load_links()
    for code, info in links.items():
        if info["url"] == url:
            return jsonify({"code": code})

    code = gen_code()
    links[code] = {
        "url": url,
        "created": datetime.now().strftime("%d.%m.%Y %H:%M")
    }
    save_links(links)
    return jsonify({"code": code})

@app.route("/api/links")
def list_links():
    links = load_links()
    result = [
        {"code": code, "url": info["url"], "created": info["created"]}
        for code, info in links.items()
    ]
    result.sort(key=lambda x: x["created"], reverse=True)
    return jsonify({"links": result})

@app.route("/api/links/<code>", methods=["DELETE"])
def delete_link(code):
    links = load_links()
    links.pop(code, None)
    save_links(links)
    return jsonify({"ok": True})

@app.route("/<code>")
def redirect_short(code):
    links = load_links()
    if code in links:
        return redirect(links[code]["url"], code=302)
    return "Ссылка не найдена", 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5656)

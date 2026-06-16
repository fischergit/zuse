"""Local browser-based Web UI for Zuse.

This module intentionally uses the Python standard library for the HTTP server so
`zuse-web` works after a normal `pip install -e .`. The UI talks to one persistent
in-process Zuse Agent via JSON endpoints.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from rich.console import Console

from . import __version__
from .agent import Agent
from .cli import _decide_provider, _setup_backend
from .config import CONFIG_DIR, Config, ensure_dirs, resolve_model
from .session import save_session


HTML = r"""
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Zuse Web</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --sidebar: #fbfcfe;
      --panel: #ffffff;
      --panel-2: #f8fafc;
      --line: #d7dde7;
      --line-strong: #b8c2d2;
      --text: #111827;
      --muted: #64748b;
      --blue: #1d4ed8;
      --green: #15803d;
      --red: #b91c1c;
      --yellow: #b45309;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      --sans: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
      --shadow: 0 1px 2px rgba(15, 23, 42, .05);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: var(--sans);
      color: var(--text);
      background: var(--bg);
    }
    .app { display: grid; grid-template-columns: 320px minmax(0, 1fr); height: 100vh; }
    aside {
      border-right: 1px solid var(--line);
      background: var(--sidebar);
      padding: 18px;
      overflow: auto;
    }
    main { display: flex; flex-direction: column; min-width: 0; background: var(--bg); }
    .brand {
      display:flex; align-items:center; gap: 12px;
      padding: 4px 2px 18px;
      margin-bottom: 14px;
      border-bottom: 1px solid var(--line);
    }
    .logo {
      width: 38px; height: 38px; border-radius: 10px;
      display:grid; place-items:center;
      background: #ffffff;
      border: 1px solid var(--line-strong);
      color: var(--blue); font-weight: 900; font-size: 22px;
      box-shadow: var(--shadow);
      font-family: var(--mono);
    }
    h1 { font-size: 20px; line-height: 1; margin: 0; letter-spacing: -.03em; }
    .subtitle { color: var(--muted); font-size: 12px; margin-top: 5px; font-family: var(--mono); }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      box-shadow: var(--shadow);
      padding: 14px;
      margin-bottom: 12px;
    }
    .label {
      color: var(--muted);
      font-family: var(--mono);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .10em;
      margin-bottom: 9px;
    }
    .status { display:flex; align-items:center; gap: 9px; font-weight: 700; font-size: 14px; }
    .dot { width: 8px; height: 8px; border-radius: 99px; background: var(--yellow); box-shadow: 0 0 0 3px rgba(180,83,9,.10); }
    .dot.ready { background: var(--green); box-shadow: 0 0 0 3px rgba(21,128,61,.10); }
    .dot.busy { background: var(--blue); box-shadow: 0 0 0 3px rgba(29,78,216,.10); animation: pulse 1s infinite; }
    .dot.error { background: var(--red); box-shadow: 0 0 0 3px rgba(185,28,28,.10); }
    @keyframes pulse { 50% { opacity: .35; transform: scale(.82); } }
    button {
      border: 1px solid var(--line-strong);
      border-radius: 9px;
      background: #ffffff;
      color: var(--text);
      padding: 9px 11px;
      font-weight: 650;
      cursor: pointer;
      transition: border-color .12s, background .12s, color .12s, box-shadow .12s;
      font-family: inherit;
    }
    button:hover { border-color: #93a3b8; background: #f8fafc; box-shadow: var(--shadow); }
    button:disabled { opacity: .45; cursor: not-allowed; box-shadow: none; }
    .actions { display:grid; grid-template-columns: 1fr; gap: 8px; }
    .hint { color: var(--muted); font-size: 13px; line-height: 1.45; }
    .topbar {
      display:flex; justify-content:space-between; align-items:center; gap: 14px;
      padding: 14px 22px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
      box-shadow: var(--shadow);
      z-index: 2;
    }
    .topbar strong { color: var(--text); font-family: var(--mono); letter-spacing: -.02em; }
    .chat {
      flex: 1;
      overflow: auto;
      padding: 26px clamp(18px, 5vw, 64px);
      scroll-behavior: smooth;
      background: var(--bg);
    }
    .message {
      max-width: 1040px;
      margin: 0 auto 14px;
      display: grid;
      grid-template-columns: 34px minmax(0, 1fr);
      gap: 12px;
    }
    .avatar {
      width: 34px; height: 34px; border-radius: 9px;
      display:grid; place-items:center; font-weight: 800;
      background: #ffffff;
      border: 1px solid var(--line-strong);
      color: var(--blue);
      box-shadow: var(--shadow);
      font-family: var(--mono);
      font-size: 13px;
    }
    .message.user .avatar { color: #1d4ed8; background: #eff6ff; border-color: #bfdbfe; }
    .message.assistant .avatar { color: #15803d; background: #f0fdf4; border-color: #bbf7d0; }
    .bubble {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 14px 15px;
      white-space: pre-wrap;
      line-height: 1.56;
      overflow-wrap: anywhere;
      box-shadow: var(--shadow);
    }
    .message.system .bubble { color: var(--muted); background: #fbfcfe; }
    .composer {
      padding: 14px clamp(18px, 5vw, 64px) 18px;
      border-top: 1px solid var(--line);
      background: #ffffff;
    }
    .composer-inner {
      max-width: 1040px;
      margin: 0 auto;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: end;
    }
    textarea {
      resize: none;
      min-height: 54px;
      max-height: 180px;
      border: 1px solid var(--line-strong);
      outline: none;
      color: var(--text);
      background: var(--panel-2);
      border-radius: 12px;
      padding: 14px 15px;
      font: inherit;
      line-height: 1.45;
    }
    textarea:focus { border-color: var(--blue); box-shadow: 0 0 0 3px rgba(29,78,216,.10); background: #ffffff; }
    .send { min-height: 54px; padding: 0 18px; background: #111827; color:#ffffff; border: 1px solid #111827; font-family: var(--mono); }
    .send:hover { background: #1f2937; border-color: #1f2937; }
    .top-actions { display:flex; align-items:center; gap: 8px; }
    .pill {
      display:inline-flex; align-items:center; gap: 6px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 6px 9px;
      background: #f8fafc;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      font-family: var(--mono);
    }
    .rate-list { display:grid; gap: 8px; }
    .rate-row { display:grid; gap: 5px; }
    .rate-top { display:flex; justify-content:space-between; gap: 8px; font-family: var(--mono); font-size: 11px; color: var(--muted); }
    .rate-bar { height: 7px; border: 1px solid var(--line); background: #eef2f7; border-radius: 999px; overflow: hidden; }
    .rate-fill { height: 100%; width: 0%; background: #111827; }
.rate-row.warn .rate-fill { background: #d97706; }
.rate-row.danger .rate-fill { background: #dc2626; }
.rate-row.warn .rate-top { color: #92400e; }
.rate-row.danger .rate-top { color: #991b1b; }
    .rate-empty { color: var(--muted); font-size: 12px; line-height: 1.45; }
    .quick-grid { display:grid; grid-template-columns: 1fr; gap: 7px; }
    .quick {
      text-align: left;
      font-weight: 700;
      background: #ffffff;
      font-family: var(--mono);
      font-size: 12px;
    }
    .quick small { display:block; margin-top: 3px; color: var(--muted); font-weight: 500; line-height: 1.35; font-family: var(--sans); }
    .message-head {
      display:flex; justify-content:space-between; align-items:center; gap: 10px;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: .08em;
      font-family: var(--mono);
    }
    .copy-btn {
      padding: 4px 8px;
      border-radius: 7px;
      font-size: 11px;
      font-weight: 800;
      color: var(--muted);
      background: #ffffff;
      font-family: var(--mono);
    }
    .bubble p { margin: 0 0 .8em; }
    .bubble p:last-child { margin-bottom: 0; }
    .bubble code {
      font-family: var(--mono);
      background: #f1f5f9;
      border: 1px solid #e2e8f0;
      border-radius: 5px;
      padding: 1px 5px;
      font-size: .92em;
    }
    .bubble pre {
      margin: 10px 0;
      padding: 13px;
      overflow: auto;
      background: #111827;
      color: #e5e7eb;
      border-radius: 10px;
      border: 1px solid #374151;
    }
    .bubble pre code { background: transparent; border: 0; color: inherit; padding: 0; }
    .log-box {
      max-height: 210px;
      overflow: auto;
      border: 1px solid var(--line);
      background: #0f172a;
      border-radius: 10px;
      padding: 10px;
      color: #cbd5e1;
      font-family: var(--mono);
      font-size: 11px;
      line-height: 1.45;
      white-space: pre-wrap;
    }
    .empty-log { font-family: inherit; color: #94a3b8; }
    .toast {
      position: fixed;
      right: 18px;
      bottom: 18px;
      background: #111827;
      color: #ffffff;
      padding: 10px 12px;
      border-radius: 10px;
      box-shadow: var(--shadow);
      opacity: 0;
      transform: translateY(8px);
      transition: opacity .16s, transform .16s;
      pointer-events: none;
      z-index: 10;
      font-family: var(--mono);
      font-size: 12px;
    }
    .toast.show { opacity: 1; transform: translateY(0); }
    @media (max-width: 820px) {
      .app { grid-template-columns: 1fr; }
      aside { display:none; }
      .topbar { padding: 14px 16px; }
      .chat { padding: 18px 12px; }
      .composer { padding: 12px; }
      .message { grid-template-columns: 34px minmax(0,1fr); }
      .avatar { width:34px; height:34px; border-radius: 11px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div class="brand">
        <div class="logo">Z</div>
        <div><h1>Zuse Web</h1><div class="subtitle">local agent console</div></div>
      </div>
      <div class="card">
        <div class="label">Status</div>
        <div class="status"><span id="dot" class="dot"></span><span id="status">Verbinde …</span></div>
      </div>
      <div class="card">
        <div class="label">Backend</div>
        <div id="backend" class="hint">Wird geladen …</div>
      </div>
      <div class="card" id="rateCard">
        <div class="label">Codex Rate Limit</div>
        <div id="rateLimit" class="rate-empty">Nur sichtbar, wenn Provider codex aktiv ist und Header geliefert wurden.</div>
      </div>
      <div class="card">
        <div class="label">Quick Commands</div>
        <div class="quick-grid">
          <button class="quick" data-prompt="Gib mir einen kurzen Überblick über den aktuellen Projektordner und nenne sinnvolle nächste Schritte.">inspect.project<small>Struktur + nächste Schritte</small></button>
          <button class="quick" data-prompt="Führe die Tests aus, analysiere Fehler und behebe sie falls nötig.">test.run<small>Ausführen, analysieren, fixen</small></button>
          <button class="quick" data-prompt="Prüfe den Git-Status und fasse die aktuellen Änderungen zusammen.">git.status<small>Änderungen zusammenfassen</small></button>
          <button class="quick" data-prompt="Erstelle einen Plan für diese Aufgabe und arbeite ihn Schritt für Schritt ab:">plan.execute<small>Aufgabe ergänzen</small></button>
        </div>
      </div>
      <div class="card actions">
        <button id="clearBtn">clear.session</button>
        <button id="costBtn">usage.cost</button>
        <button id="saveBtn">session.save</button>
      </div>
      <div class="card">
        <div class="label">Runtime Log</div>
        <div id="logBox" class="log-box"><span class="empty-log">Noch keine Tool-Ausgabe.</span></div>
      </div>
      <div class="card hint">
        <b>Shortcut:</b> Enter sendet, Shift+Enter macht eine neue Zeile. Lokaler Zugriff auf dieselbe Zuse-Toolchain wie die CLI.
      </div>
    </aside>
    <main>
      <div class="topbar"><div><strong>zuse://web</strong></div><div class="top-actions"><span id="jobPill" class="pill">Keine Jobs</span><div id="mobileStatus" class="hint">Initialisiere …</div></div></div>
      <div id="chat" class="chat"></div>
      <div class="composer">
        <div class="composer-inner">
          <textarea id="input" placeholder="Command or task for Zuse …" rows="2"></textarea>
          <button id="sendBtn" class="send">RUN</button>
        </div>
      </div>
    </main>
  </div>
<div id="toast" class="toast"></div>
  <script>
  const chat = document.getElementById('chat');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('sendBtn');
  const statusEl = document.getElementById('status');
  const mobileStatus = document.getElementById('mobileStatus');
  const backendEl = document.getElementById('backend');
  const dot = document.getElementById('dot');
  const jobPill = document.getElementById('jobPill');
  const logBox = document.getElementById('logBox');
  const rateLimitEl = document.getElementById('rateLimit');
  const toast = document.getElementById('toast');
  let busy = false;
  let ready = false;
  let lastStatus = '';
  let activeJob = null;
  let streamText = '';
  let streamContent = null;

  function esc(s) { return (s || '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
  function inlineMarkdown(s) {
    return esc(s)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*]+)\*/g, '<em>$1</em>');
  }
  function renderMarkdown(text) {
    const parts = String(text || '').split(/```/);
    let out = '';
    for (let i = 0; i < parts.length; i++) {
      if (i % 2 === 1) {
        let code = parts[i].replace(/^\w+\n/, '');
        out += `<pre><code>${esc(code.trim())}</code></pre>`;
      } else {
        const blocks = parts[i].split(/\n{2,}/).filter(Boolean);
        out += blocks.map(b => `<p>${inlineMarkdown(b).replace(/\n/g, '<br>')}</p>`).join('');
      }
    }
    return out || '<p></p>';
  }
  function showToast(text) {
    toast.textContent = text;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 1400);
  }
  async function copyText(text) {
    try { await navigator.clipboard.writeText(text || ''); showToast('Kopiert'); }
    catch (_) { showToast('Kopieren nicht möglich'); }
  }
  function addStreamingAssistant() {
    if (streamContent) return;
    const div = document.createElement('div');
    div.className = 'message assistant';
    div.innerHTML = `<div class="avatar">Z</div><div class="bubble"><div class="message-head"><span>Zuse · live</span><button class="copy-btn" type="button">Kopieren</button></div><div class="content"></div></div>`;
    div.querySelector('.copy-btn').onclick = () => copyText(streamText);
    streamContent = div.querySelector('.content');
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
  }
  function updateStreamingAssistant(delta) {
    streamText += delta || '';
    addStreamingAssistant();
    streamContent.innerHTML = renderMarkdown(streamText || '…');
    chat.scrollTop = chat.scrollHeight;
  }
  function finishStreamingAssistant(finalText) {
    if (!streamContent) {
      addMessage('assistant', finalText || 'Fertig.');
      return;
    }
    if (finalText && finalText.length >= streamText.length) streamText = finalText;
    streamContent.innerHTML = renderMarkdown(streamText || finalText || 'Fertig.');
    streamText = '';
    streamContent = null;
  }
  function renderRateLimit(data) {
    if (!data) {
      rateLimitEl.className = 'rate-empty';
      rateLimitEl.textContent = 'Provider ist nicht codex.';
      return;
    }
    const limits = data.limits || [];
    if (!limits.length) {
      rateLimitEl.className = 'rate-empty';
      rateLimitEl.textContent = data.error || 'Noch keine Rate-Limit-Header von Codex empfangen.';
      return;
    }
    rateLimitEl.className = 'rate-list';
    rateLimitEl.innerHTML = limits.map(l => {
      const used = l.used_percent == null ? 0 : Math.round(l.used_percent);
      const remaining = l.remaining == null ? '?' : l.remaining;
      const limit = l.limit == null ? '?' : l.limit;
      const reset = l.reset_seconds == null ? '' : ` · reset ${l.reset_seconds}s`;
      const cls = used >= 90 ? 'danger' : used >= 80 ? 'warn' : '';
      return `<div class="rate-row ${cls}"><div class="rate-top"><span>${esc(l.name)}</span><span>${used}% used · ${remaining}/${limit}${reset}</span></div><div class="rate-bar"><div class="rate-fill" style="width:${used}%"></div></div></div>`;
    }).join('');
  }
  function addMessage(kind, text) {
    const div = document.createElement('div');
    div.className = `message ${kind}`;
    const label = kind === 'user' ? 'Du' : kind === 'assistant' ? 'Z' : 'i';
    const title = kind === 'user' ? 'Du' : kind === 'assistant' ? 'Zuse' : 'System';
    const body = kind === 'assistant' ? renderMarkdown(text) : `<p>${inlineMarkdown(text).replace(/\n/g, '<br>')}</p>`;
    div.innerHTML = `<div class="avatar">${label}</div><div class="bubble"><div class="message-head"><span>${title}</span><button class="copy-btn" type="button">Kopieren</button></div><div class="content">${body}</div></div>`;
    div.querySelector('.copy-btn').onclick = () => copyText(text);
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
  }
  function setStatus(text, state='ready') {
    lastStatus = text;
    statusEl.textContent = text;
    mobileStatus.textContent = text;
    dot.className = `dot ${state}`;
  }
  function setBusy(v) {
    busy = v;
    sendBtn.disabled = v || !ready;
    input.disabled = v || !ready;
    jobPill.textContent = v ? 'Job läuft' : 'Keine Jobs';
    if (!v && ready) input.focus();
  }
  async function api(path, opts={}) {
    const res = await fetch(path, {headers: {'Content-Type':'application/json'}, ...opts});
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }
  async function refreshStatus() {
    try {
      const s = await api('/api/status');
      ready = s.ready;
      backendEl.textContent = s.ready ? `${s.provider} / ${s.model}` : (s.error || 'Initialisiere …');
      renderRateLimit(s.codex_rate_limit);
      if (!busy) setStatus(s.ready ? 'Bereit' : (s.error ? 'Fehler' : 'Initialisiere …'), s.error ? 'error' : (s.ready ? 'ready' : 'busy'));
      setBusy(busy);
    } catch (e) { setStatus('Verbindung verloren', 'error'); }
  }
  async function refreshLogs() {
    try {
      const r = await api('/api/logs');
      logBox.textContent = r.logs || 'Noch keine Tool-Ausgabe.';
      logBox.scrollTop = logBox.scrollHeight;
    } catch (_) {}
  }
  async function pollJob(id) {
    activeJob = id;
    while (true) {
      await new Promise(r => setTimeout(r, 900));
      const job = await api(`/api/job?id=${encodeURIComponent(id)}`);
      await refreshLogs();
      if (job.status === 'done') {
        finishStreamingAssistant(job.answer || 'Fertig.');
        setStatus('Bereit', 'ready');
        activeJob = null;
        setBusy(false);
        await refreshLogs();
        return;
      }
      if (job.status === 'error') {
        addMessage('system', 'Fehler: ' + job.error);
        setStatus('Fehler', 'error');
        activeJob = null;
        setBusy(false);
        await refreshLogs();
        return;
      }
      setStatus('Zuse arbeitet …', 'busy');
    }
  }
  async function send() {
    const text = input.value.trim();
    if (!text || busy || !ready) return;
    input.value = '';
    input.style.height = '';
    addMessage('user', text);
    setBusy(true);
    setStatus('Zuse arbeitet …', 'busy');
    try {
      const r = await api('/api/chat', {method:'POST', body: JSON.stringify({message: text})});
      pollJob(r.id);
    } catch (e) {
      addMessage('system', 'Fehler: ' + e.message);
      setStatus('Fehler', 'error');
      setBusy(false);
    }
  }
  function connectEvents() {
    const es = new EventSource('/api/events');
    es.addEventListener('delta', e => {
      const data = JSON.parse(e.data || '{}');
      updateStreamingAssistant(data.text || '');
    });
    es.addEventListener('thinking', e => {
      const data = JSON.parse(e.data || '{}');
      if (data.text) refreshLogs();
    });
    es.addEventListener('job', e => {
      const data = JSON.parse(e.data || '{}');
      if (data.status === 'running') setStatus('Zuse arbeitet …', 'busy');
      if (data.status === 'error') {
        addMessage('system', 'Fehler: ' + (data.error || 'unbekannt'));
        setBusy(false);
      }
    });
    es.addEventListener('status', e => {
      const data = JSON.parse(e.data || '{}');
      if (data.codex_rate_limit !== undefined) renderRateLimit(data.codex_rate_limit);
    });
    es.onerror = () => setStatus('Event-Stream reconnect …', busy ? 'busy' : 'ready');
  }
  sendBtn.onclick = send;
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 180) + 'px';
  });
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  document.querySelectorAll('.quick').forEach(btn => {
    btn.onclick = () => {
      input.value = btn.dataset.prompt || '';
      input.focus();
      input.dispatchEvent(new Event('input'));
    };
  });
  document.getElementById('clearBtn').onclick = async () => {
    const r = await api('/api/clear', {method:'POST', body:'{}'}); addMessage('system', r.message); await refreshLogs();
  };
  document.getElementById('costBtn').onclick = async () => {
    const r = await api('/api/cost'); addMessage('system', r.summary);
  };
  document.getElementById('saveBtn').onclick = async () => {
    const r = await api('/api/save', {method:'POST', body:'{}'}); addMessage('system', r.message);
  };
  addMessage('system', 'Zuse WebGUI startet …');
  refreshStatus();
  refreshLogs();
  connectEvents();
  setInterval(refreshStatus, 2500);
  setInterval(refreshLogs, 3000);
  </script>
</body>
</html>
""".strip()


@dataclass
class Job:
    id: str
    message: str
    status: str = "queued"
    answer: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class WebEvent:
    id: int
    kind: str
    payload: dict[str, Any]


class WebStreamView:
    def __init__(self, state: "WebState", console: Console, markdown: bool = True, show_thinking: bool = True) -> None:
        self.state = state
        self.console = console
        self.markdown = markdown
        self.show_thinking = show_thinking

    def __enter__(self) -> "WebStreamView":
        self.state.emit("step", {"status": "model"})
        return self

    def on_text(self, delta: str) -> None:
        if delta:
            self.state.emit("delta", {"text": delta})

    def on_thinking(self, delta: str) -> None:
        if delta and self.show_thinking:
            self.state.emit("thinking", {"text": delta})

    def __exit__(self, *exc) -> None:
        return None


class WebState:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.console = Console(record=True, force_terminal=False, width=100)
        self.agent: Agent | None = None
        self.init_error = ""
        self.ready = False
        self.busy = False
        self.jobs: dict[str, Job] = {}
        self.events: list[WebEvent] = []
        self.next_event_id = 1
        self.event_cond = threading.Condition()
        self.lock = threading.RLock()
        self.turn_lock = threading.Lock()
        threading.Thread(target=self._init_agent, daemon=True).start()

    def _init_agent(self) -> None:
        try:
            self.agent = build_agent(self.args, self.console)
            self.agent.stream_view_factory = self.make_stream_view
            with self.lock:
                self.ready = True
            self.emit("status", self.status())
        except Exception as e:  # noqa: BLE001
            with self.lock:
                self.init_error = f"{type(e).__name__}: {e}"
            self.emit("status", self.status())

    def make_stream_view(self, console: Console, markdown: bool = True, show_thinking: bool = True) -> WebStreamView:
        return WebStreamView(self, console, markdown, show_thinking)

    def emit(self, kind: str, payload: dict[str, Any]) -> None:
        with self.event_cond:
            event = WebEvent(self.next_event_id, kind, payload)
            self.next_event_id += 1
            self.events.append(event)
            self.events = self.events[-500:]
            self.event_cond.notify_all()

    def event_stream(self, last_id: int = 0):
        while True:
            with self.event_cond:
                self.event_cond.wait_for(
                    lambda: any(e.id > last_id for e in self.events), timeout=15
                )
                pending = [e for e in self.events if e.id > last_id]
            if not pending:
                yield None
                continue
            for event in pending:
                last_id = event.id
                yield event

    def status(self) -> dict[str, Any]:
        with self.lock:
            agent = self.agent
            data = {
                "ready": self.ready,
                "busy": self.busy,
                "error": self.init_error,
                "provider": agent.config.provider if agent else "",
                "model": agent.config.active_model if agent else "",
            }
            data["codex_rate_limit"] = self.codex_rate_limit()
            return data

    def codex_rate_limit(self) -> dict[str, Any] | None:
        agent = self.agent
        if not agent or agent.config.provider != "codex":
            return None
        backend = agent.backend
        getter = getattr(backend, "rate_limit_status", None)
        if not getter:
            return {"provider": "codex", "limits": [], "headers": {}}
        try:
            return getter()
        except Exception as e:  # noqa: BLE001
            return {"provider": "codex", "error": str(e), "limits": [], "headers": {}}

    def submit(self, message: str) -> Job:
        if not self.ready or self.agent is None:
            raise RuntimeError(self.init_error or "Zuse initialisiert noch.")
        job = Job(id=uuid.uuid4().hex, message=message)
        with self.lock:
            self.jobs[job.id] = job
        self.emit("job", {"id": job.id, "status": job.status, "message": message})
        threading.Thread(target=self._run_job, args=(job.id,), daemon=True).start()
        return job

    def _run_job(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job.status = "running"
            self.busy = True
        self.emit("job", {"id": job_id, "status": "running"})
        self.emit("status", self.status())
        try:
            assert self.agent is not None
            with self.turn_lock:
                answer = self.agent.run_turn(job.message) or "Fertig."
            with self.lock:
                job.answer = answer
                job.status = "done"
            self.emit("job", {"id": job_id, "status": "done", "answer": answer})
        except Exception as e:  # noqa: BLE001
            error = f"{type(e).__name__}: {e}"
            with self.lock:
                job.error = error
                job.status = "error"
            self.emit("job", {"id": job_id, "status": "error", "error": error})
        finally:
            with self.lock:
                self.busy = any(j.status in {"queued", "running"} for j in self.jobs.values())
            self.emit("status", self.status())

    def get_job(self, job_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(job_id)

    def clear(self) -> str:
        if not self.agent:
            raise RuntimeError("Zuse ist noch nicht bereit.")
        with self.turn_lock:
            self.agent.backend.clear()
            self.agent.permissions.reset_session()
        return "Conversation cleared."

    def cost(self) -> str:
        if not self.agent:
            raise RuntimeError("Zuse ist noch nicht bereit.")
        return self.agent.usage.summary(self.agent.cost_model)

    def logs(self, tail: int = 12_000) -> str:
        text = self.console.export_text(clear=False)
        return text[-tail:].strip()

    def save(self) -> str:
        if not self.agent:
            raise RuntimeError("Zuse ist noch nicht bereit.")
        name = f"web-{time.strftime('%Y%m%d-%H%M%S')}"
        save_session(name, self.agent.backend.export_messages())
        return f"Gespeichert als {name} in {CONFIG_DIR / 'sessions' / (name + '.json')}"

    def shutdown(self) -> None:
        if self.agent:
            self.agent.shutdown()


def build_agent(args: argparse.Namespace, console: Console) -> Agent:
    ensure_dirs()
    cfg = Config.load()
    if args.ollama_host:
        cfg.ollama_host = args.ollama_host
    if args.openai_base_url:
        cfg.openai_base_url = args.openai_base_url
    if args.no_learning:
        cfg.learning = False
    if args.no_web:
        cfg.enable_web = False
    if args.browser_window:
        cfg.browser_headless = False
    if args.auto:
        cfg.auto = True
    if args.yolo:
        cfg.yolo = True
    if args.no_thinking:
        cfg.thinking = False
    if args.no_markdown:
        cfg.stream_markdown = False
    if args.effort:
        cfg.effort = args.effort

    cfg.provider = _decide_provider(args, cfg)
    if args.model:
        if cfg.provider == "ollama":
            cfg.local_model = args.model
        elif cfg.provider == "openai":
            cfg.openai_model = args.model
        elif cfg.provider == "codex":
            cfg.codex_model = args.model
        else:
            cfg.model = resolve_model(args.model)

    factory = _setup_backend(cfg, console)
    if factory is None:
        raise RuntimeError(console.export_text() or "Backend konnte nicht initialisiert werden.")
    return Agent(factory, cfg, console)


def json_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def make_handler(state: WebState):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send(HTTPStatus.OK, HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path == "/api/status":
                self._json(HTTPStatus.OK, state.status())
                return
            if parsed.path == "/api/cost":
                try:
                    self._json(HTTPStatus.OK, {"summary": state.cost()})
                except Exception as e:  # noqa: BLE001
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
                return
            if parsed.path == "/api/logs":
                self._json(HTTPStatus.OK, {"logs": state.logs()})
                return
            if parsed.path == "/api/events":
                self._events()
                return
            if parsed.path == "/api/job":
                query = dict(q.split("=", 1) for q in parsed.query.split("&") if "=" in q)
                job = state.get_job(query.get("id", ""))
                if not job:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "Job nicht gefunden"})
                    return
                self._json(
                    HTTPStatus.OK,
                    {"id": job.id, "status": job.status, "answer": job.answer, "error": job.error},
                )
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                payload = self._read_json()
                if parsed.path == "/api/chat":
                    message = str(payload.get("message") or "").strip()
                    if not message:
                        self._json(HTTPStatus.BAD_REQUEST, {"error": "Nachricht fehlt"})
                        return
                    job = state.submit(message)
                    self._json(HTTPStatus.OK, {"id": job.id, "status": job.status})
                    return
                if parsed.path == "/api/clear":
                    self._json(HTTPStatus.OK, {"message": state.clear()})
                    return
                if parsed.path == "/api/save":
                    self._json(HTTPStatus.OK, {"message": state.save()})
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except Exception as e:  # noqa: BLE001
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("content-length", "0"))
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            return json.loads(raw or "{}")

        def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            self._send(status, json_bytes(payload), "application/json; charset=utf-8")

        def _events(self) -> None:
            self.send_response(HTTPStatus.OK.value)
            self.send_header("content-type", "text/event-stream; charset=utf-8")
            self.send_header("cache-control", "no-store")
            self.send_header("connection", "keep-alive")
            self.end_headers()
            last_id = 0
            try:
                for event in state.event_stream(last_id):
                    if event is None:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        continue
                    last_id = event.id
                    data = json.dumps(event.payload, ensure_ascii=False)
                    packet = f"id: {event.id}\nevent: {event.kind}\ndata: {data}\n\n".encode("utf-8")
                    self.wfile.write(packet)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status.value)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return Handler


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zuse-web", description="Zuse — lokale WebGUI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true", help="Browser nicht automatisch öffnen")
    p.add_argument("-m", "--model")
    p.add_argument("--local", action="store_true", help="Use a local model via Ollama")
    p.add_argument("--provider", choices=["anthropic", "ollama", "openai", "codex"])
    p.add_argument("--ollama-host")
    p.add_argument("--openai-base-url")
    p.add_argument("-e", "--effort", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--auto", action="store_true", default=True, help="Autonomous mode (default)")
    p.add_argument("--no-auto", action="store_false", dest="auto")
    p.add_argument("--yolo", action="store_true", help="Auto-approve all tool permissions")
    p.add_argument("--no-thinking", action="store_true")
    p.add_argument("--no-web", action="store_true")
    p.add_argument("--no-learning", action="store_true")
    p.add_argument("--no-markdown", action="store_true")
    p.add_argument("--browser-window", action="store_true")
    p.add_argument("-v", "--version", action="version", version=f"zuse-web {__version__}")
    return p


def run_server(args: argparse.Namespace) -> int:
    state = WebState(args)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    url = f"http://{args.host}:{args.port}/"
    print(f"Zuse WebGUI läuft auf {url}")
    print("Beenden mit Ctrl+C.")
    if not args.no_open:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
        return 0
    except KeyboardInterrupt:
        print("\nZuse WebGUI beendet.")
        return 130
    finally:
        state.shutdown()
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return run_server(args)


if __name__ == "__main__":
    sys.exit(main())

(function () {
  'use strict';

  // ── Read config from the <script> tag that loaded this file ──────────────
  var scriptEl = document.currentScript ||
    (function () {
      var scripts = document.querySelectorAll('script[data-key]');
      return scripts[scripts.length - 1];
    })();

  var API_KEY    = scriptEl ? scriptEl.getAttribute('data-key')    : '';
  var TENANT     = scriptEl ? scriptEl.getAttribute('data-tenant') : '';
  var API_URL    = scriptEl ? (scriptEl.getAttribute('data-api-url') || scriptEl.src.replace(/\/widget\.js.*$/, '')) : '';
  var BOT_NAME   = scriptEl ? (scriptEl.getAttribute('data-name')  || 'Assistant') : 'Assistant';
  var BOT_INITIALS = BOT_NAME.slice(0, 1).toUpperCase();

  if (!API_KEY) { console.warn('[RBS Widget] data-key is required.'); return; }

  // ── Prevent double-init ──────────────────────────────────────────────────
  if (window.__RBSWidgetLoaded) return;
  window.__RBSWidgetLoaded = true;

  // ── Session ID ───────────────────────────────────────────────────────────
  var SESSION_KEY = 'rbs_widget_session_' + TENANT;
  var sessionId = localStorage.getItem(SESSION_KEY);
  if (!sessionId) {
    sessionId = 'sess_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    localStorage.setItem(SESSION_KEY, sessionId);
  }

  // ── CSS ──────────────────────────────────────────────────────────────────
  var style = document.createElement('style');
  style.textContent = [
    '#rbs-widget-btn{position:fixed;bottom:24px;right:24px;z-index:99998;width:56px;height:56px;border-radius:50%;background:linear-gradient(135deg,#6366f1,#38bdf8);border:none;cursor:pointer;box-shadow:0 4px 24px rgba(99,102,241,.45);display:flex;align-items:center;justify-content:center;color:#fff;font-size:24px;transition:transform .2s,box-shadow .2s}',
    '#rbs-widget-btn:hover{transform:scale(1.08);box-shadow:0 6px 32px rgba(99,102,241,.6)}',
    '#rbs-widget-box{position:fixed;bottom:92px;right:24px;z-index:99999;width:360px;max-width:calc(100vw - 32px);height:480px;border-radius:16px;background:#1a1a2e;border:1px solid rgba(255,255,255,.1);box-shadow:0 16px 48px rgba(0,0,0,.5);display:flex;flex-direction:column;overflow:hidden;transition:opacity .2s,transform .2s;opacity:0;transform:translateY(12px) scale(.97);pointer-events:none}',
    '#rbs-widget-box.open{opacity:1;transform:translateY(0) scale(1);pointer-events:all}',
    '#rbs-w-header{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:linear-gradient(135deg,rgba(99,102,241,.25),rgba(56,189,248,.15));border-bottom:1px solid rgba(255,255,255,.08)}',
    '#rbs-w-header .rbs-w-avatar{width:32px;height:32px;border-radius:8px;background:linear-gradient(135deg,#6366f1,#38bdf8);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;color:#fff;flex-shrink:0}',
    '#rbs-w-header .rbs-w-info{margin-left:10px;flex:1}',
    '#rbs-w-header .rbs-w-name{font-size:14px;font-weight:600;color:#f1f5f9}',
    '#rbs-w-header .rbs-w-status{font-size:10px;color:#4ade80;display:flex;align-items:center;gap:4px}',
    '#rbs-w-header .rbs-w-status span{width:6px;height:6px;border-radius:50%;background:#4ade80;display:inline-block}',
    '#rbs-w-header .rbs-w-actions{display:flex;gap:4px}',
    '#rbs-w-header .rbs-w-actions button{background:none;border:none;cursor:pointer;color:#94a3b8;padding:4px;border-radius:4px;display:flex;align-items:center;justify-content:center;transition:background .15s}',
    '#rbs-w-header .rbs-w-actions button:hover{background:rgba(255,255,255,.08);color:#f1f5f9}',
    '#rbs-w-msgs{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px;scroll-behavior:smooth}',
    '#rbs-w-msgs::-webkit-scrollbar{width:4px}',
    '#rbs-w-msgs::-webkit-scrollbar-track{background:transparent}',
    '#rbs-w-msgs::-webkit-scrollbar-thumb{background:rgba(255,255,255,.12);border-radius:2px}',
    '.rbs-msg-user{align-self:flex-end;max-width:80%;background:linear-gradient(135deg,#6366f1,#4f46e5);color:#fff;padding:8px 12px;border-radius:12px 12px 2px 12px;font-size:13px;line-height:1.5;word-break:break-word}',
    '.rbs-msg-bot{align-self:flex-start;max-width:85%;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08);color:#e2e8f0;padding:8px 12px;border-radius:12px 12px 12px 2px;font-size:13px;line-height:1.6;word-break:break-word}',
    '.rbs-msg-bot p{margin:0 0 6px}',
    '.rbs-msg-bot p:last-child{margin:0}',
    '.rbs-msg-bot strong{color:#a5b4fc}',
    '.rbs-msg-bot code{background:rgba(255,255,255,.1);padding:1px 5px;border-radius:3px;font-size:12px}',
    '.rbs-msg-bot ul,.rbs-msg-bot ol{margin:4px 0 4px 16px;padding:0}',
    '.rbs-msg-bot li{margin-bottom:2px}',
    '.rbs-sources{display:flex;flex-wrap:wrap;gap:4px;padding:0 2px;margin-top:4px}',
    '.rbs-src-tag{font-size:10px;font-weight:600;background:rgba(20,184,166,.15);color:#2dd4bf;padding:2px 6px;border-radius:4px;cursor:default}',
    '.rbs-typing{display:flex;gap:4px;align-items:center;padding:4px 0}',
    '.rbs-typing span{width:6px;height:6px;border-radius:50%;background:#6366f1;display:inline-block;animation:rbsDot 1.2s infinite}',
    '.rbs-typing span:nth-child(2){animation-delay:.2s}',
    '.rbs-typing span:nth-child(3){animation-delay:.4s}',
    '@keyframes rbsDot{0%,80%,100%{transform:scale(.6);opacity:.4}40%{transform:scale(1);opacity:1}}',
    '#rbs-w-form{display:flex;align-items:center;gap:8px;padding:12px;border-top:1px solid rgba(255,255,255,.08)}',
    '#rbs-w-input{flex:1;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:8px 12px;font-size:13px;color:#f1f5f9;outline:none;resize:none;transition:border-color .2s;font-family:inherit}',
    '#rbs-w-input::placeholder{color:#64748b}',
    '#rbs-w-input:focus{border-color:rgba(99,102,241,.6)}',
    '#rbs-w-send{width:36px;height:36px;border-radius:8px;background:linear-gradient(135deg,#6366f1,#38bdf8);border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:opacity .2s}',
    '#rbs-w-send:disabled{opacity:.4;cursor:not-allowed}',
    '#rbs-w-send svg{width:16px;height:16px;stroke:#fff;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}',
  ].join('');
  document.head.appendChild(style);

  // ── Build DOM ────────────────────────────────────────────────────────────
  var btn = document.createElement('button');
  btn.id = 'rbs-widget-btn';
  btn.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
  btn.setAttribute('aria-label', 'Open chat');
  document.body.appendChild(btn);

  var box = document.createElement('div');
  box.id = 'rbs-widget-box';
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-label', BOT_NAME + ' chat');
  box.innerHTML =
    '<div id="rbs-w-header">' +
      '<div class="rbs-w-avatar">' + BOT_INITIALS + '</div>' +
      '<div class="rbs-w-info">' +
        '<div class="rbs-w-name">' + BOT_NAME + '</div>' +
        '<div class="rbs-w-status"><span></span>Online</div>' +
      '</div>' +
      '<div class="rbs-w-actions">' +
        '<button id="rbs-w-clear" title="Clear conversation">' +
          '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-4.5"/></svg>' +
        '</button>' +
        '<button id="rbs-w-close" title="Close">' +
          '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
        '</button>' +
      '</div>' +
    '</div>' +
    '<div id="rbs-w-msgs"></div>' +
    '<form id="rbs-w-form">' +
      '<input id="rbs-w-input" type="text" placeholder="Type your question…" autocomplete="off" />' +
      '<button id="rbs-w-send" type="submit" disabled>' +
        '<svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>' +
      '</button>' +
    '</form>';
  document.body.appendChild(box);

  var msgsEl  = document.getElementById('rbs-w-msgs');
  var inputEl = document.getElementById('rbs-w-input');
  var sendBtn = document.getElementById('rbs-w-send');
  var isOpen  = false;
  var isLoading = false;

  // ── Toggle open/close ────────────────────────────────────────────────────
  function toggleWidget() {
    isOpen = !isOpen;
    box.classList.toggle('open', isOpen);
    btn.setAttribute('aria-expanded', String(isOpen));
    if (isOpen && msgsEl.children.length === 0) {
      appendBotMsg('Hello! I can answer questions grounded in our verified database. How can I help you today?');
    }
    if (isOpen) setTimeout(function () { inputEl.focus(); }, 150);
  }

  btn.addEventListener('click', toggleWidget);
  document.getElementById('rbs-w-close').addEventListener('click', toggleWidget);

  // ── Clear ────────────────────────────────────────────────────────────────
  document.getElementById('rbs-w-clear').addEventListener('click', function () {
    msgsEl.innerHTML = '';
    sessionId = 'sess_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    localStorage.setItem(SESSION_KEY, sessionId);
    appendBotMsg('Conversation cleared. How can I help you?');
  });

  // ── Input enable/disable ─────────────────────────────────────────────────
  inputEl.addEventListener('input', function () {
    sendBtn.disabled = !this.value.trim() || isLoading;
  });

  // ── Send ─────────────────────────────────────────────────────────────────
  document.getElementById('rbs-w-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var q = inputEl.value.trim();
    if (!q || isLoading) return;
    inputEl.value = '';
    sendBtn.disabled = true;
    appendUserMsg(q);
    sendMessage(q);
  });

  function appendUserMsg(text) {
    var el = document.createElement('div');
    el.className = 'rbs-msg-user';
    el.textContent = text;
    msgsEl.appendChild(el);
    scrollBottom();
  }

  function appendBotMsg(text, sources) {
    var el = document.createElement('div');
    el.className = 'rbs-msg-bot';
    el.innerHTML = simpleMarkdown(text);
    if (sources && sources.length) {
      var srcs = document.createElement('div');
      srcs.className = 'rbs-sources';
      sources.forEach(function (s, idx) {
        var tag = document.createElement('span');
        tag.className = 'rbs-src-tag';
        tag.textContent = '[' + (idx + 1) + ']';
        tag.title = s.section ? s.document_name + ' — ' + s.section : s.document_name;
        srcs.appendChild(tag);
      });
      el.appendChild(srcs);
    }
    msgsEl.appendChild(el);
    scrollBottom();
    return el;
  }

  function showTyping() {
    var el = document.createElement('div');
    el.className = 'rbs-msg-bot rbs-typing-wrap';
    el.innerHTML = '<div class="rbs-typing"><span></span><span></span><span></span></div>';
    msgsEl.appendChild(el);
    scrollBottom();
    return el;
  }

  function scrollBottom() {
    msgsEl.scrollTop = msgsEl.scrollHeight;
  }

  // ── Stream chat ──────────────────────────────────────────────────────────
  function sendMessage(query) {
    isLoading = true;
    var typingEl = showTyping();
    var streamEl = null;
    var accumulated = '';

    fetch(API_URL + '/api/v1/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY,
        'X-Tenant-ID': TENANT,
      },
      body: JSON.stringify({ query: query, session_id: sessionId, user_id: 'widget-embed' }),
    })
    .then(function (res) {
      if (!res.ok) return res.json().then(function (d) { throw new Error(d.detail || res.statusText); });
      typingEl.remove();
      streamEl = document.createElement('div');
      streamEl.className = 'rbs-msg-bot';
      msgsEl.appendChild(streamEl);

      var reader = res.body.getReader();
      var decoder = new TextDecoder();
      var buffer = '';
      var lastCitations = null;

      function read() {
        return reader.read().then(function (result) {
          if (result.done) {
            if (lastCitations && streamEl) {
              var srcs = document.createElement('div');
              srcs.className = 'rbs-sources';
              lastCitations.forEach(function (s, idx) {
                var tag = document.createElement('span');
                tag.className = 'rbs-src-tag';
                tag.textContent = '[' + (idx + 1) + ']';
                tag.title = s.section ? s.document_name + ' — ' + s.section : s.document_name;
                srcs.appendChild(tag);
              });
              streamEl.appendChild(srcs);
            }
            finish();
            return;
          }
          buffer += decoder.decode(result.value, { stream: true });
          var lines = buffer.split('\n');
          buffer = lines.pop() || '';
          lines.forEach(function (line) {
            line = line.trim();
            if (!line || !line.startsWith('data: ')) return;
            try {
              var chunk = JSON.parse(line.slice(6));
              if (chunk.text) {
                accumulated += chunk.text;
                streamEl.innerHTML = simpleMarkdown(accumulated);
                scrollBottom();
              }
              if (chunk.citations) lastCitations = chunk.citations;
            } catch (e) {}
          });
          return read();
        });
      }

      return read();
    })
    .catch(function (err) {
      if (typingEl.parentNode) typingEl.remove();
      appendBotMsg('Sorry, something went wrong: ' + err.message);
      finish();
    });

    function finish() {
      isLoading = false;
      sendBtn.disabled = !inputEl.value.trim();
    }
  }

  // ── Markdown renderer with links, images, map embeds ────────────────────
  function isImageExt(url) {
    return /\.(jpg|jpeg|png|gif|svg|webp|bmp)(\?|#|$)/i.test(url);
  }
  function isMapUrl(url) {
    return /(google\.com\/maps|maps\.google|maps\.app\.goo\.gl|openstreetmap\.org)/i.test(url);
  }
  function makeMapEmbed(url) {
    var m = url.match(/[?&]q=([^&]+)/);
    if (m) return 'https://maps.google.com/maps?q=' + encodeURIComponent(decodeURIComponent(m[1])) + '&output=embed';
    m = url.match(/@(-?\d+\.\d+),(-?\d+\.\d+)/);
    if (m) return 'https://maps.google.com/maps?q=' + m[1] + ',' + m[2] + '&output=embed';
    m = url.match(/\/place\/([^/@?]+)/);
    if (m) return 'https://maps.google.com/maps?q=' + encodeURIComponent(decodeURIComponent(m[1])) + '&output=embed';
    return '';
  }
  function renderUrl(url, linkText) {
    var escapedUrl = url.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    if (isImageExt(url)) {
      return '<span class="rbs-img-wrap" style="display:block;margin:6px 0"><img src="' + escapedUrl + '" alt="' + (linkText || '').replace(/"/g, '&quot;') + '" loading="lazy" style="max-width:100%;border-radius:8px;max-height:200px" onerror="this.style.display=\'none\'" />' + (linkText ? '<span style="display:block;font-size:11px;opacity:.7;margin-top:2px">' + linkText.replace(/&/g,'&amp;').replace(/</g,'&lt;') + '</span>' : '') + '</span>';
    }
    if (isMapUrl(url)) {
      var embedUrl = makeMapEmbed(url);
      var html = '<a href="' + escapedUrl + '" target="_blank" rel="noopener" style="color:#a5b4fc;text-decoration:underline;font-size:12px">📍 Open in Google Maps</a>';
      if (embedUrl) html += '<div style="margin-top:4px"><iframe src="' + embedUrl + '" width="100%" height="160" style="border-radius:8px;border:1px solid rgba(255,255,255,.1)" loading="lazy" allowfullscreen></iframe></div>';
      return html;
    }
    var displayText = linkText || url;
    return '<a href="' + escapedUrl + '" target="_blank" rel="noopener" style="color:#a5b4fc;text-decoration:underline;word-break:break-all">' + displayText.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</a>';
  }
  function simpleMarkdown(text) {
    var escaped = text
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code>$1</code>');

    // Convert [text](url) → links/images/maps
    escaped = escaped.replace(/!?\[([^\]]*)\]\(([^)]+)\)/g, function (_, linkText, rawUrl) {
      return renderUrl(rawUrl, linkText);
    });

    // Convert bare URLs
    escaped = escaped.replace(/(https?:\/\/[^\s()<>]+(?:\.[^\s()<>]+)*[^\s()<>!.,;:?])/g, function (url) {
      return renderUrl(url, '');
    });

    // Headings
    escaped = escaped.replace(/^### (.+)$/gm, '<strong class="rws-h">$1</strong>');
    escaped = escaped.replace(/^## (.+)$/gm, '<strong class="rws-h">$1</strong>');
    escaped = escaped.replace(/^# (.+)$/gm, '<strong class="rws-h">$1</strong>');

    // Lists
    escaped = escaped.replace(/^\s*[-*•] (.+)$/gm, '<li>$1</li>');
    escaped = escaped.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul style="margin:4px 0 4px 12px;padding:0">$1</ul>');

    // Paragraphs
    escaped = escaped.replace(/\n{2,}/g, '</p><p>');
    escaped = escaped.replace(/^(?!<[uo]l|<p|<a|<div|<strong|<em|<span)(.+)$/gm, '<p>$1</p>');
    escaped = escaped.replace(/<p><\/p>/g, '');

    return escaped;
  }

  // ── Public API ───────────────────────────────────────────────────────────
  window.RBSWidget = {
    open:   function () { if (!isOpen) toggleWidget(); },
    close:  function () { if (isOpen)  toggleWidget(); },
    toggle: toggleWidget,
  };

})();

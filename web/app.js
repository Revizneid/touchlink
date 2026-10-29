/* TouchLink mobile web app — xem & điều khiển máy tính */
(function () {
'use strict';

/* ---------- protocol constants (mirror of desktop/protocol.py) ---------- */
var PROTOCOL_VERSION = 2;
var PROTOCOL_CAPS = [
  'screen_locked', 'keep_awake', 'multi_monitor', 'clipboard_sync', 'chat', 'tiles',
];

var $ = function (id) { return document.getElementById(id); };
var el = {
  login: $('login'), viewer: $('viewer'),
  host: $('f-host'), fid: $('f-id'), fpass: $('f-pass'), fremember: $('f-remember'),
  segDirect: $('seg-direct'), segRelay: $('seg-relay'), modeSeg: $('mode-seg'),
  fieldHost: $('field-host'), fieldRelay: $('field-relay'), fRelay: $('f-relay'),
  btnConnect: $('btn-connect'), loginError: $('login-error'),
  canvas: $('screen'), topbar: $('topbar'), status: $('status'),
  btnExit: $('btn-exit'), btnMode: $('btn-mode'), btnKeys: $('btn-keys'),
  btnQuick: $('btn-quick'), btnMenu: $('btn-menu'),
  quickkeys: $('quickkeys'), scrollstrip: $('scrollstrip'), ime: $('ime'),
  sheet: $('sheet'), sheetClose: $('sheet-close'),
  clip: $('clip'), clipClose: $('clip-close'), clipText: $('clip-text'),
  clipGet: $('clip-get'), clipSet: $('clip-set'), clipAuto: $('clip-auto'),
  chat: $('chat'), chatClose: $('chat-close'), chatList: $('chat-list'),
  chatInput: $('chat-input'), chatSend: $('chat-send'),
  toast: $('toast'), lost: $('lost'), lostMsg: $('lost-msg'), btnRelogin: $('btn-relogin'),
  sQuality: $('s-quality'), sFps: $('s-fps'), sScale: $('s-scale'), sMonitor: $('s-monitor'),
  sMode: $('s-mode'), sSens: $('s-sens'), sInvert: $('s-invert'), s2: $('s-2finger'),
  sCbsync: $('s-cbsync'), sAwake: $('s-awake'), btnFullscreen: $('btn-fullscreen'), btnReconnect: $('btn-reconnect'),
  btnClip: $('btn-clip'), btnChat: $('btn-chat'), connMeta: $('conn-meta'),
  vQuality: $('v-quality'), vFps: $('v-fps'), vScale: $('v-scale'), vSens: $('v-sens')
};

/* Điền wss URL của relay đã triển khai vào đây (hoặc dùng ?relay= trên URL) */
var DEFAULT_RELAY = 'wss://touchlink-relay.onrender.com/ws';

var MODE = (window.__TOUCHLINK_MODE ||
  new URLSearchParams(location.search).get('mode') ||
  (location.protocol === 'https:' && !['localhost', '127.0.0.1'].includes(location.hostname)
    ? 'relay' : 'direct'));
var DEFAULT_PORT = '8420';

var st = {
  ws: null, authed: false, closing: false, host: '',
  fw: 0, fh: 0, fit: 1, zoom: 1, panX: 0, panY: 0,
  mode: localStorage.getItem('tl_mode') || 'direct',
  sens: parseInt(localStorage.getItem('tl_sens') || '12', 10),
  invert: localStorage.getItem('tl_invert') === '1',
  twoFinger: localStorage.getItem('tl_2finger') || 'auto',
  sticky: {}, dragging: false, dragArmed: false,
  srv: { fps: 12, quality: 60, scale: 100, monitor: 1, clipboard_sync: true, keep_awake: true },
  monitors: [], meta: {},
  peerV: 1, peerCaps: [],
  resumeToken: localStorage.getItem('tl_resumeToken') || '',
  resumeDeviceId: localStorage.getItem('tl_resumeDeviceId') || '',
  reconnectDelayMs: 1500,
  reconnectAttempt: 0,
  wakeLock: null,
  // Tile state: canvas chứa full screenshot (vẽ tile lên trên)
  tileCanvas: null, tileCtx: null,
};
var bmp = null, redrawNeeded = false;
var frameCount = 0, fpsShown = 0, pingMs = 0, eventCount = 0;

window.__tl = {
  get frames() { return frameCount; },
  get ping() { return pingMs; },
  get events() { return eventCount; },
  get connected() { return !!(st.ws && st.authed); }
};

/* ---------- helpers ---------- */
function toast(msg, ms) {
  el.toast.textContent = msg;
  el.toast.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(function () { el.toast.hidden = true; }, ms || 2200);
}
function vib(ms) { try { navigator.vibrate && navigator.vibrate(ms); } catch (e) {} }
function show(elx, on) { elx.classList.toggle('hidden', !on); }
function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }

function getCompatProfile() {
  var ua = navigator.userAgent || '';
  var isIOS = /iPad|iPhone|iPod/i.test(ua) || (/Macintosh/i.test(ua) && 'ontouch' in window);
  var isAndroid = /Android/i.test(ua);
  var family = isIOS ? 'ios' : (isAndroid ? 'android' : 'desktop');
  return {
    family: family,
    playsInline: true,
    usesVisualViewport: !!(window.visualViewport && (isIOS || isAndroid)),
    hideAddressBar: isIOS || isAndroid,
    supportsWakeLock: 'wakeLock' in navigator,
    keyboardAdjustment: isIOS ? 'visualViewport' : (isAndroid ? 'viewport' : 'none')
  };
}

function applyViewportCompat() {
  var profile = getCompatProfile();
  var root = document.documentElement;
  var viewport = window.visualViewport;
  if (profile.usesVisualViewport && viewport) {
    var vh = Math.max(320, viewport.height || window.innerHeight);
    root.style.setProperty('--app-vh', vh + 'px');
    root.style.height = vh + 'px';
    document.body.style.minHeight = vh + 'px';
    var keyboardOffset = Math.max(0, window.innerHeight - viewport.height);
    document.body.style.paddingBottom = (keyboardOffset > 0 && profile.family === 'ios') ? (keyboardOffset * 0.6) + 'px' : '';
  } else {
    root.style.setProperty('--app-vh', window.innerHeight + 'px');
    root.style.height = window.innerHeight + 'px';
    document.body.style.minHeight = window.innerHeight + 'px';
    document.body.style.paddingBottom = '';
  }
  if (profile.family === 'ios') {
    document.body.classList.add('ios-device');
  } else {
    document.body.classList.remove('ios-device');
  }
}

function bindViewportCompat() {
  applyViewportCompat();
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', applyViewportCompat);
    window.visualViewport.addEventListener('scroll', applyViewportCompat);
  }
  window.addEventListener('resize', applyViewportCompat);
  window.addEventListener('orientationchange', applyViewportCompat);
}

function wsUrlFromHost(h) {
  h = (h || '').trim() || location.host;
  if (/^(wss?):\/\//i.test(h)) {
    var u1 = h.replace(/\/+$/, '');
    return /\/ws$/i.test(u1) ? u1 : u1 + '/ws';
  }
  if (/^https?:\/\//i.test(h)) {
    var p2 = /^https/i.test(h) ? 'wss' : 'ws';
    var rest = h.replace(/^https?:\/\//i, '').replace(/\/+$/, '');
    return /\/ws$/i.test(rest) ? p2 + '://' + rest : p2 + '://' + rest + '/ws';
  }
  var m = h.match(/^([^:\/\s]+)(?::(\d+))?$/);
  if (!m) return null;
  if (location.protocol === 'https:') return 'wss://' + m[1] + (m[2] ? ':' + m[2] : '') + '/ws';
  return 'ws://' + m[1] + ':' + (m[2] || DEFAULT_PORT) + '/ws';
}

/* ---------- Wake-up UX (relay có thể đang ngủ trên Render v.v.) ---------- */
var wakeup = (function () {
  var WAKEUP_THRESHOLD_MS = 3000;  // sau 3s chưa phản hồi → hiện đếm giây
  var BACKOFF_STEPS = [1, 2, 4, 8, 15];  // giây giữa các lần retry
  var _timer = null, _countTimer = null, _elapsed = 0, _step = 0;
  var _active = false, _cancelled = false;
  var _bar = null;  // DOM element hiển thị wake-up status

  function _getBar() {
    if (!_bar) {
      _bar = document.createElement('div');
      _bar.id = 'wakeup-bar';
      _bar.style.cssText = [
        'position:fixed;top:0;left:0;right:0;z-index:9999',
        'background:linear-gradient(90deg,#f59e0b,#ef4444)',
        'color:#fff;font-size:14px;font-weight:600',
        'padding:10px 16px;display:flex;align-items:center;gap:12px',
        'box-shadow:0 2px 8px rgba(0,0,0,.3)'
      ].join(';');
      var txt = document.createElement('span');
      txt.id = 'wakeup-txt';
      var btn = document.createElement('button');
      btn.id = 'wakeup-cancel';
      btn.textContent = 'Hủy';
      btn.style.cssText = 'margin-left:auto;background:rgba(255,255,255,.25);border:none;' +
        'color:#fff;padding:4px 14px;border-radius:6px;cursor:pointer;font-weight:700';
      btn.onclick = function () { cancel(); };
      _bar.appendChild(txt); _bar.appendChild(btn);
    }
    return _bar;
  }

  function _setText(s) {
    var txt = document.getElementById('wakeup-txt');
    if (txt) txt.textContent = s;
  }

  function _show() {
    var bar = _getBar();
    if (!bar.parentNode) document.body.insertBefore(bar, document.body.firstChild);
    bar.style.display = 'flex';
  }

  function _hide() {
    if (_bar && _bar.parentNode) _bar.style.display = 'none';
  }

  function _tick() {
    if (!_active) return;
    _elapsed++;
    _setText('⏳ Đang đánh thức máy chủ relay… (' + _elapsed + 's)' +
      (_step > 0 ? ' — lần thử ' + (_step + 1) : ''));
    _countTimer = setTimeout(_tick, 1000);
  }

  /** Gọi khi WS mở → bắt đầu đếm giờ WAKEUP_THRESHOLD_MS */
  function onOpen(retryFn) {
    _cancelled = false;
    _active = true;
    _timer = setTimeout(function () {
      if (!_active) return;
      _elapsed = 0;
      _show();
      _tick();
    }, WAKEUP_THRESHOLD_MS);
    // Lưu retry function để dùng khi WS đóng mà chưa authed
    wakeup._retryFn = retryFn;
  }

  /** Gọi khi đã auth thành công → dừng hết */
  function onAuthedOk() {
    _active = false;
    clearTimeout(_timer); clearTimeout(_countTimer);
    _step = 0;
    _hide();
  }

  /** Gọi khi WS đóng mà chưa authed (relay đang ngủ hoặc lỗi mạng tạm) */
  function onClosed(isRelay, retryFn) {
    clearTimeout(_timer); clearTimeout(_countTimer);
    if (_cancelled || !_active || !isRelay) {
      _active = false; _hide(); return;
    }
    if (_step >= BACKOFF_STEPS.length) {
      // Hết retry → báo lỗi
      _active = false; _hide();
      loginError('Không kết nối được relay sau ' + BACKOFF_STEPS.length + ' lần thử. Kiểm tra URL relay.');
      return;
    }
    var delay = BACKOFF_STEPS[_step];
    _step++;
    _setText('⏳ Relay chưa phản hồi — thử lại sau ' + delay + 's…');
    _show();
    _countTimer = setTimeout(function () {
      if (_cancelled) return;
      _elapsed = 0;
      if (retryFn) retryFn();
    }, delay * 1000);
  }

  function cancel() {
    _cancelled = true; _active = false;
    clearTimeout(_timer); clearTimeout(_countTimer);
    _step = 0; _hide();
    // Dừng WS nếu còn mở
    if (st.ws) { try { st.ws.onclose = null; st.ws.close(); } catch (e) {} }
    el.btnConnect.disabled = false;
    el.btnConnect.textContent = 'Kết nối';
    loginError('Đã hủy kết nối relay.');
  }

  return { onOpen: onOpen, onAuthedOk: onAuthedOk, onClosed: onClosed, cancel: cancel,
    isActive: function () { return _active; },
    reset: function () { _step = 0; _cancelled = false; } };
}());

/* ---------- connect & auth ---------- */
function connMode() {
  return (typeof st.connMode === 'string' && st.connMode === 'relay') ? 'relay' : 'direct';
}
function currentHostInput() {
  return connMode() === 'relay' ? el.fRelay.value : el.host.value;
}
function buildAuthMessage(id, pass, mode) {
  var msg = { type: mode === 'relay' ? 'connect' : 'auth', id: id, device_id: id, password: pass };
  if (st.resumeToken && st.resumeDeviceId === id) {
    msg.resume_token = st.resumeToken;
    delete msg.password;
  }
  return msg;
}

function scheduleReconnect() {
  if (st.closing || !st.host || !st.cred) return;
  if (st.reconnectTimer) clearTimeout(st.reconnectTimer);
  var base = Math.min(30000, 1500 * Math.pow(2, Math.max(0, st.reconnectAttempt)));
  var jitter = Math.round(Math.random() * 1000);
  st.reconnectDelayMs = base + jitter;
  st.reconnectAttempt += 1;
  st.reconnectTimer = setTimeout(function () {
    if (!st.closing) {
      toast('Tự động kết nối lại…', 2500);
      wakeup.reset();
      connect(st.host, st.cred.id, st.cred.pass);
    }
  }, st.reconnectDelayMs);
}

function acquireWakeLock() {
  if (!('wakeLock' in navigator) || !st.authed || document.visibilityState !== 'visible') return;
  try {
    navigator.wakeLock.request('screen').then(function (lock) {
      st.wakeLock = lock;
      lock.addEventListener('release', function () { st.wakeLock = null; });
    }).catch(function () {});
  } catch (e) {}
}

function connect(hostStr, id, pass) {
  var mode = connMode();
  var url = wsUrlFromHost(hostStr);
  if (!url) {
    loginError(mode === 'relay' ? 'Địa chỉ relay không hợp lệ' : 'Địa chỉ máy tính không hợp lệ');
    return;
  }
  if (location.protocol === 'https:' && url.indexOf('ws://') === 0) {
    loginError('Trang chạy HTTPS nên không mở được kết nối ws:// tới IP nội bộ.\n' +
      'Hãy chọn chế độ "Qua relay" (wss), hoặc mở app từ chính máy tính: http://<IP-máy-tính>:8420');
    return;
  }
  st.host = hostStr;
  st.cred = { id: id, pass: pass };
  st.closing = false; st.authed = false;
  try { if (st.ws) { st.ws.onclose = null; st.ws.close(); } } catch (e) {}
  var ws;
  try { ws = new WebSocket(url); } catch (e) { loginError('Không tạo được kết nối: ' + e.message); return; }
  st.ws = ws;
  ws.binaryType = 'arraybuffer';
  loginError('');
  el.btnConnect.disabled = true;
  el.btnConnect.textContent = 'Đang kết nối…';

  // Wake-up UX: chỉ kích hoạt trong relay mode
  var isRelay = (mode === 'relay');
  var _retryFn = function () { connect(hostStr, id, pass); };
  if (isRelay) {
    wakeup.onOpen(_retryFn);
  }

  // Timeout chỉ dùng cho LAN (relay tự retry qua wakeup)
  var authTimer = null;
  if (!isRelay) {
    authTimer = setTimeout(function () {
      if (!st.authed) { try { ws.close(); } catch (e) {} loginError('Hết thời gian chờ — kiểm tra ID/mật khẩu và cùng mạng Wi-Fi.'); }
    }, 12000);
  }

  ws.onopen = function () {
    var msg = buildAuthMessage(id, pass, mode);
    ws.send(JSON.stringify(msg));
  };
  ws.onmessage = function (ev) {
    if (ev.data instanceof ArrayBuffer) { onFrame(ev.data); return; }
    var m;
    try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (m.type === 'auth_ok' || (m.type === 'auth_result' && m.ok)) {
      clearTimeout(authTimer);
      if (isRelay) wakeup.onAuthedOk();
      var d = m.type === 'auth_ok' ? m : (m.data || {});
      // Gửi hello ngược ngay sau khi xác thực thành công
      ws.send(JSON.stringify({ type: 'hello', v: PROTOCOL_VERSION, caps: PROTOCOL_CAPS }));
      onAuthed(d);
    } else if (m.type === 'hello') {
      // Nhận hello từ agent — ghi nhận phiên bản để dùng sau
      st.peerV = (typeof m.v === 'number' && m.v >= 1) ? m.v : 1;
      st.peerCaps = Array.isArray(m.caps) ? m.caps : [];
    } else if (m.type === 'auth_fail' || (m.type === 'auth_result' && !m.ok)) {
      clearTimeout(authTimer);
      if (isRelay) wakeup.onAuthedOk();  // dừng retry (lỗi auth ≠ relay ngủ)
      st.resumeToken = '';
      localStorage.removeItem('tl_resumeToken');
      localStorage.removeItem('tl_resumeDeviceId');
      el.btnConnect.disabled = false;
      el.btnConnect.textContent = 'Kết nối';
      show(el.viewer, false); show(el.login, true);
      loginError((m.message || 'Sai thông tin đăng nhập'));
    } else if (m.type === 'screen_locked') {
      if (m.locked && m.svc) {
        toast('🔒 Màn hình máy tính đang khóa — đang điều khiển QUA SERVICE: gõ mật khẩu Windows rồi Enter để mở khóa.', 8000);
      } else if (m.locked) {
        toast('🔒 Máy tính đang KHÓA màn hình — chưa cài service nên không xem/điều khiển được. Cài "TouchLinkSvc" trong app máy tính (Cài đặt → Service).', 8000);
      } else {
        toast('Máy tính đã mở khóa màn hình', 3000);
      }
    } else if (m.type === 'pong') {
      pingMs = Math.max(0, Date.now() - (m.t || Date.now()));
    } else if (m.type === 'settings') {
      applyServerSettings(m.settings || {});
    } else if (m.type === 'clipboard') {
      onClipboard(m.text || '');
    } else if (m.type === 'chat') {
      addChat(m.from || 'PC', m.text || '');
    } else if (m.type === 'clients') {
      st.meta.viewers = m.n; updateMeta();
    }
  };
  ws.onclose = function () {
    clearTimeout(authTimer);
    if (!st.authed) {
      // Chưa auth → relay có thể đang ngủ → retry backoff
      if (isRelay && !wakeup.isActive && !st.closing) {
        el.btnConnect.textContent = 'Đang chờ relay…';
        wakeup.onClosed(true, _retryFn);
        return;
      } else if (isRelay && !st.closing) {
        wakeup.onClosed(true, _retryFn);
        return;
      }
    }
    el.btnConnect.disabled = false;
    el.btnConnect.textContent = 'Kết nối';
    if (st.authed && !st.closing) {
      show(el.viewer, true); show(el.login, false);
      el.lostMsg.textContent = 'Mất kết nối với máy tính.';
      show(el.lost, true);
      if (!st._retried) {
        st._retried = true;
        clearTimeout(st._retry_t);
        st._retry_t = setTimeout(function () {
          if (!st.closing) {
            scheduleReconnect();
          }
        }, 4000);
      }
    }
    st.authed = false;
  };
  ws.onerror = function () {};
}
function loginError(msg) {
  el.loginError.hidden = !msg;
  el.loginError.textContent = msg || '';

}

function onAuthed(d) {
  st.authed = true;
  st.reconnectAttempt = 0;
  if (d && d.resume_token) {
    st.resumeToken = d.resume_token;
    st.resumeDeviceId = st.cred && st.cred.id ? st.cred.id : '';
    localStorage.setItem('tl_resumeToken', st.resumeToken);
    localStorage.setItem('tl_resumeDeviceId', st.resumeDeviceId);
  }
  show(el.login, false); show(el.viewer, true); show(el.lost, false);
  el.btnConnect.disabled = false; el.btnConnect.textContent = 'Kết nối';
  if (el.fremember.checked) {
    localStorage.setItem('tl_host', st.host);
    localStorage.setItem('tl_id', el.fid.value.trim());
    localStorage.setItem('tl_pass', el.fpass.value);
  }
  applyServerSettings(d.settings || {});
  st.monitors = d.monitors || [];
  fillMonitors();
  st.meta = { hostname: d.hostname, device_id: d.device_id, version: d.version, viewers: 1 };
  if (d.safe_test) toast('⚠ SAFE-TEST: thao tác không được thực thi thật', 4000);
  if (d.screen_locked) {
    setTimeout(function () {
      if (d.svc_ok) {
        toast('🔒 Máy đang khóa — đang điều khiển QUA SERVICE: gõ mật khẩu Windows rồi Enter.', 8000);
      } else {
        toast('🔒 Máy đang khóa và chưa cài service — không xem/điều khiển được. Cài "TouchLinkSvc" trong app (Cài đặt).', 8000);
      }
    }, 800);
  }
  st._retried = false;
  updateMeta();
  show(el.scrollstrip, true);
  frameCount = 0; fpsShown = 0; pingMs = 0;
  toast('Đã kết nối tới ' + (d.hostname || 'máy tính'));
  acquireWakeLock();
  if ('requestFullscreen' in document.documentElement) { /* không tự mở */ }
}

function applyServerSettings(s) {
  ['fps', 'quality', 'scale', 'monitor', 'clipboard_sync', 'keep_awake'].forEach(function (k) {
    if (k in s) st.srv[k] = s[k];
  });
  el.sFps.value = st.srv.fps; el.vFps.textContent = st.srv.fps;
  el.sQuality.value = st.srv.quality; el.vQuality.textContent = st.srv.quality;
  el.sScale.value = st.srv.scale; el.vScale.textContent = st.srv.scale + '%';
  el.sCbsync.checked = !!st.srv.clipboard_sync;
  el.clipAuto.checked = !!st.srv.clipboard_sync;
  if ('keep_awake' in st.srv) el.sAwake.checked = !!st.srv.keep_awake;
  if (el.sMonitor.selectedIndex >= 0 && el.sMonitor.value !== String(st.srv.monitor)) {
    var opt = Array.prototype.find.call(el.sMonitor.options, function (o) { return o.value === String(st.srv.monitor); });
    if (opt) el.sMonitor.value = opt.value;
  }
  updateMeta();
}
function fillMonitors() {
  el.sMonitor.innerHTML = '';
  (st.monitors.length ? st.monitors : [{ index: 1, label: 'Màn hình chính' }]).forEach(function (m) {
    var o = document.createElement('option');
    o.value = m.index; o.textContent = m.label || ('Màn hình ' + m.index);
    el.sMonitor.appendChild(o);
  });
  el.sMonitor.value = String(st.srv.monitor);
}
function updateMeta() {
  var bits = [];
  if (st.meta.hostname) bits.push('Máy: ' + st.meta.hostname);
  if (st.meta.device_id) bits.push('ID: ' + st.meta.device_id);
  if (st.meta.viewers != null) bits.push('Người xem: ' + st.meta.viewers);
  if (st.meta.version) bits.push('v' + st.meta.version);
  el.connMeta.textContent = bits.join(' · ');
}

/* ---------- frames & canvas ---------- */

/**
 * Tạo/reset offscreen canvas để giữ full frame khi dùng tile mode.
 * Gọi khi fw/fh thay đổi.
 */
function ensureTileCanvas(fw, fh) {
  if (!st.tileCanvas) {
    st.tileCanvas = document.createElement('canvas');
    st.tileCtx = st.tileCanvas.getContext('2d');
  }
  if (st.tileCanvas.width !== fw || st.tileCanvas.height !== fh) {
    st.tileCanvas.width = fw;
    st.tileCanvas.height = fh;
    // Điền màu đen khi thay đổi kích thước
    st.tileCtx.fillStyle = '#000';
    st.tileCtx.fillRect(0, 0, fw, fh);
  }
}

/**
 * Xử lý frame 0x01 (toàn khung JPEG cũ).
 */
function onFrameFull(buf) {
  try {
    var dv = new DataView(buf);
    if (dv.getUint8(0) !== 0x01) return;
    var fw = dv.getUint16(1);
    var fh = dv.getUint16(3);
    st.fw = fw; st.fh = fh;
    var blob = new Blob([buf.slice(5)], { type: 'image/jpeg' });
    if (window.createImageBitmap) {
      createImageBitmap(blob).then(function (b) {
        if (bmp && bmp.close) bmp.close();
        bmp = b;
        // Cập nhật offscreen tile canvas
        ensureTileCanvas(fw, fh);
        st.tileCtx.drawImage(b, 0, 0);
        redrawNeeded = true;
      }).catch(function () {});
    } else {
      var img = new Image();
      img.onload = function () {
        bmp = img;
        ensureTileCanvas(fw, fh);
        st.tileCtx.drawImage(img, 0, 0);
        redrawNeeded = true;
      };
      img.src = URL.createObjectURL(blob);
    }
    frameCount++;
  } catch (e) {}
}

/**
 * Xử lý frame 0x02 (tile dirty-rect).
 * Wire format: [0x02][fw:u16][fh:u16][tile_size:u16][n_tiles:u16]
 *              per tile: [tx:u16][ty:u16][jpeg_len:u32][jpeg...]
 */
function onFrameTile(buf) {
  try {
    var dv = new DataView(buf);
    if (dv.getUint8(0) !== 0x02) return;
    var fw = dv.getUint16(1);
    var fh = dv.getUint16(3);
    // var tileSize = dv.getUint16(5);  // không cần ở client
    var nTiles = dv.getUint16(7);
    if (nTiles === 0) { frameCount++; return; }
    st.fw = fw; st.fh = fh;
    ensureTileCanvas(fw, fh);

    var offset = 9;  // sau header 9 byte
    var pending = nTiles;
    var newBmp = null;

    function finalize() {
      // Sau khi tất cả tile đã vẽ lên tileCanvas → tạo ImageBitmap từ canvas
      if (window.createImageBitmap) {
        createImageBitmap(st.tileCanvas).then(function (b) {
          if (bmp && bmp.close) bmp.close();
          bmp = b;
          redrawNeeded = true;
        }).catch(function () {});
      } else {
        // Fallback: vẽ trực tiếp (không cần bmp)
        redrawNeeded = true;
        bmp = st.tileCanvas;  // draw() sẽ drawImage canvas
      }
      frameCount++;
    }

    for (var i = 0; i < nTiles; i++) {
      if (offset + 8 > buf.byteLength) break;
      var tx = dv.getUint16(offset);
      var ty = dv.getUint16(offset + 2);
      var jlen = dv.getUint32(offset + 4);
      offset += 8;
      if (offset + jlen > buf.byteLength) break;
      var jpegSlice = buf.slice(offset, offset + jlen);
      offset += jlen;
      /* jshint loopfunc: true */
      (function (jtx, jty, jbuf) {
        var blob2 = new Blob([jbuf], { type: 'image/jpeg' });
        if (window.createImageBitmap) {
          createImageBitmap(blob2).then(function (tb) {
            st.tileCtx.drawImage(tb, jtx, jty);
            if (tb.close) tb.close();
            pending--;
            if (pending <= 0) finalize();
          }).catch(function () {
            pending--;
            if (pending <= 0) finalize();
          });
        } else {
          var timg = new Image();
          timg.onload = function () {
            st.tileCtx.drawImage(timg, jtx, jty);
            pending--;
            if (pending <= 0) finalize();
          };
          timg.onerror = function () {
            pending--;
            if (pending <= 0) finalize();
          };
          timg.src = URL.createObjectURL(blob2);
        }
      }(tx, ty, jpegSlice));
    }
  } catch (e) {}
}

function onFrame(buf) {
  try {
    var dv = new DataView(buf);
    var type = dv.getUint8(0);
    if (type === 0x01) {
      onFrameFull(buf);
    } else if (type === 0x02) {
      onFrameTile(buf);
    }
    // type không nhận ra → bỏ qua
  } catch (e) {}
}

var ctx = el.canvas.getContext('2d');
function draw() {
  requestAnimationFrame(draw);
  if (!bmp || !st.fw) return;
  redrawNeeded = false;
  var dpr = window.devicePixelRatio || 1;
  var vw = el.canvas.clientWidth, vh = el.canvas.clientHeight;
  if (el.canvas.width !== Math.round(vw * dpr) || el.canvas.height !== Math.round(vh * dpr)) {
    el.canvas.width = Math.round(vw * dpr);
    el.canvas.height = Math.round(vh * dpr);
  }
  st.fit = Math.min(vw / st.fw, vh / st.fh);
  var s = st.fit * st.zoom;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, vw, vh);
  var ox = vw / 2 + st.panX - (st.fw * s) / 2;
  var oy = vh / 2 + st.panY - (st.fh * s) / 2;
  ctx.imageSmoothingEnabled = st.zoom < 1.6;
  ctx.setTransform(dpr * s, 0, 0, dpr * s, dpr * ox, dpr * oy);
  ctx.drawImage(bmp, 0, 0);
}
requestAnimationFrame(draw);

function clampPan() {
  var vw = el.canvas.clientWidth, vh = el.canvas.clientHeight;
  var s = st.fit * st.zoom;
  var mx = Math.max(0, (st.fw * s - vw) / 2 + 30);
  var my = Math.max(0, (st.fh * s - vh) / 2 + 30);
  st.panX = clamp(st.panX, -mx, mx);
  st.panY = clamp(st.panY, -my, my);
}
function toImage(cx, cy) {
  var r = el.canvas.getBoundingClientRect();
  var vw = r.width, vh = r.height;
  var s = st.fit * st.zoom;
  var ox = vw / 2 + st.panX - (st.fw * s) / 2;
  var oy = vh / 2 + st.panY - (st.fh * s) / 2;
  return {
    x: clamp((cx - r.left - ox) / s, 0, st.fw - 1),
    y: clamp((cy - r.top - oy) / s, 0, st.fh - 1)
  };
}

/* ---------- input sending ---------- */
function send(o) {
  if (st.ws && st.ws.readyState === 1) { st.ws.send(JSON.stringify(o)); eventCount++; }
}
function sendMouse(action, x, y, extra) {
  var o = { type: 'input', kind: 'mouse', action: action, x: (x == null ? null : Math.round(x)), y: (y == null ? null : Math.round(y)) };
  if (extra) for (var k in extra) o[k] = extra[k];
  send(o);
}
function sendKey(key, mods) { send({ type: 'input', kind: 'key', key: key, mods: mods || [] }); }
function sendText(t) { send({ type: 'input', kind: 'text', text: t }); }
function sendScroll(n, hn) {
  var o = { type: 'input', kind: 'mouse', action: 'scroll' };
  if (n) o.amount = st.invert ? -n : n;
  if (hn) o.hamount = st.invert ? -hn : hn;
  send(o);
}
function activeMods() {
  var m = [];
  ['ctrl', 'alt', 'shift', 'win'].forEach(function (k) { if (st.sticky[k]) m.push(k); });
  return m;
}
function clearSticky() {
  st.sticky = {};
  Array.prototype.forEach.call(document.querySelectorAll('.qk.mod'), function (b) { b.classList.remove('on'); });
}

/* ---------- pointer handling ---------- */
var pointers = new Map();
var single = { id: null, x0: 0, y0: 0, t0: 0, moved: false, longFired: false, holdTimer: null, downSent: false };
var gesture = null;
var lastTap = { t: 0, x: 0, y: 0 };
var relPending = { dx: 0, dy: 0 }, relScheduled = false;
var scrollAcc = { y: 0, x: 0 };
var topbarTimer = null;

function wakeTopbar() {
  el.topbar.classList.remove('dim');
  clearTimeout(topbarTimer);
  topbarTimer = setTimeout(function () { el.topbar.classList.add('dim'); }, 4500);
}
wakeTopbar();

function flushRel() {
  relScheduled = false;
  if (relPending.dx || relPending.dy) {
    sendMouse('move', null, null, { rel: [Math.round(relPending.dx), Math.round(relPending.dy)] });
    relPending.dx = 0; relPending.dy = 0;
  }
}

el.canvas.addEventListener('pointerdown', function (e) {
  wakeTopbar();
  el.canvas.setPointerCapture(e.pointerId);
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY });
  if (pointers.size === 2) {
    // bắt đầu gesture 2 ngón — hủy thao tác 1 ngón đang dang dở
    cancelSingle(e);
    var pts = Array.from(pointers.values());
    gesture = {
      dist0: Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y),
      mid0: { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 },
      zoom0: st.zoom, pan0: { x: st.panX, y: st.panY },
      mode: null, lastMid: { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 },
      lastDist: Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y)
    };
    scrollAcc.y = 0; scrollAcc.x = 0;
    return;
  }
  if (pointers.size > 2) return;
  // 1 ngón / chuột
  single.id = e.pointerId;
  single.x0 = e.clientX; single.y0 = e.clientY; single.t0 = Date.now();
  single.moved = false; single.longFired = false; single.downSent = false;
  var isMouse = e.pointerType === 'mouse';
  if (isMouse || st.mode === 'direct') {
    var p = toImage(e.clientX, e.clientY);
    if (isMouse) {
      sendMouse('down', p.x, p.y, { button: e.button === 2 ? 'right' : (e.button === 1 ? 'middle' : 'left') });
      single.downSent = true;
    } else {
      sendMouse('down', p.x, p.y, { button: 'left' });
      single.downSent = true;
      single.holdTimer = setTimeout(function () {
        if (!single.moved && single.id != null && !single.longFired) {
          single.longFired = true;
          sendMouse('up', p.x, p.y, { button: 'left' });
          sendMouse('click', p.x, p.y, { button: 'right' });
          vib(30);
        }
      }, 550);
    }
  } else {
    // touchpad: chờ phân loại tap / giữ
    var isSecondTap = (Date.now() - lastTap.t < 320) &&
      Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) < 60;
    single.holdTimer = setTimeout(function () {
      if (single.id != null && !single.moved) {
        if (isSecondTap) {
          st.dragging = true;
          sendMouse('down', null, null, { button: 'left' });
          vib(15);
        } else if (Date.now() - single.t0 > 550 && !single.longFired) {
          single.longFired = true;
          sendMouse('click', null, null, { button: 'right' });
          vib(30);
        }
      }
    }, isSecondTap ? 180 : 600);
  }
});

el.canvas.addEventListener('pointermove', function (e) {
  wakeTopbar();
  var pt = pointers.get(e.pointerId);
  if (pt) { pt.x = e.clientX; pt.y = e.clientY; }
  if (gesture && pointers.size >= 2) {
    var pts = Array.from(pointers.values()).slice(0, 2);
    var dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
    var mid = { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 };
    if (!gesture.mode) {
      var ratio = dist / (gesture.dist0 || 1);
      var pref = st.twoFinger;
      if (Math.abs(ratio - 1) > 0.09) gesture.mode = 'zoom';
      else if (pref === 'scroll') gesture.mode = 'scroll';
      else if (pref === 'pan') gesture.mode = 'pan';
      else gesture.mode = (st.zoom > 1.02) ? 'pan' : 'scroll';
    }
    if (gesture.mode === 'zoom') {
      st.zoom = clamp(gesture.zoom0 * (dist / (gesture.dist0 || 1)), 0.4, 6);
      clampPan(); redrawNeeded = true;
    } else if (gesture.mode === 'pan') {
      st.panX = gesture.pan0.x + (mid.x - gesture.mid0.x);
      st.panY = gesture.pan0.y + (mid.y - gesture.mid0.y);
      clampPan(); redrawNeeded = true;
    } else {
      scrollAcc.y += mid.y - gesture.lastMid.y;
      scrollAcc.x += mid.x - gesture.lastMid.x;
      var ny = Math.round(scrollAcc.y / 40), nx = Math.round(scrollAcc.x / 40);
      if (ny || nx) {
        scrollAcc.y -= ny * 40; scrollAcc.x -= nx * 40;
        sendScroll(ny, nx);
      }
    }
    gesture.lastMid = mid; gesture.lastDist = dist;
    return;
  }
  if (e.pointerId !== single.id) return;
  var moved = Math.hypot(e.clientX - single.x0, e.clientY - single.y0);
  if (moved > 10 && !single.longFired) {
    if (single.holdTimer) { clearTimeout(single.holdTimer); single.holdTimer = null; }
  }
  if (moved > 6) single.moved = true;
  if (st.mode === 'direct' || e.pointerType === 'mouse') {
    if (single.longFired && e.pointerType !== 'mouse') return; // sau chuột phải thì thôi kéo
    var p2 = toImage(e.clientX, e.clientY);
    scheduleMove(p2);
  } else {
    // touchpad: di chuyển tương đối
    if (pt) {
      relPending.dx += (e.clientX - pt.x) * (st.sens / 10);
      relPending.dy += (e.clientY - pt.y) * (st.sens / 10);
      pt.x0 = pt.x; pt.y0 = pt.y;
      if (!relScheduled) { relScheduled = true; requestAnimationFrame(flushRel); }
    }
  }
});

function scheduleMove(p) {
  scheduleMove.last = p;
  if (scheduleMove.scheduled) return;
  scheduleMove.scheduled = true;
  requestAnimationFrame(function () {
    scheduleMove.scheduled = false;
    var p3 = scheduleMove.last;
    if (p3 && single.id != null) sendMouse('move', p3.x, p3.y);
  });
}

function cancelSingle(e) {
  if (single.holdTimer) { clearTimeout(single.holdTimer); single.holdTimer = null; }
  if (single.downSent && !single.longFired && single.id != null && e && e.pointerId === single.id) {
    var p = toImage(e.clientX, e.clientY);
    sendMouse('up', p.x, p.y, { button: 'left' });
  }
  if (st.dragging) { sendMouse('up', null, null, { button: 'left' }); st.dragging = false; }
  single.id = null; single.downSent = false;
}

el.canvas.addEventListener('pointerup', function (e) {
  var pt = pointers.get(e.pointerId);
  pointers.delete(e.pointerId);
  if (gesture) {
    if (pointers.size < 2) gesture = null;
    return;
  }
  if (e.pointerId !== single.id) return;
  if (single.holdTimer) { clearTimeout(single.holdTimer); single.holdTimer = null; }
  var quick = (Date.now() - single.t0) < 250 && !single.moved;
  if (e.pointerType === 'mouse') {
    var p = toImage(e.clientX, e.clientY);
    sendMouse('up', p.x, p.y, { button: e.button === 2 ? 'right' : (e.button === 1 ? 'middle' : 'left') });
  } else if (st.mode === 'direct') {
    if (!single.longFired) {
      var p2 = toImage(e.clientX, e.clientY);
      sendMouse('up', p2.x, p2.y, { button: 'left' });
    }
  } else {
    // touchpad
    if (st.dragging) {
      st.dragging = false;
      sendMouse('up', null, null, { button: 'left' });
    } else if (quick && !single.longFired) {
      sendMouse('click', null, null, { button: 'left' });
      lastTap = { t: Date.now(), x: e.clientX, y: e.clientY };
      vib(10);
    }
  }
  single.id = null; single.downSent = false;
});
el.canvas.addEventListener('pointercancel', function (e) {
  pointers.delete(e.pointerId);
  cancelSingle(e);
  if (pointers.size < 2) gesture = null;
});
el.canvas.addEventListener('wheel', function (e) {
  e.preventDefault();
  var amt = Math.round(-e.deltaY / 40);
  if (amt) sendScroll(amt, e.deltaX ? Math.round(-e.deltaX / 40) : 0);
}, { passive: false });
el.canvas.addEventListener('contextmenu', function (e) { e.preventDefault(); });

/* dải cuộn bên phải */
var strip = { lastY: null, id: null };
el.scrollstrip.addEventListener('pointerdown', function (e) {
  strip.id = e.pointerId; strip.lastY = e.clientY;
  el.scrollstrip.setPointerCapture(e.pointerId);
});
el.scrollstrip.addEventListener('pointermove', function (e) {
  if (e.pointerId !== strip.id || strip.lastY == null) return;
  scrollAcc.y += e.clientY - strip.lastY;
  strip.lastY = e.clientY;
  var ny = Math.round(scrollAcc.y / 30);
  if (ny) { scrollAcc.y -= ny * 30; sendScroll(ny, 0); }
});
['pointerup', 'pointercancel'].forEach(function (ev) {
  el.scrollstrip.addEventListener(ev, function (e) {
    if (e.pointerId === strip.id) { strip.id = null; strip.lastY = null; }
  });
});

/* ---------- bàn phím ---------- */
el.btnKeys.addEventListener('click', function () {
  el.ime.focus({ preventScroll: true });
  toast('Đang mở bàn phím — gõ trực tiếp (hỗ trợ tiếng Việt)');
});
el.ime.addEventListener('input', function () {
  var v = el.ime.value;
  if (v) { sendText(v); el.ime.value = ''; }
});
el.ime.addEventListener('keydown', function (e) {
  if (e.isComposing || e.keyCode === 229) return;
  var k = e.key;
  var specials = ['Enter', 'Backspace', 'Tab', 'Escape', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
    'Home', 'End', 'PageUp', 'PageDown', 'Delete', 'Insert'];
  var map = { Enter: 'enter', Backspace: 'backspace', Tab: 'tab', Escape: 'escape',
    ArrowUp: 'arrowup', ArrowDown: 'arrowdown', ArrowLeft: 'arrowleft', ArrowRight: 'arrowright',
    Home: 'home', End: 'end', PageUp: 'pageup', PageDown: 'pagedown', Delete: 'delete', Insert: 'insert' };
  var mods = [];
  if (e.ctrlKey) mods.push('ctrl');
  if (e.altKey) mods.push('alt');
  if (e.shiftKey) mods.push('shift');
  if (e.metaKey) mods.push('win');
  if (specials.indexOf(k) >= 0) {
    e.preventDefault();
    sendKey(map[k], mods.concat(activeMods()));
    clearSticky();
  } else if (/^F\d{1,2}$/.test(k)) {
    e.preventDefault();
    sendKey(k.toLowerCase(), mods.concat(activeMods()));
    clearSticky();
  }
});

el.btnQuick.addEventListener('click', function () {
  var on = el.quickkeys.classList.toggle('hidden');
  if (!on) closePanels(null);
});
el.quickkeys.addEventListener('click', function (e) {
  var b = e.target.closest('button');
  if (!b) return;
  if (b.classList.contains('mod')) {
    var m = b.dataset.mod;
    st.sticky[m] = !st.sticky[m];
    b.classList.toggle('on', st.sticky[m]);
    return;
  }
  vib(10);
  if (b.dataset.key) {
    sendKey(b.dataset.key, activeMods());
    clearSticky();
  } else if (b.dataset.combo) {
    var parts = b.dataset.combo.split('+');
    var key = parts.pop();
    if (b.dataset.combo === 'ctrl+alt+delete') {
      toast('Windows không cho gửi Ctrl+Alt+Del từ xa. Dùng nút "Task Mgr" (Ctrl+Shift+Esc).', 4000);
      return;
    }
    sendKey(key, parts);
  } else if (b.dataset.media) {
    sendKey(b.dataset.media);
  }
});

/* ---------- panels ---------- */
function closePanels(keep) {
  [el.sheet, el.clip, el.chat].forEach(function (p) { if (p !== keep) show(p, false); });
}
el.btnMenu.addEventListener('click', function () {
  var willShow = el.sheet.classList.contains('hidden');
  closePanels(willShow ? el.sheet : null);
  show(el.sheet, willShow);
});
el.btnClip.addEventListener('click', function () {
  var willShow = el.clip.classList.contains('hidden');
  closePanels(willShow ? el.clip : null);
  show(el.clip, willShow);
  if (willShow) send({ type: 'clipboard_get' });
});
el.btnChat.addEventListener('click', function () {
  var willShow = el.chat.classList.contains('hidden');
  closePanels(willShow ? el.chat : null);
  show(el.chat, willShow);
});
el.sheetClose.addEventListener('click', function () { show(el.sheet, false); });
el.clipClose.addEventListener('click', function () { show(el.clip, false); });
el.chatClose.addEventListener('click', function () { show(el.chat, false); });

/* cài đặt */
function bindRange(input, label, key, fmt) {
  input.addEventListener('input', function () {
    label.textContent = fmt(input.value);
  });
  input.addEventListener('change', function () {
    var s = {}; s[key] = parseInt(input.value, 10);
    send({ type: 'settings', settings: s });
  });
}
bindRange(el.sQuality, el.vQuality, 'quality', function (v) { return v; });
bindRange(el.sFps, el.vFps, 'fps', function (v) { return v; });
bindRange(el.sScale, el.vScale, 'scale', function (v) { return v + '%'; });
el.sMonitor.addEventListener('change', function () {
  send({ type: 'settings', settings: { monitor: parseInt(el.sMonitor.value, 10) } });
});
el.sCbsync.addEventListener('change', function () {
  send({ type: 'settings', settings: { clipboard_sync: el.sCbsync.checked } });
  el.clipAuto.checked = el.sCbsync.checked;
});
el.sAwake.addEventListener('change', function () {
  send({ type: 'settings', settings: { keep_awake: el.sAwake.checked } });
  toast(el.sAwake.checked ? 'Máy tính sẽ không tự sleep khi TouchLink chạy' : 'Đã trả lại chế độ sleep của Windows');
});
function saveClientPrefs() {
  localStorage.setItem('tl_mode', st.mode);
  localStorage.setItem('tl_sens', String(st.sens));
  localStorage.setItem('tl_invert', st.invert ? '1' : '0');
  localStorage.setItem('tl_2finger', st.twoFinger);
}
el.sMode.value = st.mode; el.sSens.value = st.sens; el.vSens.textContent = st.sens;
el.sInvert.checked = st.invert; el.s2.value = st.twoFinger;
el.sMode.addEventListener('change', function () {
  st.mode = el.sMode.value; saveClientPrefs();
  el.btnMode.textContent = st.mode === 'touchpad' ? ' ⇥ ' : ' 🖱 ';
  toast(st.mode === 'touchpad' ? 'Touchpad: vuốt = di chuột, chạm = click' : 'Trực tiếp: chạm = click tại điểm chạm');
});
el.sSens.addEventListener('input', function () { el.vSens.textContent = el.sSens.value; });
el.sSens.addEventListener('change', function () { st.sens = parseInt(el.sSens.value, 10); saveClientPrefs(); });
el.sInvert.addEventListener('change', function () { st.invert = el.sInvert.checked; saveClientPrefs(); });
el.s2.addEventListener('change', function () { st.twoFinger = el.s2.value; saveClientPrefs(); });
el.btnMode.textContent = st.mode === 'touchpad' ? ' ⇥ ' : ' 🖱 ';
el.btnMode.addEventListener('click', function () {
  el.sMode.value = st.mode === 'direct' ? 'touchpad' : 'direct';
  el.sMode.dispatchEvent(new Event('change'));
});

el.btnFullscreen.addEventListener('click', function () {
  var d = document.documentElement;
  if (document.fullscreenElement) { document.exitFullscreen().catch(function () {}); }
  else {
    d.requestFullscreen().then(function () {
      if (screen.orientation && screen.orientation.lock) screen.orientation.lock('landscape').catch(function () {});
    }).catch(function () { toast('Trình duyệt không cho toàn màn hình'); });
  }
});
el.btnReconnect.addEventListener('click', function () {
  show(el.lost, false);
  connect(st.host, el.fid.value.trim(), el.fpass.value);
});
el.btnExit.addEventListener('click', function () {
  st.closing = true;
  if (st.ws) { try { st.ws.close(); } catch (e) {} }
  st.authed = false;
  closePanels(null);
  show(el.quickkeys, false);
  show(el.viewer, false); show(el.login, true);
});
el.btnRelogin.addEventListener('click', function () {
  show(el.lost, false);
  show(el.viewer, false); show(el.login, true);
});

/* clipboard */
function onClipboard(text) {
  el.clipText.value = text;
  if (!el.clip.classList.contains('hidden')) return;
  toast('📋 Clipboard máy tính: ' + (text.length > 60 ? text.slice(0, 60) + '…' : text || '(trống)'));
}
el.clipGet.addEventListener('click', function () { send({ type: 'clipboard_get' }); });
el.clipSet.addEventListener('click', function () {
  send({ type: 'clipboard_set', text: el.clipText.value });
  toast('Đã gửi clipboard tới máy tính');
});
el.clipAuto.addEventListener('change', function () {
  el.sCbsync.checked = el.clipAuto.checked;
  send({ type: 'settings', settings: { clipboard_sync: el.clipAuto.checked } });
});

/* chat */
function addChat(from, text) {
  var d = document.createElement('div');
  d.className = 'chat-msg';
  var b = document.createElement('b');
  b.textContent = from;
  d.appendChild(b);
  d.appendChild(document.createTextNode(text));
  el.chatList.appendChild(d);
  el.chatList.scrollTop = el.chatList.scrollHeight;
  if (el.chat.classList.contains('hidden')) toast('💬 ' + from + ': ' + text);
}
el.chatSend.addEventListener('click', sendChat);
el.chatInput.addEventListener('keydown', function (e) { if (e.key === 'Enter') sendChat(); });
function sendChat() {
  var t = el.chatInput.value.trim();
  if (!t) return;
  send({ type: 'chat', text: t });
  el.chatInput.value = '';
}

/* ---------- stats ---------- */
setInterval(function () {
  fpsShown = frameCount - (draw._f || 0);
  draw._f = frameCount;
  var zoomPct = Math.round(st.zoom * 100);
  el.status.textContent = st.authed
    ? (fpsShown + ' fps · ' + pingMs + ' ms · ' + zoomPct + '%')
    : '—';
}, 1000);
setInterval(function () {
  if (st.authed) send({ type: 'ping', t: Date.now() });
}, 2000);

document.addEventListener('visibilitychange', function () {
  if (document.visibilityState === 'visible') {
    acquireWakeLock();
  } else if (st.wakeLock && st.wakeLock.release) {
    st.wakeLock.release().catch(function () {});
  }
});

/* ---------- login UI ---------- */
function setConnMode(mode, save) {
  st.connMode = (mode === 'relay') ? 'relay' : 'direct';
  if (save) localStorage.setItem('tl_connMode', st.connMode);
  var relay = st.connMode === 'relay';
  el.segDirect.classList.toggle('on', !relay);
  el.segRelay.classList.toggle('on', relay);
  show(el.fieldHost, !relay);
  show(el.fieldRelay, relay);
  loginError('');
}

function initLogin() {
  var params = new URLSearchParams(location.search);
  var forcedRelay = !!window.__TOUCHLINK_MODE; // trang do relay phục vụ -> khóa chế độ relay
  if (forcedRelay) {
    show(el.modeSeg, false);
    setConnMode('relay', false);
  } else {
    setConnMode(params.get('mode') || localStorage.getItem('tl_connMode') || MODE, false);
    el.segDirect.addEventListener('click', function () { setConnMode('direct', true); });
    el.segRelay.addEventListener('click', function () { setConnMode('relay', true); });
  }
  el.host.value = localStorage.getItem('tl_host') || location.host || '';
  el.fRelay.value = params.get('relay') || localStorage.getItem('tl_relay') || DEFAULT_RELAY;
  el.fid.value = params.get('id') || localStorage.getItem('tl_id') || '';
  el.fpass.value = localStorage.getItem('tl_pass') || '';
  $('login-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var id = el.fid.value.trim();
    var pass = el.fpass.value;
    if (!id) { loginError('Nhập mã máy (ID) — xem ở app TouchLink trên máy tính'); return; }
    if (!pass) { loginError('Nhập mật khẩu'); return; }
    var host = currentHostInput().trim();
    if (connMode() === 'relay') {
      if (!host) host = DEFAULT_RELAY;
      if (!host) { loginError('Nhập địa chỉ relay (wss://…)'); return; }
      localStorage.setItem('tl_relay', host);
    }
    if (el.fremember.checked) localStorage.setItem('tl_host', host);
    connect(host, id, pass);
  });
  if (params.get('auto') === '1' && el.fid.value && el.fpass.value) {
    setTimeout(function () { el.btnConnect.click(); }, 250);
  }
  // Enter trong ô ID/mật khẩu: mọi bàn phím (kể cả Android IME) đều gửi được form
  [el.fid, el.fpass].forEach(function (i) {
    i.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) {
        e.preventDefault();
        var form = $('login-form');
        if (form.requestSubmit) form.requestSubmit();
        else el.btnConnect.click();
      }
    });
  });
}
bindViewportCompat();
initLogin();
})();

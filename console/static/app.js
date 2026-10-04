/* مِرْقاة committee console — single-page UI (no build step, no framework). */
(() => {
  'use strict';

  // ------------------------------------------------------------ state & helpers
  const S = { pub: null, me: null, t: {}, lang: 'ar', dir: 'rtl', timers: [], route: '', loginStep: 'email',
    loginEmail: '', mockCode: '', cooldown: 0, selAgent: 'classifier', settingsTab: 'general' };
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const t = (key, vars) => {
    let s = S.t[key];
    if (s == null) s = key;
    if (vars) for (const k of Object.keys(vars)) s = s.split('{' + k + '}').join(String(vars[k]));
    return s;
  };
  const T = (k, v) => esc(t(k, v));
  const has = (p) => !!(S.me && S.me.permissions.includes(p));
  const store = {
    get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  class ApiError extends Error {
    constructor(status, key, detail) { super(key || 'error'); this.status = status; this.key = key; this.detail = detail; }
  }
  async function api(path, { method = 'GET', body } = {}) {
    const opt = { method, headers: { Accept: 'application/json' }, credentials: 'same-origin' };
    if (method !== 'GET') { opt.headers['X-Mirqah'] = '1'; opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body ?? {}); }
    let res;
    try { res = await fetch('/api' + path, opt); } catch (e) { throw new ApiError(0, 'network'); }
    let data = null;
    const ct = res.headers.get('content-type') || '';
    if (ct.includes('json')) data = await res.json().catch(() => null);
    else data = await res.text();
    if (!res.ok) {
      const d = data && data.detail !== undefined ? data.detail : data;
      const key = typeof d === 'string' ? d : (d && (d.error || d.detail)) || (data && data.error) || 'error';
      if (res.status === 401 && key === 'login_required' && S.me) { S.me = null; toast(t('auth.session_expired'), 'bad'); render(); }
      throw new ApiError(res.status, key, d && d.detail);
    }
    return data;
  }
  function errText(e) {
    if (!(e instanceof ApiError)) return t('common.error');
    if (e.status === 403 && e.key === 'forbidden') return t('common.forbidden');
    for (const ns of ['auth.err.', 'tasks.err.', 'users.err.', 'roles.err.', 'lang.err.', 'review.err.']) {
      if (S.t[ns + e.key]) return t(ns + e.key);
    }
    if (e.key === 'settings_invalid' && e.detail) return String(e.detail);
    if (e.key === 'mail_failed' && e.detail) return String(e.detail);
    return t('common.error') + (e.key && e.key !== 'error' ? ` (${e.key})` : '');
  }

  const locale = () => ({ ar: 'ar-u-nu-latn', ur: 'ur-u-nu-latn', zh: 'zh-CN', en: 'en-GB' }[S.lang] || S.lang);
  const tz = () => (S.pub && S.pub.timezone) || 'Asia/Riyadh';
  function fmt(ts, opts) {
    if (!ts) return '—';
    try { return new Intl.DateTimeFormat(locale(), { timeZone: tz(), ...opts }).format(new Date(ts * 1000)); }
    catch { return new Date(ts * 1000).toLocaleString(); }
  }
  const fTime = (ts) => fmt(ts, { hour: '2-digit', minute: '2-digit', hour12: false });
  const fDT = (ts) => fmt(ts, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
  const fNum = (n) => (n == null ? '—' : new Intl.NumberFormat(locale()).format(n));
  const fDur = (ms) => (ms == null ? '—' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} ${t('common.seconds')}`);
  const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);
  const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: tz(), year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  const tafsirName = (k) => ({ al_tabari: 'الطبري', ibn_kathir: 'ابن كثير', al_baghawi: 'البغوي', al_saadi: 'السعدي' }[k] || k);
  const initials = (n) => (n || '?').trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase();

  // ------------------------------------------------------------ icons (stroke, 24px grid)
  const P = {
    home: 'M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z',
    tasks: 'M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2',
    chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
    report: 'M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6',
    review: 'M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9',
    bolt: 'M13 2L4 14h7l-1 8 9-12h-7z',
    log: 'M4 4h16v16H4zM8 8h8M8 12h8M8 16h5',
    users: 'M16 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 20v-2a4 4 0 0 0-3-3.9M16 2.1a4 4 0 0 1 0 7.8',
    shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
    gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
    sun: 'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4',
    moon: 'M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z',
    auto: 'M12 3a9 9 0 1 0 0 18zM12 3a9 9 0 0 1 0 18',
    globe: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20',
    menu: 'M3 6h18M3 12h18M3 18h18',
    x: 'M18 6L6 18M6 6l12 12',
    play: 'M6 4l14 8-14 8z',
    stop: 'M6 6h12v12H6z',
    refresh: 'M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5',
    plus: 'M12 5v14M5 12h14',
    info: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01',
    warn: 'M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01',
    check: 'M20 6L9 17l-5-5',
    lock: 'M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4',
    mail: 'M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM22 6l-10 7L2 6',
    download: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3',
    user: 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
    out: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
    brain: 'M9.5 2A2.5 2.5 0 0 0 7 4.5v.1A3 3 0 0 0 4.5 8 3 3 0 0 0 3 10.6 3 3 0 0 0 4 15a3 3 0 0 0 3 4 2.5 2.5 0 0 0 5 .5V4.5A2.5 2.5 0 0 0 9.5 2zM14.5 2A2.5 2.5 0 0 1 17 4.5v.1A3 3 0 0 1 19.5 8 3 3 0 0 1 21 10.6 3 3 0 0 1 20 15a3 3 0 0 1-3 4 2.5 2.5 0 0 1-5 .5',
    arrow: 'M5 12h14M13 6l6 6-6 6',
  };
  const ico = (name, cls = '') => `<svg class="ic ${cls}" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${P[name] || ''}"/></svg>`;

  // Original generic robot drawing, tinted with currentColor.
  const robot = (color, running) => `<svg class="robot c-${color} ${running ? 'running' : ''}" viewBox="0 0 100 100" aria-hidden="true">
    <line x1="50" y1="8" x2="50" y2="18" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
    <circle cx="50" cy="7" r="4" fill="currentColor"/>
    <rect x="22" y="18" width="56" height="36" rx="12" fill="currentColor"/>
    <rect x="30" y="26" width="40" height="20" rx="8" fill="#0b1220" opacity=".85"/>
    <circle cx="41" cy="36" r="4.5" fill="#a7f3d0"/><circle cx="59" cy="36" r="4.5" fill="#a7f3d0"/>
    <rect x="30" y="58" width="40" height="28" rx="9" fill="currentColor"/>
    <circle cx="50" cy="72" r="7" fill="none" stroke="#0b1220" stroke-width="2.5" opacity=".7"/>
    <path d="M50 66v12M44 72h12" stroke="#0b1220" stroke-width="2.5" opacity=".7"/>
    <rect x="14" y="62" width="12" height="7" rx="3.5" fill="currentColor"/><rect x="74" y="62" width="12" height="7" rx="3.5" fill="currentColor"/>
    <rect x="35" y="87" width="9" height="9" rx="3" fill="currentColor"/><rect x="56" y="87" width="9" height="9" rx="3" fill="currentColor"/>
  </svg>`;

  // ------------------------------------------------------------ toasts & modal
  function toast(msg, kind = '') {
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.textContent = msg;
    $('#toasts').appendChild(el);
    setTimeout(() => el.remove(), kind === 'bad' ? 6000 : 3200);
  }
  function modal(html, { wide = false } = {}) {
    const root = $('#modal-root');
    root.innerHTML = `<div class="modal-back" data-close-back><div class="modal ${wide ? 'wide' : ''}" role="dialog" aria-modal="true">${html}</div></div>`;
    const first = root.querySelector('input, select, textarea, button.primary');
    if (first) setTimeout(() => first.focus(), 30);
    return root.firstElementChild;
  }
  const closeModal = () => { $('#modal-root').innerHTML = ''; };
  function confirmBox(message) {
    return new Promise((resolve) => {
      const m = modal(`<div class="modal-h"><h2>${ico('warn')} </h2></div><p>${esc(message)}</p>
        <div class="form-actions"><button class="btn" data-x="no">${T('common.cancel')}</button><button class="btn danger" data-x="yes">${T('common.yes')}</button></div>`);
      m.addEventListener('click', (e) => {
        const b = e.target.closest('[data-x]');
        if (b) { closeModal(); resolve(b.dataset.x === 'yes'); }
      });
    });
  }
  const modalHead = (title) => `<div class="modal-h"><h2>${esc(title)}</h2><button class="icon-btn" data-act="close-modal" aria-label="${T('common.close')}">${ico('x')}</button></div>`;

  // ------------------------------------------------------------ theme & language
  function applyTheme() {
    const mode = store.get('mq-theme', 'auto');
    const root = document.documentElement;
    root.dataset.theme = mode;
    root.classList.toggle('sys-dark', window.matchMedia('(prefers-color-scheme: dark)').matches);
  }
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', applyTheme);

  async function setLang(code, persist = true) {
    const langs = (S.pub && S.pub.languages) || [];
    const lang = langs.find((l) => l.code === code) || langs.find((l) => l.is_default) || { code: 'ar', dir: 'rtl' };
    try {
      const b = await api('/i18n/' + lang.code);
      S.t = b.strings;
    } catch { /* keep current strings */ }
    S.lang = lang.code;
    S.dir = lang.dir;
    document.documentElement.lang = lang.code;
    document.documentElement.dir = lang.dir;
    document.title = `${S.pub ? S.pub.team_name : 'مِرْقاة'} · ${t('app.title')}`;
    if (persist) store.set('mq-lang', lang.code);
  }

  // ------------------------------------------------------------ routing
  const NAV = [
    { r: 'dashboard', icon: 'home', k: 'nav.dashboard', p: 'view_dashboard' },
    { r: 'tasks', icon: 'tasks', k: 'nav.tasks', p: 'view_tasks' },
    { r: 'progress', icon: 'chart', k: 'nav.progress', p: 'view_dashboard' },
    { r: 'review', icon: 'review', k: 'nav.review', p: 'view_tasks' },
    { r: 'reports', icon: 'report', k: 'nav.reports', p: 'view_reports' },
    { r: 'calls', icon: 'bolt', k: 'nav.calls', p: 'view_tasks', opt: true },
    { sep: true },
    { admin: true, r: 'users', icon: 'users', k: 'nav.users', p: 'manage_users' },
    { admin: true, r: 'roles', icon: 'shield', k: 'nav.roles', p: 'manage_roles' },
    { admin: true, r: 'audit', icon: 'log', k: 'nav.audit', p: 'view_audit', opt: true },
    { admin: true, r: 'settings', icon: 'gear', k: 'nav.settings', p: 'manage_settings' },
  ];
  const parts = () => (location.hash.replace(/^#\/?/, '') || 'dashboard').split('/').map(decodeURIComponent);
  window.addEventListener('hashchange', () => { document.body.classList.remove('nav-open'); render(); });

  function clearTimers() { S.timers.forEach(clearInterval); S.timers = []; }
  function every(ms, fn) { S.timers.push(setInterval(() => { if (!document.hidden) fn(); }, ms)); }

  // ------------------------------------------------------------ shell
  function shell(inner) {
    const [r] = parts();
    const items = NAV.filter((n) => n.sep || has(n.p));
    const nav = items.map((n) => n.sep ? (items.some((x) => !x.sep && ['users', 'roles', 'audit', 'settings'].includes(x.r)) ? '<span class="sep"></span>' : '')
      : `<a href="#/${n.r}" class="${r === n.r ? 'on' : ''} ${n.admin ? 'adm' : ''}" title="${T(n.k)}">${ico(n.icon)}<span class="${n.opt ? 'lbl-opt' : ''}">${T(n.k)}</span></a>`).join('');
    const theme = store.get('mq-theme', 'auto');
    const langs = (S.pub.languages || []).map((l) => `<button class="mi ${l.code === S.lang ? 'on' : ''}" data-act="lang" data-code="${esc(l.code)}">${esc(l.name_native)}</button>`).join('');
    return `<header class="topbar"><div class="topbar-in">
      <button class="icon-btn menu-btn" data-act="nav-toggle" aria-label="${T('nav.menu')}">${ico('menu')}</button>
      <a class="brand" href="#/dashboard"><img src="/static/logo.svg" alt=""><span><span class="brand-name">${esc(S.pub.team_name)}</span>
        <span class="brand-sub">${T('app.title')}</span></span><span class="badge-beta">BETA</span></a>
      <nav class="nav" aria-label="${T('nav.menu')}">${nav}</nav>
      <div class="top-actions">
        <div class="dropdown"><button class="icon-btn" data-act="dd" aria-label="${T('lang.switch')}">${ico('globe')}</button>
          <div class="dropdown-menu"><div class="mh">${T('lang.switch')}</div>${langs}</div></div>
        <button class="icon-btn" data-act="theme" title="${T('theme.toggle')}: ${T('theme.' + theme)}" aria-label="${T('theme.toggle')}">${ico(theme === 'dark' ? 'moon' : theme === 'light' ? 'sun' : 'auto')}</button>
        <div class="dropdown"><button class="user-chip" data-act="dd"><span class="avatar">${esc(initials(S.me.name))}</span><span class="nm">${esc(S.me.name)}</span></button>
          <div class="dropdown-menu"><div class="mh">${esc(S.me.email)}<br>${esc(S.lang === 'ar' || S.lang === 'ur' ? S.me.role.name_ar : S.me.role.name_en)}</div>
            <a class="mi" href="#/profile">${ico('user')} ${T('nav.profile')}</a><hr>
            <button class="mi" data-act="logout">${ico('out')} ${T('auth.logout')}</button></div></div>
      </div></div></header>
      <div class="drawer-back" data-act="nav-toggle"></div>
      <main class="page" id="page">${inner}</main>`;
  }
  const head = (titleKey, subKey, actions = '') => `<div class="page-head"><div><h1>${T(titleKey)}</h1>${subKey ? `<p class="muted">${T(subKey)}</p>` : ''}</div>${actions ? `<div class="head-actions">${actions}</div>` : ''}</div>`;
  const loading = () => `<div class="empty"><div class="spinner" style="margin:auto"></div></div>`;
  const statusChip = (st) => {
    const cls = { done: 'ok', running: 'info', queued: '', failed: 'bad', cancelled: 'warn', skipped: '', interrupted: 'warn' }[st] || '';
    return `<span class="chip ${cls}">${st === 'running' ? '<span class="dot live"></span>' : ''}${T('tasks.status.' + st)}</span>`;
  };

  // ------------------------------------------------------------ render root
  async function render() {
    clearTimers();
    closeModal();
    const app = $('#app');
    if (!S.me) { app.innerHTML = loginView(); bindLogin(); return; }
    const [r, a, b] = parts();
    const routes = {
      dashboard: [viewDashboard, 'view_dashboard'], tasks: [a ? viewTask : viewTasks, 'view_tasks'],
      progress: [viewProgress, 'view_dashboard'], reports: [a ? viewReport : viewReports, 'view_reports'],
      review: [a ? viewReviewWindow : viewReview, 'view_tasks'], calls: [viewCalls, 'view_tasks'],
      audit: [viewAudit, 'view_audit'], users: [viewUsers, 'manage_users'], roles: [viewRoles, 'manage_roles'],
      settings: [viewSettings, 'manage_settings'], profile: [viewProfile, null],
    };
    let entry = routes[r];
    if (!entry || (entry[1] && !has(entry[1]))) {
      const first = NAV.find((n) => !n.sep && has(n.p));
      if (r !== 'profile' && first && first.r !== r) { location.hash = '#/' + first.r; return; }
      entry = [viewProfile, null];
    }
    app.innerHTML = shell(loading());
    try { await entry[0](a, b); } catch (e) {
      if (e instanceof ApiError && e.status === 401) return;
      $('#page').innerHTML = `<div class="notice bad">${ico('warn')}<span>${esc(errText(e))}</span></div>`;
    }
  }
  const setPage = (html) => { const p = $('#page'); if (p) p.innerHTML = html; };

  // ------------------------------------------------------------ login
  function loginView() {
    const langs = (S.pub.languages || []).map((l) => `<button class="mi ${l.code === S.lang ? 'on' : ''}" data-act="lang" data-code="${esc(l.code)}">${esc(l.name_native)}</button>`).join('');
    const theme = store.get('mq-theme', 'auto');
    const mock = S.pub.mail_mode === 'mock' ? `<div class="notice warn mt">${ico('info')}<span>${T('auth.mock_banner')}</span></div>` : '';
    const noUsers = !S.pub.has_users ? `<div class="notice mt">${ico('info')}<span class="ltr-isolate">${T('auth.no_users')}</span></div>` : '';
    let body;
    if (S.loginStep === 'email') {
      body = `<form id="f-email" class="stack" novalidate>
        <div class="field"><label for="email">${T('auth.email')}</label>
          <input class="input ltr" id="email" type="email" autocomplete="email" inputmode="email" required placeholder="${T('auth.email_ph')}" value="${esc(S.loginEmail)}"></div>
        <button class="btn primary block" type="submit">${ico('mail')} ${T('auth.send_code')}</button>
        <p class="faint" id="login-msg"></p></form>
        ${S.pub.guest_access ? `<div class="auth-or"><span>${T('auth.or')}</span></div>
        <button class="btn outline-accent block" type="button" data-act="guest">${ico('user')} ${T('auth.guest_btn')}</button>
        <p class="faint mt-s">${T('auth.guest_note')}</p>` : ''}`;
    } else {
      body = `<form id="f-code" class="stack" novalidate>
        <p class="muted">${T('auth.sent_generic')}</p>
        <p class="faint ltr">${esc(S.loginEmail)}</p>
        ${S.mockCode ? `<div class="notice ok"><span>${T('auth.mock_code')}: <span class="mock-code">${esc(S.mockCode)}</span></span></div>` : ''}
        <div class="field"><label for="code">${T('auth.code')}</label>
          <input class="input code-input" id="code" inputmode="numeric" autocomplete="one-time-code" maxlength="8" required></div>
        <button class="btn primary block" type="submit">${ico('lock')} ${T('auth.verify')}</button>
        <div class="row between"><button class="btn ghost sm" type="button" data-act="login-back">${T('auth.change_email')}</button>
          <button class="btn ghost sm" type="button" data-act="resend" ${S.cooldown > 0 ? 'disabled' : ''} id="resend">${S.cooldown > 0 ? T('auth.resend_in', { s: S.cooldown }) : T('auth.resend')}</button></div>
        <p class="faint" id="login-msg"></p></form>`;
    }
    return `<div class="auth-top"><div class="dropdown"><button class="icon-btn" data-act="dd" aria-label="${T('lang.switch')}">${ico('globe')}</button><div class="dropdown-menu">${langs}</div></div>
      <button class="icon-btn" data-act="theme" aria-label="${T('theme.toggle')}">${ico(theme === 'dark' ? 'moon' : theme === 'light' ? 'sun' : 'auto')}</button></div>
      <div class="auth-wrap"><div class="auth-card">
        <div class="auth-brand"><img src="/static/logo.svg" alt=""><div><h1>${esc(S.pub.team_name)}</h1><p class="muted">${T('app.title')} · ${esc(S.pub.project_name)}</p></div></div>
        <div class="card"><h2>${T('auth.title')}</h2><p class="muted mt-s mb">${T('auth.subtitle')}</p>${body}</div>${mock}${noUsers}
      </div></div>`;
  }
  let cooldownTimer = null;
  function startCooldown(s) {
    S.cooldown = s;
    clearInterval(cooldownTimer);
    cooldownTimer = setInterval(() => {
      S.cooldown -= 1;
      const b = $('#resend');
      if (b) { b.disabled = S.cooldown > 0; b.textContent = S.cooldown > 0 ? t('auth.resend_in', { s: S.cooldown }) : t('auth.resend'); }
      if (S.cooldown <= 0) clearInterval(cooldownTimer);
    }, 1000);
  }
  async function sendCode(email) {
    const msg = $('#login-msg');
    try {
      const r = await api('/auth/request-otp', { method: 'POST', body: { email } });
      S.loginEmail = email;
      S.mockCode = r.mock_code || '';
      S.loginStep = 'code';
      if (r.mail_error) toast(t('auth.err.mail_error'), 'bad');
      $('#app').innerHTML = loginView(); bindLogin();
      startCooldown(r.cooldown_s || 60);
    } catch (e) { if (msg) { msg.textContent = errText(e); msg.style.color = 'var(--danger)'; } }
  }
  function bindLogin() {
    const fe = $('#f-email');
    if (fe) fe.addEventListener('submit', (e) => { e.preventDefault(); const v = $('#email').value.trim(); if (v) sendCode(v); });
    const fc = $('#f-code');
    if (fc) {
      fc.addEventListener('submit', async (e) => {
        e.preventDefault();
        const msg = $('#login-msg');
        try {
          const r = await api('/auth/verify-otp', { method: 'POST', body: { email: S.loginEmail, code: $('#code').value.trim() } });
          S.me = r.user; S.mockCode = ''; S.loginStep = 'email';
          if (S.me.lang && S.me.lang !== S.lang) await setLang(S.me.lang);
          if (!location.hash || location.hash === '#/') location.hash = '#/dashboard';
          render();
        } catch (err) { msg.textContent = errText(err); msg.style.color = 'var(--danger)'; $('#code').select(); }
      });
    }
  }

  // ------------------------------------------------------------ dashboard
  async function viewDashboard() {
    const d = await api('/dashboard');
    setPage(dashHTML(d));
    every(5000, async () => {
      try { const n = await api('/dashboard'); if (parts()[0] === 'dashboard' && !$('.modal')) setPage(dashHTML(n)); } catch { /* next tick */ }
    });
  }
  function dashHTML(d) {
    const llm = d.llm || {};
    const ag = d.agents.agents;
    const running = d.agents.running;
    const sel = ag.find((a) => a.key === S.selAgent) || ag[0];
    const busy = !!running;
    const wires = ag.map((a, i) => {
      const x = ((i + 0.5) / ag.length) * 1000;
      const live = running && (running.agent === a.key || (a.key === 'checker' && ['classifier', 'verifier'].includes(running.agent)));
      return `<path class="${live ? 'live' : ''} c-${a.color}" stroke="currentColor" d="M500 0 C 500 40, ${x} 30, ${x} 70"/>`;
    }).join('');
    const cards = ag.map((a) => {
      const st = a.status;
      const stTxt = T('dash.status.' + st);
      const stCls = { running: 'c-blue', queued: 'c-amber', idle: 'faint', preview: 'c-amber', human: 'c-red' }[st] || '';
      let bubble = '';
      if (a.now) bubble = `<b>${esc(tafsirName(a.now.tafsir))} · <span class="mono">${esc(a.now.window)}</span></b><br><span class="faint">${T('dash.now')}…</span>`;
      else if (a.recent && a.recent[0]) {
        const r = a.recent[0];
        bubble = `<span class="faint mono">${esc(fTime(r.finished_at))}</span> ${esc(tafsirName(r.tafsir))} <span class="mono">${esc(r.window)}</span> · ${statusChip(r.status)}`;
        if (r.result && r.result.moves != null) bubble += `<br>${T('dash.moves')} ${r.result.moves} · ${T('dash.candidates')} ${r.result.auto_candidate}`;
      } else if (a.key === 'checker') bubble = `${T('dash.today')}: ${fNum(a.today.ok)} ${T('dash.ok')}`;
      else if (a.key === 'specialist') bubble = `${T('dash.today')}: ${fNum(a.today.n)} ${T('dash.decisions')} · ✓${fNum(a.today.approve)} ✎${fNum(a.today.needs_edit)} ✕${fNum(a.today.reject)}`;
      else bubble = `<span class="faint">${T('dash.nothing_running')}</span>`;
      return `<button class="agent ${a.key === sel.key ? 'sel' : ''}" data-act="sel-agent" data-k="${a.key}">${robot(a.color, st === 'running')}
        <span class="agent-name">${T('agent.' + a.key)}</span>
        <span class="agent-state ${stCls}"><span class="dot ${st === 'running' ? 'live' : ''}"></span>${stTxt}${a.next ? ` · ${T('dash.queue_steps', { n: a.next })}` : ''}</span>
        ${a.model ? `<span class="faint mono">${esc(a.model)}</span>` : ''}
        <span class="agent-bubble">${bubble}</span></button>`;
    }).join('');
    const llmModels = (llm.models || []).map((m) => `<span class="chip ${m.name === llm.classifier_model || m.name === llm.verifier_model ? 'ok' : ''} mono">${esc(m.name)}</span>`).join(' ');
    const inst = (name, ok) => ok ? `<span class="chip ok">${ico('check')} ${T('dash.installed')}</span>` : `<span class="chip bad">${T('dash.not_installed', { m: name })}</span>`;
    const p = d.progress;
    const tot = p.totals;
    const tafRows = p.tafsirs.map((r) => `<div class="tafsir-row"><b>${esc(r.name_ar)}</b>
        <div><div class="bar lg" title="${r.both}/${r.windows}"><i style="width:${pct(r.both, r.windows)}%"></i><i class="b" style="width:${pct(r.classifier - r.both, r.windows)}%"></i></div>
        <div class="faint mt-s">${T('dash.classified')} ${fNum(r.classifier)} · ${T('dash.both')} ${fNum(r.both)} · ${T('dash.committee')} ${fNum(r.committee)} · ${T('dash.candidates')} ${fNum(r.committee_candidates)} · ${T('dash.specialist')} ${fNum(r.committee_specialist)}</div></div>
        <span class="mono faint">${fNum(r.both)}/${fNum(r.windows)}</span></div>`).join('');
    const g = d.gates;
    const gate = (k, on) => `<div class="gate"><span>${T(k)}</span><span class="chip ${on ? 'ok' : 'warn'}">${ico(on ? 'check' : 'lock')} ${T(on ? 'gate.open' : 'gate.closed')}</span></div>`;
    const tasks = d.tasks.length ? d.tasks.map((x) => `<tr class="click" data-href="#/tasks/${x.id}"><td class="mono">#${x.id}</td><td style="min-width:200px">${esc(x.title_ar)}</td>
        <td>${statusChip(x.status)}</td><td class="hide-sm" style="min-width:120px"><div class="bar"><i style="width:${pct(x.done_steps + x.skipped_steps, x.total_steps)}%"></i><i class="r" style="width:${pct(x.failed_steps, x.total_steps)}%"></i></div></td>
        <td class="num">${fNum(x.done_steps + x.skipped_steps)}/${fNum(x.total_steps)}</td></tr>`).join('')
      : `<tr><td colspan="5" class="empty">${T('tasks.empty')}</td></tr>`;
    const detail = agentDetail(sel, d);
    const sampleBtn = has('run_tasks') ? `<button class="btn primary" data-act="run-sample">${ico('play')} ${T('dash.start_sample')} <span class="mono">${esc(d.sample_ayah)}</span></button>` : '';
    return `${head('dash.title', 'dash.subtitle', `<span class="chip ${llm.reachable ? 'ok' : 'bad'}"><span class="dot ${llm.reachable ? 'live' : ''}"></span>${llm.reachable ? 'live' : 'offline'} · ${esc(fTime(d.server_time))}</span>
        <button class="btn" data-act="probe">${ico('refresh')} ${T('dash.probe')}</button>${sampleBtn}`)}
      <section class="card mission">
        <div class="brain"><div class="brain-orb ${llm.reachable ? '' : 'off'} ${busy ? 'busy' : ''}">${ico('brain')}</div>
          <div class="brain-meta"><div class="kicker">${T('dash.llm_layer')} · ${esc(llm.runtime || '')}</div>
            <div class="m">${esc(llm.classifier_model || '')} <span class="faint">+</span> ${esc(llm.verifier_model || '')}</div>
            <div class="faint"><span class="mono">${esc(llm.base_url || '')}</span> · ${llm.reachable ? `<span class="c-green">${T('dash.reachable')}</span>` : `<span style="color:var(--danger)">${T('dash.unreachable')}</span>`}${llm.version ? ` · v${esc(llm.version)}` : ''} · ${busy ? `<span class="c-green">${T('dash.brain_busy')}</span>` : T('dash.brain_idle')}</div></div></div>
        <svg class="wires" viewBox="0 0 1000 70" preserveAspectRatio="none" aria-hidden="true">${wires}</svg>
        <div class="agents">${cards}</div>
      </section>
      <section class="card mt">${detail}</section>
      <div class="grid g3 mt">
        <section class="card span2"><div class="card-h"><div><h2>${T('dash.progress')}</h2><div class="faint">${T('dash.caption_counts')}</div></div><a class="btn sm" href="#/progress">${T('nav.progress')} ${ico('arrow')}</a></div>
          <div class="grid g4 mb">
            <div><div class="kicker">${T('dash.windows')}</div><div class="stat">${fNum(tot.windows)}</div></div>
            <div><div class="kicker">${T('dash.classified')}</div><div class="stat">${fNum(tot.classifier)}<small> / ${fNum(tot.windows)}</small></div></div>
            <div><div class="kicker">${T('dash.both')}</div><div class="stat">${fNum(tot.both)}</div></div>
            <div><div class="kicker">${T('dash.committee')}: ${T('dash.candidates')} · ${T('dash.specialist')}</div><div class="stat">${fNum(tot.committee_candidates)}<small> · ${fNum(tot.committee_specialist)}</small></div></div>
          </div>${tafRows}</section>
        <section class="card"><div class="card-h"><h2>${T('dash.gates')}</h2>${has('manage_settings') ? `<a class="btn sm" href="#/settings/gates">${ico('gear')}</a>` : ''}</div>
          ${gate('gate.phase0', g.phase0_merged)}${gate('gate.sample', g.sample_reviewed)}
          <p class="faint mt-s">${T('gate.bulk_rule')}</p>
          <div class="mt"><div class="kicker">${T('dash.models_on_host')}</div><div class="row mt-s">${llmModels || `<span class="faint">—</span>`}</div>
          <div class="stack mt-s"><div class="row"><span class="faint">${T('agent.classifier')}:</span>${inst(llm.classifier_model, llm.classifier_installed)}</div>
          <div class="row"><span class="faint">${T('agent.verifier')}:</span>${inst(llm.verifier_model, llm.verifier_installed)}</div></div></div></section>
      </div>
      <section class="mt"><div class="card-h"><h2>${T('dash.recent_tasks')}</h2><a class="btn sm" href="#/tasks">${T('nav.tasks')} ${ico('arrow')}</a></div>
        <div class="table-wrap"><table class="t"><tbody>${tasks}</tbody></table></div></section>`;
  }
  function agentDetail(a, d) {
    const did = (a.recent || []).map((r) => `<div class="ev"><span class="tm">${esc(fTime(r.finished_at))}</span><span>${esc(tafsirName(r.tafsir))} <span class="mono">${esc(r.window)}</span> · ${statusChip(r.status)}
      ${r.result && r.result.moves != null ? `<span class="faint">${T('dash.moves')} ${r.result.moves} · ${T('dash.candidates')} ${r.result.auto_candidate} · ${T('dash.flags')} ${r.result.flags}</span>` : ''}
      <span class="faint">· ${fDur(r.duration_ms)}</span></span></div>`).join('') || `<p class="faint">—</p>`;
    let now = `<p class="big-next" style="font-size:20px">${T('dash.nothing_running')}</p>`;
    if (a.now) now = `<p class="big-next" style="font-size:20px;color:var(--accent-text)">${esc(tafsirName(a.now.tafsir))} · <span class="mono">${esc(a.now.window)}</span></p><p class="faint">${esc(a.now.title_ar || '')}</p><p class="faint">${T('dash.model')}: <span class="mono">${esc(a.now.model || '')}</span></p>`;
    else if (!['classifier', 'verifier', 'chair'].includes(a.key)) now = `<p class="muted">${T('agent.' + a.key + '.desc')}</p>`;
    let next;
    if (a.next) next = `<p class="big-next">${T('dash.queue_steps', { n: a.next })}</p>`;
    else if (a.key === 'specialist') next = `<a class="btn outline-accent" href="#/review">${ico('review')} ${T('nav.review')}</a>`;
    else next = has('run_tasks') ? `<button class="btn outline-accent" data-act="new-task">${ico('plus')} ${T('tasks.new')}</button>` : '<p class="faint">—</p>';
    const td = a.today || {};
    let today = '';
    if (['classifier', 'verifier', 'chair'].includes(a.key)) today = `${T('dash.today')}: ${fNum(td.ok)} ${T('dash.ok')} · ${fNum(td.bad)} ${T('dash.failed')}`;
    else if (a.key === 'checker') today = `${T('dash.today')}: ${fNum(td.ok)} ${T('dash.ok')}`;
    else if (a.key === 'specialist') today = `${T('dash.today')}: ${fNum(td.n)} ${T('dash.decisions')}`;
    return `<div class="card-h"><div class="row">${robot(a.color, a.status === 'running').replace('class="robot', 'style="width:40px;height:40px" class="robot')}
        <div><h2>${T('agent.' + a.key)}</h2><div class="faint">${T('agent.' + a.key + '.desc')}</div></div></div>
        <span class="faint">${today}${a.today && a.today.avg_ms ? ` · ${T('dash.avg')} ${fDur(Math.round(a.today.avg_ms))}` : ''}</span></div>
      <div class="agent-detail"><div class="card flat"><div class="kicker mb">${ico('check')} ${T('dash.last_runs')}</div>${did}</div>
        <div class="card flat"><div class="kicker mb">${T('dash.now')}</div>${now}</div>
        <div class="card flat"><div class="kicker mb">${T('dash.next')}</div>${next}</div></div>`;
  }

  // ------------------------------------------------------------ tasks
  async function viewTasks() {
    const load = async () => {
      const d = await api('/tasks');
      const rows = d.tasks.length ? d.tasks.map((x) => `<tr class="click" data-href="#/tasks/${x.id}">
          <td class="mono">#${x.id}</td><td>${esc(x.title_ar)}${x.params.bulk ? ` <span class="chip warn">${T('tasks.bulk')}</span>` : ''}</td>
          <td>${statusChip(x.status)}</td><td style="min-width:140px"><div class="bar"><i style="width:${pct(x.done_steps + x.skipped_steps, x.total_steps)}%"></i><i class="r" style="width:${pct(x.failed_steps, x.total_steps)}%"></i></div></td>
          <td class="num">${fNum(x.done_steps)}✓ ${x.failed_steps ? `${fNum(x.failed_steps)}✕ ` : ''}${x.skipped_steps ? `${fNum(x.skipped_steps)}↷ ` : ''}/ ${fNum(x.total_steps)}</td>
          <td class="hide-sm">${esc(x.created_by_name || '')}</td><td class="num hide-sm">${esc(fDT(x.created_at))}</td></tr>`).join('')
        : `<tr><td colspan="7" class="empty">${T('tasks.empty')}</td></tr>`;
      setPage(`${head('tasks.title', 'tasks.subtitle', has('run_tasks') ? `<button class="btn primary" data-act="new-task">${ico('plus')} ${T('tasks.new')}</button>` : '')}
        <div class="table-wrap"><table class="t"><thead><tr><th>#</th><th>${T('tasks.kind')}</th><th>${T('common.status')}</th><th>${T('tasks.steps')}</th><th></th><th class="hide-sm">${T('tasks.created_by')}</th><th class="hide-sm">${T('common.created')}</th></tr></thead><tbody>${rows}</tbody></table></div>`);
    };
    await load();
    every(4000, () => { if (!$('.modal')) load().catch(() => {}); });
  }

  function newTaskModal(preset = {}) {
    const sample = '24:35';
    const kinds = ['committee', 'classifier', 'verifier', 'chair', 'dryrun'];
    const taf = ['al_tabari', 'ibn_kathir', 'al_baghawi', 'al_saadi'];
    const m = modal(`${modalHead(t('tasks.new'))}
      <form id="f-task" class="stack">
        <div class="field"><span class="label">${T('tasks.kind')}</span>
          <div class="stack">${kinds.map((k) => `<label class="check"><input type="radio" name="kind" value="${k}" ${k === (preset.kind || 'committee') ? 'checked' : ''}><span>${T('kind.' + k)}</span></label>`).join('')}</div></div>
        <div class="field"><span class="label">${T('tasks.scope')}</span>
          <div class="seg" role="radiogroup">${['sample', 'ayat', 'surah'].map((s) => `<button type="button" data-scope="${s}" class="${s === (preset.scope || 'sample') ? 'on' : ''}">${T('scope.' + s, { a: sample })}</button>`).join('')}</div></div>
        <div class="field" id="ayat-f" style="display:none"><label for="ayat">${T('tasks.ayat')}</label><input class="input ltr" id="ayat" placeholder="${T('tasks.ayat_ph')}"></div>
        <div class="field"><span class="label">${T('tasks.tafsirs')}</span>
          <div class="perm-grid">${taf.map((x) => `<label class="check"><input type="checkbox" name="taf" value="${x}" checked><span>${esc(tafsirName(x))}</span></label>`).join('')}</div></div>
        <label class="check"><input type="checkbox" id="skip" checked><span>${T('tasks.skip_done')}</span></label>
        <div id="task-preview" class="notice"><div class="spinner sm"></div></div>
        <div class="form-actions"><button type="button" class="btn" data-act="close-modal">${T('common.cancel')}</button>
          <button type="submit" class="btn primary" id="task-go">${ico('play')} ${T('tasks.run')}</button></div>
      </form>`);
    let scope = preset.scope || 'sample';
    const body = () => ({ kind: $('input[name=kind]:checked', m).value, scope, ayat: $('#ayat', m).value,
      tafsirs: $$('input[name=taf]:checked', m).map((x) => x.value), skip_done: $('#skip', m).checked });
    let seq = 0;
    const preview = async () => {
      const my = ++seq;
      $('#ayat-f', m).style.display = scope === 'ayat' ? '' : 'none';
      const box = $('#task-preview', m);
      try {
        const p = await api('/tasks/preview', { method: 'POST', body: body() });
        if (my !== seq) return;
        const per = Object.entries(p.per_tafsir).map(([k, v]) => `${tafsirName(k)} ${v}`).join(' · ');
        box.className = 'notice ' + (p.blocked ? 'bad' : p.bulk ? 'warn' : 'ok');
        box.innerHTML = `${ico(p.blocked ? 'lock' : 'info')}<span><b>${T('tasks.preview', { steps: fNum(p.steps), windows: fNum(p.windows) })}</b><br><span class="faint">${esc(per)}</span>
          <br><span class="faint">${T('agent.classifier')}: <span class="mono">${esc(p.models.classifier)}</span> · ${T('agent.verifier')}: <span class="mono">${esc(p.models.verifier)}</span></span>
          ${p.blocked ? `<br><b>${T('tasks.err.' + p.blocked)}</b>` : ''}</span>`;
        $('#task-go', m).disabled = !!p.blocked;
      } catch (e) {
        if (my !== seq) return;
        box.className = 'notice bad'; box.innerHTML = `${ico('warn')}<span>${esc(errText(e))}</span>`; $('#task-go', m).disabled = true;
      }
    };
    m.addEventListener('click', (e) => {
      const s = e.target.closest('[data-scope]');
      if (s) { scope = s.dataset.scope; $$('[data-scope]', m).forEach((b) => b.classList.toggle('on', b === s)); preview(); }
    });
    m.addEventListener('change', preview);
    let deb; $('#ayat', m).addEventListener('input', () => { clearTimeout(deb); deb = setTimeout(preview, 350); });
    $('#f-task', m).addEventListener('submit', async (e) => {
      e.preventDefault();
      try { const r = await api('/tasks', { method: 'POST', body: body() }); closeModal(); location.hash = '#/tasks/' + r.id; }
      catch (err) { toast(errText(err), 'bad'); }
    });
    preview();
  }

  async function viewTask(id) {
    const load = async () => {
      const d = await api('/tasks/' + id);
      const x = d.task;
      const agentName = (a) => T('agent.' + a);
      const rows = d.steps.map((s) => `<tr class="click" data-act="step" data-id="${s.id}"><td class="num">${s.seq + 1}</td><td>${agentName(s.agent)}</td><td>${esc(tafsirName(s.tafsir))}</td>
        <td class="mono">${esc(s.window)}</td><td class="mono hide-sm">${esc(s.model || '—')}</td><td>${statusChip(s.status)}</td><td class="num">${fDur(s.duration_ms)}</td>
        <td class="hide-sm">${s.result && s.result.moves != null ? `${T('dash.moves')} ${s.result.moves} · ${T('dash.candidates')} ${s.result.auto_candidate} · ${T('dash.specialist')} ${s.result.specialist}` : s.result && s.result.spans != null ? `spans ${s.result.spans}` : ''}</td></tr>`).join('');
      const actions = [
        has('manage_tasks') && ['queued', 'running'].includes(x.status) ? `<button class="btn danger" data-act="cancel-task" data-id="${x.id}">${ico('stop')} ${T('tasks.cancel')}</button>` : '',
        has('run_tasks') && x.failed_steps && !['queued', 'running'].includes(x.status) ? `<button class="btn warn" data-act="retry-task" data-id="${x.id}">${ico('refresh')} ${T('tasks.retry')}</button>` : '',
        `<a class="btn" href="#/tasks">${T('common.back')}</a>`].join('');
      const done = x.done_steps + x.skipped_steps;
      S.taskSteps = d.steps;
      setPage(`<div class="page-head"><div><div class="kicker">#${x.id}</div><h1>${esc(x.title_ar)}</h1>
          <p class="muted">${statusChip(x.status)} · ${T('tasks.created_by')} ${esc(x.created_by_name || '—')} · ${esc(fDT(x.created_at))}</p></div><div class="head-actions">${actions}</div></div>
        <section class="card mb"><div class="row between"><b>${fNum(done)} / ${fNum(x.total_steps)}</b><span class="faint">${fNum(x.failed_steps)} ${T('dash.failed')} · ${fNum(x.skipped_steps)} ${T('tasks.status.skipped')}</span></div>
          <div class="bar lg mt-s"><i style="width:${pct(done, x.total_steps)}%"></i><i class="r" style="width:${pct(x.failed_steps, x.total_steps)}%"></i></div>
          <p class="faint mt-s">${T('agent.classifier')}: <span class="mono">${esc((x.params.models || {}).classifier || '')}</span> · ${T('agent.verifier')}: <span class="mono">${esc((x.params.models || {}).verifier || '')}</span></p></section>
        <div class="table-wrap"><table class="t"><thead><tr><th>${T('tasks.step')}</th><th>${T('tasks.agent')}</th><th>${T('tasks.tafsir')}</th><th>${T('tasks.window')}</th><th class="hide-sm">${T('tasks.model')}</th><th>${T('common.status')}</th><th>${T('tasks.duration')}</th><th class="hide-sm">${T('tasks.result')}</th></tr></thead><tbody>${rows}</tbody></table></div>`);
      return x.status;
    };
    const st = await load();
    if (['queued', 'running'].includes(st)) every(3000, () => { if (!$('.modal')) load().catch(() => {}); });
  }
  function stepModal(sid) {
    const s = (S.taskSteps || []).find((x) => String(x.id) === String(sid));
    if (!s) return;
    modal(`${modalHead(`${t('agent.' + s.agent)} · ${tafsirName(s.tafsir)} ${s.window}`)}
      <div class="kv"><div><div class="k">${T('common.status')}</div><div class="v">${statusChip(s.status)}</div></div>
        <div><div class="k">${T('tasks.model')}</div><div class="v mono">${esc(s.model || '—')}</div></div>
        <div><div class="k">${T('tasks.duration')}</div><div class="v">${fDur(s.duration_ms)}</div></div>
        <div><div class="k">exit</div><div class="v mono">${esc(s.exit_code ?? '—')}</div></div></div>
      <div class="label mb">${T('tasks.output')}</div><pre class="out">${esc(s.output_tail || '—')}</pre>
      ${s.status === 'done' && s.agent !== 'packet_check' ? `<div class="form-actions"><a class="btn outline-accent" href="#/review/${esc(s.tafsir)}/${esc(s.window)}">${ico('review')} ${T('nav.review')}</a></div>` : ''}`, { wide: true });
  }

  // ------------------------------------------------------------ progress
  async function viewProgress() {
    const d = await api('/progress');
    const cols = d.matrix.columns;
    const sampleN = 35;
    const cells = d.matrix.rows.map((r) => `<div class="ma">${r.ayah_number}</div>` + cols.map((c) => {
      const x = r.cells[c.tafsir] || { status: 'none', windows: 0 };
      return `<div class="cell ${x.status} ${r.ayah_number === sampleN ? 'sample' : ''}" title="${esc(c.name_ar)} ${r.ayah_number} · ${x.committee || 0}/${x.windows}">${x.windows > 1 ? x.windows : ''}</div>`;
    }).join('')).join('');
    const p = d.progress;
    const cards = p.tafsirs.map((r) => `<div class="card"><div class="kicker">${esc(r.name_ar)}</div><div class="stat">${fNum(r.both)}<small> / ${fNum(r.windows)}</small></div>
      <div class="bar mt-s"><i style="width:${pct(r.both, r.windows)}%"></i><i class="b" style="width:${pct(r.classifier - r.both, r.windows)}%"></i></div>
      <p class="faint mt-s">${fNum(r.ayat)} ${T('dash.ayat')} · ${T('dash.moves')} ${fNum(r.moves)} · ${T('dash.flags')} ${fNum(r.flags)}</p></div>`).join('');
    setPage(`${head('progress.title', 'progress.subtitle')}<div class="grid g4 mb">${cards}</div>
      <section class="card"><div class="card-h"><div><h2>${T('progress.matrix')}</h2><div class="faint">${T('dash.caption_counts')} · <span class="mono">${esc(p.models.classifier)}</span> + <span class="mono">${esc(p.models.verifier)}</span></div></div>
        <div class="legend">${['none', 'partial', 'classifier', 'both', 'committee'].map((k) => `<span><i class="cell ${k}"></i>${T('progress.legend.' + k)}</span>`).join('')}</div></div>
        <div class="matrix"><div class="mh">${T('progress.ayah')}</div>${cols.map((c) => `<div class="mh">${esc(c.name_ar)}</div>`).join('')}${cells}</div></section>`);
  }

  // ------------------------------------------------------------ reports
  async function viewReports() {
    const d = await api('/reports');
    const rows = d.reports.length ? d.reports.map((r) => `<tr class="click" data-href="#/reports/${r.day}"><td class="mono">${esc(r.day)}</td>
      <td class="num">${fNum((r.steps || {}).done)}✓ ${fNum((r.steps || {}).failed)}✕</td>
      <td class="num">${fNum((r.routes || {}).moves)} · ${fNum((r.routes || {}).auto_candidate)} · ${fNum((r.routes || {}).specialist)}</td>
      <td>${r.mailed_at ? `<span class="chip ok">${ico('mail')} ${T('reports.mailed')}</span>` : `<span class="chip">${T('reports.not_mailed')}</span>`}</td>
      <td class="num hide-sm">${esc(fDT(r.generated_at))}</td></tr>`).join('') : `<tr><td colspan="5" class="empty">${T('reports.empty')}</td></tr>`;
    setPage(`${head('reports.title', 'reports.subtitle', has('generate_reports') ? `<button class="btn primary" data-act="gen-report" data-day="${d.today}">${ico('report')} ${T('reports.generate_today')}</button>` : '')}
      <div class="table-wrap"><table class="t"><thead><tr><th>${T('audit.when')}</th><th>${T('reports.steps')}</th><th>${T('dash.moves')} · ${T('dash.candidates')} · ${T('dash.specialist')}</th><th>${T('common.status')}</th><th class="hide-sm">${T('common.created')}</th></tr></thead><tbody>${rows}</tbody></table></div>`);
  }
  async function viewReport(day) {
    const d = await api('/reports/' + day);
    const c = d.content;
    const agents = Object.entries(c.agents).map(([k, v]) => `<tr><td>${T('agent.' + k)}</td><td class="num">${fNum(v.done)}</td><td class="num">${fNum(v.failed)}</td><td class="num">${fNum(v.skipped)}</td><td class="mono">${esc(v.models.join(', ') || '—')}</td><td class="num">${v.avg_s != null ? v.avg_s + ' ' + T('common.seconds') : '—'}</td></tr>`).join('')
      || `<tr><td colspan="6" class="empty">—</td></tr>`;
    const wins = Object.entries(c.windows_by_tafsir).map(([k, v]) => `<span class="chip">${esc(tafsirName(k))} ${fNum(v)}</span>`).join(' ') || '<span class="faint">—</span>';
    const fails = c.failures.map((f) => `<div class="ev"><span class="tm">#${f.task_id}</span><span>${T('agent.' + f.agent)} · ${esc(tafsirName(f.tafsir))} <span class="mono">${esc(f.window)}</span> · <span class="mono faint">${esc(f.last_line)}</span></span></div>`).join('');
    const acts = [
      `<a class="btn" href="/api/reports/${esc(day)}/markdown">${ico('download')} ${T('common.download')} .md</a>`,
      has('generate_reports') ? `<button class="btn" data-act="gen-report" data-day="${esc(day)}">${ico('refresh')} ${T('reports.regenerate')}</button>` : '',
      has('generate_reports') ? `<button class="btn primary" data-act="mail-report" data-day="${esc(day)}">${ico('mail')} ${T('reports.mail')}</button>` : '',
      `<a class="btn" href="#/reports">${T('common.back')}</a>`].join('');
    setPage(`<div class="page-head"><div><div class="kicker">${T('reports.title')}</div><h1 class="ltr" style="text-align:start">${esc(c.day)}</h1>
        <p class="muted">${d.mailed_at ? `${T('reports.mailed')} ${esc(fDT(d.mailed_at))}` : T('reports.not_mailed')} · ${T('reports.content_ar_note')}</p></div><div class="head-actions">${acts}</div></div>
      <div class="grid g4 mb">
        <div class="card"><div class="kicker">${T('reports.steps')}</div><div class="stat">${fNum(c.steps.done)}<small> / ${fNum(c.steps.total)}</small></div><p class="faint">${fNum(c.steps.failed)} ${T('dash.failed')} · ${fNum(c.steps.skipped)} ${T('tasks.status.skipped')}</p></div>
        <div class="card"><div class="kicker">${T('reports.routes')}</div><div class="stat">${fNum(c.routes.auto_candidate)}<small> · ${fNum(c.routes.specialist)}</small></div><p class="faint">${esc(c.routes_caption_ar)}</p></div>
        <div class="card"><div class="kicker">${T('reports.decisions')}</div><div class="stat">${fNum(c.decisions.n)}</div><p class="faint">✓${fNum(c.decisions.approve)} ✎${fNum(c.decisions.needs_edit)} ✕${fNum(c.decisions.reject)}</p></div>
        <div class="card"><div class="kicker">${T('reports.cumulative')}</div><div class="stat">${fNum(c.progress.both)}<small> / ${fNum(c.progress.windows)}</small></div><p class="faint">${T('dash.classified')} ${fNum(c.progress.classifier)}</p></div>
      </div>
      <section class="card mb"><div class="card-h"><h2>${T('reports.agents')}</h2></div><div class="table-wrap"><table class="t"><thead><tr><th>${T('tasks.agent')}</th><th>${T('dash.ok')}</th><th>${T('dash.failed')}</th><th>${T('tasks.status.skipped')}</th><th>${T('tasks.model')}</th><th>${T('dash.avg')}</th></tr></thead><tbody>${agents}</tbody></table></div>
        <div class="mt"><div class="kicker mb">${T('reports.windows_today')}</div><div class="row">${wins}</div></div></section>
      ${c.committee && c.committee.windows ? `<section class="card mb"><h2>${T('review.committee')}</h2><p class="mt-s">${T('dash.windows')} ${fNum(c.committee.windows)} · ${T('dash.moves')} ${fNum(c.committee.moves)} · ${T('dash.candidates')} ${fNum(c.committee.auto_candidate)} · ${T('dash.specialist')} ${fNum(c.committee.specialist)}</p>
        <div class="row mt-s">${Object.entries(c.committee.reasons || {}).filter(([, v]) => v).map(([k, v]) => `<span class="chip violet">${T('review.reason.' + k)} ${fNum(v)}</span>`).join('')}</div></section>` : ''}
      ${c.perf ? perfHTML(c.perf) : ''}
      <div class="grid g2">
        <section class="card"><h2>${T('reports.next')}</h2><ul class="mt-s">${(c.next_ar || []).map((x) => `<li dir="rtl">${esc(x)}</li>`).join('') || '<li>—</li>'}</ul></section>
        <section class="card"><h2>${T('reports.failures')}</h2>${fails || '<p class="faint mt-s">—</p>'}</section></div>`);
  }

  // ------------------------------------------------------------ review
  async function viewReview() {
    const d = await api('/review/units');
    const rows = d.units.length ? d.units.map((u) => `<tr class="click" data-href="#/review/${u.tafsir}/${u.window}"><td class="mono">${esc(u.ayah)}</td><td>${esc(u.name_ar)}</td>
      <td class="mono">${esc(u.window)} ${u.committee ? `<span class="chip violet">${T('dash.committee')}</span>` : ''}</td><td class="num">${fNum(u.moves)}</td><td class="num">${fNum(u.auto_candidate)}</td><td class="num">${fNum(u.specialist)}</td>
      <td class="num hide-sm">${u.flags == null ? '—' : fNum(u.flags)}</td><td class="num">${u.decided ? `<span class="chip ok">${fNum(u.decided)}/${fNum(u.moves)}</span>` : `<span class="chip">0/${fNum(u.moves)}</span>`}</td></tr>`).join('')
      : `<tr><td colspan="8" class="empty">${T('review.empty')}</td></tr>`;
    setPage(`${head('review.title', 'review.subtitle', has('review_units') ? `<a class="btn" href="/api/review/export">${ico('download')} ${T('review.export')}</a>` : '')}
      <p class="faint mb">${T('agent.classifier')}: <span class="mono">${esc(d.models.classifier)}</span> · ${T('dash.caption_counts')}</p>
      <div class="table-wrap"><table class="t"><thead><tr><th>${T('progress.ayah')}</th><th>${T('tasks.tafsir')}</th><th>${T('tasks.window')}</th><th>${T('dash.moves')}</th><th>${T('dash.candidates')}</th><th>${T('dash.specialist')}</th><th class="hide-sm">${T('dash.flags')}</th><th>${T('review.decided')}</th></tr></thead><tbody>${rows}</tbody></table></div>`);
  }
  async function viewReviewWindow(tafsir, win) {
    const d = await api(`/review/${encodeURIComponent(tafsir)}/${encodeURIComponent(win)}`);
    const preview = {};
    (d.chair ? d.chair.moves : []).forEach((c) => { preview[c.move_id] = c; });
    const canDecide = has('review_units');
    const reasonChip = (code) => code ? `<span class="chip warn mono" title="${T('review.verifier_reason')}">${esc(code)}</span>` : '';
    const moves = d.moves.map((m) => {
      const c = m.committee;
      const p = preview[m.move_id];
      const dec = m.decision;
      const score = (m.score || {}).total;
      let chairChip = '';
      if (c) chairChip = `<span class="chip ${c.committee_route === 'auto_candidate' ? 'ok' : 'violet'}">${T('review.committee')}: ${c.committee_route === 'auto_candidate' ? T('route.auto_candidate') : T('review.reason.' + ((c.abstention_reasons || [])[0] || 'weak_evidence'))}</span>`;
      else if (p) chairChip = `<span class="chip ${p.committee_route === 'auto_candidate' ? 'ok' : 'violet'}" title="${T('review.chair_note')}">${T('review.chair')}: ${p.reason ? T('review.reason.' + p.reason) : T('route.auto_candidate')}</span>`;
      const agents = c ? `<div class="kv"><div><div class="k">${T('agent.classifier')}</div><div class="v mono">${esc(c.primary_proposer || '—')} · ${c.score_proposer ?? '—'}</div></div>
          <div><div class="k">${T('agent.verifier')}</div><div class="v mono">${esc(c.primary_reviewer || '—')} · ${c.score_reviewer ?? '—'}</div></div>
          <div><div class="k">${T('review.certainty')}</div><div class="v">${esc(m.certainty || '—')}</div></div>
          <div><div class="k">${T('review.flags')}</div><div class="v mono" style="font-size:12px">${esc((m.flags || []).join(', ') || '—')}</div></div></div>`
        : `<div class="kv"><div><div class="k">${T('review.primary')}</div><div class="v mono">${esc(m.primary || '—')}</div></div>
          <div><div class="k">${T('review.certainty')}</div><div class="v">${esc(m.certainty || '—')}</div></div>
          <div><div class="k">${T('review.score')}</div><div class="v">${score ?? '—'}</div></div>
          <div><div class="k">${T('review.flags')}</div><div class="v mono" style="font-size:12px">${esc((m.flags || []).join(', ') || '—')}</div></div></div>`;
      return `<article class="move" data-move="${esc(m.key)}">
        <div class="row between"><div class="row"><b class="mono">${esc(m.key)}</b><span class="chip ${m.route === 'auto_candidate' ? 'ok' : 'warn'}">${T('route.' + (m.route || 'specialist'))}</span>
          ${chairChip}${reasonChip(m.reason_code)}</div>
          ${dec ? `<span class="chip ${dec.decision === 'approve' ? 'ok' : dec.decision === 'reject' ? 'bad' : 'warn'}">${T('review.decision.' + dec.decision)} · ${esc(dec.user_name)} · ${esc(fDT(dec.created_at))}</span>` : ''}</div>
        ${agents}
        ${c && c.abstention_ar ? `<p class="faint mb" dir="rtl">${esc(c.abstention_ar)}</p>` : ''}
        <div class="label mb">${T('review.text')} <span class="faint mono">${esc((m.span_ids || []).join(' '))}</span></div>
        <div class="move-text">${esc(m.text || '')}</div>
        ${m.rationale_ar ? `<p class="faint mt-s"><b>${T('review.rationale')}</b> (${T('review.rationale_note')}): <span dir="rtl">${esc(m.rationale_ar)}</span></p>` : ''}
        ${canDecide ? `<div class="decide"><div class="stack"><label class="check"><input type="checkbox" data-compare><span>${T('review.compare')}</span></label>
            <input class="input" data-note placeholder="${T('review.note_ph')}" maxlength="1000"></div>
          <div class="row"><button class="btn primary" data-act="decide" data-d="approve">${ico('check')} ${T('review.approve')}</button>
            <button class="btn warn" data-act="decide" data-d="needs_edit">${T('review.needs_edit')}</button>
            <button class="btn danger" data-act="decide" data-d="reject">${ico('x')} ${T('review.reject')}</button></div></div>` : ''}
      </article>`;
    }).join('') || `<div class="empty">${T('common.empty')}</div>`;
    const sum = d.summary || {};
    const reasons = Object.entries(sum.by_abstention_reason || {}).filter(([, v]) => v).map(([k, v]) => `<span class="chip violet">${T('review.reason.' + k)} ${fNum(v)}</span>`).join(' ');
    const mdl = d.models ? `${T('agent.classifier')}: <span class="mono">${esc((d.models.proposer || {}).tag || '')}</span> · ${T('agent.verifier')}: <span class="mono">${esc((d.models.reviewer || {}).tag || '')}</span>` : '';
    S.reviewCtx = { tafsir, win };
    setPage(`<div class="page-head"><div><div class="kicker">${T('review.title')}</div><h1>${esc(d.name_ar)} · <span class="mono">${esc(d.window)}</span></h1>
        <p class="muted">${T('progress.ayah')} <span class="mono">${esc(d.ayah)}</span> · ${T('review.source')}: <span class="mono">${esc(d.source_file)}</span> · sha256 <span class="mono">${esc((d.source_sha256 || '').slice(0, 12))}…</span></p></div>
        <div class="head-actions"><a class="btn" href="#/review">${T('common.back')}</a></div></div>
      ${canDecide ? '' : `<div class="notice mb">${ico('info')}<span>${T('review.read_only')}</span></div>`}
      <div class="notice mb">${ico('shield')}<span>${T('review.subtitle')} ${d.is_committee ? T('review.committee_note') : T('review.chair_note')}</span></div>
      ${d.is_committee ? `<section class="card mb"><div class="row between"><div class="row"><b>${T('review.committee')}</b> ${mdl}</div>
        <span class="faint">${T('dash.moves')} ${fNum(sum.move_count)} · ${T('dash.candidates')} ${fNum(sum.auto_candidate)} · ${T('dash.specialist')} ${fNum(sum.specialist)} · ${esc(sum.caption || '')}</span></div>
        ${reasons ? `<div class="row mt-s">${reasons}</div>` : ''}</section>` : ''}
      ${moves}`);
  }

  // ------------------------------------------------------------ calls & audit
  function perfHTML(pf) {
    if (!pf.agents.length) return '';
    const cards = pf.agents.map((a) => `<div class="card"><div class="kicker">${T('agent.' + a.agent)}${a.model ? ` · <span class="mono">${esc(a.model)}</span>` : ''}</div>
      <div class="stat">${a.median_s ?? '—'}<small> ${T('common.seconds')} · ${T('perf.median')}</small></div>
      <p class="faint mt-s">${T('perf.p95')} ${a.p95_s ?? '—'} · ${T('perf.max')} ${a.max_s ?? '—'} ${T('common.seconds')}</p>
      <p class="faint">${fNum(a.ok)}/${fNum(a.n)} ${T('dash.ok')}${a.failed ? ` · <span style="color:var(--danger)">${fNum(a.failed)} ${T('dash.failed')}</span>` : ''}${a.chars_per_s ? ` · ${fNum(a.chars_per_s)} ${T('perf.chars_per_s')}` : ''}</p>
      <p class="faint">${a.moves_per_window != null ? `${T('perf.moves_per_window')} ${a.moves_per_window} · ` : ''}${T('dash.candidates')} ${fNum(a.auto_candidate)}</p>
      ${Object.keys(a.failure_codes || {}).length ? `<div class="row mt-s">${Object.entries(a.failure_codes).map(([k, v]) => `<span class="chip bad mono">${esc(k)} ${v}</span>`).join('')}</div>` : ''}
      ${a.eta_min != null ? `<p class="mt-s"><b>${T('perf.eta', { n: fNum(a.remaining_windows), m: fNum(a.eta_min) })}</b></p>` : ''}</div>`).join('');
    return `<section class="mb"><div class="card-h"><div><h2>${T('perf.title')}</h2><div class="faint">${esc(pf.caption_ar)} · ${T('perf.eta_note')}</div></div></div><div class="grid g3">${cards}</div></section>`;
  }
  async function viewCalls() {
    const [d, pf] = await Promise.all([api('/llm/calls'), api('/llm/perf')]);
    const rows = d.calls.length ? d.calls.map((c) => `<tr><td class="num">${esc(fDT(c.finished_at))}</td><td>${T('agent.' + c.agent)}</td><td class="mono">${esc(c.model || '')}</td>
      <td>${esc(tafsirName(c.tafsir))} <span class="mono">${esc(c.window)}</span></td><td>${statusChip(c.status)}</td><td class="num">${fDur(c.duration_ms)}</td>
      <td class="hide-sm">${c.result && c.result.moves != null ? `${c.result.moves} · ${c.result.auto_candidate} · ${c.result.specialist} · ${c.result.flags ?? '—'}` : c.result && c.result.reason_code ? `<span class="chip bad mono">${esc(c.result.reason_code)}</span>` : '—'}</td><td class="num"><a href="#/tasks/${c.task_id}">#${c.task_id}</a></td></tr>`).join('')
      : `<tr><td colspan="8" class="empty">${T('common.empty')}</td></tr>`;
    setPage(`${head('calls.title', 'calls.subtitle')}${perfHTML(pf)}<div class="table-wrap"><table class="t"><thead><tr><th>${T('audit.when')}</th><th>${T('tasks.agent')}</th><th>${T('tasks.model')}</th><th>${T('tasks.window')}</th><th>${T('common.status')}</th><th>${T('tasks.duration')}</th><th class="hide-sm">${T('dash.moves')} · ${T('dash.candidates')} · ${T('dash.specialist')} · ${T('dash.flags')}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`);
  }
  async function viewAudit() {
    const d = await api('/audit');
    const rows = d.audit.map((a) => `<tr><td class="num">${esc(fDT(a.at))}</td><td>${esc(a.user_name || '—')}</td><td class="mono">${esc(a.action)}</td><td class="mono">${esc(a.target || '')}</td>
      <td class="mono hide-sm" style="font-size:12px;max-width:380px;overflow-wrap:anywhere">${esc(a.detail ? JSON.stringify(a.detail) : '')}</td><td class="mono hide-sm">${esc(a.ip || '')}</td></tr>`).join('')
      || `<tr><td colspan="6" class="empty">${T('common.empty')}</td></tr>`;
    setPage(`${head('audit.title')}<div class="table-wrap"><table class="t"><thead><tr><th>${T('audit.when')}</th><th>${T('audit.who')}</th><th>${T('audit.action')}</th><th>${T('audit.target')}</th><th class="hide-sm">${T('common.details')}</th><th class="hide-sm">IP</th></tr></thead><tbody>${rows}</tbody></table></div>`);
  }

  // ------------------------------------------------------------ users
  let rolesCache = [];
  const roleName = (r) => (S.lang === 'ar' || S.lang === 'ur' ? r.name_ar : r.name_en);
  async function viewUsers() {
    const [u, r] = await Promise.all([api('/users'), api('/roles')]);
    rolesCache = r.roles;
    S.usersCache = u.users;
    const rows = u.users.map((x) => `<tr><td><div class="row"><span class="avatar">${esc(initials(x.name))}</span><div><b>${esc(x.name)}</b><div class="faint ltr" style="text-align:start">${esc(x.email)}</div></div></div></td>
      <td>${esc(S.lang === 'ar' || S.lang === 'ur' ? x.role_name_ar : x.role_name_en)}</td><td class="hide-sm">${esc(((S.pub.languages || []).find((l) => l.code === x.lang) || {}).name_native || t('users.lang_default'))}</td>
      <td>${x.active ? `<span class="chip ok">${T('common.active')}</span>` : `<span class="chip bad">${T('common.inactive')}</span>`}</td>
      <td class="num hide-sm">${x.last_login_at ? esc(fDT(x.last_login_at)) : T('common.never')}</td>
      <td class="num"><button class="btn sm" data-act="edit-user" data-id="${x.id}">${T('common.edit')}</button></td></tr>`).join('');
    setPage(`${head('users.title', 'users.subtitle', `<button class="btn primary" data-act="add-user">${ico('plus')} ${T('users.add')}</button>`)}
      <div class="table-wrap"><table class="t"><thead><tr><th>${T('users.name')}</th><th>${T('users.role')}</th><th class="hide-sm">${T('users.lang')}</th><th>${T('common.status')}</th><th class="hide-sm">${T('users.last_login')}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`);
  }
  function userModal(user) {
    const langs = (S.pub.languages || []).map((l) => `<option value="${esc(l.code)}" ${user && user.lang === l.code ? 'selected' : ''}>${esc(l.name_native)}</option>`).join('');
    const roles = rolesCache.map((r) => `<option value="${r.id}" ${user && user.role_id === r.id ? 'selected' : ''}>${esc(roleName(r))}</option>`).join('');
    const m = modal(`${modalHead(user ? t('common.edit') + ' · ' + user.name : t('users.add'))}
      <form id="f-user" class="form-grid">
        <div class="field full"><label for="u-email">${T('users.email')}</label><input class="input ltr" id="u-email" type="email" required value="${esc(user ? user.email : '')}" ${user ? 'disabled' : ''}></div>
        <div class="field"><label for="u-name">${T('users.name')}</label><input class="input" id="u-name" required maxlength="80" value="${esc(user ? user.name : '')}"></div>
        <div class="field"><label for="u-role">${T('users.role')}</label><select class="input" id="u-role">${roles}</select></div>
        <div class="field"><label for="u-lang">${T('users.lang')}</label><select class="input" id="u-lang"><option value="">${T('users.lang_default')}</option>${langs}</select></div>
        <div class="field"><span class="label">${T('common.status')}</span><label class="switch"><input type="checkbox" id="u-active" ${!user || user.active ? 'checked' : ''}><span>${T('common.active')}</span></label></div>
        <div class="form-actions full">${user ? `<button type="button" class="btn ghost" data-act="revoke-user" data-id="${user.id}">${T('users.revoke')}</button>` : ''}
          <button type="button" class="btn" data-act="close-modal">${T('common.cancel')}</button><button type="submit" class="btn primary">${T('common.save')}</button></div></form>`);
    $('#f-user', m).addEventListener('submit', async (e) => {
      e.preventDefault();
      const body = { name: $('#u-name', m).value.trim(), role_id: Number($('#u-role', m).value), lang: $('#u-lang', m).value, active: $('#u-active', m).checked };
      try {
        if (user) await api('/users/' + user.id, { method: 'PATCH', body });
        else await api('/users', { method: 'POST', body: { ...body, email: $('#u-email', m).value.trim() } });
        closeModal(); toast(t('common.saved'), 'ok'); render();
      } catch (err) { toast(errText(err), 'bad'); }
    });
  }

  // ------------------------------------------------------------ roles
  async function viewRoles() {
    const d = await api('/roles');
    rolesCache = d.roles;
    S.permList = d.permissions;
    const cards = d.roles.map((r) => `<section class="card"><div class="card-h"><div><h2>${esc(roleName(r))} ${r.system ? `<span class="chip warn">${ico('lock')} ${T('roles.system')}</span>` : ''}</h2>
        <div class="faint mono">${esc(r.key)} · ${fNum(r.users)} ${T('roles.users')}</div></div>
        ${r.system ? '' : `<div class="row"><button class="btn sm" data-act="edit-role" data-id="${r.id}">${T('common.edit')}</button><button class="btn sm danger" data-act="del-role" data-id="${r.id}">${T('common.delete')}</button></div>`}</div>
        <p class="muted" dir="rtl" style="text-align:start">${esc(r.description_ar)}</p>
        <div class="row mt-s">${r.permissions.map((p) => `<span class="chip ok">${T('perm.' + p)}</span>`).join('')}</div></section>`).join('');
    setPage(`${head('roles.title', 'roles.subtitle', `<button class="btn primary" data-act="add-role">${ico('plus')} ${T('roles.add')}</button>`)}<div class="grid g2">${cards}</div>`);
  }
  function roleModal(role) {
    const perms = (S.permList || []).map((p) => `<label class="check"><input type="checkbox" name="perm" value="${p}" ${role && role.permissions.includes(p) ? 'checked' : ''} ${has(p) ? '' : 'disabled'}><span>${T('perm.' + p)}</span></label>`).join('');
    const m = modal(`${modalHead(role ? t('common.edit') : t('roles.add'))}
      <form id="f-role" class="form-grid">
        <div class="field"><label for="r-key">${T('roles.key')}</label><input class="input ltr" id="r-key" required pattern="[a-z][a-z0-9_]{1,39}" value="${esc(role ? role.key : '')}" ${role ? 'disabled' : ''}></div>
        <div class="field"><label for="r-ar">${T('roles.name_ar')}</label><input class="input" dir="rtl" id="r-ar" required value="${esc(role ? role.name_ar : '')}"></div>
        <div class="field"><label for="r-en">${T('roles.name_en')}</label><input class="input ltr" id="r-en" required value="${esc(role ? role.name_en : '')}"></div>
        <div class="field full"><label for="r-desc">${T('roles.desc')}</label><input class="input" dir="rtl" id="r-desc" value="${esc(role ? role.description_ar : '')}"></div>
        <div class="field full"><span class="label">${T('roles.permissions')}</span><div class="perm-grid">${perms}</div></div>
        <div class="form-actions full"><button type="button" class="btn" data-act="close-modal">${T('common.cancel')}</button><button type="submit" class="btn primary">${T('common.save')}</button></div></form>`, { wide: true });
    $('#f-role', m).addEventListener('submit', async (e) => {
      e.preventDefault();
      const body = { name_ar: $('#r-ar', m).value.trim(), name_en: $('#r-en', m).value.trim(), description_ar: $('#r-desc', m).value.trim(),
        permissions: $$('input[name=perm]:checked', m).map((x) => x.value) };
      try {
        if (role) await api('/roles/' + role.id, { method: 'PATCH', body });
        else await api('/roles', { method: 'POST', body: { ...body, key: $('#r-key', m).value.trim() } });
        closeModal(); toast(t('common.saved'), 'ok'); render();
      } catch (err) { toast(errText(err), 'bad'); }
    });
  }

  // ------------------------------------------------------------ settings
  const TABS = ['general', 'llm', 'smtp', 'security', 'gates', 'reports', 'languages', 'outbox'];
  async function viewSettings(tab) {
    if (tab && TABS.includes(tab)) S.settingsTab = tab;
    const tabNav = `<div class="tabs" role="tablist">${TABS.filter((x) => x !== 'languages' || has('manage_languages')).map((x) => `<button role="tab" class="${x === S.settingsTab ? 'on' : ''}" data-act="tab" data-tab="${x}">${T('settings.tab.' + x)}</button>`).join('')}</div>`;
    setPage(`${head('settings.title', 'settings.subtitle')}${tabNav}<div id="tab-body">${loading()}</div>`);
    const body = $('#tab-body');
    const tabFn = { languages: tabLanguages, outbox: tabOutbox }[S.settingsTab] || tabSection;
    body.innerHTML = await tabFn(S.settingsTab);
    bindTab(S.settingsTab);
  }
  const fieldFor = (sec, key, val, opts = {}) => {
    const id = `s-${sec}-${key}`;
    const label = T(`set.${sec}.${key}`);
    if (typeof val === 'boolean') return `<div class="field ${opts.full ? 'full' : ''}"><label class="switch"><input type="checkbox" id="${id}" data-k="${key}" ${val ? 'checked' : ''}><span>${label}</span></label>${opts.hint ? `<span class="hint">${opts.hint}</span>` : ''}</div>`;
    if (opts.choices) return `<div class="field ${opts.full ? 'full' : ''}"><label for="${id}">${label}</label><select class="input" id="${id}" data-k="${key}">${opts.choices.map((c) => `<option value="${esc(c)}" ${c === val ? 'selected' : ''}>${T(`set.${sec}.${key}.${c}`)}</option>`).join('')}</select>${opts.hint ? `<span class="hint">${opts.hint}</span>` : ''}</div>`;
    const type = typeof val === 'number' ? 'number' : opts.type || 'text';
    return `<div class="field ${opts.full ? 'full' : ''}"><label for="${id}">${label}</label><input class="input ${opts.ltr ? 'ltr' : ''}" id="${id}" data-k="${key}" type="${type}" value="${esc(val)}" ${opts.list ? `list="${opts.list}"` : ''} ${opts.ph ? `placeholder="${esc(opts.ph)}"` : ''} autocomplete="off">${opts.hint ? `<span class="hint">${opts.hint}</span>` : ''}</div>`;
  };
  async function tabSection(sec) {
    const d = await api('/settings');
    S.settings = d.settings;
    const v = d.settings[sec];
    let fields = '';
    let extra = '';
    if (sec === 'general') {
      fields = fieldFor(sec, 'project_name', v.project_name) + fieldFor(sec, 'team_name', v.team_name) + fieldFor(sec, 'timezone', v.timezone, { ltr: true })
        + fieldFor(sec, 'surah', v.surah) + fieldFor(sec, 'data_root', v.data_root, { ltr: true }) + fieldFor(sec, 'sample_ayah', v.sample_ayah, { ltr: true });
    } else if (sec === 'llm') {
      let probe = null;
      try { probe = await api('/llm/probe'); } catch { /* shown below */ }
      const dl = probe && probe.models.length ? `<datalist id="models">${probe.models.map((m) => `<option value="${esc(m.name)}">`).join('')}</datalist>` : '';
      fields = fieldFor(sec, 'runtime', v.runtime, { choices: ['ollama-local', 'hosted'], hint: T('set.llm.hosted_note') }) + fieldFor(sec, 'base_url', v.base_url, { ltr: true })
        + fieldFor(sec, 'classifier_model', v.classifier_model, { ltr: true, list: 'models' }) + fieldFor(sec, 'verifier_model', v.verifier_model, { ltr: true, list: 'models' })
        + fieldFor(sec, 'step_timeout_s', v.step_timeout_s) + fieldFor(sec, 'python_bin', v.python_bin, { ltr: true });
      extra = `${dl}<div class="card flat mt"><div class="card-h"><h3>${T('set.llm.pick')}</h3><span class="chip ${probe && probe.reachable ? 'ok' : 'bad'}">${probe && probe.reachable ? T('dash.reachable') : T('dash.unreachable')}</span></div>
        <div class="row">${probe && probe.models.length ? probe.models.map((m) => `<span class="chip mono">${esc(m.name)}${m.parameter_size ? ` · ${esc(m.parameter_size)}` : ''}${m.quantization ? ` · ${esc(m.quantization)}` : ''}</span>`).join('') : `<span class="faint">${esc((probe && probe.error) || '—')}</span>`}</div>
        <div class="row mt"><button class="btn" type="button" data-act="llm-test">${ico('bolt')} ${T('set.llm.test')}</button><span class="faint" id="llm-test-out"></span></div></div>`;
    } else if (sec === 'smtp') {
      const pwHint = d.env.smtp_password_from_env ? T('set.smtp.password_env') : v.password_set ? T('set.smtp.password_set') : '';
      fields = fieldFor(sec, 'mode', v.mode, { choices: ['mock', 'smtp'], full: true, hint: T('set.smtp.mock_note') }) + fieldFor(sec, 'host', v.host, { ltr: true, ph: 'smtp.example.com' })
        + fieldFor(sec, 'port', v.port) + fieldFor(sec, 'security', v.security, { choices: ['starttls', 'ssl', 'none'] }) + fieldFor(sec, 'username', v.username, { ltr: true })
        + fieldFor(sec, 'password', '', { type: 'password', ltr: true, hint: pwHint, ph: v.password_set ? '••••••••' : '' })
        + fieldFor(sec, 'from_email', v.from_email, { ltr: true, ph: 'no-reply@example.com' }) + fieldFor(sec, 'from_name', v.from_name);
      extra = `<div class="card flat mt"><div class="row"><div class="field" style="flex:1;min-width:220px"><label for="smtp-to">${T('set.smtp.test_to')}</label><input class="input ltr" id="smtp-to" type="email" value="${esc(S.me.email)}"></div>
        <button class="btn" type="button" data-act="smtp-test" style="align-self:flex-end">${ico('mail')} ${T('common.send')}</button></div></div>`;
    } else if (sec === 'security') {
      fields = fieldFor(sec, 'otp_length', v.otp_length) + fieldFor(sec, 'otp_ttl_min', v.otp_ttl_min) + fieldFor(sec, 'otp_max_attempts', v.otp_max_attempts)
        + fieldFor(sec, 'otp_resend_s', v.otp_resend_s) + fieldFor(sec, 'session_hours', v.session_hours)
        + fieldFor(sec, 'show_mock_code', v.show_mock_code, { full: true, hint: T('set.security.show_mock_code_note') })
        + fieldFor(sec, 'guest_access', v.guest_access, { full: true, hint: T('set.security.guest_access_note') });
    } else if (sec === 'gates') {
      fields = `<div class="notice full">${ico('shield')}<span>${T('set.gates.note')}</span></div>` + fieldFor(sec, 'phase0_merged', v.phase0_merged, { full: true })
        + fieldFor(sec, 'phase0_note', v.phase0_note, { full: true, ltr: true, ph: 'https://github.com/…/pull/…' }) + fieldFor(sec, 'sample_reviewed', v.sample_reviewed, { full: true })
        + fieldFor(sec, 'sample_max_windows', v.sample_max_windows);
    } else if (sec === 'reports') {
      const r = await api('/roles');
      fields = fieldFor(sec, 'auto_daily', v.auto_daily, { full: true }) + fieldFor(sec, 'daily_time', v.daily_time, { type: 'time', ltr: true })
        + `<div class="field full"><span class="label">${T('set.reports.mail_roles')}</span><div class="perm-grid">${r.roles.map((x) => `<label class="check"><input type="checkbox" name="mail_roles" value="${esc(x.key)}" ${v.mail_roles.includes(x.key) ? 'checked' : ''}><span>${esc(roleName(x))}</span></label>`).join('')}</div></div>`;
    }
    return `<form id="f-settings" class="card" data-sec="${sec}"><div class="form-grid">${fields}</div>
      <div class="form-actions"><button class="btn primary" type="submit">${T('common.save')}</button></div></form>${extra}`;
  }
  async function tabLanguages() {
    const d = await api('/languages');
    const rows = d.languages.map((l) => `<tr><td class="mono">${esc(l.code)}</td><td>${esc(l.name_native)}</td><td class="hide-sm">${esc(l.name_en)}</td>
      <td>${T(l.dir === 'rtl' ? 'lang.rtl' : 'lang.ltr')}</td>
      <td><div class="row" style="gap:8px;min-width:100px"><div class="bar" style="flex:1;min-width:60px"><i style="width:${l.coverage}%"></i></div><span class="faint">${l.coverage}%</span></div></td>
      <td><label class="switch"><input type="checkbox" data-act="lang-toggle" data-code="${esc(l.code)}" ${l.enabled ? 'checked' : ''} ${l.is_default ? 'disabled' : ''}></label></td>
      <td>${l.is_default ? `<span class="chip ok">${T('lang.default')}</span>` : `<button class="btn sm" data-act="lang-default" data-code="${esc(l.code)}">${T('lang.make_default')}</button>`}</td>
      <td><button class="btn sm" data-act="lang-edit" data-code="${esc(l.code)}">${T('lang.edit_translations')}</button></td></tr>`).join('');
    return `<div class="notice mb">${ico('info')}<span>${T('lang.content_note')}</span></div>
      <div class="table-wrap"><table class="t"><thead><tr><th>${T('lang.code')}</th><th>${T('lang.native')}</th><th class="hide-sm">${T('lang.en_name')}</th><th>${T('lang.dir')}</th><th>${T('lang.coverage')}</th><th>${T('common.enabled')}</th><th>${T('lang.default')}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <form id="f-lang" class="card mt"><h3 class="mb">${T('lang.add')}</h3><div class="form-grid">
        <div class="field"><label for="l-code">${T('lang.code')}</label><input class="input ltr" id="l-code" required placeholder="fr" maxlength="10"></div>
        <div class="field"><label for="l-native">${T('lang.native')}</label><input class="input" id="l-native" required placeholder="Français"></div>
        <div class="field"><label for="l-en">${T('lang.en_name')}</label><input class="input ltr" id="l-en" required placeholder="French"></div>
        <div class="field"><label for="l-dir">${T('lang.dir')}</label><select class="input" id="l-dir"><option value="ltr">${T('lang.ltr')}</option><option value="rtl">${T('lang.rtl')}</option></select></div>
      </div><div class="form-actions"><button class="btn primary" type="submit">${ico('plus')} ${T('lang.add')}</button></div></form>`;
  }
  async function tabOutbox() {
    const d = await api('/outbox');
    const rows = d.outbox.map((o) => `<tr><td class="num">${esc(fDT(o.at))}</td><td class="ltr">${esc(o.to_addr)}</td><td>${esc(o.subject)}</td><td><span class="chip">${esc(o.mode)}</span></td>
      <td><span class="chip ${o.status === 'failed' ? 'bad' : 'ok'}">${esc(o.status)}</span>${o.error ? `<div class="faint mono">${esc(o.error)}</div>` : ''}</td></tr>`).join('')
      || `<tr><td colspan="5" class="empty">${T('common.empty')}</td></tr>`;
    return `<div class="table-wrap"><table class="t"><thead><tr><th>${T('audit.when')}</th><th>${T('outbox.to')}</th><th>${T('outbox.subject')}</th><th>${T('outbox.mode')}</th><th>${T('common.status')}</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }
  function bindTab(sec) {
    const f = $('#f-settings');
    if (f) f.addEventListener('submit', async (e) => {
      e.preventDefault();
      const body = {};
      $$('[data-k]', f).forEach((el) => {
        const k = el.dataset.k;
        if (el.type === 'checkbox') body[k] = el.checked;
        else if (el.type === 'number') body[k] = Number(el.value);
        else body[k] = el.value;
      });
      if (sec === 'reports') body.mail_roles = $$('input[name=mail_roles]:checked', f).map((x) => x.value);
      try {
        await api('/settings/' + sec, { method: 'PATCH', body });
        toast(t('common.saved'), 'ok');
        if (sec === 'general') S.pub = await api('/public');
        viewSettings(sec);
      } catch (err) { toast(errText(err), 'bad'); }
    });
    const fl = $('#f-lang');
    if (fl) fl.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        await api('/languages', { method: 'POST', body: { code: $('#l-code').value.trim(), name_native: $('#l-native').value.trim(), name_en: $('#l-en').value.trim(), dir: $('#l-dir').value, enabled: true } });
        S.pub = await api('/public'); toast(t('common.saved'), 'ok'); viewSettings('languages');
      } catch (err) { toast(errText(err), 'bad'); }
    });
  }
  async function translationsModal(code) {
    const d = await api('/translations/' + code);
    const lang = ((S.pub.languages || []).find((l) => l.code === code)) || { dir: 'ltr' };
    const rows = d.items.map((it) => `<tr data-key="${esc(it.key)}"><td class="mono" style="font-size:12px">${esc(it.key)}</td><td style="font-size:13px">${esc(it.en)}</td>
      <td><input class="input" dir="${lang.dir || 'ltr'}" data-tr="${esc(it.key)}" value="${esc(it.override ?? '')}" placeholder="${esc(it.file ?? t('lang.override_ph'))}"></td></tr>`).join('');
    const m = modal(`${modalHead(t('lang.translations') + ' · ' + code)}
      ${d.items.some((i) => i.file != null) ? '' : `<div class="notice warn mb">${ico('info')}<span>${T('lang.missing_file')}</span></div>`}
      <input class="input mb" id="tr-search" placeholder="${T('lang.search')}">
      <div class="table-wrap" style="max-height:55vh;overflow:auto"><table class="t"><thead><tr><th>key</th><th>English</th><th>${esc(code)}</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="form-actions"><button class="btn" data-act="close-modal">${T('common.cancel')}</button><button class="btn primary" id="tr-save">${T('common.save')}</button></div>`, { wide: true });
    const dirty = {};
    m.addEventListener('input', (e) => {
      if (e.target.id === 'tr-search') {
        const q = e.target.value.toLowerCase();
        $$('tr[data-key]', m).forEach((r) => { r.style.display = r.textContent.toLowerCase().includes(q) || $('input', r).value.toLowerCase().includes(q) ? '' : 'none'; });
      } else if (e.target.dataset.tr) dirty[e.target.dataset.tr] = e.target.value;
    });
    $('#tr-save', m).addEventListener('click', async () => {
      try { await api('/translations/' + code, { method: 'PUT', body: dirty }); closeModal(); toast(t('common.saved'), 'ok'); if (code === S.lang) await setLang(code, false); viewSettings('languages'); }
      catch (err) { toast(errText(err), 'bad'); }
    });
  }

  // ------------------------------------------------------------ profile
  async function viewProfile() {
    const langs = (S.pub.languages || []).map((l) => `<option value="${esc(l.code)}" ${S.me.lang === l.code ? 'selected' : ''}>${esc(l.name_native)}</option>`).join('');
    setPage(`${head('profile.title')}<div class="grid g2"><section class="card"><div class="row mb"><span class="avatar" style="width:52px;height:52px;font-size:18px">${esc(initials(S.me.name))}</span>
        <div><h2>${esc(S.me.name)}</h2><div class="faint ltr" style="text-align:start">${esc(S.me.email)}</div><div class="chip ok mt-s">${esc(S.lang === 'ar' || S.lang === 'ur' ? S.me.role.name_ar : S.me.role.name_en)}</div></div></div>
        <form id="f-profile" class="stack"><div class="field"><label for="p-name">${T('users.name')}</label><input class="input" id="p-name" value="${esc(S.me.name)}" maxlength="80"></div>
        <div class="field"><label for="p-lang">${T('profile.lang')}</label><select class="input" id="p-lang"><option value="">${T('users.lang_default')}</option>${langs}</select></div>
        <div class="form-actions"><button class="btn primary" type="submit">${T('common.save')}</button></div></form></section>
      <section class="card"><h2 class="mb">${T('profile.permissions')}</h2><div class="row">${S.me.permissions.map((p) => `<span class="chip ok">${T('perm.' + p)}</span>`).join('')}</div></section></div>`);
    $('#f-profile').addEventListener('submit', async (e) => {
      e.preventDefault();
      const lang = $('#p-lang').value;
      try {
        await api('/me', { method: 'PATCH', body: { name: $('#p-name').value.trim(), lang } });
        S.me = (await api('/me')).user;
        await setLang(lang || S.pub.default_lang);
        toast(t('common.saved'), 'ok'); render();
      } catch (err) { toast(errText(err), 'bad'); }
    });
  }

  // ------------------------------------------------------------ global events
  document.addEventListener('click', async (e) => {
    const dd = e.target.closest('[data-act="dd"]');
    $$('.dropdown.open').forEach((x) => { if (!dd || x !== dd.parentElement) x.classList.remove('open'); });
    if (dd) { dd.parentElement.classList.toggle('open'); return; }
    if (e.target.matches('[data-close-back]')) { closeModal(); return; }
    const row = e.target.closest('tr[data-href]');
    if (row && !e.target.closest('a,button,input')) { location.hash = row.dataset.href; return; }
    const el = e.target.closest('[data-act]');
    if (!el) return;
    const act = el.dataset.act;
    const id = el.dataset.id;
    try {
      switch (act) {
        case 'close-modal': closeModal(); break;
        case 'nav-toggle': document.body.classList.toggle('nav-open'); break;
        case 'theme': {
          const order = ['auto', 'light', 'dark'];
          store.set('mq-theme', order[(order.indexOf(store.get('mq-theme', 'auto')) + 1) % 3]);
          applyTheme(); toast(t('theme.' + store.get('mq-theme', 'auto')));
          if (S.me) { const b = el; b.innerHTML = ico(store.get('mq-theme') === 'dark' ? 'moon' : store.get('mq-theme') === 'light' ? 'sun' : 'auto'); }
          else { $('#app').innerHTML = loginView(); bindLogin(); }
          break;
        }
        case 'lang': {
          await setLang(el.dataset.code);
          if (S.me) { await api('/me', { method: 'PATCH', body: { lang: el.dataset.code } }); S.me.lang = el.dataset.code; }
          render(); break;
        }
        case 'logout': await api('/auth/logout', { method: 'POST' }); S.me = null; location.hash = ''; render(); break;
        case 'login-back': S.loginStep = 'email'; S.mockCode = ''; $('#app').innerHTML = loginView(); bindLogin(); break;
        case 'resend': sendCode(S.loginEmail); break;
        case 'guest': {
          const r = await api('/auth/guest', { method: 'POST' });
          S.me = r.user; S.loginStep = 'email';
          if (!location.hash || location.hash === '#/') location.hash = '#/dashboard';
          render(); break;
        }
        case 'probe': await api('/llm/probe'); viewDashboard(); break;
        case 'sel-agent': S.selAgent = el.dataset.k; { const d = await api('/dashboard'); setPage(dashHTML(d)); } break;
        case 'run-sample': newTaskModal({ kind: 'committee', scope: 'sample' }); break;
        case 'new-task': newTaskModal(); break;
        case 'step': stepModal(id); break;
        case 'cancel-task': if (await confirmBox(t('tasks.confirm_cancel'))) { await api(`/tasks/${id}/cancel`, { method: 'POST' }); render(); } break;
        case 'retry-task': { const r = await api(`/tasks/${id}/retry`, { method: 'POST' }); location.hash = '#/tasks/' + r.id; break; }
        case 'gen-report': await api(`/reports/${el.dataset.day}/generate`, { method: 'POST' }); location.hash = '#/reports/' + el.dataset.day; render(); break;
        case 'mail-report': { const r = await api(`/reports/${el.dataset.day}/mail`, { method: 'POST' }); toast(t('reports.mail_result', r), r.failed ? 'bad' : 'ok'); render(); break; }
        case 'decide': {
          const art = el.closest('[data-move]');
          const body = { tafsir: S.reviewCtx.tafsir, window: S.reviewCtx.win, move_id: art.dataset.move, decision: el.dataset.d,
            compared_with_source: $('[data-compare]', art).checked, note: $('[data-note]', art).value };
          await api('/review/decision', { method: 'POST', body }); toast(t('common.saved'), 'ok'); render(); break;
        }
        case 'add-user': userModal(null); break;
        case 'edit-user': userModal((S.usersCache || []).find((u) => String(u.id) === id)); break;
        case 'revoke-user': await api(`/users/${id}/revoke-sessions`, { method: 'POST' }); toast(t('common.saved'), 'ok'); break;
        case 'add-role': roleModal(null); break;
        case 'edit-role': roleModal(rolesCache.find((r) => String(r.id) === id)); break;
        case 'del-role': if (await confirmBox(t('roles.confirm_delete'))) { await api('/roles/' + id, { method: 'DELETE' }); render(); } break;
        case 'tab': location.hash = '#/settings/' + el.dataset.tab; break;
        case 'llm-test': {
          const out = $('#llm-test-out'); out.innerHTML = '<span class="spinner sm"></span>';
          const r = await api('/llm/test', { method: 'POST' });
          out.textContent = r.ok ? t('set.llm.test_ok', r) : t('set.llm.test_fail', r); out.style.color = r.ok ? 'var(--accent-text)' : 'var(--danger)'; break;
        }
        case 'smtp-test': { const r = await api('/settings/smtp/test', { method: 'POST', body: { to: $('#smtp-to').value } }); toast(t('set.smtp.test_sent', r), 'ok'); break; }
        case 'lang-default': await api('/languages/' + el.dataset.code, { method: 'PATCH', body: { is_default: true } }); S.pub = await api('/public'); viewSettings('languages'); break;
        case 'lang-edit': translationsModal(el.dataset.code); break;
        default: break;
      }
    } catch (err) { toast(errText(err), 'bad'); }
  });
  document.addEventListener('change', async (e) => {
    const el = e.target.closest('[data-act="lang-toggle"]');
    if (!el) return;
    try { await api('/languages/' + el.dataset.code, { method: 'PATCH', body: { enabled: el.checked } }); S.pub = await api('/public'); toast(t('common.saved'), 'ok'); }
    catch (err) { el.checked = !el.checked; toast(errText(err), 'bad'); }
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeModal(); document.body.classList.remove('nav-open'); $$('.dropdown.open').forEach((x) => x.classList.remove('open')); } });

  // ------------------------------------------------------------ boot
  (async function boot() {
    applyTheme();
    try { S.pub = await api('/public'); } catch { $('#app').innerHTML = `<div class="auth-wrap"><div class="notice bad">${ico('warn')}<span>Console server not reachable.</span></div></div>`; return; }
    try { const me = await api('/me'); S.me = me.user; } catch { S.me = null; }
    const want = (S.me && S.me.lang) || store.get('mq-lang', '') || S.pub.default_lang;
    await setLang(want, false);
    render();
  })();
})();

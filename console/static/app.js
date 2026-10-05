/* مِرْقاة committee console — single-page UI (no build step, no framework). */
(() => {
  'use strict';

  // ------------------------------------------------------------ state & helpers
  const S = { pub: null, me: null, t: {}, lang: 'ar', dir: 'rtl', timers: [], route: '', loginStep: 'email',
    loginEmail: '', mockCode: '', cooldown: 0, selAgent: 'classifier', settingsTab: 'general',
    viewAs: '', demoAvailable: false, brand: { word: '', full: '' } };
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
  // read-only views: "view as user" blocks every write; demo mode blocks the committee's writes
  const viewingAs = () => !!(S.me && S.me.view_as);
  const inDemo = () => !!(S.me && S.me.mode === 'demo');
  // the sample ayah comes from Settings → General (server), never from the code
  const sampleAyah = () => (S.me && S.me.sample_ayah) || '24:11';
  const canDo = (p) => has(p) && !viewingAs() && !inDemo();
  const canAdmin = (p) => has(p) && !viewingAs();
  const store = {
    get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  class ApiError extends Error {
    constructor(status, key, detail) { super(key || 'error'); this.status = status; this.key = key; this.detail = detail; }
  }
  async function api(path, { method = 'GET', body, noViewAs = false } = {}) {
    const opt = { method, headers: { Accept: 'application/json' }, credentials: 'same-origin' };
    if (method !== 'GET') { opt.headers['X-Mirqah'] = '1'; opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body ?? {}); }
    if (S.viewAs && !noViewAs) opt.headers['X-Mirqah-View-As'] = S.viewAs;
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
      const err = new ApiError(res.status, key, d && d.detail);
      err.raw = d;
      throw err;
    }
    return data;
  }
  function errText(e) {
    if (!(e instanceof ApiError)) return t('common.error');
    if (e.status === 403 && e.key === 'forbidden') return t('common.forbidden');
    for (const ns of ['auth.err.', 'tasks.err.', 'users.err.', 'roles.err.', 'lang.err.', 'review.err.', 'publish.err.', 'common.err.']) {
      if (S.t[ns + e.key]) return t(ns + e.key);
    }
    if (e.key === 'settings_invalid' && e.detail) return String(e.detail);
    if (e.key === 'assigned_to_other') return t('review.assigned_other', { name: (e.raw && e.raw.name) || '—' });
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
    eye: 'M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
    flask: 'M9 3h6M10 3v6L4.5 18.5A2 2 0 0 0 6.2 21h11.6a2 2 0 0 0 1.7-2.5L14 9V3M7.5 14h9',
    upload: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12',
    inbox: 'M22 12h-6l-2 3h-4l-2-3H2M5.5 5.1L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z',
    chev: 'M9 6l6 6-6 6',
    pulse: 'M22 12h-4l-3 9L9 3l-3 9H2',
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

  // ------------------------------------------------------------ brand (inline SVG: follows light/dark)
  function brandMark(kind, cls) {
    const raw = S.brand[kind];
    if (!raw) return `<span class="brand-name">${esc(S.pub ? S.pub.team_name : 'مِرْقاة')}</span>`;
    const pre = 'mq' + kind[0].toUpperCase();
    return raw.replace(/<\?xml[^>]*>/, '').replace(/id="mq/g, `id="${pre}`).replace(/url\(#mq/g, `url(#${pre}`)
      .replace('<svg ', `<svg class="${cls}" focusable="false" `);
  }
  async function loadBrand() {
    const js = document.querySelector('script[src*="/static/app.js"]');
    const v = js ? (new URL(js.src).searchParams.get('v') || '') : '';
    await Promise.all(['word', 'full'].map(async (k) => {
      try {
        const r = await fetch(`/static/brand/mirqah-${k === 'word' ? 'wordmark' : 'logo'}.svg${v ? `?v=${v}` : ''}`, { credentials: 'same-origin' });
        if (r.ok) S.brand[k] = await r.text();
      } catch { /* the text name is shown instead */ }
    }));
  }

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
    { r: 'team', icon: 'pulse', k: 'nav.team', p: 'view_dashboard' },
    { r: 'review', icon: 'review', k: 'nav.review', p: 'view_tasks' },
    { r: 'reports', icon: 'report', k: 'nav.reports', p: 'view_reports' },
    { r: 'calls', icon: 'bolt', k: 'nav.calls', p: 'view_tasks', opt: true },
    { sep: true },
    { admin: true, r: 'publish', icon: 'upload', k: 'nav.publish', p: 'publish_units' },
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
    const nav = items.map((n) => n.sep ? (items.some((x) => !x.sep && ['publish', 'users', 'roles', 'audit', 'settings'].includes(x.r)) ? '<span class="sep"></span>' : '')
      : `<a href="#/${n.r}" class="${r === n.r ? 'on' : ''} ${n.admin ? 'adm' : ''}" title="${T(n.k)}">${ico(n.icon)}<span class="${n.opt ? 'lbl-opt' : ''}">${T(n.k)}</span>${n.r === 'review' ? '<b class="nav-badge" id="nb-review" hidden></b>' : ''}</a>`).join('');
    const theme = store.get('mq-theme', 'auto');
    const langs = (S.pub.languages || []).map((l) => `<button class="mi ${l.code === S.lang ? 'on' : ''}" data-act="lang" data-code="${esc(l.code)}">${esc(l.name_native)}</button>`).join('');
    return `<header class="topbar"><div class="topbar-in">
      <button class="icon-btn menu-btn" data-act="nav-toggle" aria-label="${T('nav.menu')}">${ico('menu')}</button>
      <a class="brand" href="#/dashboard" aria-label="${esc(S.pub.team_name)}">${brandMark('word', 'brand-logo')}
        <span class="brand-sub">${T('app.title')}</span><span class="badge-beta">BETA</span></a>
      <nav class="nav" aria-label="${T('nav.menu')}">${nav}</nav>
      <div class="top-actions">
        ${S.demoAvailable ? `<div class="mode-toggle" role="group" aria-label="${T('mode.switch_title')}" title="${T('mode.switch_title')}">
          <button type="button" class="${inDemo() ? '' : 'on'}" data-act="mode" data-mode="live" aria-pressed="${!inDemo()}"><span class="dot ${inDemo() ? '' : 'live'}"></span>${T('mode.live')}</button>
          <button type="button" class="${inDemo() ? 'on' : ''}" data-act="mode" data-mode="demo" aria-pressed="${inDemo()}">${ico('flask')}<span class="lbl">${T('mode.demo')}</span></button></div>` : ''}
        <div class="dropdown"><button class="icon-btn" data-act="dd" aria-label="${T('lang.switch')}">${ico('globe')}</button>
          <div class="dropdown-menu"><div class="mh">${T('lang.switch')}</div>${langs}</div></div>
        <button class="icon-btn" data-act="theme" title="${T('theme.toggle')}: ${T('theme.' + theme)}" aria-label="${T('theme.toggle')}">${ico(theme === 'dark' ? 'moon' : theme === 'light' ? 'sun' : 'auto')}</button>
        <div class="dropdown"><button class="user-chip ${viewingAs() ? 'as' : ''}" data-act="dd"><span class="avatar">${viewingAs() ? ico('eye') : esc(initials(S.me.name))}</span><span class="nm">${esc(S.me.name)}</span></button>
          <div class="dropdown-menu"><div class="mh">${esc(S.me.email)}<br>${esc(S.lang === 'ar' || S.lang === 'ur' ? S.me.role.name_ar : S.me.role.name_en)}</div>
            <a class="mi" href="#/profile">${ico('user')} ${T('nav.profile')}</a>
            ${viewingAs() ? `<button class="mi" data-act="view-as-stop">${ico('out')} ${T('viewas.return')}</button>`
              : S.me.can_view_as ? `<button class="mi" data-act="view-as">${ico('eye')} ${T('viewas.menu')}</button>` : ''}<hr>
            <button class="mi" data-act="logout">${ico('out')} ${T('auth.logout')}</button></div></div>
      </div></div></header>
      <div class="drawer-back" data-act="nav-toggle"></div>
      ${inDemo() ? `<div class="mode-banner" role="status">${ico('flask')}<span><b>${T('demo.banner_title')}</b> ${T('demo.banner')}</span>
        <button class="btn sm" data-act="mode" data-mode="live">${T('demo.back_live')}</button></div>` : ''}
      <main class="page" id="page">${inner}</main>
      ${viewingAs() ? `<div class="viewas-bar" role="status">${ico('eye')}<span><b>${T('viewas.bar', { name: S.me.name })}</b>
        <span class="faint-in">${esc(S.me.email)} · ${esc(S.lang === 'ar' || S.lang === 'ur' ? S.me.role.name_ar : S.me.role.name_en)} — ${T('viewas.note')}</span></span>
        <button class="btn sm" data-act="view-as-stop">${T('viewas.return')}</button></div>` : ''}`;
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
    hcHide();
    const app = $('#app');
    document.body.classList.toggle('is-view-as', viewingAs());
    document.body.classList.toggle('is-demo', inDemo());
    if (!S.me) { app.innerHTML = loginView(); bindLogin(); return; }
    const [r, a, b, c] = parts();
    const routes = {
      dashboard: [viewDashboard, 'view_dashboard'], tasks: [a ? viewTask : viewTasks, 'view_tasks'],
      progress: [viewProgress, 'view_dashboard'], team: [viewTeam, 'view_dashboard'], reports: [a ? viewReport : viewReports, 'view_reports'],
      review: [a === 'learning' ? viewLearning : a ? viewReviewWindow : viewReview, 'view_tasks'], calls: [viewCalls, 'view_tasks'],
      audit: [viewAudit, 'view_audit'], users: [viewUsers, 'manage_users'], roles: [viewRoles, 'manage_roles'],
      settings: [viewSettings, 'manage_settings'], profile: [viewProfile, null], publish: [viewPublish, 'publish_units'],
    };
    let entry = routes[r];
    if (!entry || (entry[1] && !has(entry[1]))) {
      const first = NAV.find((n) => !n.sep && has(n.p));
      if (r !== 'profile' && first && first.r !== r) { location.hash = '#/' + first.r; return; }
      entry = [viewProfile, null];
    }
    app.innerHTML = shell(loading());
    fitTopbar();
    watchTopbar();
    refreshBadges();
    try { await entry[0](a, b, c); } catch (e) {
      if (e instanceof ApiError && e.status === 401) return;
      $('#page').innerHTML = `<div class="notice bad">${ico('warn')}<span>${esc(errText(e))}</span></div>`;
    }
  }
  const setPage = (html) => { const p = $('#page'); if (p) p.innerHTML = html; };
  // keep the top bar on one row: drop detail step by step (labels differ in length per language)
  function fitTopbar() {
    const bar = $('.topbar-in');
    if (!bar) return;
    const b = document.body;
    for (let i = 1; i <= 4; i++) b.classList.remove('tb-' + i);
    if (window.innerWidth <= 1200) return;  // the drawer takes over
    const tooTall = () => bar.getBoundingClientRect().height > 72 || bar.scrollWidth > bar.clientWidth + 1;
    for (let i = 1; i <= 4 && tooTall(); i++) b.classList.add('tb-' + i);
  }
  let fitT;
  window.addEventListener('resize', () => { clearTimeout(fitT); fitT = setTimeout(fitTopbar, 80); });
  // web fonts can arrive after the first fit and widen the labels: fit again once they are in
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => fitTopbar());
  window.addEventListener('load', () => fitTopbar());
  // and whatever else widens it later (fonts that load after .ready, a nav badge, a
  // language switch): if the bar ever grows past one row, fit it again
  let tbObs = null;
  function watchTopbar() {
    const bar = $('.topbar-in');
    if (!bar || !window.ResizeObserver) return;
    if (tbObs) tbObs.disconnect();
    tbObs = new ResizeObserver(() => {
      if (window.innerWidth > 1200 && bar.getBoundingClientRect().height > 72) {
        clearTimeout(fitT); fitT = setTimeout(fitTopbar, 60);
      }
    });
    tbObs.observe(bar);
  }
  // windows the chair gave me that still wait for my decision (nav badge)
  async function refreshBadges() {
    const el = $('#nb-review');
    if (!el || !S.me || !S.me.can_decide || inDemo()) return;
    try {
      const d = await api('/review/assignments?mine=true');
      const n = d.assignments.filter((a) => a.status === 'open' && a.open > 0).length;
      el.textContent = n; el.hidden = !n; el.title = t('review.mine_open', { n });
      if (n) fitTopbar();
    } catch { /* badge is optional */ }
  }

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
        <div class="auth-brand"><h1 class="sr-only">${esc(S.pub.team_name)}</h1>${brandMark('full', 'login-logo')}<p class="muted">${T('app.title')} · ${esc(S.pub.project_name)}</p></div>
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
          S.mockCode = ''; S.loginStep = 'email';
          { const me = await api('/me'); S.me = me.user; S.demoAvailable = !!me.demo_available; }
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
      try { const n = await api('/dashboard'); if (parts()[0] === 'dashboard' && !$('.modal')) { setPage(dashHTML(n)); hcPlace(); } } catch { /* next tick */ }
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
        if (r.result && r.result.moves != null) bubble += `<br>${resultLine(r.result)}`;
      } else if (a.key === 'checker') bubble = `${T('dash.today')}: ${fNum(a.today.ok)} ${T('dash.ok')}`;
      else if (a.key === 'specialist') bubble = `${T('dash.today')}: ${fNum(a.today.n)} ${T('dash.decisions')} · ✓${fNum(a.today.approve)} ✎${fNum(a.today.needs_edit)} ✕${fNum(a.today.reject)}`;
      else bubble = `<span class="faint">${T('dash.nothing_running')}</span>`;
      return `<button class="agent ${a.key === sel.key ? 'sel' : ''} ${HC.key === a.key ? 'hc-on' : ''}" data-act="sel-agent" data-k="${a.key}" data-hc="${a.key}" aria-describedby="hovercard">${robot(a.color, st === 'running')}
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
        <div class="faint mt-s">${T('dash.classified')} ${fNum(r.classifier)} · ${T('dash.both')} ${fNum(r.both)} · ${T('dash.committee')} ${fNum(r.committee)} ${T('dash.unit_windows')} · ${T('dash.moves_of_these')}: ${T('dash.candidates')} ${fNum(r.committee_candidates)} · ${T('dash.specialist')} ${fNum(r.committee_specialist)}</div></div>
        <span class="mono faint">${fNum(r.both)}/${fNum(r.windows)}</span></div>`).join('');
    const g = d.gates;
    const gate = (k, on, v) => `<div class="gate"><span>${T(k, v)}</span><span class="chip ${on ? 'ok' : 'warn'}">${ico(on ? 'check' : 'lock')} ${T(on ? 'gate.open' : 'gate.closed')}</span></div>`;
    const tasks = d.tasks.length ? d.tasks.map((x) => taskGroupRows(x, { compact: true })).join('')
      : `<tr><td colspan="5" class="empty">${T('tasks.empty')}</td></tr>`;
    const detail = agentDetail(sel, d);
    const sampleBtn = canDo('run_tasks') ? `<button class="btn primary" data-act="run-sample" ${llm.reachable ? '' : `disabled title="${T('dash.engine_offline_note')}"`}>${ico('play')} ${T('dash.start_sample')} <span class="mono">${esc(d.sample_ayah)}</span></button>` : '';
    const pill = d.simulated ? `<span class="chip violet"><span class="dot live"></span>${T('mode.demo')} · ${esc(fTime(d.server_time))}</span>`
      : llm.reachable ? `<span class="chip ok"><span class="dot live"></span>${T('dash.connected')} · ${esc(fTime(d.server_time))}</span>`
        : `<span class="chip warn"><span class="dot"></span>${T('dash.engine_offline')} · ${esc(fTime(d.server_time))}</span>`;
    const offline = !d.simulated && !llm.reachable ? `<div class="notice warn mb">${ico('info')}<span>${T('dash.engine_offline_note')}</span></div>` : '';
    return `${head('dash.title', 'dash.subtitle', `${pill}
        <button class="btn" data-act="probe">${ico('refresh')} ${T('dash.probe')}</button>${sampleBtn}`)}${offline}
      <section class="card mission">
        <div class="brain"><div class="brain-orb ${llm.reachable ? '' : 'off'} ${busy ? 'busy' : ''} ${HC.key === 'model' ? 'hc-on' : ''}" data-hc="model" tabindex="0" role="button" aria-label="${T('dash.llm_layer')}" aria-describedby="hovercard">${ico('brain')}</div>
          <div class="brain-meta"><div class="kicker">${T('dash.llm_layer')} · ${esc(llm.runtime || '')}</div>
            <div class="m">${esc(llm.classifier_model || '')} <span class="faint">+</span> ${esc(llm.verifier_model || '')}</div>
            <div class="faint">${llm.simulated ? T('mode.demo_engine') : (llm.address_hidden ? T('dash.engine_private') : `<span class="mono">${esc(llm.base_url || '')}</span>`)} · ${llm.reachable ? `<span class="c-green">${T('dash.reachable')}</span>` : `<span style="color:var(--warn)">${T('dash.unreachable')}</span>`}${llm.version && !llm.simulated ? ` · v${esc(llm.version)}` : ''} · ${busy ? `<span class="c-green">${T('dash.brain_busy')}</span>` : T('dash.brain_idle')}</div></div></div>
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
            <div><div class="kicker">${T('dash.committee')} (${T('dash.moves')}): ${T('dash.candidates')} · ${T('dash.specialist')}</div><div class="stat">${fNum(tot.committee_candidates)}<small> · ${fNum(tot.committee_specialist)}</small></div></div>
          </div>${tafRows}</section>
        <section class="card"><div class="card-h"><h2>${T('dash.gates')}</h2>${has('manage_settings') ? `<a class="btn sm" href="#/settings/gates">${ico('gear')}</a>` : ''}</div>
          ${gate('gate.phase0', g.phase0_merged)}${gate('gate.sample', g.sample_reviewed, { a: esc(d.sample_ayah || sampleAyah()) })}
          <p class="faint mt-s">${T('gate.bulk_rule')}</p>
          <div class="mt"><div class="kicker">${T('dash.models_on_host')}</div><div class="row mt-s">${llmModels || `<span class="faint">—</span>`}</div>
          <div class="stack mt-s"><div class="row"><span class="faint">${T('agent.classifier')}:</span>${inst(llm.classifier_model, llm.classifier_installed)}</div>
          <div class="row"><span class="faint">${T('agent.verifier')}:</span>${inst(llm.verifier_model, llm.verifier_installed)}</div></div></div></section>
      </div>
      <section class="mt"><div class="card-h"><h2>${T('dash.recent_tasks')}</h2><a class="btn sm" href="#/tasks">${T('nav.tasks')} ${ico('arrow')}</a></div>
        <div class="table-wrap"><table class="t tasks-t"><tbody>${tasks}</tbody></table></div></section>`;
  }
  function agentDetail(a, d) {
    const did = (a.recent || []).map((r) => `<div class="ev"><span class="tm">${esc(fTime(r.finished_at))}</span><span>${esc(tafsirName(r.tafsir))} <span class="mono">${esc(r.window)}</span> · ${statusChip(r.status)}
      ${r.result && r.result.moves != null ? `<span class="faint">${resultLine(r.result, true)}</span>` : ''}
      <span class="faint">· ${fDur(r.duration_ms)}</span></span></div>`).join('') || `<p class="faint">—</p>`;
    let now = `<p class="big-next" style="font-size:20px">${T('dash.nothing_running')}</p>`;
    if (a.now) now = `<p class="big-next" style="font-size:20px;color:var(--accent-text)">${esc(tafsirName(a.now.tafsir))} · <span class="mono">${esc(a.now.window)}</span></p><p class="faint">${esc(a.now.title_ar || '')}</p><p class="faint">${T('dash.model')}: <span class="mono">${esc(a.now.model || '')}</span></p>`;
    else if (!['classifier', 'method_specialist', 'verifier', 'chair'].includes(a.key)) now = `<p class="muted">${T('agent.' + a.key + '.desc')}</p>`;
    let next;
    if (a.next) next = `<p class="big-next">${T('dash.queue_steps', { n: a.next })}</p>`;
    else if (a.key === 'specialist') next = `<a class="btn outline-accent" href="#/review">${ico('review')} ${T('nav.review')}</a>`;
    else next = canDo('run_tasks') ? `<button class="btn outline-accent" data-act="new-task">${ico('plus')} ${T('tasks.new')}</button>` : '<p class="faint">—</p>';
    const td = a.today || {};
    let today = '';
    if (['classifier', 'method_specialist', 'verifier', 'chair'].includes(a.key)) today = `${T('dash.today')}: ${fNum(td.ok)} ${T('dash.ok')} · ${fNum(td.bad)} ${T('dash.failed')}`;
    else if (a.key === 'checker') today = `${T('dash.today')}: ${fNum(td.ok)} ${T('dash.ok')}`;
    else if (a.key === 'specialist') today = `${T('dash.today')}: ${fNum(td.n)} ${T('dash.decisions')}`;
    return `<div class="card-h"><div class="row">${robot(a.color, a.status === 'running').replace('class="robot', 'style="width:40px;height:40px" class="robot')}
        <div><h2>${T('agent.' + a.key)}</h2><div class="faint">${T('agent.' + a.key + '.desc')}</div></div></div>
        <span class="faint">${today}${a.today && a.today.avg_ms ? ` · ${T('dash.avg')} ${fDur(Math.round(a.today.avg_ms))}` : ''}</span></div>
      <div class="agent-detail"><div class="card flat"><div class="kicker mb">${ico('check')} ${T('dash.last_runs')}</div>${did}</div>
        <div class="card flat"><div class="kicker mb">${T('dash.now')}</div>${now}</div>
        <div class="card flat"><div class="kicker mb">${T('dash.next')}</div>${next}</div></div>`;
  }

  function resultLine(res, full = false) {
    if (!res || res.moves == null) return '';
    if (res.confirm != null) return ['confirm', 'reject', 'reframe', 'abstain', 'invalid'].filter((k) => res[k]).map((k) => `${T('spec.verdict.' + k)} ${res[k]}`).join(' · ') || `${T('dash.moves')} ${res.moves}`;
    const parts = [`${T('dash.moves')} ${res.moves}`];
    if (res.auto_candidate != null) parts.push(`${T('dash.candidates')} ${res.auto_candidate}`);
    if (full && res.flags != null) parts.push(`${T('dash.flags')} ${res.flags}`);
    return parts.join(' · ');
  }

  // ------------------------------------------------------------ hover cards (mission control)
  // Hover a robot (or the model orb) for its real numbers: step timings, failures, the
  // tokens the model server reported, what it is doing now. Click pins; Esc closes.
  // The card lives outside #page so the 5-second dashboard refresh never removes it.
  const HC = { key: null, pinned: false, data: {}, timer: null, showT: null, hideT: null, el: null, seq: 0 };
  const canHover = () => window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  // token counts read like the model server reports them (12.3K), in every language
  const fCompact = (n) => (n == null ? '—' : new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(n));
  function fSecs(s) {
    if (s == null) return '—';
    if (s < 60) return `${s < 10 ? s : Math.round(s)} ${t('common.seconds')}`;
    const r = Math.round(s), h = Math.floor(r / 3600), m = Math.floor((r % 3600) / 60), sec = String(r % 60).padStart(2, '0');
    return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
  }
  const fGB = (b) => (b == null ? '—' : `${(b / 1e9).toFixed(1)} GB`);
  function fAgo(sec) {
    if (sec == null) return '—';
    const rtf = new Intl.RelativeTimeFormat(locale(), { numeric: 'auto', style: 'short' });
    const s = Math.max(0, Math.round(sec));
    if (s < 60) return rtf.format(-s, 'second');
    if (s < 3600) return rtf.format(-Math.round(s / 60), 'minute');
    if (s < 86400) return rtf.format(-Math.round(s / 3600), 'hour');
    return rtf.format(-Math.round(s / 86400), 'day');
  }
  function hcEl() {
    if (HC.el) return HC.el;
    const el = document.createElement('div');
    el.id = 'hovercard'; el.className = 'hc'; el.setAttribute('role', 'tooltip'); el.hidden = true;
    el.addEventListener('mouseenter', () => clearTimeout(HC.hideT));
    el.addEventListener('mouseleave', () => { if (!HC.pinned) hcHideSoon(); });
    document.body.appendChild(el);
    HC.el = el;
    return el;
  }
  const hcAnchor = () => (HC.key ? document.querySelector(`[data-hc="${HC.key}"]`) : null);
  function hcPlace() {
    if (!HC.key || !HC.el || HC.el.hidden) return;
    const a = hcAnchor();
    if (!a) { hcHide(); return; }
    $$('[data-hc].hc-on').forEach((x) => { if (x !== a) x.classList.remove('hc-on'); });
    a.classList.add('hc-on');
    const el = HC.el;
    const sheet = window.innerWidth <= 640;
    el.classList.toggle('sheet', sheet);
    if (sheet) { el.style.left = el.style.top = ''; return; }
    // beside the robot (never over it), on the side with more room; below/above on narrow screens
    const r = a.getBoundingClientRect();
    const g = 10, gap = 10, w = el.offsetWidth, h = el.offsetHeight, vw = document.documentElement.clientWidth, vh = window.innerHeight;
    const roomL = r.left - gap - g, roomR = vw - r.right - gap - g;
    let x, y;
    if (Math.max(roomL, roomR) >= w) {
      x = roomR >= roomL ? r.right + gap : r.left - gap - w;
      y = Math.max(g, Math.min(vh - h - g, r.top - 4));
    } else {
      x = Math.max(g, Math.min(vw - w - g, r.left + r.width / 2 - w / 2));
      y = r.bottom + gap;
      if (y + h > vh - g) { const up = r.top - h - gap; y = up >= g ? up : Math.max(g, vh - h - g); }
    }
    el.style.left = `${Math.round(x)}px`; el.style.top = `${Math.round(y)}px`;
  }
  async function hcLoad() {
    const key = HC.key, seq = ++HC.seq;
    if (!key) return;
    try {
      const d = await api('/agents/' + encodeURIComponent(key));
      HC.data[key] = d;
      if (HC.key === key && seq === HC.seq) hcPaint();
    } catch (e) {
      if (HC.key === key && !HC.data[key]) { HC.el.innerHTML = `<div class="hc-body"><div class="notice bad">${ico('warn')}<span>${esc(errText(e))}</span></div></div>`; hcPlace(); }
    }
  }
  function hcPaint() {
    const d = HC.data[HC.key];
    HC.el.innerHTML = d ? hcHTML(HC.key, d) : `<div class="hc-body"><div class="spinner" style="margin:18px auto"></div></div>`;
    HC.el.classList.toggle('pinned', HC.pinned);
    hcPlace();
  }
  function hcShow(key, pinned = false) {
    clearTimeout(HC.showT); clearTimeout(HC.hideT);
    const el = hcEl();
    const changed = HC.key !== key;
    HC.key = key; HC.pinned = pinned || (HC.pinned && !changed);
    el.hidden = false;
    if (changed || !el.innerHTML) hcPaint(); else { el.classList.toggle('pinned', HC.pinned); hcPlace(); }
    if (changed) hcLoad();
    if (!HC.timer) HC.timer = setInterval(() => { if (!document.hidden && HC.key) hcLoad(); }, 3000);
  }
  function hcHide() {
    clearTimeout(HC.showT); clearTimeout(HC.hideT);
    if (HC.timer) { clearInterval(HC.timer); HC.timer = null; }
    $$('[data-hc].hc-on').forEach((x) => x.classList.remove('hc-on'));
    HC.key = null; HC.pinned = false; HC.seq++;
    if (HC.el) { HC.el.hidden = true; HC.el.innerHTML = ''; }
  }
  function hcHideSoon() {
    clearTimeout(HC.hideT);
    HC.hideT = setTimeout(() => {
      // the 5-second refresh replaces the anchor: keep the card while the pointer is still on it
      const a = hcAnchor();
      if (HC.pinned || (a && a.matches(':hover')) || (HC.el && HC.el.matches(':hover'))) return;
      hcHide();
    }, 220);
  }
  function hcPin(key) {
    if (HC.pinned && HC.key === key) { HC.pinned = false; if (canHover()) hcShow(key); else hcHide(); return; }
    hcShow(key, true);
  }
  document.addEventListener('mouseover', (e) => {
    if (!canHover()) return;
    const a = e.target.closest('[data-hc]');
    if (!a) return;
    clearTimeout(HC.hideT);
    if (HC.pinned && HC.key !== a.dataset.hc) return; // a pinned card stays until closed
    if (HC.key === a.dataset.hc && !HC.el.hidden) return;
    clearTimeout(HC.showT);
    HC.showT = setTimeout(() => hcShow(a.dataset.hc), HC.key ? 60 : 160);
  });
  document.addEventListener('mouseout', (e) => {
    if (!canHover()) return;
    const a = e.target.closest('[data-hc]');
    if (!a || (e.relatedTarget && (a.contains(e.relatedTarget) || e.relatedTarget.closest?.('#hovercard')))) return;
    clearTimeout(HC.showT);
    if (!HC.pinned) hcHideSoon();
  });
  document.addEventListener('focusin', (e) => { const a = e.target.closest?.('[data-hc]'); if (a && !HC.pinned) hcShow(a.dataset.hc); });
  document.addEventListener('focusout', (e) => { const a = e.target.closest?.('[data-hc]'); if (a && !HC.pinned) hcHideSoon(); });
  window.addEventListener('resize', () => hcPlace());
  window.addEventListener('scroll', () => hcPlace(), { passive: true });

  function hcTile(label, value, sub = '', cls = '') {
    return `<div class="hc-tile ${cls}"><div class="k">${label}</div><div class="v">${value}</div>${sub ? `<div class="s">${sub}</div>` : ''}</div>`;
  }
  function hcSpark(d) {
    const pts = d.spark || [];
    if (!pts.length) return '';
    const max = Math.max(...pts.map((p) => p.s), 1);
    const bars = pts.map((p) => `<i class="${p.st !== 'done' ? (p.st === 'failed' ? 'bad' : 'warn') : ''} ${p.arm === 'B' ? 'arm-b' : ''}" style="height:${Math.max(p.st === 'done' ? 6 : 45, Math.round((100 * p.s) / max))}%" title="${esc(tafsirName(p.t))} ${esc(p.w)} · ${esc(fSecs(p.s))}${p.arm === 'B' ? ' · B' : ''}"></i>`).join('');
    return `<div class="hc-sec"><div class="hc-k">${T('hc.recent', { n: pts.length })}<span class="faint ltr-num">${T('hc.max')} ${esc(fSecs(max))}</span></div><div class="hc-spark">${bars}</div></div>`;
  }
  function hcCtx(d) {
    const maxp = (d.today && d.today.max_prompt) || (d.week && d.week.max_prompt) || 0;
    const ctx = d.loaded && d.loaded.context_length;
    if (!maxp) return '';
    if (!ctx) return `<div class="hc-sec"><div class="hc-k">${T('hc.ctx')}<span class="mono">${fNum(maxp)}</span></div><div class="faint">${T('hc.ctx_unknown')}</div></div>`;
    const p = Math.min(100, Math.round((100 * maxp) / ctx));
    const hot = maxp >= 0.98 * ctx;
    return `<div class="hc-sec"><div class="hc-k">${T('hc.ctx')}<span class="mono">${fNum(maxp)} / ${fNum(ctx)}</span></div>
      <div class="bar"><i class="${hot ? 'r' : p > 80 ? 'w' : ''}" style="width:${p}%"></i></div>
      ${hot ? `<div class="hc-warn">${ico('warn')}<span>${T('hc.ctx_warn')}</span></div>` : ''}</div>`;
  }
  function hcNow(d) {
    const n = d.now;
    if (!n) {
      const last = (d.spark || []).slice(-1)[0];
      return `<div class="hc-now idle"><span class="dot"></span><span>${last ? T('hc.idle_since', { ago: fAgo(d.server_time - last.at) }) : T('dash.nothing_running')}</span></div>`;
    }
    const lim = n.timeout_s || 0;
    const p = lim ? Math.min(100, Math.round((100 * n.elapsed_s) / lim)) : 0;
    const proc = n.proc ? T('hc.process', { pid: n.pid, rss: n.proc.rss_mb ?? '—', cpu: n.proc.cpu_pct }) : n.pid ? `pid ${n.pid}` : '';
    return `<div class="hc-now"><div class="row"><span class="dot live"></span><b><bdi>${esc(tafsirName(n.tafsir))}</bdi> · <span class="mono">${esc(n.window)}</span></b>${n.variant ? ` <span class="chip info">B</span>` : ` <span class="chip">A</span>`}
        ${HC.key === 'checker' ? `<span class="faint">${T('hc.checking', { a: t('agent.' + n.agent) })}</span>` : ''}</div>
      <div class="bar mt-s"><i class="${p > 85 ? 'r' : p > 60 ? 'w' : 'b'}" style="width:${p}%"></i></div>
      <div class="faint"><span class="ltr-num">${esc(fSecs(n.elapsed_s))}</span> ${T('hc.of_limit', { t: fSecs(lim) })} · ${T('hc.task', { id: n.task_id, done: n.task_done, total: n.task_total })}${n.task_failed ? ` · <span style="color:var(--danger)">${fNum(n.task_failed)}✕</span>` : ''}</div>
      ${proc ? `<div class="faint mono hc-proc">${proc}</div>` : ''}</div>`;
  }
  function hcFoot(d) {
    const q = d.queue || {};
    const arms = d.arms_today || {};
    const armTxt = Object.keys(arms).length ? Object.keys(arms).sort().map((k) => `${k} ${fNum(arms[k])}`).join(' · ') : '—';
    const lf = d.last_failure;
    return `<div class="hc-kv">
      <div><span>${T('hc.queue')}</span><b>${q.waiting ? T('hc.queue_v', { n: fNum(q.waiting), eta: q.eta_s ? fSecs(q.eta_s) : '—' }) : T('hc.queue_empty')}</b></div>
      <div><span>${T('hc.arms')}</span><b class="mono">${esc(armTxt)}</b></div>
      <div><span>${T('hc.last_fail')}</span><b>${lf ? `<span class="mono" style="color:var(--danger)">${esc(lf.code)}</span> · <bdi>${esc(tafsirName(lf.tafsir))}</bdi> <span class="mono">${esc(lf.window)}</span> · <bdi>${esc(fAgo(d.server_time - lf.at))}</bdi>` : T('hc.none')}</b></div>
      ${lf && lf.line ? `<div class="hc-line mono" title="${esc(lf.line)}">${esc(lf.line)}</div>` : ''}</div>`;
  }
  function hcOutcomes(key, d) {
    const o = d.outcomes_today || {};
    const chips = [];
    if (key === 'method_specialist') {
      for (const k of ['confirm', 'reject', 'reframe', 'abstain', 'invalid']) if (o[k]) chips.push(`<span class="chip ${k === 'confirm' ? 'ok' : k === 'invalid' ? 'bad' : 'warn'}">${T('spec.verdict.' + k)} ${fNum(o[k])}</span>`);
    } else if (key !== 'checker') {
      if (o.moves != null) chips.push(`<span class="chip">${T('dash.moves')} ${fNum(o.moves)}</span>`);
      if (o.auto_candidate != null) chips.push(`<span class="chip ok">${T('dash.candidates')} ${fNum(o.auto_candidate)}</span>`);
      if (o.specialist != null) chips.push(`<span class="chip warn">${T('dash.specialist')} ${fNum(o.specialist)}</span>`);
      if (o.flags) chips.push(`<span class="chip">${T('dash.flags')} ${fNum(o.flags)}</span>`);
    }
    const rs = Object.entries(d.reasons_today || {}).sort((a, b) => b[1] - a[1]).slice(0, 4)
      .map(([k, v]) => `<span class="chip ${/^[A-Z_]+$/.test(k) ? 'bad' : ''}">${/^[A-Z_]+$/.test(k) ? `<span class="mono">${esc(k)}</span>` : T('review.reason.' + k)} ${fNum(v)}</span>`);
    if (!chips.length && !rs.length) return '';
    return `<div class="hc-sec"><div class="hc-k">${T(key === 'checker' ? 'hc.reject_codes' : 'hc.outcomes')}</div><div class="hc-chips">${chips.join('')}${rs.join('')}</div></div>`;
  }
  function hcHeadHTML(key, d, title, model, state) {
    const color = { classifier: 'blue', method_specialist: 'teal', verifier: 'violet', checker: 'green', chair: 'amber', specialist: 'red' }[key];
    const icon = key === 'model' ? `<span class="hc-orb">${ico('brain')}</span>` : robot(color, state === 'running');
    const chip = { running: `<span class="chip info"><span class="dot live"></span>${T('dash.status.running')}</span>`, queued: `<span class="chip warn">${T('dash.status.queued')}</span>`,
      idle: `<span class="chip">${T('dash.status.idle')}</span>`, human: `<span class="chip bad">${T('dash.status.human')}</span>`,
      on: `<span class="chip ok"><span class="dot live"></span>${T('dash.reachable')}</span>`, off: `<span class="chip warn">${T('dash.unreachable')}</span>` }[state] || '';
    return `<div class="hc-h">${icon}<div class="hc-t"><b>${title}</b>${model ? `<div class="mono faint">${model}</div>` : ''}</div>${chip}</div>`;
  }
  function hcHTML(key, d) {
    const foot = `<div class="hc-f"><span>${T('hc.caption')}</span><span>${T(!canHover() ? 'hc.tap_close' : HC.pinned ? 'hc.pinned' : 'hc.pin_hint')}</span></div>`;
    if (key === 'model') return hcModelHTML(d) + foot;
    if (key === 'specialist') {
      const td = d.today || {}, wk = d.week || {}, rv = d.review || {};
      return `${hcHeadHTML(key, d, T('agent.specialist'), '', 'human')}<div class="hc-body">
        <div class="hc-tiles">
          ${hcTile(T('hc.decisions'), fNum(td.n), T('hc.d7', { v: fNum(wk.n) }))}
          ${hcTile(T('hc.verdicts'), `<span class="c-green">✓${fNum(td.approve)}</span> <span class="c-amber">✎${fNum(td.needs_edit)}</span> <span class="c-red">✕${fNum(td.reject)}</span>`, T('dash.today'))}
          ${hcTile(T('hc.lessons'), fNum(td.lessons), T('hc.d7', { v: fNum(wk.lessons) }))}
        </div>
        <div class="hc-sec"><div class="hc-k">${T('hc.review_waiting')}<b>${fNum(rv.waiting)}</b></div>
          <div class="bar"><i style="width:${pct(rv.decided, rv.moves)}%"></i></div>
          <div class="faint">${T('hc.review_of', { d: fNum(rv.decided), n: fNum(rv.moves), u: fNum(rv.units) })}</div></div>
        ${(d.people || []).length ? `<div class="hc-sec"><div class="hc-k">${T('hc.team')}</div><table class="hc-tab"><thead><tr><th>${T('users.name')}</th><th>${T('hc.open')}</th><th>${T('hc.oldest')}</th><th>${T('dash.today')}</th></tr></thead><tbody>${d.people.map((p) => `<tr><td>${esc(p.name)}</td><td class="num">${fNum(p.open_moves)}</td><td class="num">${p.open_windows ? esc(fAgo(p.oldest_days * 86400)) : '—'}</td><td class="num">${fNum(p.decided_today)}</td></tr>`).join('')}</tbody></table></div>` : ''}
        <div class="hc-kv"><div><span>${T('hc.last_decision')}</span><b>${d.last_decision_at ? esc(fAgo(d.server_time - d.last_decision_at)) : '—'}</b></div></div>
        <a class="btn sm outline-accent" href="#/review">${ico('review')} ${T('nav.review')}</a></div>${foot}`;
    }
    const td = d.today || {}, wk = d.week || {};
    const state = d.now ? 'running' : (d.queue && d.queue.waiting) ? 'queued' : 'idle';
    if (!wk.n && !d.now) {
      return `${hcHeadHTML(key, d, T('agent.' + key), esc(d.model || ''), state)}<div class="hc-body"><p class="muted">${T('agent.' + key + '.desc')}</p><p class="faint">${T('hc.no_steps')}</p></div>${foot}`;
    }
    const sub7 = (v) => T('hc.d7', { v });
    let tiles;
    if (key === 'checker') {
      tiles = `${hcTile(T('hc.checked'), fNum(td.ok), sub7(fNum(wk.ok)))}
        ${hcTile(T('hc.rejected'), fNum(td.failed), sub7(fNum(wk.failed)), td.failed ? 'bad' : '')}
        ${hcTile(T('hc.fail'), td.fail_pct != null ? `${td.fail_pct}%` : '—', sub7(wk.fail_pct != null ? `${wk.fail_pct}%` : '—'), td.fail_pct > 10 ? 'bad' : '')}`;
    } else {
      const model = key !== 'chair';
      const loaded = d.loaded;
      const memSub = !loaded ? '' : loaded.loaded === false ? T('hc.not_loaded')
        : loaded.expires_at ? T('hc.unloads_in', { m: Math.max(0, Math.round((loaded.expires_at - d.server_time) / 60)) }) : T('hc.kept_loaded');
      tiles = `${hcTile(T('hc.steps'), `${fNum(td.ok)}<small>✓</small>${td.failed ? ` <small style="color:var(--danger)">${fNum(td.failed)}✕</small>` : ''}`, sub7(fNum(wk.n - (wk.skipped || 0))))}
        ${hcTile(T('hc.fail'), td.fail_pct != null ? `${td.fail_pct}%` : '—', sub7(wk.fail_pct != null ? `${wk.fail_pct}%` : '—'), td.fail_pct > 10 ? 'bad' : '')}
        ${hcTile(T('hc.median'), `<span class="ltr-num">${esc(fSecs(td.median_s))}</span>`, sub7(fSecs(wk.median_s)))}
        ${hcTile(T('hc.p95'), `<span class="ltr-num">${esc(fSecs(td.p95_s))}</span>`, sub7(fSecs(wk.p95_s)))}
        ${model ? hcTile(T('hc.tokens'), fCompact((td.tokens_in || 0) + (td.tokens_out || 0)), `${T('hc.in_out', { i: fCompact(td.tokens_in), o: fCompact(td.tokens_out) })} · ${sub7(fCompact((wk.tokens_in || 0) + (wk.tokens_out || 0)))}`, 'wide')
          : hcTile(T('hc.max'), `<span class="ltr-num">${esc(fSecs(td.max_s))}</span>`, sub7(fSecs(wk.max_s)))}
        ${model ? hcTile(T('hc.speed'), td.tokens_per_s != null ? `<span class="ltr-num">${td.tokens_per_s}</span>` : '—', sub7(wk.tokens_per_s ?? '—'))
          : hcTile(T('hc.busy'), `<span class="ltr-num">${esc(fSecs(td.busy_s))}</span>`, sub7(fSecs(wk.busy_s)))}
        ${model ? hcTile(T('hc.calls'), fNum(td.model_calls), sub7(fNum(wk.model_calls))) : ''}
        ${model ? hcTile(T('hc.memory'), loaded && loaded.size ? fGB(loaded.size_vram || loaded.size) : '—', memSub) : ''}`;
    }
    return `${hcHeadHTML(key, d, T('agent.' + key), esc(d.model || ''), state)}<div class="hc-body">
      ${hcNow(d)}<div class="hc-tiles">${tiles}</div>${key !== 'checker' ? hcSpark(d) + hcCtx(d) : ''}${hcOutcomes(key, d)}${hcFoot(d)}</div>${foot}`;
  }
  function hcModelHTML(d) {
    const llm = d.llm || {};
    const ps = d.ps || {};
    const loaded = (ps.models || []).map((m) => `<div class="hc-model"><span class="mono">${esc(m.name)}</span>
        <span class="faint">${fGB(m.size_vram || m.size)}${m.context_length ? ` · ${T('hc.ctx_short', { n: fNum(m.context_length) })}` : ''} · ${m.expires_at ? T('hc.unloads_in', { m: Math.max(0, Math.round((m.expires_at - (ps.at || d.server_time)) / 60)) }) : T('hc.kept_loaded')}</span></div>`).join('')
      || `<p class="faint">${ps.available ? T('hc.nothing_loaded') : esc(ps.error || '—')}</p>`;
    const per = Object.entries(d.per_model || {}).map(([name, p]) => `<tr><td class="mono">${esc(name)}</td><td class="num">${fNum(p.steps)}</td><td class="num">${fCompact(p.tokens_in)}</td><td class="num">${fCompact(p.tokens_out)}</td><td class="num">${fNum(p.max_prompt || null)}</td></tr>`).join('');
    const td = d.today || {};
    const run = d.running;
    return `${hcHeadHTML('model', d, T('dash.llm_layer'), `${esc(llm.runtime || '')}${llm.version && !llm.simulated ? ` · v${esc(llm.version)}` : ''}`, llm.reachable ? 'on' : 'off')}
      <div class="hc-body">
        ${run ? `<div class="hc-now"><div class="row"><span class="dot live"></span><b>${T('agent.' + run.agent)}</b> · <bdi>${esc(tafsirName(run.tafsir))}</bdi> <span class="mono">${esc(run.window)}</span><span class="faint ltr-num">${esc(fSecs(Math.round(d.server_time - run.started_at)))}</span></div></div>`
          : `<div class="hc-now idle"><span class="dot"></span><span>${T('dash.brain_idle')}</span></div>`}
        <div class="hc-tiles">
          ${hcTile(T('hc.steps'), fNum(td.steps), T('dash.today'))}
          ${hcTile(T('hc.calls'), fNum(td.calls), T('hc.last5_v', { n: fNum(d.last5 && d.last5.calls) }))}
          ${hcTile(T('hc.tokens'), fCompact((td.tokens_in || 0) + (td.tokens_out || 0)), T('hc.in_out', { i: fCompact(td.tokens_in), o: fCompact(td.tokens_out) }))}
        </div>
        <div class="hc-sec"><div class="hc-k">${T('hc.in_memory')}</div>${loaded}</div>
        <div class="hc-kv"><div><span>${T('hc.host')}</span><b class="${llm.address_hidden ? '' : 'mono'}">${llm.simulated ? T('mode.demo_engine') : (llm.address_hidden ? T('dash.engine_private') : esc(llm.base_url || '—'))}</b></div></div>
        ${per ? `<div class="hc-sec"><div class="hc-k">${T('hc.per_model')}</div><table class="hc-tab"><thead><tr><th>${T('tasks.model')}</th><th>${T('hc.steps')}</th><th>${T('hc.t_in')}</th><th>${T('hc.t_out')}</th><th>${T('hc.max_prompt')}</th></tr></thead><tbody>${per}</tbody></table></div>` : ''}
      </div>`;
  }

  // ------------------------------------------------------------ publish (super admins → mirqah.app)
  async function viewPublish() {
    const d = await api('/publish');
    if (d.simulated) {
      setPage(`${head('publish.title', 'publish.subtitle')}<div class="notice">${ico('flask')}<span>${T('publish.demo')}</span></div>`);
      return;
    }
    S.publishCtx = d;
    const live = d.live;
    const c = d.counts || { units: 0, windows: 0, by_tafsir: {}, by_method: {} };
    const excerpt = (u) => esc((u.text || '').length > 150 ? u.text.slice(0, 150) + '…' : (u.text || ''));
    const unitRow = (u, kind) => `<tr><td><span class="chip ${kind === 'added' ? 'ok' : kind === 'removed' ? 'bad' : 'warn'}">${T('publish.kind.' + kind)}</span></td>
      <td>${esc(tafsirName(u.tafsir))}</td><td class="mono">${esc(u.window)}</td><td class="mono">${esc(u.primary || '—')}</td><td class="hide-sm">${esc(u.certainty || '—')}</td>
      <td class="pub-text" dir="rtl">${excerpt(u)}</td></tr>`;
    const diffRows = [...d.added.map((u) => unitRow(u, 'added')), ...d.changed.map((u) => unitRow(u, 'changed')), ...d.removed.map((u) => unitRow(u, 'removed'))];
    const checks = [];
    if (d.failed.length) checks.push(`<div class="notice bad">${ico('warn')}<span>${T('publish.failed', { n: d.failed.length })} ${[...new Set(d.failed.map((f) => f.reason))].map((r) => `<span class="chip bad">${T('publish.reason.' + r)}</span>`).join(' ')}</span></div>`);
    if (d.overlaps.length) checks.push(`<div class="notice warn">${ico('info')}<span>${T('publish.overlaps', { n: d.overlaps.length })} ${d.overlaps.slice(0, 4).map((o) => `<span class="chip mono">${esc(tafsirName(o.tafsir))} ${esc(o.window)}: ${esc(o.a_primary)} / ${esc(o.b_primary)}</span>`).join(' ')}</span></div>`);
    if (d.duplicates) checks.push(`<div class="notice">${ico('info')}<span>${T('publish.duplicates', { n: d.duplicates })}</span></div>`);
    if (d.windows_waiting) checks.push(`<div class="notice">${ico('inbox')}<span>${T('publish.waiting', { n: d.windows_waiting })}</span></div>`);
    const hist = d.history.length ? d.history.map((h) => `<tr><td class="mono"><b>v${h.version}</b> ${h.live ? `<span class="chip ok"><span class="dot live"></span>${T('publish.is_live')}</span>` : ''}</td>
      <td class="num">${fNum(h.units)}</td><td class="hide-sm"><span class="c-green">+${fNum((h.summary || {}).added || 0)}</span> <span class="c-red">−${fNum((h.summary || {}).removed || 0)}</span> <span class="c-amber">~${fNum((h.summary || {}).changed || 0)}</span></td>
      <td>${esc(h.created_by_name || '—')}</td><td class="num hide-sm">${esc(fDT(h.created_at))}</td><td class="hide-sm">${esc(h.note || '')}</td>
      <td class="num"><div class="row tight end">${!h.live && canDo('publish_units') ? `<button class="btn sm" data-act="make-live" data-v="${h.version}">${ico('refresh')} ${T('publish.make_live')}</button>` : ''}<a class="btn sm" href="/api/publish/${h.version}/download">${ico('download')}</a></div></td></tr>`).join('')
      : `<tr><td colspan="7" class="empty">${T('publish.no_history')}</td></tr>`;
    const canPublish = canDo('publish_units') && (d.changes > 0 || (!live && c.units > 0));
    setPage(`${head('publish.title', 'publish.subtitle', canDo('publish_units') ? `<button class="btn primary" data-act="publish" ${canPublish ? '' : `disabled title="${T('publish.nothing')}"`}>${ico('upload')} ${T('publish.publish_v', { v: (d.history[0] ? d.history[0].version : 0) + 1 })}</button>` : '')}
      <div class="grid g3 mb">
        <section class="card"><div class="kicker">${T('publish.live')}</div>${live ? `<div class="stat">v${live.version}<small> · ${fNum(live.units)} ${T('publish.units')}</small></div>
          <div class="faint">${esc(fDT(live.made_live_at))} · ${esc(live.created_by_name || '')}</div>${live.note ? `<p class="mt-s">${esc(live.note)}</p>` : ''}` : `<p class="muted">${T('publish.none_live')}</p>`}
          <div class="faint mt-s">${T('publish.public_url')}<br><a class="mono pub-url" href="${esc(d.public_url)}" target="_blank" rel="noopener">${esc(d.public_url)}</a></div></section>
        <section class="card"><div class="kicker">${T('publish.ready')}</div><div class="stat">${fNum(c.units)}<small> · ${fNum(c.windows)} ${T('publish.windows')}</small></div>
          <div class="row tight mt-s">${Object.entries(c.by_tafsir || {}).map(([k, v]) => `<span class="chip">${esc(tafsirName(k))} ${fNum(v)}</span>`).join('') || '<span class="faint">—</span>'}</div>
          <div class="row tight mt-s">${Object.entries(c.by_method || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<span class="chip mono">${esc(k)} ${fNum(v)}</span>`).join('')}</div></section>
        <section class="card"><div class="kicker">${T('publish.changes')}</div><div class="stat">${fNum(d.changes)}</div>
          <div class="row tight mt-s"><span class="chip ok">+${fNum(d.added.length)} ${T('publish.kind.added')}</span><span class="chip warn">~${fNum(d.changed.length)} ${T('publish.kind.changed')}</span><span class="chip bad">−${fNum(d.removed.length)} ${T('publish.kind.removed')}</span></div>
          <p class="faint mt-s">${T('publish.rule')}</p></section>
      </div>
      ${checks.join('')}
      <section class="mt"><div class="card-h"><h2>${T('publish.diff')}</h2></div>
        <div class="table-wrap"><table class="t"><thead><tr><th></th><th>${T('tasks.tafsir')}</th><th>${T('tasks.window')}</th><th>${T('review.primary')}</th><th class="hide-sm">${T('review.certainty')}</th><th>${T('review.text')}</th></tr></thead>
        <tbody>${diffRows.slice(0, 300).join('') || `<tr><td colspan="6" class="empty">${T('publish.no_changes')}</td></tr>`}</tbody></table></div>
        ${diffRows.length > 300 ? `<p class="faint mt-s">${T('publish.more', { n: diffRows.length - 300 })}</p>` : ''}</section>
      <section class="mt"><div class="card-h"><h2>${T('publish.history')}</h2></div>
        <div class="table-wrap"><table class="t"><thead><tr><th>${T('publish.version')}</th><th>${T('publish.units')}</th><th class="hide-sm">${T('publish.changes')}</th><th>${T('publish.by')}</th><th class="hide-sm">${T('audit.when')}</th><th class="hide-sm">${T('publish.note')}</th><th></th></tr></thead><tbody>${hist}</tbody></table></div></section>`);
  }
  function publishModal() {
    const d = S.publishCtx || {};
    const v = (d.history && d.history[0] ? d.history[0].version : 0) + 1;
    const m = modal(`${modalHead(t('publish.publish_v', { v }))}
      <p>${T('publish.confirm', { n: (d.counts || {}).units || 0, a: (d.added || []).length, r: (d.removed || []).length, c: (d.changed || []).length })}</p>
      <div class="field"><label for="pub-note">${T('publish.note')}</label><textarea class="input" id="pub-note" rows="3" maxlength="500" placeholder="${T('publish.note_ph')}"></textarea></div>
      <div class="notice mt">${ico('shield')}<span>${T('publish.privacy')}</span></div>
      <div class="form-actions"><button class="btn" data-act="close-modal">${T('common.cancel')}</button><button class="btn primary" id="pub-go">${ico('upload')} ${T('publish.go')}</button></div>`);
    $('#pub-go', m).addEventListener('click', async () => {
      const b = $('#pub-go', m); b.disabled = true;
      try { const r = await api('/publish', { method: 'POST', body: { note: $('#pub-note', m).value } }); closeModal(); toast(t('publish.done', { v: r.live.version }), 'ok'); render(); }
      catch (err) { b.disabled = false; toast(errText(err), 'bad'); }
    });
  }

  // ------------------------------------------------------------ team & agents performance
  // History, not the live state (mission control is live). Counts of decisions, routing
  // and timing — never accuracy. Charts are HTML columns (no library): 2px surface gaps,
  // 4px rounded data-ends, one shared tooltip built with textContent, a table view.
  const AGENT_KEYS = ['classifier', 'method_specialist', 'verifier', 'chair'];
  const DEC_KEYS = ['approve', 'needs_edit', 'reject'];
  const decColor = { approve: 'var(--accent)', needs_edit: 'var(--warn)', reject: 'var(--danger)' };
  const fDay = (iso, long) => { try { return new Intl.DateTimeFormat(locale(), long ? { weekday: 'short', day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short' }).format(new Date(iso + 'T12:00:00')); } catch (e) { return iso; } };
  const fHours = (h) => (h == null ? '—' : h < 1 ? `${Math.max(1, Math.round(h * 60))} ${t('team.min')}` : h < 48 ? `${(Math.round(h * 10) / 10).toLocaleString(locale())} ${t('team.h')}` : `${Math.round(h / 24).toLocaleString(locale())} ${t('team.d')}`);
  const compact = (n) => (n == null ? '—' : new Intl.NumberFormat(locale(), { notation: n >= 10000 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(n));
  const niceMax = (m) => { if (m <= 4) return 4; const p = 10 ** Math.floor(Math.log10(m)); const f = m / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p; };
  const tipAttr = (title, rows) => `data-tip="${esc(JSON.stringify({ title, rows }))}"`;

  // days → columns: one per day up to 45 days, then weeks, then months (columns stay readable)
  function bucketize(days, value, marks) {
    if (days.length <= 45) return { cols: days.map((d, i) => ({ label: fDay(d), long: fDay(d, true), idx: [i], days: [d] })), value, marks };
    const monthly = days.length > 120;
    const cols = [];
    days.forEach((d, i) => {
      const dt = new Date(d + 'T12:00:00');
      const key = monthly ? d.slice(0, 7) : (() => { const m = new Date(dt); m.setDate(m.getDate() - ((m.getDay() + 6) % 7)); return m.toISOString().slice(0, 10); })();
      let c = cols[cols.length - 1];
      if (!c || c.key !== key) { c = { key, idx: [], days: [] }; cols.push(c); }
      c.idx.push(i); c.days.push(d);
    });
    const fm = (d) => { try { return new Intl.DateTimeFormat(locale(), { month: 'short', year: '2-digit' }).format(new Date(d + 'T12:00:00')); } catch (e) { return d.slice(0, 7); } };
    cols.forEach((c) => { c.label = monthly ? fm(c.days[0]) : fDay(c.days[0]); c.long = monthly ? fm(c.days[0]) : `${fDay(c.days[0])} – ${fDay(c.days[c.days.length - 1])}`; });
    const v2 = (ci, k) => cols[ci].idx.reduce((a, i) => a + (value(i, k) || 0), 0);
    const m2 = {}; cols.forEach((c) => { const all = c.days.flatMap((d) => marks[d] || []); if (all.length) m2[c.key] = all; });
    return { cols, value: v2, marks: m2, grouped: true };
  }

  // one stacked-column chart: series [{key,label,color}], value(dayIdx,key), marks per day
  function colChart({ days: dayList, series, value: dayValue, marks: dayMarks = {}, height = 190, unit = '' }) {
    const B = bucketize(dayList, dayValue, dayMarks);
    const days = B.cols.map((c) => c.key || c.days[0]);
    const value = B.value; const marks = B.marks;
    const label = (i) => B.cols[i].label; const long = (i) => B.cols[i].long;
    const totals = days.map((_, i) => series.reduce((a, s) => a + (value(i, s.key) || 0), 0));
    const max = niceMax(Math.max(1, ...totals));
    const ticks = [0, max / 2, max].map((v) => `<span style="bottom:${(100 * v) / max}%">${fNum(v)}</span>`).join('');
    const every = Math.max(1, Math.ceil(days.length / (days.length > 60 ? 6 : 8)));
    const cols = days.map((d, i) => {
      const segs = series.map((s) => [s, value(i, s.key) || 0]).filter(([, v]) => v > 0);
      const rows = segs.map(([s, v]) => ({ v: fNum(v), label: iso(s.label), color: s.color }));
      const ms = marks[d] || [];
      ms.forEach((m) => rows.push({ ms: true, label: m }));
      const title = `${long(i)} · ${fNum(totals[i])}${unit ? ' ' + unit : ''}`;
      return `<div class="vc-col" tabindex="0" ${tipAttr(title, rows)}>
        ${ms.length ? `<span class="vc-ms" aria-hidden="true"></span>` : ''}
        <div class="vc-stack" style="height:${(100 * totals[i]) / max}%">${segs.map(([s, v]) => `<i style="flex:${v};background:${s.color}"></i>`).join('')}</div></div>`;
    }).join('');
    const xl = days.map((d, i) => { const k = days.length - 1 - i; const on = k % every === 0;
      return `<span class="${on && (k / every) % 2 ? 'alt' : ''}">${on ? esc(label(i)) : ''}</span>`; }).join('');
    const legend = series.map((s) => `<span class="lg"><i style="background:${s.color}"></i><bdi>${esc(s.label)}</bdi> <b>${fNum(days.reduce((a, _, i) => a + (value(i, s.key) || 0), 0))}</b></span>`).join('')
      + (B.grouped ? `<span class="faint">${T(dayList.length > 120 ? 'team.per_month' : 'team.per_week')}</span>` : '');
    const hasMs = Object.keys(marks).length;
    const tableRows = days.map((d, i) => (totals[i] || (marks[d] || []).length) ? `<tr><td>${esc(long(i))}</td>${series.map((s) => `<td class="num">${fNum(value(i, s.key) || 0)}</td>`).join('')}<td class="num"><b>${fNum(totals[i])}</b></td>${hasMs ? `<td>${esc((marks[d] || []).join(' · '))}</td>` : ''}</tr>` : '').join('');
    return `<div class="vc-legend">${legend}${hasMs ? `<span class="lg"><i class="ms"></i>${T('team.milestone')}</span>` : ''}</div>
      <div class="vchart" dir="ltr" style="--vc-h:${height}px"><div class="vc-y">${ticks}</div>
        <div class="vc-plot"><div class="vc-grid"><i style="bottom:0"></i><i style="bottom:50%"></i><i style="bottom:100%"></i></div><div class="vc-cols">${cols}</div></div>
        <div class="vc-x">${xl}</div></div>
      <details class="vc-table"><summary>${T('team.as_table')}</summary><div class="table-wrap"><table class="t"><thead><tr><th>${T('team.day')}</th>${series.map((s) => `<th class="num">${esc(s.label)}</th>`).join('')}<th class="num">${T('team.total')}</th>${hasMs ? `<th>${T('team.milestone')}</th>` : ''}</tr></thead>
        <tbody>${tableRows || `<tr><td colspan="${series.length + 2 + (hasMs ? 1 : 0)}" class="empty">${T('team.no_data')}</td></tr>`}</tbody></table></div></details>`;
  }
  // a 100% split bar (approve / needs edit / reject …) with its numbers beside it
  function splitBar(parts, { label = '' } = {}) {
    const tot = parts.reduce((a, p) => a + p.v, 0);
    if (!tot) return `<div class="hbar empty"><i></i></div>`;
    const rows = parts.filter((p) => p.v).map((p) => ({ v: `${fNum(p.v)} · ${pct(p.v, tot)}%`, label: p.label, color: p.color }));
    return `<div class="hbar" tabindex="0" ${tipAttr(label || t('team.total') + ' ' + fNum(tot), rows)}>${parts.filter((p) => p.v).map((p) => `<i style="flex:${p.v};background:${p.color}"></i>`).join('')}</div>`;
  }
  function wireTips(root) {
    let tip = $('#vtip');
    if (!tip) { tip = document.createElement('div'); tip.id = 'vtip'; tip.setAttribute('role', 'tooltip'); document.body.appendChild(tip); }
    const show = (el, x, y) => {
      let d; try { d = JSON.parse(el.dataset.tip); } catch (e) { return; }
      tip.textContent = '';
      const h = document.createElement('div'); h.className = 'vt-h'; h.textContent = d.title; tip.appendChild(h);
      (d.rows || []).forEach((r) => {
        const row = document.createElement('div'); row.className = 'vt-r' + (r.ms ? ' ms' : '');
        const k = document.createElement('i'); if (r.color) k.style.background = r.color; row.appendChild(k);
        if (!r.ms) { const v = document.createElement('b'); v.textContent = r.v; row.appendChild(v); }
        const l = document.createElement('span'); l.textContent = r.label; row.appendChild(l);
        tip.appendChild(row);
      });
      tip.classList.add('on');
      const r = el.getBoundingClientRect();
      const tw = tip.offsetWidth; const th = tip.offsetHeight;
      let left = (x ?? r.left + r.width / 2) + 14; if (left + tw > innerWidth - 8) left = (x ?? r.left) - tw - 14; if (left < 8) left = 8;
      let top = (y ?? r.top) - th / 2; top = Math.max(8, Math.min(innerHeight - th - 8, top));
      tip.style.left = left + 'px'; tip.style.top = top + 'px';
    };
    const hide = () => tip.classList.remove('on');
    $$('[data-tip]', root).forEach((el) => {
      el.addEventListener('pointermove', (e) => show(el, e.clientX, e.clientY));
      el.addEventListener('pointerleave', hide);
      el.addEventListener('focus', () => show(el));
      el.addEventListener('blur', hide);
    });
  }
  const iso = (s) => `\u2068${s}\u2069`;  // isolate a name inside a sentence of the other direction
  const msText = (m) => t('team.ms.' + m.kind, { who: iso(m.who || ''), n: fNum(m.n || 0), v: m.version || '', units: fNum(m.units || 0) });
  const msIcon = { first_review: 'review', decisions_n: 'check', first_lesson: 'brain', desk_cleared: 'inbox', team_decisions_n: 'users', published: 'upload' };

  async function viewTeam() {
    const days = S.teamDays || 30;
    const d = await api('/team?days=' + days);
    const tm = d.team; const ag = d.agents;
    const all = d.scope === 'all';
    const people = d.people || [];
    const pcolor = {}; people.forEach((p, i) => { pcolor[p.id] = `var(--p${(i % 6) + 1})`; });
    const range = `<div class="seg" role="group" aria-label="${T('team.range')}">${d.range.options.map((n) => `<button type="button" data-act="team-range" data-days="${n}" class="${n === d.range.days ? 'on' : ''}" aria-pressed="${n === d.range.days}">${T('team.range.' + n)}</button>`).join('')}</div>`;
    const sim = d.simulated ? `<span class="chip violet"><span class="dot live"></span>${T('mode.demo')}</span>` : '';
    // milestones by day, for the chart markers
    const marks = {};
    d.milestones.forEach((m) => { const k = new Date(m.at * 1000).toLocaleDateString('en-CA', { timeZone: tz() }); (marks[k] = marks[k] || []).push(msText(m)); });
    // decisions per day: by person for managers, by decision for everyone else
    const decSeries = all && people.length
      ? people.map((p) => ({ key: String(p.id), label: p.name, color: pcolor[p.id] }))
      : DEC_KEYS.map((k) => ({ key: k, label: t('review.decision.' + k), color: decColor[k] }));
    const decChart = colChart({ days: d.daily.map((x) => x.day), series: decSeries, marks,
      value: (i, k) => (all && people.length ? (d.daily[i].by_person[k] || 0) : d.daily[i][k]), unit: t('team.decisions_unit') });
    const tile = (k, v, sub = '', cls = '') => `<section class="card tile ${cls}"><div class="kicker">${T(k)}</div><div class="tile-v">${v}</div>${sub ? `<div class="faint tile-s">${sub}</div>` : ''}</section>`;
    const decSplit = splitBar(DEC_KEYS.map((k) => ({ v: tm[k], label: t('review.decision.' + k), color: decColor[k] })));
    const short = tm.specialists < tm.min_specialists;
    const tiles = `<div class="tiles">
      ${tile('team.k.decided', fNum(tm.decided), decSplit + `<span class="ltr-num">${DEC_KEYS.map((k) => `${fNum(tm[k])} ${t('team.short.' + k)}`).join(' · ')}</span>`)}
      ${tile('team.k.open', `${fNum(tm.open_moves)}<small> ${T('team.moves')}</small>`, T('team.in_windows', { n: fNum(tm.open_windows) }))}
      ${tile('team.k.clear', esc(fHours(tm.median_clear_h)), T('team.k.clear_s'))}
      ${tile('team.k.oldest', tm.oldest_h != null ? esc(fHours(tm.oldest_h)) : '—', T('team.k.oldest_s'), tm.oldest_h >= 48 ? 'warn' : '')}
      ${tile('team.k.lessons', fNum(tm.lessons), T('team.k.lessons_s'))}
      ${tile('team.k.specialists', `${fNum(tm.specialists)}<small> / ${fNum(tm.min_specialists)}</small>`, short ? T('team.k.too_few') : T('team.k.active', { n: fNum(tm.active) }), short ? 'warn' : '')}</div>`;
    const canRemind = canDo('manage_tasks') && !d.simulated;
    const prow = (p) => {
      const split = splitBar(DEC_KEYS.map((k) => ({ v: p[k], label: t('review.decision.' + k), color: decColor[k] })), { label: iso(p.name) });
      const cool = p.remind_after ? t('team.remind_wait', { t: fTime(p.remind_after) }) : '';
      const btn = !canRemind ? '' : p.open_windows ? `<button class="btn sm" data-act="team-remind" data-id="${p.id}" ${cool ? `disabled title="${esc(cool)}"` : `title="${T('team.remind_hint')}"`}>${ico('mail')} ${T('team.remind')}</button>`
        : `<span class="faint">${T('team.nothing_open')}</span>`;
      return `<tr><td><span class="pdot" style="background:${all ? pcolor[p.id] : 'var(--accent)'}"></span><b><bdi>${esc(p.name)}</bdi></b>${p.current ? '' : ` <span class="chip">${T('team.former')}</span>`}</td>
        <td class="num">${fNum(p.open_moves)} <span class="faint">/ ${fNum(p.open_windows)}</span></td>
        <td class="num ${p.oldest_h >= 48 ? 'c-amber' : ''}">${p.oldest_h != null ? esc(fHours(p.oldest_h)) : '—'}</td>
        <td class="num"><b>${fNum(p.decided)}</b>${p.decided_today ? ` <span class="faint">+${fNum(p.decided_today)} ${T('team.today')}</span>` : ''}</td>
        <td class="split-cell">${split}</td>
        <td class="num hide-sm">${esc(fHours(p.median_clear_h))}</td><td class="num hide-sm">${fNum(p.lessons)}</td>
        <td class="num hide-sm">${p.last_decision_at ? esc(fDT(p.last_decision_at)) : '—'}</td>
        ${canRemind ? `<td class="num">${btn}${p.last_reminder_at ? `<div class="faint tiny">${T('team.reminded', { t: fDT(p.last_reminder_at) })}</div>` : ''}</td>` : ''}</tr>`;
    };
    const peopleCard = people.length ? `<section class="card mt"><div class="card-h"><h2>${T(all ? 'team.people' : 'team.you')}</h2><span class="faint">${T('team.people_s')}</span></div>
      <div class="table-wrap"><table class="t team-t"><thead><tr><th>${T('team.col.name')}</th><th class="num">${T('team.col.open')}</th><th class="num">${T('team.col.oldest')}</th><th class="num">${T('team.col.decided')}</th><th>${T('team.col.split')}</th><th class="num hide-sm">${T('team.col.clear')}</th><th class="num hide-sm">${T('team.col.lessons')}</th><th class="num hide-sm">${T('team.col.last')}</th>${canRemind ? '<th></th>' : ''}</tr></thead>
      <tbody>${people.map(prow).join('')}</tbody></table></div></section>` : '';
    const msList = d.milestones.length ? d.milestones.slice().reverse().slice(0, 14).map((m) => `<li><span class="ms-ic">${ico(msIcon[m.kind] || 'check')}</span><span>${esc(msText(m))}</span><span class="faint num">${esc(fDT(m.at))}</span></li>`).join('')
      : `<li class="empty">${T('team.no_milestones')}</li>`;
    // agents
    const agName = (k) => t('agent.' + k);
    const agColor = (k) => `var(--ag-${k})`;
    const agSeries = AGENT_KEYS.filter((k) => ag.table.some((r) => r.agent === k)).map((k) => ({ key: k, label: agName(k), color: agColor(k) }));
    if (ag.daily.some((x) => x.failed)) agSeries.push({ key: 'failed', label: t('team.failed_steps'), color: 'var(--danger)' });
    const agChart = colChart({ days: ag.daily.map((x) => x.day), series: agSeries, value: (i, k) => (k === 'failed' ? ag.daily[i].failed : ag.daily[i].by_agent[k]), unit: t('team.steps_unit') });
    const at = ag.totals;
    const agTiles = `<div class="tiles">
      ${tile('team.a.done', fNum(at.done), T('team.a.done_s'))}
      ${tile('team.a.fail', at.fail_pct == null ? '—' : `${fNum(at.fail_pct)}<small>%</small>`, T('team.a.fail_s', { n: fNum(at.failed) }), at.fail_pct >= 10 ? 'warn' : '')}
      ${tile('team.a.recovered', fNum(at.retried_ok), T('team.a.recovered_s'))}
      ${tile('team.a.median', at.classifier_median_s == null ? '—' : esc(fSecs(at.classifier_median_s)), T('team.a.median_s'))}
      ${tile('team.a.tokens', `<span class="ltr-num">${compact(at.tokens_in)} / ${compact(at.tokens_out)}</span>`, T('team.a.tokens_s'))}</div>`;
    const causeChips = (c) => Object.entries(c || {}).sort((a, b) => b[1] - a[1]).map(([k, n]) => `<span class="chip ${k === 'restart' || k === 'engine' ? 'warn' : 'bad'} cause">${T('tasks.cause.' + k)} ${fNum(n)}</span>`).join(' ') || '<span class="faint">—</span>';
    const agRows = ag.table.length ? ag.table.map((r) => `<tr><td><span class="pdot" style="background:${agColor(r.agent)}"></span><b>${esc(agName(r.agent))}</b><div class="faint mono tiny">${esc(r.models.join(', ') || '—')}</div></td>
        <td class="num"><b>${fNum(r.ok)}</b></td><td class="num">${r.failed ? `<span class="c-red">${fNum(r.failed)}</span>` : '0'} <span class="faint">${r.fail_pct != null ? `(${fNum(r.fail_pct)}%)` : ''}</span></td>
        <td class="num">${fNum(r.retried_ok)}</td><td class="num">${r.median_s == null ? '—' : esc(fSecs(r.median_s))}</td><td class="num hide-sm">${r.p95_s == null ? '—' : esc(fSecs(r.p95_s))}</td>
        <td class="num hide-sm"><span class="ltr-num">${r.model_calls ? `${compact(r.tokens_in)} / ${compact(r.tokens_out)}` : '—'}</span></td><td class="hide-sm">${causeChips(r.causes)}</td></tr>`).join('')
      : `<tr><td colspan="8" class="empty">${T('team.no_steps')}</td></tr>`;
    const ro = d.routing || {};
    const routeRow = (k, label) => { const x = ro[k] || {}; const tot = DEC_KEYS.reduce((a, j) => a + (x[j] || 0), 0);
      return `<div class="route-row"><div class="route-l"><b>${T(label)}</b><span class="faint">${fNum(tot)} ${T('team.decisions_unit')}</span></div>${splitBar(DEC_KEYS.map((j) => ({ v: x[j] || 0, label: t('review.decision.' + j), color: decColor[j] })), { label: t(label) })}
        <div class="route-n faint ltr-num">${tot ? `${pct(x.approve || 0, tot)}% ${t('team.short.approve')}` : '—'}</div></div>`; };
    const routing = `<section class="card"><div class="card-h"><h2>${T('team.r.title')}</h2></div>
      ${routeRow('suggested', 'team.r.suggested')}${routeRow('referred', 'team.r.referred')}
      ${ro.arms ? `<div class="route-sep"></div>${(() => { ro.baseline = ro.arms.baseline; ro.profile = ro.arms.profile; return routeRow('baseline', 'team.r.baseline') + routeRow('profile', 'team.r.profile'); })()}` : ''}
      <p class="faint mt-s">${T('team.r.note')}</p></section>`;
    setPage(`${head('team.title', 'team.subtitle', `${sim}${range}`)}
      ${short ? `<div class="notice warn mb">${ico('warn')}<span>${T(tm.specialists ? 'team.too_few' : 'set.workflow.no_specialists', { n: fNum(tm.specialists), min: fNum(tm.min_specialists) })}</span></div>` : ''}
      <h2 class="section-title">${ico('users')} ${T('team.sec.people')}</h2>
      ${tiles}
      <div class="grid team-grid mt"><section class="card"><div class="card-h"><h2>${T('team.c.decisions')}</h2><span class="faint">${esc(fDay(d.range.from))} – ${esc(fDay(d.range.to))}</span></div>${decChart}</section>
        <section class="card"><div class="card-h"><h2>${T('team.c.milestones')}</h2></div><ol class="ms-list">${msList}</ol></section></div>
      ${peopleCard}
      <h2 class="section-title">${ico('brain')} ${T('team.sec.agents')}</h2>
      ${agTiles}
      <div class="grid team-grid mt"><section class="card"><div class="card-h"><h2>${T('team.c.steps')}</h2><span class="faint">${T('team.c.steps_s')}</span></div>${agChart}</section>${routing}</div>
      <section class="card mt"><div class="card-h"><h2>${T('team.c.agents')}</h2></div>
        <div class="table-wrap"><table class="t"><thead><tr><th>${T('tasks.agent')}</th><th class="num">${T('team.col.done')}</th><th class="num">${T('team.col.failed')}</th><th class="num">${T('team.col.recovered')}</th><th class="num">${T('team.col.median')}</th><th class="num hide-sm">p95</th><th class="num hide-sm">${T('team.col.tokens')}</th><th class="hide-sm">${T('team.col.causes')}</th></tr></thead><tbody>${agRows}</tbody></table></div>
        <p class="faint mt-s">${T('team.caption')}</p></section>`);
    wireTips($('#app') || document);
  }

  // ------------------------------------------------------------ tasks
  // A retry is not a new task: it is attempt n of the original. Lists show one row per
  // original with the combined result (last outcome of every step); attempts fold under it.
  const effOf = (x) => (x.chain && x.chain.effective) || { status: x.status, done: x.done_steps, failed: x.failed_steps,
    skipped: x.skipped_steps, total: x.total_steps, retries: 0, recovered: false };
  const stepBar = (done, skipped, failed, total) => `<div class="bar"><i style="width:${pct(done + skipped, total)}%"></i><i class="r" style="width:${pct(failed, total)}%"></i></div>`;
  const stepCounts = (done, failed, skipped, total) => `<span dir="ltr" class="ltr-num">${fNum(done)}✓ ${failed ? `${fNum(failed)}✕ ` : ''}${skipped ? `${fNum(skipped)}↷ ` : ''}/ ${fNum(total)}</span>`;
  const taskTitle = (x) => `<bdi dir="auto">${esc(x.title_ar)}</bdi>`;  // Arabic titles keep their order in an English page
  const attemptName = (a) => (a.n ? T('tasks.retry_n', { n: a.n }) : T('tasks.original'));
  const causeChip = (c) => (c ? ` <span class="chip ${c === 'restart' || c === 'engine' ? 'warn' : 'bad'} cause">${T('tasks.cause.' + c)}</span>` : '');
  const recoveredChip = (e) => (e.recovered ? ` <span class="chip ok" title="${T('tasks.after_retries', { n: e.retries })}">${ico('refresh')} ${T('tasks.after_retries', { n: e.retries })}</span>` : '');
  const attemptsOpen = (x) => {
    const atts = (x.chain && x.chain.attempts) || [];
    if (atts.length < 2) return false;
    S.taskOpen = S.taskOpen || {};
    if (x.id in S.taskOpen) return S.taskOpen[x.id];
    return atts.some((a) => a.n && ['queued', 'running'].includes(a.status));  // a retry is running: show it
  };
  const attemptsToggle = (x, open) => {
    const e = effOf(x);
    if (!e.retries) return '';
    return `<button type="button" class="att-toggle ${open ? 'on' : ''}" data-act="toggle-attempts" data-id="${x.id}" aria-expanded="${open}"
      title="${T('tasks.retries_title', { n: e.retries })}" aria-label="${T('tasks.retries_title', { n: e.retries })}">${ico('chev', 'chev')}${ico('refresh')}<b>${fNum(e.retries)}</b></button>`;
  };
  function taskGroupRows(x, { compact = false } = {}) {
    const e = effOf(x);
    const atts = (x.chain && x.chain.attempts) || [];
    const open = attemptsOpen(x);
    const main = `<tr class="click grp ${open ? 'open' : ''}" data-href="#/tasks/${x.id}" data-grp="${x.id}">
        <td class="mono">#${x.id}</td><td${compact ? ' style="min-width:200px"' : ''}><div class="task-title">${taskTitle(x)}${x.params && x.params.bulk ? ` <span class="chip warn">${T('tasks.bulk')}</span>` : ''}${attemptsToggle(x, open)}</div></td>
        <td>${statusChip(e.status)}${compact ? '' : recoveredChip(e)}</td>
        <td class="${compact ? 'hide-sm' : ''}" style="min-width:${compact ? 120 : 140}px">${stepBar(e.done, e.skipped, e.failed, e.total)}</td>
        <td class="num">${compact ? `<span dir="ltr" class="ltr-num">${fNum(e.done + e.skipped)}/${fNum(e.total)}</span>` : stepCounts(e.done, e.failed, e.skipped, e.total)}</td>
        ${compact ? '' : `<td class="hide-sm">${esc(x.created_by_name || '')}</td><td class="num hide-sm">${esc(fDT(x.created_at))}</td>`}</tr>`;
    if (atts.length < 2) return main;
    const subs = atts.map((a, i) => `<tr class="click sub ${i === atts.length - 1 ? 'last' : ''}" data-href="#/tasks/${a.id}" data-parent="${x.id}" ${open ? '' : 'hidden'}>
        <td class="mono faint">#${a.id}</td><td><span class="tree" aria-hidden="true"></span><span class="att-name">${attemptName(a)}</span>${causeChip(a.cause)}</td>
        <td>${statusChip(a.status)}</td>
        <td class="${compact ? 'hide-sm' : ''}">${stepBar(a.done_steps, a.skipped_steps, a.failed_steps, a.total_steps)}</td>
        <td class="num">${compact ? `<span dir="ltr" class="ltr-num">${fNum(a.done_steps + a.skipped_steps)}/${fNum(a.total_steps)}</span>` : stepCounts(a.done_steps, a.failed_steps, a.skipped_steps, a.total_steps)}</td>
        ${compact ? '' : `<td class="hide-sm">${esc(a.created_by_name || '')}</td><td class="num hide-sm">${esc(fDT(a.created_at))}</td>`}</tr>`).join('');
    return main + subs;
  }
  function toggleAttempts(id) {
    const head = $(`tr[data-grp="${id}"]`);
    if (!head) return;
    const open = !head.classList.contains('open');
    S.taskOpen = S.taskOpen || {};
    S.taskOpen[id] = open;
    head.classList.toggle('open', open);
    const b = $('.att-toggle', head);
    if (b) { b.classList.toggle('on', open); b.setAttribute('aria-expanded', String(open)); }
    $$(`tr[data-parent="${id}"]`).forEach((r) => { r.hidden = !open; });
  }

  async function viewTasks() {
    const load = async () => {
      const d = await api('/tasks');
      const rows = d.tasks.length ? d.tasks.map((x) => taskGroupRows(x)).join('')
        : `<tr><td colspan="7" class="empty">${T('tasks.empty')}</td></tr>`;
      setPage(`${head('tasks.title', 'tasks.subtitle', canDo('run_tasks') ? `<button class="btn primary" data-act="new-task">${ico('plus')} ${T('tasks.new')}</button>` : '')}
        <div class="table-wrap"><table class="t tasks-t"><thead><tr><th>#</th><th>${T('tasks.kind')}</th><th>${T('common.status')}</th><th>${T('tasks.steps')}</th><th></th><th class="hide-sm">${T('tasks.created_by')}</th><th class="hide-sm">${T('common.created')}</th></tr></thead><tbody>${rows}</tbody></table></div>`);
    };
    await load();
    every(4000, () => { if (!$('.modal')) load().catch(() => {}); });
  }

  function newTaskModal(preset = {}) {
    const sample = sampleAyah();
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
        <div class="field"><span class="label">${T('tasks.variant')}</span>
          <div class="seg" role="radiogroup">${['baseline', 'profile', 'ab'].map((v) => `<button type="button" data-variant="${v}" class="${v === (preset.variant || 'baseline') ? 'on' : ''}">${T('variant.' + v)}</button>`).join('')}</div>
          <p class="faint mt-s" id="variant-hint">${T('variant.hint.' + (preset.variant || 'baseline'))}</p></div>
        <label class="check"><input type="checkbox" id="skip" checked><span>${T('tasks.skip_done')}</span></label>
        <div id="task-preview" class="notice"><div class="spinner sm"></div></div>
        <div class="form-actions"><button type="button" class="btn" data-act="close-modal">${T('common.cancel')}</button>
          <button type="submit" class="btn primary" id="task-go">${ico('play')} ${T('tasks.run')}</button></div>
      </form>`);
    let scope = preset.scope || 'sample';
    let variant = preset.variant || 'baseline';
    const body = () => ({ kind: $('input[name=kind]:checked', m).value, scope, ayat: $('#ayat', m).value,
      tafsirs: $$('input[name=taf]:checked', m).map((x) => x.value), skip_done: $('#skip', m).checked, variant });
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
      const v = e.target.closest('[data-variant]');
      if (v) { variant = v.dataset.variant; $$('[data-variant]', m).forEach((b) => b.classList.toggle('on', b === v)); $('#variant-hint', m).textContent = t('variant.hint.' + variant); preview(); }
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

  // automatic retries: which attempt, when it runs again, or that it waits for the engine
  const retryChip = (s) => {
    if (s.status !== 'queued' || !(s.attempt > 1 || s.not_before || s.interruptions)) return '';
    const engine = (s.last_error || '').includes('engine offline');
    const label = engine ? t('tasks.retry.engine') : s.attempt > 1 ? t('tasks.retry.at', { n: s.attempt, t: fTime(s.not_before) }) : t('tasks.retry.restart');
    return ` <span class="chip ${engine ? 'bad' : 'warn'}" title="${esc(s.last_error || '')}">${ico('refresh')} ${esc(label)}</span>`;
  };
  async function viewTask(id) {
    const load = async () => {
      const d = await api('/tasks/' + id);
      const x = d.task;
      const agentName = (a) => T('agent.' + a);
      const stepNote = (r) => {
        if (!r) return '';
        if (r.confirm != null) return ['confirm', 'reject', 'reframe', 'abstain', 'invalid'].filter((k) => r[k]).map((k) => `<span class="chip ${k === 'confirm' ? 'ok' : k === 'invalid' ? 'bad' : 'warn'}">${T('spec.verdict.' + k)} ${r[k]}</span>`).join(' ') || `<span class="faint">${T('dash.moves')} 0</span>`;
        if (r.moves != null) return `${T('dash.moves')} ${r.moves} · ${T('dash.candidates')} ${r.auto_candidate} · ${T('dash.specialist')} ${r.specialist}`;
        if (r.spans != null) return `spans ${r.spans}`;
        if (r.reason === 'agent_missing') {
          const m = r.missing || [];
          const k = m.length > 1 ? 'tasks.skip.no_both' : m[0] === 'classifier' ? 'tasks.skip.no_classifier' : 'tasks.skip.no_verifier';
          return `<span class="chip warn">${T(k)}</span>`;
        }
        if (r.reason === 'already_verified') return `<span class="faint">${T('tasks.skip.already')}</span>`;
        if (r.reason_code) return `<span class="chip bad mono">${esc(r.reason_code)}</span>`;
        return '';
      };
      // the chain this task belongs to: the original and its retries (attempt 1, 2, …)
      const ch = d.chain && d.chain.attempts && d.chain.attempts.length > 1 ? d.chain : null;
      const eff = ch ? ch.effective : effOf(x);
      const chainActive = ch ? ch.attempts.some((a) => ['queued', 'running'].includes(a.status)) : false;
      const isRetry = ch && ch.position > 0;
      const later = (s) => {  // on the original: which later attempt finished this step
        if (!ch || !ch.final) return '';
        const f = ch.final[`${s.agent}|${s.tafsir}|${s.window}|${s.variant || ''}`];
        if (!f || f.task_id === x.id) return '';
        return f.status === 'done' ? ` <a class="chip ok" href="#/tasks/${f.task_id}">${ico('check')} ${T('tasks.fixed_in', { id: f.task_id })}</a>`
          : ` <a class="chip ${['queued', 'running'].includes(f.status) ? 'info' : 'warn'}" href="#/tasks/${f.task_id}">${ico('refresh')} ${T('tasks.retried_in', { id: f.task_id })}</a>`;
      };
      const rows = d.steps.map((s) => `<tr class="click" data-act="step" data-id="${s.id}"><td class="num">${s.seq + 1}</td><td>${agentName(s.agent)}${s.variant ? ` <span class="chip violet" title="${T('variant.profile')}">${T('variant.short.' + s.variant)}</span>` : ''}</td><td>${esc(tafsirName(s.tafsir))}</td>
        <td class="mono">${esc(s.window)}</td><td class="mono hide-sm">${esc(s.model || '—')}</td><td>${statusChip(s.status)}${retryChip(s)}${causeChip(s.cause)}${later(s)}</td><td class="num">${fDur(s.duration_ms)}</td>
        <td class="hide-sm">${stepNote(s.result)}</td></tr>`).join('');
      const actions = [
        canDo('manage_tasks') && ['queued', 'running'].includes(x.status) ? `<button class="btn danger" data-act="cancel-task" data-id="${x.id}">${ico('stop')} ${T('tasks.cancel')}</button>` : '',
        canDo('run_tasks') && eff.failed && !chainActive && !['queued', 'running'].includes(x.status) ? `<button class="btn warn" data-act="retry-task" data-id="${x.id}" title="${T('tasks.retry_hint')}">${ico('refresh')} ${T('tasks.retry')}</button>` : '',
        `<a class="btn" href="#/tasks">${T('common.back')}</a>`].join('');
      const done = x.done_steps + x.skipped_steps;
      S.taskSteps = d.steps;
      const attempts = ch ? `<section class="card mb attempts-card"><div class="row between"><b>${T('tasks.attempts')}</b>
          <span class="row tight">${T('tasks.final')}: ${statusChip(eff.status)} <span class="faint num">${stepCounts(eff.done, eff.failed, eff.skipped, eff.total)}</span></span></div>
          <ol class="attempts">${ch.attempts.map((a) => `<li class="${a.id === x.id ? 'cur' : ''}"><a href="#/tasks/${a.id}" ${a.id === x.id ? 'aria-current="page"' : ''}>
            <span class="att-top"><span class="mono faint">#${a.id}</span> <b>${attemptName(a)}</b></span>
            <span class="att-mid">${statusChip(a.status)}${causeChip(a.cause)}</span>
            <span class="att-bot faint">${stepCounts(a.done_steps, a.failed_steps, a.skipped_steps, a.total_steps)} · ${esc(fDT(a.created_at))}</span></a></li>`).join('')}</ol>
          <p class="faint mt-s">${T('tasks.chain_note')}</p></section>` : '';
      const title = isRetry ? T('tasks.retry_of', { n: ch.position, id: ch.origin_id }) : taskTitle(x);
      setPage(`<div class="page-head"><div><div class="kicker">#${x.id}${isRetry ? ` · <a href="#/tasks/${ch.origin_id}">${T('tasks.original')} #${ch.origin_id}</a>` : ''}</div><h1>${title}</h1>
          <p class="muted">${statusChip(x.status)}${ch && !isRetry ? recoveredChip(eff) : ''} · ${T('tasks.created_by')} ${esc(x.created_by_name || '—')} · ${esc(fDT(x.created_at))}</p></div><div class="head-actions">${actions}</div></div>
        ${attempts}
        <section class="card mb"><div class="row between"><b>${fNum(done)} / ${fNum(x.total_steps)}${ch ? ` <span class="faint">· ${T(isRetry ? 'tasks.this_retry' : 'tasks.this_run')}</span>` : ''}</b><span class="faint">${fNum(x.failed_steps)} ${T('dash.failed')} · ${fNum(x.skipped_steps)} ${T('tasks.status.skipped')}</span></div>
          <div class="bar lg mt-s"><i style="width:${pct(done, x.total_steps)}%"></i><i class="r" style="width:${pct(x.failed_steps, x.total_steps)}%"></i></div>
          <p class="faint mt-s">${T('agent.classifier')}: <span class="mono">${esc((x.params.models || {}).classifier || '')}</span> · ${T('agent.verifier')}: <span class="mono">${esc((x.params.models || {}).verifier || '')}</span></p></section>
        <div class="table-wrap"><table class="t"><thead><tr><th>${T('tasks.step')}</th><th>${T('tasks.agent')}</th><th>${T('tasks.tafsir')}</th><th>${T('tasks.window')}</th><th class="hide-sm">${T('tasks.model')}</th><th>${T('common.status')}</th><th>${T('tasks.duration')}</th><th class="hide-sm">${T('tasks.result')}</th></tr></thead><tbody>${rows}</tbody></table></div>`);
      return ['queued', 'running'].includes(x.status) || chainActive;
    };
    const live = await load();
    if (live) every(3000, () => { if (!$('.modal')) load().catch(() => {}); });
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
    const sampleN = Number(sampleAyah().split(':')[1]);
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
    setPage(`${head('reports.title', 'reports.subtitle', canDo('generate_reports') ? `<button class="btn primary" data-act="gen-report" data-day="${d.today}">${ico('report')} ${T('reports.generate_today')}</button>` : '')}
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
      canDo('generate_reports') ? `<button class="btn" data-act="gen-report" data-day="${esc(day)}">${ico('refresh')} ${T('reports.regenerate')}</button>` : '',
      canDo('generate_reports') ? `<button class="btn primary" data-act="mail-report" data-day="${esc(day)}">${ico('mail')} ${T('reports.mail')}</button>` : '',
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
    const meId = S.me.id;
    const open = (u) => (u.decided || 0) < (u.moves || 0);
    if (!S.reviewFilter) S.reviewFilter = d.can_decide && d.my_open_windows ? 'mine' : d.units.some(open) ? 'pending' : 'all';
    const filters = [['pending', 'review.filter.pending'], ['all', 'review.filter.all']];
    if (d.can_decide) filters.unshift(['mine', 'review.filter.mine']);
    if (d.can_assign) filters.push(['unassigned', 'review.filter.unassigned']);
    if (!filters.some(([k]) => k === S.reviewFilter)) S.reviewFilter = filters[0][0];
    const units = d.units.filter((u) => S.reviewFilter === 'mine' ? u.assigned && u.assigned.user_id === meId && u.assigned.status === 'open'
      : S.reviewFilter === 'pending' ? open(u)
      : S.reviewFilter === 'unassigned' ? !u.assigned || u.assigned.status !== 'open' : true);
    const counts = { mine: d.units.filter((u) => u.assigned && u.assigned.user_id === meId && u.assigned.status === 'open').length,
      unassigned: d.units.filter((u) => u.committee && (!u.assigned || u.assigned.status !== 'open') && u.decided < u.moves).length,
      pending: d.units.filter(open).length, all: d.units.length };
    const armChip = (u) => u.arm ? `<span class="chip info" title="${T('review.arm_note')}">${T('review.arm', { a: u.arm })}${d.reveals_arms && u.variant ? ` · ${T('variant.short.' + u.variant)}` : ''}</span>` : '';
    const who = (u) => {
      const a = u.assigned;
      if (!a) return u.committee ? `<span class="faint">${T('review.unassigned')}</span>` : '<span class="faint">—</span>';
      const me = a.user_id === meId;
      return `<span class="chip ${a.status === 'done' ? 'ok' : me ? 'info' : ''}">${a.status === 'done' ? ico('check') + ' ' : ''}${esc(me ? t('review.you') : a.name || '—')}</span>`;
    };
    const rows = units.length ? units.map((u) => `<tr class="click" data-href="#/review/${u.tafsir}/${u.window}${u.arm ? '/' + u.arm : ''}"><td class="mono">${esc(u.ayah)}</td><td>${esc(u.name_ar)}</td>
      <td class="mono">${esc(u.window)} ${u.committee ? `<span class="chip violet">${T('dash.committee')}</span>` : ''} ${armChip(u)}</td><td class="num">${fNum(u.moves)}</td><td class="num hide-sm">${fNum(u.auto_candidate)}</td><td class="num hide-sm">${fNum(u.specialist)}</td>
      <td class="num hide-sm">${u.flags == null ? '—' : fNum(u.flags)}</td><td>${who(u)}</td><td class="num">${u.decided ? `<span class="chip ok">${fNum(u.decided)}/${fNum(u.moves)}</span>` : `<span class="chip">0/${fNum(u.moves)}</span>`}</td></tr>`).join('')
      : `<tr><td colspan="9" class="empty">${T(S.reviewFilter === 'mine' ? 'review.mine_empty' : S.reviewFilter === 'pending' && d.units.length ? 'review.pending_empty' : 'review.empty')}</td></tr>`;
    const tabs = `<div class="seg mb" role="tablist">${filters.map(([k, key]) => `<button type="button" role="tab" class="${S.reviewFilter === k ? 'on' : ''}" data-act="review-filter" data-f="${k}">${T(key)} <span class="chip">${fNum(counts[k])}</span></button>`).join('')}</div>`;
    const decideNote = !d.can_decide && has('review_units') ? `<div class="notice mb">${ico('shield')}<span>${T('review.specialists_only')}</span></div>` : '';
    setPage(`${head('review.title', 'review.subtitle', `<a class="btn outline-accent" href="#/review/learning">${ico('chart')} ${T('learn.title')}</a>${has('review_units') ? `<a class="btn" href="/api/review/export">${ico('download')} ${T('review.export')}</a>` : ''}`)}
      ${decideNote}${tabs}
      <p class="faint mb">${T('agent.classifier')}: <span class="mono">${esc(d.models.classifier)}</span> · ${T('dash.caption_counts')} · ${T('review.assign_note')}</p>
      <div class="table-wrap"><table class="t"><thead><tr><th>${T('progress.ayah')}</th><th>${T('tasks.tafsir')}</th><th>${T('tasks.window')}</th><th>${T('dash.moves')}</th><th class="hide-sm">${T('dash.candidates')}</th><th class="hide-sm">${T('dash.specialist')}</th><th class="hide-sm">${T('dash.flags')}</th><th>${T('review.assigned_to')}</th><th>${T('review.decided')}</th></tr></thead><tbody>${rows}</tbody></table></div>`);
  }
  async function viewReviewWindow(tafsir, win, arm) {
    const d = await api(`/review/${encodeURIComponent(tafsir)}/${encodeURIComponent(win)}${arm ? '?arm=' + encodeURIComponent(arm) : ''}`);
    const errTypes = d.error_types || {};
    const methods = d.methods || [];
    const names = d.method_names || {};
    // a method code shown by its Arabic name; a reply that is not one code (e.g. the copied list) says so
    const mName = (code) => !code ? '—' : names[code] ? `<span title="${esc(code)}">${esc(names[code])}</span>`
      : `<span class="chip bad" title="${esc(code)}">${T('review.invalid_output')}</span>`;
    const certName = (c) => !c ? '—' : ['explicit', 'strong', 'weak', 'insufficient'].includes(c) ? `<span title="${esc(c)}">${T('review.cert.' + c)}</span>` : esc(c);
    const lesson = (m, dec) => {
      if (!Object.keys(errTypes).length) return '';
      const t0 = (dec && dec.teach) || {};
      return `<details class="lesson"${t0.error_type || t0.teach || t0.correct_primary ? ' open' : ''}><summary>${ico('flask')} ${T('learn.lesson')}</summary>
        <div class="lesson-grid"><label class="field"><span class="label">${T('learn.error_type')}</span><select class="input" data-error>
          <option value="">${T('learn.error_none')}</option>${Object.entries(errTypes).map(([k, v]) => `<option value="${esc(k)}"${t0.error_type === k ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></label>
        <label class="field"><span class="label">${T('learn.correct')}</span><select class="input" data-correct>
          <option value="">${T('learn.correct_none')}</option>${methods.map((x) => `<option value="${esc(x)}"${t0.correct_primary === x ? ' selected' : ''}>${esc(names[x] || x)}</option>`).join('')}</select></label></div>
        <label class="check"><input type="checkbox" data-teach${t0.teach ? ' checked' : ''}><span>${T('learn.teach')}</span></label>
        <p class="faint">${T('learn.teach_note')}</p></details>`;
    };
    const decBtn = (dec, v, cls, label) => {
      const on = !!dec && dec.decision === v;
      return `<button class="btn ${cls}${on ? ' on' : ''}" data-act="decide" data-d="${v}" aria-pressed="${on}">${label}</button>`;
    };
    // after a decision: what was saved, and the controls folded behind «change decision»
    const decideBlock = (m, dec) => {
      const controls = `<div class="decide"${dec ? ' hidden' : ''}><div class="stack"><label class="check"><input type="checkbox" data-compare${dec && dec.compared_with_source ? ' checked' : ''}><span>${T('review.compare')}</span></label>
            <input class="input" data-note placeholder="${T('review.note_ph')}" maxlength="1000" value="${esc((dec && dec.note) || '')}">${lesson(m, dec)}</div>
          <div class="row">${decBtn(dec, 'approve', 'primary', `${ico('check')} ${T('review.approve')}`)}${decBtn(dec, 'needs_edit', 'warn', T('review.needs_edit'))}${decBtn(dec, 'reject', 'danger', `${ico('x')} ${T('review.reject')}`)}</div></div>`;
      if (!dec) return controls;
      return `<div class="decided-bar"><span class="saved ${dec.decision}">${ico('check')} ${T('review.saved_as', { d: t('review.decision.' + dec.decision) })}</span>${dec.note ? `<span class="faint note">${esc(dec.note)}</span>` : ''}
          <button type="button" class="btn sm" data-act="change-decision">${T('review.change')}</button></div>${controls}`;
    };
    const lessonChip = (dec) => {
      const t0 = (dec && dec.teach) || {};
      if (!t0.error_type && !t0.teach) return '';
      return `<span class="chip ${t0.teach ? 'ok' : ''}">${t0.teach ? T('learn.taught') : T('learn.lesson')}${t0.error_type ? ' · ' + esc(errTypes[t0.error_type] || t0.error_type) : ''}${t0.correct_primary ? ' → ' + esc(names[t0.correct_primary] || t0.correct_primary) : ''}</span>`;
    };
    const preview = {};
    (d.chair ? d.chair.moves : []).forEach((c) => { preview[c.move_id] = c; });
    const canDecide = canDo('review_units') && !!d.can_decide;
    const asg = d.assignment;
    const reasonChip = (code) => code ? `<span class="chip warn mono" title="${T('review.verifier_reason')}">${esc(code)}</span>` : '';
    // context: the window's pinned text, so each move is read with what comes before and after it
    const ctx = !d.simulated && d.context && d.context.text ? d.context : null;
    const CTX_CHARS = 280;
    const moveRange = (m) => {
      if (!ctx) return null;
      const r = (m.span_ids || []).map((id) => ctx.spans[id]).filter(Boolean);
      return r.length ? [Math.min(...r.map((x) => x[0])), Math.max(...r.map((x) => x[1]))] : null;
    };
    const moveInContext = (m) => {
      const r = moveRange(m);
      if (!r) return `<div class="move-text">${esc(m.text || '')}</div>`;
      const [a, b] = r;
      let before = ctx.text.slice(Math.max(0, a - CTX_CHARS), a);
      let after = ctx.text.slice(b, b + CTX_CHARS);
      const fromPrev = a < CTX_CHARS && ctx.prev ? `<span class="ctx-part">${T('review.ctx_prev_part')}</span>${esc(ctx.prev.text.slice(-(CTX_CHARS - a)))}<span class="ctx-sep"> ⋯ </span>` : '';
      const toNext = b + CTX_CHARS > ctx.text.length && ctx.next ? `<span class="ctx-sep"> ⋯ </span><span class="ctx-part">${T('review.ctx_next_part')}</span>${esc(ctx.next.text.slice(0, CTX_CHARS - (ctx.text.length - b)))}` : '';
      const cutBefore = a - CTX_CHARS > 0 ? '… ' : '';
      const cutAfter = b + CTX_CHARS < ctx.text.length ? ' …' : '';
      return `<div class="move-text move-ctx"><span class="ctx-out">${fromPrev}${cutBefore}${esc(before)}</span><mark class="ctx-cur">${esc(ctx.text.slice(a, b))}</mark><span class="ctx-out">${esc(after)}${cutAfter}${toNext}</span></div>`;
    };
    // the whole window with every move marked; a click jumps to that move
    const fullText = () => {
      if (!ctx) return '';
      const marks = d.moves.map((m) => ({ m, r: moveRange(m) })).filter((x) => x.r).sort((x, y) => x.r[0] - y.r[0]);
      let pos = 0; let html = '';
      for (const { m, r } of marks) {
        if (r[0] < pos) continue;   // overlapping moves: the first one keeps the mark
        html += esc(ctx.text.slice(pos, r[0]));
        html += `<mark class="ctx-mv ${m.decision ? 'done ' + m.decision.decision : 'open'}" data-act="goto-move" data-k="${esc(m.key)}" title="${esc(m.key)}"><b class="ctx-tag">${esc(m.key)}</b>${esc(ctx.text.slice(r[0], r[1]))}</mark>`;
        pos = r[1];
      }
      html += esc(ctx.text.slice(pos));
      return `<details class="card mb ctx-full"><summary>${ico('eye')} <b>${T('review.ctx_full')}</b> <span class="faint">${T('review.ctx_full_hint')}</span></summary>
        ${ctx.prev ? `<p class="faint ctx-edge">${T('review.ctx_prev_part')} <span class="mono">${esc(ctx.prev.window)}</span></p>` : ''}
        <div class="move-text ctx-doc">${html}</div>
        ${ctx.next ? `<p class="faint ctx-edge">${T('review.ctx_next_part')} <span class="mono">${esc(ctx.next.window)}</span></p>` : ''}</details>`;
    };
    const moves = d.moves.map((m) => {
      const c = m.committee;
      const p = preview[m.move_id];
      const dec = m.decision;
      const score = (m.score || {}).total;
      let chairChip = '';
      if (c) chairChip = `<span class="chip ${c.committee_route === 'auto_candidate' ? 'ok' : 'violet'}">${T('review.committee')}: ${c.committee_route === 'auto_candidate' ? T('route.auto_candidate') : T('review.reason.' + ((c.abstention_reasons || [])[0] || 'weak_evidence'))}</span>`;
      else if (p) chairChip = `<span class="chip ${p.committee_route === 'auto_candidate' ? 'ok' : 'violet'}" title="${T('review.chair_note')}">${T('review.chair')}: ${p.reason ? T('review.reason.' + p.reason) : T('route.auto_candidate')}</span>`;
      const agents = c ? `<div class="kv"><div><div class="k">${T('agent.classifier')}</div><div class="v">${mName(c.primary_proposer)} · ${c.score_proposer ?? '—'}</div></div>
          <div><div class="k">${T('agent.verifier')}</div><div class="v">${mName(c.primary_reviewer)} · ${c.score_reviewer ?? '—'}</div></div>
          <div><div class="k">${T('review.certainty')}</div><div class="v">${certName(m.certainty)}</div></div>
          <div><div class="k">${T('review.flags')}</div><div class="v mono" style="font-size:12px">${esc((m.flags || []).join(', ') || '—')}</div></div></div>`
        : `<div class="kv"><div><div class="k">${T('review.primary')}</div><div class="v">${mName(m.primary)}</div></div>
          <div><div class="k">${T('review.certainty')}</div><div class="v">${certName(m.certainty)}</div></div>
          <div><div class="k">${T('review.score')}</div><div class="v">${score ?? '—'}</div></div>
          <div><div class="k">${T('review.flags')}</div><div class="v mono" style="font-size:12px">${esc((m.flags || []).join(', ') || '—')}</div></div></div>`;
      const article = `<article class="move" data-move="${esc(m.key)}"${dec ? ' data-decided="1"' : ''}>
        <div class="row between"><div class="row"><b class="mono">${esc(m.key)}</b><span class="chip ${m.route === 'auto_candidate' ? 'ok' : 'warn'}">${T('route.' + (m.route || 'specialist'))}</span>
          ${chairChip}${reasonChip(m.reason_code)}</div>
          <div class="row">${dec ? `<span class="chip ${dec.decision === 'approve' ? 'ok' : dec.decision === 'reject' ? 'bad' : 'warn'}">${T('review.decision.' + dec.decision)} · ${esc(dec.user_name)} · ${esc(fDT(dec.created_at))}</span>` : ''}${lessonChip(dec)}</div></div>
        ${agents}
        ${c && c.abstention_ar ? `<p class="faint mb" dir="rtl">${esc(c.abstention_ar)}</p>` : ''}
        ${m.method_specialist ? (() => { const sv = m.method_specialist; return `<div class="spec-note"><span class="chip ${sv.verdict === 'confirm' ? 'ok' : sv.verdict === 'invalid' ? 'bad' : 'warn'}">${ico('flask')} ${T('spec.title', { f: T('learn.family.' + sv.family) })}: ${T('spec.verdict.' + sv.verdict)}${sv.primary ? ` · ${mName(sv.primary)}` : ''}</span>${sv.reason_code && sv.reason_code !== 'ok' ? ` <span class="chip">${esc(errTypes[sv.reason_code] || sv.reason_code)}</span>` : ''}${sv.note_ar ? `<span class="faint" dir="rtl">${esc(sv.note_ar)}</span>` : ''}</div>`; })() : ''}
        <div class="label mb">${T('review.text')} <span class="faint mono">${esc((m.span_ids || []).join(' '))}</span>${ctx ? ` <span class="faint">· ${T('review.ctx_hint')}</span>` : ''}</div>
        ${d.simulated ? `<div class="move-text sim">${ico('flask')} ${T('demo.text_hidden')}</div>` : moveInContext(m)}
        ${m.rationale_ar ? `<p class="faint mt-s"><b>${T('review.rationale')}</b> (${T('review.rationale_note')}): <span dir="rtl">${esc(m.rationale_ar)}</span></p>` : ''}
        ${canDecide ? decideBlock(m, dec) : ''}
      </article>`;
      if (!dec || S.reviewShowDecided) return article;
      // decided moves fold to one line so what is still open stands out
      return `<details class="move-fold"><summary><b class="mono">${esc(m.key)}</b><span class="chip ${dec.decision === 'approve' ? 'ok' : dec.decision === 'reject' ? 'bad' : 'warn'}">${T('review.decision.' + dec.decision)}</span>
        <span class="fold-text">${d.simulated ? '' : esc((m.text || '').slice(0, 120))}</span></summary>${article}</details>`;
    }).join('') || `<div class="empty">${T('common.empty')}</div>`;
    const nDone = d.moves.filter((m) => m.decision).length;
    const progress = d.moves.length ? `<div class="review-progress mb"><span>${T('review.progress', { done: fNum(nDone), total: fNum(d.moves.length) })}</span>
        ${nDone ? `<button type="button" class="btn sm" data-act="toggle-decided">${T(S.reviewShowDecided ? 'review.hide_decided' : 'review.show_decided', { n: fNum(nDone) })}</button>` : ''}</div>
      ${nDone === d.moves.length ? `<div class="notice mb">${ico('check')}<span>${T('review.window_done')}</span><a class="btn sm" href="#/review">${T('review.back_to_list')}</a></div>` : ''}` : '';
    const sum = d.summary || {};
    const reasons = Object.entries(sum.by_abstention_reason || {}).filter(([, v]) => v).map(([k, v]) => `<span class="chip violet">${T('review.reason.' + k)} ${fNum(v)}</span>`).join(' ');
    const mdl = d.models ? `${T('agent.classifier')}: <span class="mono">${esc((d.models.proposer || {}).tag || '')}</span> · ${T('agent.verifier')}: <span class="mono">${esc((d.models.reviewer || {}).tag || '')}</span>` : '';
    S.reviewCtx = { tafsir, win, arm: arm || '' };
    setPage(`<div class="page-head"><div><div class="kicker">${T('review.title')}</div><h1>${esc(d.name_ar)} · <span class="mono">${esc(d.window)}</span>${d.arm ? ` <span class="chip info">${T('review.arm', { a: d.arm })}${d.variant ? ' · ' + T('variant.short.' + d.variant) : ''}</span>` : ''}</h1>
        <p class="muted">${T('progress.ayah')} <span class="mono">${esc(d.ayah)}</span> · ${d.simulated ? T('demo.source_none') : `${T('review.source')}: <span class="mono">${esc(d.source_file)}</span> · sha256 <span class="mono">${esc((d.source_sha256 || '').slice(0, 12))}…</span>`}</p></div>
        <div class="head-actions"><a class="btn" href="#/review">${T('common.back')}</a></div></div>
      ${asg || (d.specialists || []).length ? `<section class="card mb assign-bar"><div class="row between"><div class="row">${ico('inbox')}<b>${T('review.assigned_to')}</b>
          ${asg ? `<span class="chip ${asg.status === 'done' ? 'ok' : asg.user_id === S.me.id ? 'info' : ''}">${esc(asg.user_id === S.me.id ? t('review.you') : asg.name || '—')}</span><span class="faint">${T(asg.assigned_by ? 'review.assigned_manual' : 'review.assigned_chair')} · ${esc(fDT(asg.assigned_at))}</span>` : `<span class="faint">${T('review.unassigned')}</span>`}</div>
          ${(d.specialists || []).length && canDo('manage_tasks') ? `<div class="row"><select class="input sm" id="reassign-to" aria-label="${T('review.reassign')}">${d.specialists.map((p) => `<option value="${p.id}" ${asg && asg.user_id === p.id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>
            <button class="btn sm" data-act="reassign" data-t="${esc(tafsir)}" data-w="${esc(win)}">${T('review.reassign')}</button>
            ${asg && asg.status === 'open' && asg.user_id !== S.me.id && !inDemo() ? `<button class="btn sm" data-act="remind-assignee" data-id="${asg.user_id}" title="${T('team.remind_hint')}">${ico('mail')} ${T('team.remind')}</button>` : ''}</div>` : ''}</div></section>` : ''}
      ${canDecide ? '' : `<div class="notice mb">${ico('info')}<span>${inDemo() ? T('demo.read_only') : viewingAs() ? T('viewas.note')
        : !S.me.can_decide ? T('review.specialists_only') : asg && asg.status === 'open' && asg.user_id !== S.me.id ? T('review.assigned_other', { name: asg.name || '—' }) : T('review.read_only')}</span></div>`}
      ${d.arm ? `<div class="notice mb">${ico('info')}<span>${T('review.arm_note')}</span></div>` : ''}
      <div class="notice mb">${ico('shield')}<span>${T('review.subtitle')} ${d.is_committee ? T('review.committee_note') : T('review.chair_note')}</span></div>
      ${d.is_committee ? `<section class="card mb"><div class="row between"><div class="row"><b>${T('review.committee')}</b> ${mdl}</div>
        <span class="faint">${T('dash.moves')} ${fNum(sum.move_count)} · ${T('dash.candidates')} ${fNum(sum.auto_candidate)} · ${T('dash.specialist')} ${fNum(sum.specialist)} · ${esc(sum.caption || '')}</span></div>
        ${reasons ? `<div class="row mt-s">${reasons}</div>` : ''}</section>` : ''}
      ${fullText()}${progress}${moves}`);
    if (S.reviewFocus) {
      const next = $(`[data-move="${CSS.escape(S.reviewFocus)}"]`);
      S.reviewFocus = null;
      if (next) next.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }
  }

  async function viewLearning() {
    const d = await api('/learning');
    const fam = (k) => T('learn.family.' + k);
    const errs = d.errors.length ? d.errors.map((e) => `<span class="chip warn">${esc(e.label_ar)} ${fNum(e.count)}</span>`).join(' ') : `<span class="faint">${T('learn.no_errors')}</span>`;
    const abTable = (ab) => {
      if (!ab) return '';
      if (ab.error) return `<p class="faint">${esc(ab.error)}</p>`;
      if (!ab.paired_windows.length) return `<p class="faint mt-s">${T('learn.ab_none')}</p>`;
      const row = (k) => { const a = ab.arms[k]; return `<tr><td><b>${T('learn.arm_' + k)}</b></td><td class="num">${fNum(a.windows)}</td><td class="num">${fNum(a.moves)}</td><td class="num">${fNum(a.auto_candidate)}</td><td class="num">${fNum(a.specialist)}</td><td class="num">${fNum(a.trap_hits)}</td><td class="num">${fNum(a.trap_hits_candidates)}</td></tr>`; };
      return `<div class="table-wrap mt-s"><table class="t"><thead><tr><th>${T('learn.arm')}</th><th>${T('dash.windows')}</th><th>${T('dash.moves')}</th><th>${T('dash.candidates')}</th><th>${T('dash.specialist')}</th><th>${T('learn.traps')}</th><th>${T('learn.traps_cand')}</th></tr></thead><tbody>${row('A')}${row('B')}</tbody></table></div>
        <p class="faint mt-s">${T('learn.traps_note')} · ${esc(ab.caption_ar)}</p>`;
    };
    const cards = d.tafsirs.map((x) => {
      const p = x.profile;
      const bank = x.bank || { count: 0, by_family: {} };
      const dec = x.decisions || {};
      return `<section class="card mb"><div class="row between"><div class="row"><h2>${esc(x.name_ar)}</h2>${p ? `<span class="chip ${p.status === 'draft' ? 'warn' : 'ok'}" title="${esc(p.status_ar || p.status)}">${T('learn.profile')} <bdi class="mono">${esc(p.version)}</bdi> · ${T('learn.status.' + (p.status === 'draft' ? 'draft' : 'reviewed'))}</span>` : `<span class="chip bad">${T('learn.no_profile')}</span>`}</div>
          <span class="faint">${T('learn.bank', { n: fNum(bank.count) })}</span></div>
        <div class="row mt-s">${Object.entries(bank.by_family).map(([k, v]) => `<span class="chip ok">${fam(k)} ${fNum(v)}</span>`).join('') || `<span class="faint">${T('learn.bank_empty')}</span>`}</div>
        <p class="faint mt-s">${T('review.decision.approve')} ${fNum(dec.approve || 0)} · ${T('review.decision.needs_edit')} ${fNum(dec.needs_edit || 0)} · ${T('review.decision.reject')} ${fNum(dec.reject || 0)} · ${T('learn.lessons')} ${fNum(dec.lessons || 0)}</p>
        ${p ? `<details class="mt-s"><summary>${T('learn.rules')}</summary><ol class="rules" dir="rtl">${(p.golden_rules_ar || []).map((r) => `<li>${esc(r)}</li>`).join('')}</ol>
          <p class="faint" dir="rtl">${esc(p.source_ar || '')}</p></details>` : ''}
        ${d.reveals_arms ? abTable(x.ab) : ''}</section>`;
    }).join('');
    setPage(`${head('learn.title', 'learn.subtitle', `<a class="btn" href="#/review">${T('common.back')}</a>`)}
      <section class="card mb"><h2>${T('learn.how')}</h2><ol class="steps mt-s">${[1, 2, 3, 4].map((i) => `<li>${T('learn.how.' + i)}</li>`).join('')}</ol></section>
      <div class="grid g3 mb"><div class="card"><div class="kicker">${T('learn.lessons')}</div><div class="stat">${fNum(d.lessons)}</div></div>
        <div class="card"><div class="kicker">${T('learn.decisions')}</div><div class="stat">${fNum(d.decisions)}</div></div>
        <div class="card"><div class="kicker">${T('learn.errors')}</div><div class="row mt-s">${errs}</div></div></div>
      ${cards}`);
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
      <td><div class="row tight">${(x.roles && x.roles.length ? x.roles : [{ key: x.role_key, name_ar: x.role_name_ar, name_en: x.role_name_en }]).map((r) => `<span class="chip ${r.key === 'specialist' ? 'info' : r.key === 'super_admin' ? 'warn' : ''}">${esc(roleName(r))}</span>`).join('')}</div></td><td class="hide-sm">${esc(((S.pub.languages || []).find((l) => l.code === x.lang) || {}).name_native || t('users.lang_default'))}</td>
      <td>${x.active ? `<span class="chip ok">${T('common.active')}</span>` : `<span class="chip bad">${T('common.inactive')}</span>`}</td>
      <td class="num hide-sm">${x.last_login_at ? esc(fDT(x.last_login_at)) : T('common.never')}</td>
      <td class="num">${canAdmin('manage_users') ? `<button class="btn sm" data-act="edit-user" data-id="${x.id}">${T('common.edit')}</button>` : ''}</td></tr>`).join('');
    setPage(`${head('users.title', 'users.subtitle', canAdmin('manage_users') ? `<button class="btn primary" data-act="add-user">${ico('plus')} ${T('users.add')}</button>` : '')}
      <div class="table-wrap"><table class="t"><thead><tr><th>${T('users.name')}</th><th>${T('users.roles')}</th><th class="hide-sm">${T('users.lang')}</th><th>${T('common.status')}</th><th class="hide-sm">${T('users.last_login')}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`);
  }
  function userModal(user) {
    const langs = (S.pub.languages || []).map((l) => `<option value="${esc(l.code)}" ${user && user.lang === l.code ? 'selected' : ''}>${esc(l.name_native)}</option>`).join('');
    const held = new Set(user ? (user.role_ids || [user.role_id]) : []);
    const roles = rolesCache.map((r) => `<label class="check role-pick"><input type="checkbox" name="u-roles" value="${r.id}" ${held.has(r.id) ? 'checked' : ''}><span><b>${esc(roleName(r))}</b><span class="faint" dir="rtl">${esc(r.description_ar || '')}</span></span></label>`).join('');
    const m = modal(`${modalHead(user ? t('common.edit') + ' · ' + user.name : t('users.add'))}
      <form id="f-user" class="form-grid">
        <div class="field full"><label for="u-email">${T('users.email')}</label><input class="input ltr" id="u-email" type="email" required value="${esc(user ? user.email : '')}" ${user ? 'disabled' : ''}></div>
        <div class="field"><label for="u-name">${T('users.name')}</label><input class="input" id="u-name" required maxlength="80" value="${esc(user ? user.name : '')}"></div>
        <div class="field full"><span class="label">${T('users.roles')}</span><div class="role-grid">${roles}</div><span class="hint">${T('users.roles_hint')}</span></div>
        <div class="field"><label for="u-lang">${T('users.lang')}</label><select class="input" id="u-lang"><option value="">${T('users.lang_default')}</option>${langs}</select></div>
        <div class="field"><span class="label">${T('common.status')}</span><label class="switch"><input type="checkbox" id="u-active" ${!user || user.active ? 'checked' : ''}><span>${T('common.active')}</span></label></div>
        ${user ? '' : `<div class="field full"><label class="switch"><input type="checkbox" id="u-notify" checked><span>${T('users.notify')}</span></label><span class="hint">${T('users.notify_hint')}</span></div>`}
        <div class="form-actions full">${user ? `<button type="button" class="btn ghost" data-act="revoke-user" data-id="${user.id}">${T('users.revoke')}</button>` : ''}
          <button type="button" class="btn" data-act="close-modal">${T('common.cancel')}</button><button type="submit" class="btn primary">${T('common.save')}</button></div></form>`);
    $('#f-user', m).addEventListener('submit', async (e) => {
      e.preventDefault();
      const roleIds = $$('input[name=u-roles]:checked', m).map((x) => Number(x.value));
      if (!roleIds.length) { toast(t('users.err.no_role'), 'bad'); return; }
      const body = { name: $('#u-name', m).value.trim(), role_ids: roleIds, lang: $('#u-lang', m).value, active: $('#u-active', m).checked };
      try {
        if (user) await api('/users/' + user.id, { method: 'PATCH', body });
        else {
          const r = await api('/users', { method: 'POST', body: { ...body, email: $('#u-email', m).value.trim(), notify: $('#u-notify', m).checked } });
          if (r.mailed === false) toast(t('users.notify_failed'), 'bad');
          else if (r.mailed) toast(t('users.notify_sent'), 'ok');
        }
        closeModal(); if (user) toast(t('common.saved'), 'ok'); render();
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
        ${r.system || !canAdmin('manage_roles') ? '' : `<div class="row"><button class="btn sm" data-act="edit-role" data-id="${r.id}">${T('common.edit')}</button><button class="btn sm danger" data-act="del-role" data-id="${r.id}">${T('common.delete')}</button></div>`}</div>
        <p class="muted" dir="rtl" style="text-align:start">${esc(r.description_ar)}</p>
        <div class="row mt-s">${r.permissions.map((p) => `<span class="chip ok">${T('perm.' + p)}</span>`).join('')}</div></section>`).join('');
    setPage(`${head('roles.title', 'roles.subtitle', canAdmin('manage_roles') ? `<button class="btn primary" data-act="add-role">${ico('plus')} ${T('roles.add')}</button>` : '')}<div class="grid g2">${cards}</div>`);
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
  const TABS = ['general', 'llm', 'smtp', 'security', 'gates', 'reports', 'workflow', 'demo', 'languages', 'outbox'];
  async function viewSettings(tab) {
    if (tab && TABS.includes(tab)) S.settingsTab = tab;
    const tabNav = `<div class="tabs" role="tablist">${TABS.filter((x) => x !== 'languages' || has('manage_languages')).map((x) => `<button role="tab" class="${x === S.settingsTab ? 'on' : ''}" data-act="tab" data-tab="${x}">${T('settings.tab.' + x)}</button>`).join('')}</div>`;
    setPage(`${head('settings.title', 'settings.subtitle')}${tabNav}<div id="tab-body">${loading()}</div>`);
    const body = $('#tab-body');
    const tabFn = { languages: tabLanguages, outbox: tabOutbox, demo: tabDemo }[S.settingsTab] || tabSection;
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
        + fieldFor(sec, 'surah', v.surah) + fieldFor(sec, 'data_root', v.data_root, { ltr: true }) + fieldFor(sec, 'sample_ayah', v.sample_ayah, { ltr: true })
        + fieldFor(sec, 'console_url', v.console_url, { ltr: true, full: true, ph: 'https://console.mirqah.app', hint: T('set.general.console_url_hint') });
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
    } else if (sec === 'workflow') {
      const [r, w] = await Promise.all([api('/roles'), api('/workflow')]);
      fields = `<div class="notice full">${ico('inbox')}<span>${T('set.workflow.note')}</span></div>`
        + fieldFor(sec, 'auto_assign', v.auto_assign, { full: true, hint: T('set.workflow.auto_assign_hint') })
        + fieldFor(sec, 'reminders', v.reminders, { full: true })
        + fieldFor(sec, 'min_specialists', v.min_specialists)
        + fieldFor(sec, 'reminder_time', v.reminder_time, { type: 'time', ltr: true })
        + fieldFor(sec, 'auto_retry', v.auto_retry, { full: true, hint: T('set.workflow.auto_retry_hint') })
        + fieldFor(sec, 'retry_first_min', v.retry_first_min) + fieldFor(sec, 'retry_second_min', v.retry_second_min)
        + fieldFor(sec, 'retry_max', v.retry_max)
        + fieldFor(sec, 'failure_alerts', v.failure_alerts, { full: true, hint: T('set.workflow.failure_alerts_hint') })
        + `<div class="field full"><span class="label">${T('set.workflow.alert_roles')}</span><div class="perm-grid">${r.roles.map((x) => `<label class="check"><input type="checkbox" name="alert_roles" value="${esc(x.key)}" ${v.alert_roles.includes(x.key) ? 'checked' : ''}><span>${esc(roleName(x))}</span></label>`).join('')}</div></div>`;
      const team = (w.specialists || []).map((p) => `<tr><td>${esc(p.name)}</td><td class="num">${fNum(p.open_windows)}</td><td class="num">${fNum(p.open_moves)}</td><td class="num">${p.oldest_days ? fNum(Math.round(p.oldest_days)) : '—'}</td><td class="num">${fNum(p.decided_today)}</td></tr>`).join('')
        || `<tr><td colspan="5" class="empty">${T('set.workflow.no_specialists')}</td></tr>`;
      extra = `<section class="card mt"><div class="card-h"><h3>${T('set.workflow.team')}</h3><span class="chip ${w.enough_specialists ? 'ok' : 'warn'}">${fNum((w.specialists || []).length)} / ${fNum(w.min_specialists)}</span></div>
        <div class="table-wrap"><table class="t"><thead><tr><th>${T('users.name')}</th><th>${T('set.workflow.open_windows')}</th><th>${T('set.workflow.open_moves')}</th><th>${T('set.workflow.oldest')}</th><th>${T('set.workflow.today')}</th></tr></thead><tbody>${team}</tbody></table></div>
        ${canDo('manage_tasks') ? `<div class="row mt"><button class="btn" type="button" data-act="wf-sweep">${ico('inbox')} ${T('set.workflow.sweep')}</button><button class="btn" type="button" data-act="wf-remind">${ico('mail')} ${T('set.workflow.remind')}</button></div>` : ''}</section>`;
    } else if (sec === 'reports') {
      const r = await api('/roles');
      fields = fieldFor(sec, 'auto_daily', v.auto_daily, { full: true }) + fieldFor(sec, 'daily_time', v.daily_time, { type: 'time', ltr: true })
        + `<div class="field full"><span class="label">${T('set.reports.mail_roles')}</span><div class="perm-grid">${r.roles.map((x) => `<label class="check"><input type="checkbox" name="mail_roles" value="${esc(x.key)}" ${v.mail_roles.includes(x.key) ? 'checked' : ''}><span>${esc(roleName(x))}</span></label>`).join('')}</div></div>`;
    }
    return `<form id="f-settings" class="card" data-sec="${sec}"><div class="form-grid">${fields}</div>
      <div class="form-actions">${canAdmin('manage_settings') ? `<button class="btn primary" type="submit">${T('common.save')}</button>` : `<span class="faint">${T('viewas.note')}</span>`}</div></form>${extra}`;
  }
  async function tabDemo() {
    const [st, d] = await Promise.all([api('/demo'), api('/settings')]);
    const v = d.settings.demo;
    S.settings = d.settings;
    const c = st.counts || {};
    const status = st.available
      ? `<div class="notice ok">${ico('check')}<span>${T('demo.status', { from: fmt(st.start, { day: '2-digit', month: 'short', year: 'numeric' }), to: fmt(st.end, { day: '2-digit', month: 'short', year: 'numeric' }), m: st.months })}</span></div>
        <div class="grid g4 mt">${[['tasks', 'nav.tasks'], ['task_steps', 'reports.steps'], ['decisions', 'reports.decisions'], ['reports', 'nav.reports']].map(([k, l]) => `<div class="card flat"><div class="kicker">${T(l)}</div><div class="stat">${fNum(c[k])}</div></div>`).join('')}</div>`
      : `<div class="notice">${ico('info')}<span>${T('demo.status_none')}</span></div>`;
    const months = [9, 12, 18].map((m) => `<option value="${m}" ${m === v.months ? 'selected' : ''}>${T('demo.months_n', { n: m })}</option>`).join('');
    const can = canAdmin('manage_settings');
    return `<section class="card"><div class="card-h"><div><h2>${ico('flask')} ${T('settings.tab.demo')}</h2><p class="faint mt-s">${T('demo.note')}</p></div></div>
        ${status}
        ${can ? `<div class="row mt"><div class="field" style="min-width:180px"><label for="demo-months">${T('set.demo.months')}</label><select class="input" id="demo-months">${months}</select></div>
          <button class="btn primary" data-act="demo-seed" style="align-self:flex-end">${ico('refresh')} ${T(st.available ? 'demo.regenerate' : 'demo.generate')}</button>
          ${st.available ? `<button class="btn danger" data-act="demo-clear" style="align-self:flex-end">${ico('x')} ${T('demo.delete')}</button>` : ''}</div>` : ''}</section>
      <form id="f-settings" class="card mt" data-sec="demo"><div class="form-grid">
        ${fieldFor('demo', 'guest_mode', v.guest_mode, { choices: ['live', 'demo'], full: true, hint: T('set.demo.guest_mode_hint') })}
        <input type="hidden" data-k="months" value="${esc(v.months)}"></div>
        <div class="form-actions">${can ? `<button class="btn primary" type="submit">${T('common.save')}</button>` : ''}</div></form>`;
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
      <td><span class="chip ${o.status === 'failed' ? 'bad' : 'ok'}">${esc(o.status)}</span>${o.error ? `<div class="faint mono">${esc(o.error)}</div>` : ''}</td>
      <td class="num">${o.has_html ? `<a class="btn sm" href="/api/outbox/${o.id}/html" target="_blank" rel="noopener">${ico('eye')} ${T('outbox.preview')}</a>` : ''}</td></tr>`).join('')
      || `<tr><td colspan="6" class="empty">${T('common.empty')}</td></tr>`;
    return `<div class="table-wrap"><table class="t"><thead><tr><th>${T('audit.when')}</th><th>${T('outbox.to')}</th><th>${T('outbox.subject')}</th><th>${T('outbox.mode')}</th><th>${T('common.status')}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }
  function bindTab(sec) {
    const f = $('#f-settings');
    if (f) f.addEventListener('submit', async (e) => {
      e.preventDefault();
      const body = {};
      $$('[data-k]', f).forEach((el) => {
        const k = el.dataset.k;
        if (el.type === 'checkbox') body[k] = el.checked;
        else if (el.type === 'number' || (el.type === 'hidden' && /^\d+$/.test(el.value))) body[k] = Number(el.value);
        else body[k] = el.value;
      });
      if (sec === 'reports') body.mail_roles = $$('input[name=mail_roles]:checked', f).map((x) => x.value);
      if (sec === 'workflow') body.alert_roles = $$('input[name=alert_roles]:checked', f).map((x) => x.value);
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

  // ------------------------------------------------------------ view as another user (super admin, read-only)
  async function viewAsModal() {
    const d = await api('/view-as/users', { noViewAs: true });
    const rn = (u) => (S.lang === 'ar' || S.lang === 'ur' ? u.role_name_ar : u.role_name_en);
    const rows = d.users.map((u) => `<button class="pick" data-act="view-as-pick" data-email="${esc(u.email)}">
        <span class="avatar">${esc(initials(u.name))}</span><span class="pick-main"><b>${esc(u.name)}</b><span class="faint ltr">${esc(u.email)}</span></span>
        <span class="chip ${u.role_key === 'super_admin' ? 'warn' : u.role_key === 'specialist' ? 'violet' : ''}">${esc(rn(u))}</span></button>`).join('')
      || `<div class="empty">${T('viewas.empty')}</div>`;
    const m = modal(`${modalHead(t('viewas.title'))}<p class="muted mb">${T('viewas.intro')}</p>
      <input class="input mb" id="va-search" placeholder="${T('viewas.search')}" autocomplete="off">
      <div class="pick-list">${rows}</div>`);
    $('#va-search', m).addEventListener('input', (e) => {
      const q = e.target.value.toLowerCase();
      $$('.pick', m).forEach((b) => { b.style.display = b.textContent.toLowerCase().includes(q) ? '' : 'none'; });
    });
  }
  async function startViewAs(email) {
    await api('/view-as', { method: 'POST', body: { email }, noViewAs: true });
    S.viewAs = email; store.set('mq-view-as', email);
    location.hash = '#/dashboard'; location.reload();
  }
  async function stopViewAs() {
    try { await api('/view-as/stop', { method: 'POST' }); } catch { /* clear locally anyway */ }
    S.viewAs = ''; store.set('mq-view-as', '');
    location.reload();
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
    const hcA = e.target.closest('[data-hc]');
    if (hcA && !hcA.dataset.act) { hcPin(hcA.dataset.hc); return; }
    if (HC.key && !hcA && !e.target.closest('#hovercard')) hcHide();
    else if (HC.key && !HC.pinned && e.target.closest('#hovercard') && !e.target.closest('a,button')) { HC.pinned = true; hcPaint(); }
    const row = e.target.closest('tr[data-href]');
    if (row && !e.target.closest('a,button,input')) { location.hash = row.dataset.href; return; }
    const el = e.target.closest('[data-act]');
    if (!el) return;
    const act = el.dataset.act;
    const id = el.dataset.id;
    try {
      switch (act) {
        case 'close-modal': closeModal(); break;
        case 'mode': {
          if (el.classList.contains('on')) break;
          const r = await api('/mode', { method: 'POST', body: { mode: el.dataset.mode } });
          const me = await api('/me'); S.me = me.user; S.demoAvailable = me.demo_available;
          toast(t(r.mode === 'demo' ? 'mode.on_demo' : 'mode.on_live'), 'ok'); render(); break;
        }
        case 'view-as': viewAsModal(); break;
        case 'view-as-pick': await startViewAs(el.dataset.email); break;
        case 'view-as-stop': await stopViewAs(); break;
        case 'demo-seed': {
          el.disabled = true; el.innerHTML = `<span class="spinner sm"></span> ${T('demo.generating')}`;
          try { await api('/demo/seed', { method: 'POST', body: { months: Number($('#demo-months').value) } }); S.demoAvailable = true; toast(t('common.saved'), 'ok'); }
          finally { render(); }
          break;
        }
        case 'demo-clear': if (await confirmBox(t('demo.confirm_delete'))) { await api('/demo', { method: 'DELETE' }); S.demoAvailable = false; const me = await api('/me'); S.me = me.user; render(); } break;
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
          S.loginStep = 'email';
          { const me = await api('/me'); S.me = me.user || r.user; S.demoAvailable = !!me.demo_available; }
          if (!location.hash || location.hash === '#/') location.hash = '#/dashboard';
          render(); break;
        }
        case 'probe': await api('/llm/probe'); viewDashboard(); break;
        case 'sel-agent': S.selAgent = el.dataset.k; hcPin(el.dataset.k); { const d = await api('/dashboard'); setPage(dashHTML(d)); hcPlace(); } break;
        case 'run-sample': newTaskModal({ kind: 'committee', scope: 'sample' }); break;
        case 'new-task': newTaskModal(); break;
        case 'step': stepModal(id); break;
        case 'review-filter': S.reviewFilter = el.dataset.f; viewReview(); break;
        case 'reassign': {
          await api('/review/assign', { method: 'POST', body: { tafsir: el.dataset.t, window: el.dataset.w, user_id: Number($('#reassign-to').value) } });
          toast(t('common.saved'), 'ok'); render(); break;
        }
        case 'publish': publishModal(); break;
        case 'make-live': if (await confirmBox(t('publish.confirm_live', { v: el.dataset.v }))) { await api(`/publish/${el.dataset.v}/live`, { method: 'POST' }); toast(t('common.saved'), 'ok'); render(); } break;
        case 'wf-sweep': { const r = await api('/workflow/sweep', { method: 'POST' }); toast(t('set.workflow.swept', r), 'ok'); break; }
        case 'wf-remind': { const r = await api('/workflow/remind', { method: 'POST' }); toast(t('set.workflow.reminded', r), r.failed ? 'bad' : 'ok'); break; }
        case 'cancel-task': if (await confirmBox(t('tasks.confirm_cancel'))) { await api(`/tasks/${id}/cancel`, { method: 'POST' }); render(); } break;
        case 'retry-task': { const r = await api(`/tasks/${id}/retry`, { method: 'POST' }); location.hash = '#/tasks/' + r.id; break; }
        case 'toggle-attempts': toggleAttempts(id); break;
        case 'team-range': S.teamDays = Number(el.dataset.days) || 30; render(); break;
        case 'team-remind': case 'remind-assignee': {
          el.disabled = true;
          try { const r = await api(`/team/remind/${id}`, { method: 'POST' }); toast(t('team.reminded_ok', { name: r.name, n: r.windows }), 'ok'); }
          catch (err) { toast(err.key === 'remind_cooldown' ? t('team.err.cooldown') : errText(err), 'bad'); }
          render(); break;
        }
        case 'gen-report': await api(`/reports/${el.dataset.day}/generate`, { method: 'POST' }); location.hash = '#/reports/' + el.dataset.day; render(); break;
        case 'mail-report': { const r = await api(`/reports/${el.dataset.day}/mail`, { method: 'POST' }); toast(t('reports.mail_result', r), r.failed ? 'bad' : 'ok'); render(); break; }
        case 'decide': {
          const art = el.closest('[data-move]');
          const val = (sel) => { const x = $(sel, art); return x ? (x.type === 'checkbox' ? x.checked : x.value) : ''; };
          const body = { tafsir: S.reviewCtx.tafsir, window: S.reviewCtx.win, move_id: art.dataset.move, decision: el.dataset.d,
            compared_with_source: $('[data-compare]', art).checked, note: $('[data-note]', art).value, arm: S.reviewCtx.arm || '',
            error_type: val('[data-error]') || '', correct_primary: val('[data-correct]') || '', teach: !!val('[data-teach]') };
          await api('/review/decision', { method: 'POST', body });
          // land on the next move that still waits for a decision
          const open = $$('article.move:not([data-decided])').map((x) => x.dataset.move).filter((k) => k !== art.dataset.move);
          const after = open.find((k) => $$('article.move').findIndex((x) => x.dataset.move === k) > $$('article.move').indexOf(art));
          S.reviewFocus = after || open[0] || null;
          toast(t('review.saved'), 'ok'); render(); break;
        }
        case 'change-decision': {
          const box = $('.decide', el.closest('[data-move]'));
          box.hidden = !box.hidden;
          el.textContent = box.hidden ? t('review.change') : t('common.cancel');
          break;
        }
        case 'toggle-decided': S.reviewShowDecided = !S.reviewShowDecided; render(); break;
        case 'goto-move': {
          const art = $(`[data-move="${CSS.escape(el.dataset.k)}"]`);
          if (art) {
            const fold = art.closest('details.move-fold');
            if (fold) fold.open = true;
            art.scrollIntoView({ block: 'start', behavior: 'smooth' });
            art.classList.add('flash'); setTimeout(() => art.classList.remove('flash'), 1400);
          }
          break;
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
  document.addEventListener('keydown', (e) => {
    const hcA = (e.key === 'Enter' || e.key === ' ') && e.target.closest && e.target.closest('[data-hc][role="button"]');
    if (hcA) { e.preventDefault(); hcPin(hcA.dataset.hc); }
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { hcHide(); closeModal(); document.body.classList.remove('nav-open'); $$('.dropdown.open').forEach((x) => x.classList.remove('open')); } });

  // ------------------------------------------------------------ boot
  (async function boot() {
    applyTheme();
    try { S.pub = await api('/public'); } catch { $('#app').innerHTML = `<div class="auth-wrap"><div class="notice bad">${ico('warn')}<span>Console server not reachable.</span></div></div>`; return; }
    S.viewAs = store.get('mq-view-as', '');
    await loadBrand();
    try {
      const me = await api('/me'); S.me = me.user; S.demoAvailable = !!me.demo_available;
      // the server is the authority: drop a stale switch (account disabled, no longer super admin…)
      if (S.viewAs && !S.me.view_as) { S.viewAs = ''; store.set('mq-view-as', ''); }
    } catch { S.me = null; }
    const want = (S.me && S.me.lang) || store.get('mq-lang', '') || S.pub.default_lang;
    await setLang(want, false);
    render();
  })();
})();

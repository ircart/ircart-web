// IRCart front end - single page app

const PAGE = 120;
const $    = (sel, root = document) => root.querySelector(sel);
const $$   = (sel, root = document) => [...root.querySelectorAll(sel)];
let me = null, csrf = '', observer = null, filesCache = {};

// ---- helpers ----

function esc(text) {
	return String(text ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

function when(ts) {
	const s = Math.floor(Date.now() / 1000) - ts;
	if (s < 60) return 'just now';
	if (s < 3600) return `${Math.floor(s / 60)}m ago`;
	if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
	if (s < 86400 * 30) return `${Math.floor(s / 86400)}d ago`;
	return new Date(ts * 1000).toISOString().slice(0, 10);
}

function artLink(name) { return '/art/' + name.split('/').map(encodeURIComponent).join('/'); }
function artApi(name) { return '/api/art/' + name.split('/').map(encodeURIComponent).join('/'); }
function starText(avg, votes) { return votes ? `<span class="stars-sm">★ ${avg.toFixed(1)}</span> (${votes})` : ''; }
function thumbSize(cols, width = 236) { return Math.max(1.2, Math.min(7, (width - 12) / (Math.max(cols, 1) * 0.6))) + 'px'; }

function setMeta(title, desc) {
	document.title = title ? `${title} - IRCart` : 'IRCart - IRC ASCII & ANSI art archive';
	if (desc) $('meta[name=description]').setAttribute('content', desc);
	$('link[rel=canonical]').setAttribute('href', location.origin + location.pathname);
}

function toast(msg, bad = false) {
	const t = $('#toast');
	t.textContent = msg;
	t.className = bad ? 'bad' : '';
	t.hidden = false;
	clearTimeout(t.timer);
	t.timer = setTimeout(() => t.hidden = true, 3500);
}

async function api(url, body) {
	const opts = {headers: {'X-CSRF': csrf}};
	if (body instanceof FormData) Object.assign(opts, {method: 'POST', body});
	else if (body) Object.assign(opts, {method: 'POST', body: JSON.stringify(body), headers: {'X-CSRF': csrf, 'Content-Type': 'application/json'}});
	const res  = await fetch(url, opts);
	const data = await res.json().catch(() => ({error: res.statusText}));
	if (!res.ok) { const err = new Error(data.error || res.statusText); err.data = data; throw err; }
	return data;
}

async function copyText(text, label) {
	try {
		if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
		else {
			const ta = document.createElement('textarea');
			ta.value = text;
			ta.style.position = 'fixed';
			ta.style.opacity = '0';
			document.body.appendChild(ta);
			ta.select();
			document.execCommand('copy');
			ta.remove();
		}
		toast(`copied as ${label}`);
	} catch (ex) { toast('copy failed: ' + ex.message, true); }
}

// ---- sha256 (pure js so the proof-of-work also works without https) ----

function sha256(msg) {
	const K = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
	const bytes = new TextEncoder().encode(msg);
	const len   = ((bytes.length + 9 + 63) >> 6) << 6;
	const buf   = new Uint8Array(len);
	buf.set(bytes);
	buf[bytes.length] = 0x80;
	const view = new DataView(buf.buffer);
	view.setUint32(len - 4, bytes.length * 8);
	let h = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
	const w = new Uint32Array(64);
	const rotr = (x, n) => (x >>> n) | (x << (32 - n));
	for (let o = 0; o < len; o += 64) {
		for (let i = 0; i < 16; i++) w[i] = view.getUint32(o + i * 4);
		for (let i = 16; i < 64; i++) {
			const s0 = rotr(w[i-15], 7) ^ rotr(w[i-15], 18) ^ (w[i-15] >>> 3);
			const s1 = rotr(w[i-2], 17) ^ rotr(w[i-2], 19) ^ (w[i-2] >>> 10);
			w[i] = (w[i-16] + s0 + w[i-7] + s1) | 0;
		}
		let [a, b, c, d, e, f, g, hh] = h;
		for (let i = 0; i < 64; i++) {
			const t1 = (hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) | 0;
			const t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0;
			hh = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
		}
		h = h.map((v, i) => (v + [a, b, c, d, e, f, g, hh][i]) | 0);
	}
	return h[0] >>> 0;
}

// ---- captcha ----

function captchaBox(holder) {
	let current = null, pow = null;
	holder.className = 'captcha';
	async function load() {
		holder.innerHTML = '<span class="dim">loading captcha...</span>';
		try { current = await api('/api/captcha'); } catch (ex) { holder.innerHTML = `<span class="error">${esc(ex.message)}</span>`; return; }
		holder.innerHTML = `<img src="${current.image}" alt="captcha"><input placeholder="type the text" maxlength="8" autocomplete="off"><button type="button" title="new captcha">↻</button><span class="pow">verifying browser...</span>`;
		$('button', holder).onclick = load;
		const {salt, bits} = current;
		pow = new Promise((resolve) => {
			let nonce = 0;
			const step = () => {
				for (let i = 0; i < 4000; i++, nonce++) {
					if ((sha256(salt + nonce) >>> (32 - bits)) === 0) { $('.pow', holder).textContent = 'browser verified ✓'; resolve(String(nonce)); return; }
				}
				setTimeout(step, 0);
			};
			step();
		});
	}
	load();
	return {
		reload: load,
		async values() { return {captcha_id: current && current.id, captcha: $('input', holder) ? $('input', holder).value : '', nonce: await pow}; },
	};
}

// ---- router ----

const routes = [
	[/^\/$/,                  () => galleryPage('main')],
	[/^\/uploads$/,           () => galleryPage('uploads')],
	[/^\/art\/(.+)$/,         (m) => artPage(decodeURIComponent(m[1]))],
	[/^\/dirs$/,              () => go('/')],
	[/^\/dir\/(.*)$/,         (m) => galleryPage('main', {dir: decodeURIComponent(m[1])})],
	[/^\/artists$/,           () => authorsPage()],
	[/^\/artist\/(.+)$/,      (m) => authorPage(decodeURIComponent(m[1]))],
	[/^\/user\/(.+)$/,        (m) => userPage(decodeURIComponent(m[1]))],
	[/^\/recent$/,            () => recentPage()],
	[/^\/about$/,             () => aboutPage()],
	[/^\/login$/,             () => authPage('login')],
	[/^\/register$/,          () => authPage('register')],
	[/^\/upload$/,            () => uploadPage()],
	[/^\/admin$/,             () => adminPage()],
	[/^\/admin\/reports$/,    () => reportsPage()],
	[/^\/admin\/dupes$/,      () => dupesPage()],
	[/^\/admin\/near$/,       () => nearPage()],
];

function go(url) { history.pushState(null, '', url); route(); }

async function route() {
	if (observer) { observer.disconnect(); observer = null; }
	$('nav').classList.remove('open');
	$('#menu').setAttribute('aria-expanded', 'false');
	setMeta('', '');
	const path = location.pathname;
	$$('nav a').forEach((a) => a.classList.toggle('active', a.getAttribute('href') === path || (path.startsWith('/admin') && path !== '/admin/reports' && a.getAttribute('href') === '/admin')));
	window.scrollTo(0, 0);
	refreshBadges();
	for (const [re, fn] of routes) {
		const m = path.match(re);
		if (m) { try { await fn(m); } catch (ex) { page(`<h1>Error</h1><p class="error">${esc(ex.message)}</p>`); } return; }
	}
	page('<h1>404</h1><p>No such page.</p>');
}

function page(html) { $('#page').innerHTML = html; return $('#page'); }

document.addEventListener('click', (e) => {
	const a = e.target.closest('a');
	if (!a || e.ctrlKey || e.metaKey || e.shiftKey || a.target === '_blank') return;
	const href = a.getAttribute('href');
	if (href && href.startsWith('/') && !href.startsWith('/random') && !href.startsWith('/avatar') && !href.startsWith('/static')) { e.preventDefault(); go(href); }
});
window.addEventListener('popstate', route);

// ---- account ----

async function loadMe() {
	const data = await api('/api/me');
	me = data.user;
	csrf = data.csrf;
	const box = $('#account');
	if (me) {
		box.innerHTML = `<a href="/upload" class="btn"><svg class="ic"><use href="#i-upload"/></svg>Upload</a><a href="/user/${encodeURIComponent(me.name)}" class="btn">${me.avatar ? `<img src="/avatar/${encodeURIComponent(me.name)}?${Date.now()}" alt="">` : '<svg class="ic"><use href="#i-user"/></svg>'}${esc(me.name)}</a><button id="logout" class="btn"><svg class="ic"><use href="#i-logout"/></svg>Logout</button>`;
		$('#logout').onclick = async () => { await api('/api/logout', {}); await loadMe(); route(); };
	} else box.innerHTML = '<a href="/login" class="btn"><svg class="ic"><use href="#i-login"/></svg>Login</a><a href="/register" class="btn primary"><svg class="ic"><use href="#i-userplus"/></svg>Register</a>';
	$$('.admin-only').forEach((el) => el.hidden = !(me && me.admin));
	refreshBadges();
}

function refreshBadges() {
	if (!me || !me.admin) { $('#upload-count').hidden = true; return; }
	api('/api/admin/status').then((s) => {
		$('#report-count').textContent = s.open_reports || ''; $('#report-count').hidden = !s.open_reports;
		$('#upload-count').textContent = s.queued_uploads || ''; $('#upload-count').hidden = !s.queued_uploads;
	}).catch(() => {});
}

function authPage(mode) {
	const p = page(`<div class="form auth"><h1>${mode === 'login' ? 'Login' : 'Register'}</h1>
		<label>Username</label><input id="f-name" autocomplete="username" maxlength="20">
		<label>Password</label><input id="f-pass" type="password" autocomplete="${mode === 'login' ? 'current-password' : 'new-password'}">
		${mode === 'register' ? '<label>Password again</label><input id="f-pass2" type="password" autocomplete="new-password"><p class="dim">3-20 letters, digits, _ or -. Passwords 8+ characters. No email needed.</p>' : ''}
		<div id="f-captcha"></div>
		<button class="primary" id="f-go">${mode === 'login' ? 'Login' : 'Create account'}</button>
		<p class="dim">${mode === 'login' ? 'No account? <a href="/register">Register</a>' : 'Have an account? <a href="/login">Login</a>'}</p></div>`);
	const cap = captchaBox($('#f-captcha', p));
	$('#f-go').onclick = async () => {
		if (mode === 'register' && $('#f-pass').value !== $('#f-pass2').value) return toast('passwords do not match', true);
		$('#f-go').disabled = true;
		try {
			await api('/api/' + mode, {name: $('#f-name').value.trim(), password: $('#f-pass').value, ...(await cap.values())});
			await loadMe();
			go('/');
		} catch (ex) { toast(ex.message, true); cap.reload(); }
		$('#f-go').disabled = false;
	};
}

// ---- gallery ----

async function getFiles(scope) {
	while (true) {
		const data = await api('/api/files?scope=' + scope);
		if (data.ready) return (filesCache[scope] = data.files);
		page(`<p class="dim">Generating previews... ${data.progress}%</p>`);
		await new Promise((r) => setTimeout(r, 2000));
	}
}

function card(f) {
	const author = f.author ? ` · by ${esc(f.author)}` : '';
	const flag = me && me.admin ? `<span class="flag" role="button" title="report as broken / renders wrong" data-flag="${esc(f.name)}"><svg class="ic"><use href="#i-flag"/></svg></span>` : '';
	return `<a class="card" href="${artLink(f.name)}">${flag}<div class="thumb"><pre class="art" style="font-size:${thumbSize(Math.min(f.cols, 120))}" data-thumb="${esc(f.name)}"></pre></div><div class="label"><b title="${esc(f.name)}">${esc(f.name)}</b><span>${f.lines} lines · ${f.cols} cols${author}</span> ${starText(f.avg, f.votes)}</div></a>`;
}

async function fillThumbs(root, list) {
	if (!list.length) return;
	const thumbs = await api('/api/thumbs', {names: list.map((f) => f.name)});
	list.forEach((f) => { const el = root.querySelector(`[data-thumb="${CSS.escape(f.name)}"]`); if (el) { el.style.fontSize = thumbSize(Math.min(f.cols, 120), el.parentElement.clientWidth || 236); el.innerHTML = thumbs[f.name] || ''; } });
}

function infiniteGrid(container, list, emptyText = 'nothing here') {
	let shown = 0, busy = false;
	container.innerHTML = '<div class="grid"></div><div class="sentinel"></div>';
	const grid = $('.grid', container), sentinel = $('.sentinel', container);
	grid.addEventListener('click', async (e) => {
		const flag = e.target.closest('.flag');
		if (!flag) return;
		e.preventDefault();
		e.stopPropagation();
		if (flag.classList.contains('done')) return;
		try { await api('/api/report', {art: flag.dataset.flag, reason: 'broken'}); flag.classList.add('done'); toast(`reported ${flag.dataset.flag} as broken`); } catch (ex) { toast(ex.message, true); }
	});
	sentinel.id = 'sentinel';
	async function more() {
		if (busy) return;
		if (shown >= list.length) { sentinel.textContent = list.length ? 'end' : emptyText; return; }
		busy = true;
		const batch = list.slice(shown, shown + PAGE);
		shown += batch.length;
		grid.insertAdjacentHTML('beforeend', batch.map(card).join(''));
		sentinel.textContent = 'loading...';
		await fillThumbs(grid, batch);
		sentinel.textContent = shown < list.length ? '' : 'end';
		busy = false;
		if (shown < list.length && sentinel.getBoundingClientRect().top < window.innerHeight + 800) more();
	}
	const obs = new IntersectionObserver((entries) => { if (entries[0].isIntersecting) more(); }, {rootMargin: '800px'});
	obs.observe(sentinel);
	observer = obs;
	more();
}

async function galleryPage(scope, preset = {}) {
	const files = await getFiles(scope);
	const dirs  = [...new Set(files.map((f) => f.dir))].sort();
	const title = scope === 'uploads' ? 'Uploads' : preset.dir !== undefined ? `/${esc(preset.dir || '(root)')}` : 'Gallery';
	if (scope === 'uploads') setMeta('Uploads', 'IRC art uploaded by the IRCart community.'); else if (preset.dir !== undefined) setMeta(`/${preset.dir || '(root)'} - IRC art directory`, `${files.filter((f) => f.dir === preset.dir).length} IRC art pieces in /${preset.dir || '(root)'}.`);
	const p = page(`<h1>${title}</h1><div class="controls">
		<input type="search" id="q" maxlength="100" placeholder="search names${scope === 'uploads' ? ' or accounts' : ' or artists'}">
		${scope === 'main' && preset.dir === undefined ? `<select id="dir"><option value="*">all dirs</option>${dirs.map((d) => `<option value="${esc(d)}">${d ? esc(d) : '(root)'}</option>`).join('')}</select>` : ''}
		<select id="sort">${scope === 'main' && preset.dir === undefined ? '<option value="random">random</option>' : ''}<option value="name">name</option><option value="mtime">date</option><option value="top">rating</option><option value="lines">lines</option><option value="cols">width</option><option value="size">size</option></select><button class="btn" id="order" type="button"></button>
		<span id="count" class="dim"></span></div><div id="results"></div>`);
	const params = new URLSearchParams(location.search);
	$('#q').value = (params.get('q') || '').slice(0, 100);
	const pick = (sel, value) => { if (sel && [...sel.options].some((o) => o.value === value)) sel.value = value; };
	pick($('#dir'), params.get('dir'));
	if ($('#dir') && $('#dir').value !== '*') $('#sort').value = 'name';
	pick($('#sort'), params.get('sort'));
	let rev = params.get('order') === 'rev';
	const syncUrl = () => {
		const url = new URL(location.href), defSort = $('#sort').options[0].value;
		for (const [key, value, def] of [['q', $('#q').value.slice(0, 100), ''], ['dir', $('#dir') ? $('#dir').value : '*', '*'], ['sort', $('#sort').value, $('#dir') && $('#dir').value !== '*' ? 'name' : defSort], ['order', rev ? 'rev' : '', '']]) {
			if (value !== def) url.searchParams.set(key, value); else url.searchParams.delete(key);
		}
		history.replaceState(null, '', url.pathname + url.search);
	};
	const rnd = new Map(files.map((f) => [f.name, Math.random()]));
	const apply = () => {
		const q = $('#q').value.toLowerCase(), dir = preset.dir !== undefined ? preset.dir : ($('#dir') ? $('#dir').value : '*'), sort = $('#sort').value;
		const hideNazi = dir === '*' && sort === 'random' && !q; // the randomized home page never shows nazi/, searching still finds it
		const list = files.filter((f) => (dir === '*' || f.dir === dir) && !(hideNazi && f.dir === 'nazi') && (f.name.toLowerCase().includes(q) || (f.author || '').toLowerCase().includes(q)));
		const num = {mtime: 1, lines: 1, cols: 1, size: 1}[sort];
		list.sort((a, b) => sort === 'random' ? rnd.get(a.name) - rnd.get(b.name) : sort === 'top' ? (b.avg - a.avg) || (b.votes - a.votes) : num ? b[sort] - a[sort] : a.name.localeCompare(b.name));
		if (rev && sort !== 'random') list.reverse();
		const asc = (sort === 'name') !== rev; // name sorts A-Z by default, everything else biggest/newest first
		$('#order').hidden = sort === 'random';
		$('#order').textContent = asc ? '↑ asc' : '↓ desc';
		$('#order').title = asc ? 'ascending, click for descending' : 'descending, click for ascending';
		$('#count').textContent = `${list.length.toLocaleString()} files`;
		if (observer) observer.disconnect();
		infiniteGrid($('#results', p), list);
	};
	$('#q').oninput = () => { syncUrl(); apply(); };
	$('#sort').onchange = () => { rev = false; syncUrl(); apply(); };
	$('#order').onclick = () => { rev = !rev; syncUrl(); apply(); };
	if ($('#dir')) $('#dir').onchange = () => { $('#sort').value = $('#dir').value === '*' ? 'random' : 'name'; rev = false; syncUrl(); apply(); };
	apply();
}

// ---- art page ----

function starsWidget(value, readonly) {
	return `<span class="stars${readonly ? ' readonly' : ''}">${[1, 2, 3, 4, 5].map((n) => `<span data-star="${n}" class="${n <= value ? 'on' : ''}">★</span>`).join('')}</span>`;
}

function moveControls(name, dirs) {
	const dir  = name.includes('/') ? name.slice(0, name.lastIndexOf('/')) : '';
	const base = name.slice(name.lastIndexOf('/') + 1);
	return `<select class="mv-dir">${dirs.map((d) => `<option value="${esc(d)}"${d === dir ? ' selected' : ''}>${d ? esc(d) : '(root)'}</option>`).join('')}</select>/<input class="mv-name" value="${esc(base)}">`;
}

function readMove(el) {
	const dir = $('.mv-dir', el).value, base = $('.mv-name', el).value.trim().replace(/\.txt$/, '');
	return dir ? `${dir}/${base}` : base;
}

async function showClash(dest, clashes) {
	const arts = await Promise.all(clashes.map(fetchArt));
	$('#clash-title').textContent = `Name clash: "${dest.slice(dest.lastIndexOf('/') + 1)}" is already used by ${clashes.length} file${clashes.length > 1 ? 's' : ''}. Nothing was moved.`;
	$('#clash-list').innerHTML = clashes.map((n, i) => `<div class="pane"><div class="head"><b>${esc(n)}</b></div><div class="box"><pre class="art">${arts[i] ? arts[i].html : ''}</pre></div></div>`).join('');
	$('#clash').hidden = false;
}

async function doMove(name, dest) {
	if (!dest || dest === name) return false;
	try { await api('/api/admin/move', {art: name, dest}); } catch (ex) { if (ex.data && ex.data.clashes) showClash(dest, ex.data.clashes); else toast(ex.message, true); return false; }
	filesCache = {};
	toast(`moved to ${dest}`);
	return true;
}

async function mainDirs() { return (await api('/api/dirs')).map((d) => d.dir); }
const fetchArt = (n) => api(artApi(n)).catch(() => null);

async function artPage(name) {
	const data = await api(artApi(name));
	const m = data.meta, isUpload = name.startsWith('uploads/');
	setMeta(`${name.split('/').pop()} - IRC art${data.author ? ' by ' + data.author : ''}`, `"${name}" IRC ASCII art: ${m.lines} lines, ${m.cols} columns. View, rate & copy it as IRC, ANSI or HTML.`);
	const authorHtml = data.author ? (data.author_user ? `<a href="/user/${encodeURIComponent(data.author_user)}">${esc(data.author)}</a>` : `<a href="/artist/${encodeURIComponent(data.author)}">${esc(data.author)}</a>`) : '<span class="dim">unknown</span>';
	const where = isUpload ? `uploaded by <a href="/user/${encodeURIComponent(data.uploader)}">${esc(data.uploader)}</a>` : `in <a href="/dir/${encodeURIComponent(m.dir)}">/${esc(m.dir || '(root)')}</a>`;
	const p = page(`<div class="art-head"><h1>${esc(name)}</h1>
		<span class="dim">${where} · artist ${authorHtml} · ${m.lines} lines · ${m.cols} cols · ${m.size.toLocaleString()} bytes</span></div>
		<div class="toolbar">${starsWidget(data.mine || Math.round(data.avg), !me)}<span class="dim">${data.votes ? `${data.avg.toFixed(2)} from ${data.votes} rating${data.votes > 1 ? 's' : ''}` : 'no ratings yet'}${me ? (data.mine ? ` · you rated ${data.mine}` : '') : ' · login to rate'}</span></div>
		<div class="toolbar">
			<button class="btn primary" id="copy"><svg class="ic"><use href="#i-copy"/></svg>Copy</button><select id="fmt" aria-label="copy format"><option value="irc">IRC</option><option value="ansi24">ANSI (truecolor)</option><option value="ansi256">ANSI (256)</option><option value="html">HTML</option></select>
			<button class="btn" data-zoom="-2" aria-label="zoom out">−</button><button class="btn" data-zoom="2" aria-label="zoom in">+</button>
			<button class="btn" id="report-btn"><svg class="ic"><use href="#i-flag"/></svg>Report</button>
		</div>
		<div class="panel" id="report" hidden><h3>Report a problem</h3><p class="dim">Only the site admin sees reports.</p><div class="row"><select id="r-reason">${Object.entries(data.reasons).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select><input id="r-note" placeholder="optional note, e.g. the correct name" maxlength="500" style="flex:1"></div><div id="r-captcha"></div><div class="row"><button class="btn primary" id="r-go">Send report</button><button class="btn" id="r-cancel">Cancel</button></div></div>
		<div class="art-frame"><pre class="art" id="art" style="font-size:13px">${data.html}</pre></div>
		<div id="owner"></div><div id="admin"></div>
		<div class="panel"><h3>Comments (${data.comments.length})</h3><div>${data.comments.map((c) => `<div class="comment">${c.avatar ? `<img src="/avatar/${encodeURIComponent(c.user)}" alt="">` : '<div class="noav"></div>'}<div><a href="/user/${encodeURIComponent(c.user)}">${esc(c.user)}</a> <span class="dim">${when(c.created)}</span><div class="body">${esc(c.body)}</div></div></div>`).join('') || '<p class="dim">No comments yet.</p>'}</div>
		${me ? '<textarea id="c-body" rows="3" maxlength="1000" placeholder="write a comment (plain text)"></textarea><div id="c-captcha"></div><button id="c-go" class="primary">Post comment</button>' : '<p class="dim"><a href="/login">Login</a> to comment.</p>'}</div>`);
	let zoom = 13;
	$$('[data-zoom]', p).forEach((b) => b.onclick = () => { zoom = Math.max(3, zoom + Number(b.dataset.zoom)); $('#art').style.fontSize = zoom + 'px'; });
	$('#copy').onclick = async () => {
		const fmt = $('#fmt');
		const {text} = await api(`/api/export/${name.split('/').map(encodeURIComponent).join('/')}?fmt=${fmt.value}`);
		copyText(text, fmt.options[fmt.selectedIndex].text);
	};
	$('#report-btn').onclick = () => { if (!me) { toast('login to report art', true); go('/login'); } };
	if (!me) return;
	$$('.stars span', p).forEach((s) => s.onclick = async () => {
		try { await api('/api/rate', {art: name, stars: Number(s.dataset.star)}); toast('rating saved'); filesCache = {}; artPage(name); } catch (ex) { toast(ex.message, true); }
	});
	const ccap = me.admin ? null : captchaBox($('#c-captcha', p));
	let rcap = null;
	$('#report-btn').onclick = () => {
		$('#report').hidden = !$('#report').hidden;
		if (!$('#report').hidden && !rcap && !me.admin) rcap = captchaBox($('#r-captcha', p));
	};
	$('#r-cancel').onclick = () => { $('#report').hidden = true; };
	if (new URLSearchParams(location.search).get('report') === 'wrong_author') { $('#report-btn').click(); $('#r-reason').value = 'wrong_author'; $('#r-note').placeholder = 'who made it?'; $('#r-note').focus(); }
	$('#r-go').onclick = async () => {
		try { await api('/api/report', {art: name, reason: $('#r-reason').value, note: $('#r-note').value, ...(rcap ? await rcap.values() : {})}); toast('report sent to the admin, thanks'); $('#r-note').value = ''; $('#report').hidden = true; } catch (ex) { toast(ex.message, true); }
		if (rcap) rcap.reload();
	};
	$('#c-go').onclick = async () => {
		try { await api('/api/comment', {art: name, body: $('#c-body').value, ...(ccap ? await ccap.values() : {})}); artPage(name); } catch (ex) { toast(ex.message, true); if (ccap) ccap.reload(); }
	};
	if (isUpload && (data.uploader === me.name || me.admin)) {
		$('#owner').innerHTML = `<div class="panel"><h3>${data.uploader === me.name ? 'Your upload' : 'Upload'}</h3><button class="danger" id="u-del">Delete this upload</button></div>`;
		$('#u-del').onclick = async () => { if (!confirm(`Delete ${name}?`)) return; try { await api('/api/upload/delete', {art: name}); filesCache = {}; go('/user/' + encodeURIComponent(data.uploader)); } catch (ex) { toast(ex.message, true); } };
	}
	if (me.admin) {
		const [dirs, authors] = await Promise.all([mainDirs(), api('/api/authors')]);
		$('#admin').innerHTML = `<div class="panel"><h3>Admin</h3>
			<div class="row"><span>Artist</span><input id="a-author" list="a-list" value="${esc(data.author)}" placeholder="artist name"><datalist id="a-list">${authors.map((a) => `<option value="${esc(a.author)}">`).join('')}</datalist><button id="a-save">Save artist</button></div>
			<div class="row" id="a-move"><span>${isUpload ? 'Promote to' : 'Move to'}</span>${moveControls(isUpload ? name.slice(name.lastIndexOf('/') + 1) : name, dirs)}<button id="a-mv">${isUpload ? 'Promote' : 'Move/rename'}</button><button class="danger" id="a-del">Delete</button></div></div>`;
		$('#a-save').onclick = async () => { try { await api('/api/author', {art: name, author: $('#a-author').value}); filesCache = {}; artPage(name); } catch (ex) { toast(ex.message, true); } };
		$('#a-mv').onclick = async () => { const dest = readMove($('#a-move')); if (await doMove(name, dest)) go(artLink(dest)); };
		$('#a-del').onclick = async () => { if (!confirm(`Delete ${name}.txt?`)) return; try { await api('/api/admin/delete', {art: name}); filesCache = {}; go('/'); } catch (ex) { toast(ex.message, true); } };
	}
}

// ---- dirs, authors, users, recent, about ----

async function authorsPage() {
	const authors = await api('/api/authors');
	setMeta('Artists', 'IRC art artists credited on IRCart.');
	const p = page(`<h1>Artists</h1>${authors.length ? `<div class="controls"><input type="search" id="q" maxlength="100" placeholder="search artists"><span id="count" class="dim"></span></div><div class="artists">${authors.map((a, i) => `<div class="artist" data-i="${i}"><a class="name" href="/artist/${encodeURIComponent(a.author)}">${esc(a.author)} <span>${a.count} piece${a.count === 1 ? '' : 's'}</span></a><div class="minis">${a.samples.map((f) => `<a class="mini" href="${artLink(f.name)}" title="${esc(f.name)}"><pre class="art" data-thumb="${esc(f.name)}"></pre></a>`).join('')}</div></div>`).join('')}</div>` : '<p class="dim">No art has been credited yet.</p>'}`);
	observer = new IntersectionObserver((entries) => entries.forEach((e) => {
		if (!e.isIntersecting) return;
		observer.unobserve(e.target);
		fillThumbs(e.target, authors[e.target.dataset.i].samples);
	}), {rootMargin: '600px'});
	$$('.artist', p).forEach((el) => observer.observe(el));
	if (!authors.length) return;
	const apply = () => {
		const q = $('#q').value.toLowerCase();
		let shown = 0;
		$$('.artist', p).forEach((el) => { el.hidden = !authors[el.dataset.i].author.toLowerCase().includes(q); shown += !el.hidden; });
		$('#count').textContent = `${shown} artist${shown === 1 ? '' : 's'}`;
	};
	$('#q').value = (new URLSearchParams(location.search).get('q') || '').slice(0, 100);
	$('#q').oninput = () => {
		const url = new URL(location.href);
		if ($('#q').value) url.searchParams.set('q', $('#q').value.slice(0, 100)); else url.searchParams.delete('q');
		history.replaceState(null, '', url.pathname + url.search);
		apply();
	};
	apply();
}

async function authorPage(name) {
	const data = await api('/api/author/' + encodeURIComponent(name));
	setMeta(`${data.author} - IRC art by ${data.author}`, `${data.files.length} IRC art pieces by ${data.author}.`);
	const p = page(`<h1>${esc(data.author)}</h1>${data.user ? `<p>Has an account: <a href="/user/${encodeURIComponent(data.user)}">${esc(data.user)}</a></p>` : ''}<p class="dim">${data.files.length} credited piece${data.files.length === 1 ? '' : 's'}</p><div id="results"></div>`);
	infiniteGrid($('#results', p), data.files);
}

async function userPage(name) {
	const d = await api('/api/user/' + encodeURIComponent(name));
	const u = d.user, self = me && me.name.toLowerCase() === u.name.toLowerCase();
	setMeta(`${u.name} - profile`);
	const p = page(`<div class="profile">${u.avatar ? `<img src="/avatar/${encodeURIComponent(u.name)}?${Date.now()}" alt="">` : '<div class="noav"></div>'}<div><h1>${esc(u.name)}${u.admin ? ' <span class="dim">(admin)</span>' : ''}</h1><div class="dim">joined ${new Date(u.created * 1000).toISOString().slice(0, 10)} · ${d.uploads.length} uploads · ${d.counts.comments} comments · ${d.counts.ratings} ratings</div></div></div>
		${self ? '<div class="panel"><h3>Profile picture</h3><span class="dim">JPG or PNG, max 512 KB and 512x512.</span><div class="row"><input type="file" id="av" accept=".jpg,.jpeg,.png,image/jpeg,image/png"><button id="av-go">Upload</button></div></div>' : ''}
		${d.authored.length ? '<h2>Credited art</h2><div id="auth" class="grid"></div>' : ''}
		<h2>Uploads</h2><div id="ups"></div>
		<h2>Recent comments</h2><div>${d.comments.map((c) => `<div class="activity"><a href="${artLink(c.art)}">${esc(c.art)}</a> <span class="dim">${when(c.created)}</span><div>${esc(c.body)}</div></div>`).join('') || '<p class="dim">none</p>'}</div>`);
	if (d.authored.length) { $('#auth', p).innerHTML = d.authored.map(card).join(''); fillThumbs($('#auth', p), d.authored); }
	infiniteGrid($('#ups', p), d.uploads, 'no uploads');
	if (self) $('#av-go').onclick = async () => {
		const file = $('#av').files[0];
		if (!file) return toast('pick an image first', true);
		const fd = new FormData();
		fd.append('avatar', file);
		try { await api('/api/avatar', fd); await loadMe(); userPage(name); } catch (ex) { toast(ex.message, true); }
	};
}

async function recentPage() {
	const d = await api('/api/recent');
	setMeta('Recent activity');
	page(`<h1>Recent activity</h1><div class="columns">
		<div><h2>Comments</h2>${d.comments.map((c) => `<div class="activity"><a href="/user/${encodeURIComponent(c.user)}">${esc(c.user)}</a> on <a href="${artLink(c.art)}">${esc(c.art)}</a> <span class="dim">${when(c.created)}</span><div>${esc(c.body)}</div></div>`).join('') || '<p class="dim">none yet</p>'}</div>
		<div><h2>Ratings</h2>${d.ratings.map((r) => `<div class="activity"><a href="/user/${encodeURIComponent(r.user)}">${esc(r.user)}</a> rated <a href="${artLink(r.art)}">${esc(r.art)}</a> <span class="stars-sm">${'★'.repeat(r.stars)}</span> <span class="dim">${when(r.created)}</span></div>`).join('') || '<p class="dim">none yet</p>'}</div>
		<div><h2>Uploads</h2>${d.uploads.map((u) => `<div class="activity"><a href="/user/${encodeURIComponent(u.user)}">${esc(u.user)}</a> uploaded <a href="${artLink(u.art)}">${esc(u.art.split('/').pop())}</a> <span class="dim">${when(u.created)}</span></div>`).join('') || '<p class="dim">none yet</p>'}</div></div>`);
}

function aboutPage() {
	setMeta('About');
	page(`<div class="about"><h1>About IRCart</h1>
		<p>IRCart is the central hub for IRC formatted ASCII &amp; ANSI art: thousands of pieces in mIRC color codes, browsable, rateable and ready to paste back into IRC, a terminal or a web page.</p>
		<p>The archive is the <a href="https://git.supernets.org/ircart/ircart" target="_blank" rel="noopener">ircart repository</a> on SuperNETs. Everything here comes straight from it, and uploads made on this site are saved into the same repository.</p>
		<h2>Play it on IRC</h2>
		<p>Join <b>#superbowl</b> or <b>#scroll</b> on <b>irc.supernets.org</b> (port 6697, TLS) and use the <a href="https://git.supernets.org/ircart/scroll" target="_blank" rel="noopener">scroll</a> bot: <code>.ascii &lt;name&gt;</code> plays a piece, <code>.ascii dir/name</code> picks one from a specific directory, <code>.ascii random</code> plays something random and <code>.ascii help</code> lists the rest.</p>
		<h2>Contribute</h2>
		<p><a href="/register">Create an account</a> (just a username and password) and <a href="/upload">upload your art</a>: it shows up under <a href="/uploads">Uploads</a> and on your profile. You can also send art to the git repository directly. Spot something broken, misnamed, in the wrong directory or credited to the wrong person? Use the report box on its page.</p>
		<h2>Credits</h2>
		<p>The collection spans decades of IRC and BBS art from countless artists and groups, including pp4l, blocktronics, ACiD, 16colo.rs and many others. Where we know who made a piece it carries an artist tag; if you know the artist of something untagged, report it with the name.</p>
		<p>IRCart is made by <a href="/user/acidvegas">acidvegas</a> for <a href="https://supernets.org" target="_blank" rel="noopener">SuperNETs</a>.</p></div>`);
}

// ---- upload ----

function uploadPage() {
	if (!me) { go('/login'); return; }
	const p = page(`<div class="form"><h1>Upload art</h1><p class="dim">IRC formatted text (mIRC color codes), up to 10,000 lines and 3 MB. It is saved as uploads/${esc(me.name)}/&lt;name&gt; and shows up under Uploads.</p>
		<label>Name</label><input id="u-name" maxlength="40" placeholder="letters, digits, _ or -">
		<label>File</label><input type="file" id="u-file" accept=".txt,text/plain">
		<label>...or paste it</label><textarea id="u-text" rows="8" placeholder="paste IRC art here"></textarea>
		<div id="u-captcha"></div><button class="primary" id="u-go">Upload</button><div id="u-match" class="panel" hidden></div></div>`);
	const cap = captchaBox($('#u-captcha', p));
	const send = async (force) => {
		const fd = new FormData(), file = $('#u-file').files[0];
		fd.append('name', $('#u-name').value.trim());
		if (file) fd.append('file', file); else fd.append('text', $('#u-text').value);
		Object.entries(await cap.values()).forEach(([k, v]) => fd.append(k, v));
		if (force) fd.append('force', '1');
		$('#u-go').disabled = true;
		$('#u-match').hidden = true;
		try { const r = await api('/api/upload', fd); filesCache = {}; go(artLink(r.art)); } catch (ex) {
			if (ex.data && ex.data.matches) showMatches(ex.data.matches); else { toast(ex.message, true); cap.reload(); }
		}
		$('#u-go').disabled = false;
	};
	const showMatches = (found) => {
		const box = $('#u-match');
		box.innerHTML = `<h3>Is this the same art?</h3><p>It is at least 95% the same as ${found.length === 1 ? 'a piece' : 'these pieces'} already on IRCart:</p>
			<div class="minis">${found.map((f) => `<a class="mini" href="${artLink(f.name)}" target="_blank" title="${esc(f.name)} (${f.sim}% match)"><pre class="art" data-thumb="${esc(f.name)}"></pre></a>`).join('')}</div>
			<p class="dim">${found.map((f) => `<a href="${artLink(f.name)}" target="_blank">${esc(f.name)}</a> ${f.sim}%`).join(' · ')}</p>
			<div class="row"><button class="btn primary" id="m-same">Yes, it's the same</button><button class="btn" id="m-new">No, upload it anyway</button></div>`;
		box.hidden = false;
		fillThumbs(box, found);
		$('#m-new').onclick = () => send(true);
		$('#m-same').onclick = () => {
			box.innerHTML = `<h3>No need to upload it then</h3><p>If that piece is missing its artist or credits the wrong one, open it and send a report with the correct artist:</p>
				<p>${found.map((f) => `<a class="btn" href="${artLink(f.name)}?report=wrong_author"><svg class="ic"><use href="#i-flag"/></svg>Report artist for ${esc(f.name)}</a>`).join(' ')}</p>`;
		};
	};
	$('#u-go').onclick = () => send(false);
}

// ---- admin ----

function adminGuard() { if (!me || !me.admin) { page('<h1>Admin</h1><p class="error">Admin only.</p>'); return false; } return true; }

async function adminPage() {
	if (!adminGuard()) return;
	const s = await api('/api/admin/status');
	page(`<h1>Admin</h1><div class="list">
		<a href="/admin/reports">Reports <span>${s.open_reports} open</span></a>
		<a href="/admin/dupes">Same-name files</a>
		<a href="/admin/near">Near duplicates (≥95%)</a></div>
		<div class="panel"><h3>Repository</h3><div>${s.files.toLocaleString()} files indexed</div><div>last pull: ${esc(s.git)}</div>
		${s.dirty_count ? `<p class="error">${s.dirty_count} uncommitted change${s.dirty_count > 1 ? 's' : ''} in the art repo; commit &amp; push them before pulling:</p><pre class="dim">${esc(s.dirty.join('\n'))}</pre>` : ''}
		<button id="pull" class="primary"${s.pulling ? ' disabled' : ''}>${s.pulling ? 'Pulling...' : 'Pull latest art from git'}</button></div>`);
	$('#pull').onclick = async () => {
		try { await api('/api/admin/pull', {}); toast('pull started'); setTimeout(adminPage, 3000); } catch (ex) { toast(ex.message, true); }
	};
	if (s.pulling) setTimeout(() => { if (location.pathname === '/admin') adminPage(); }, 3000);
}

function lazyGroups(container, items, build) {
	let shown = 0, busy = false;
	container.insertAdjacentHTML('beforeend', '<div id="sentinel"></div>');
	const sentinel = $('#sentinel', container);
	async function more() {
		if (busy) return;
		if (shown >= items.length) { sentinel.textContent = items.length ? 'end' : 'nothing left'; return; }
		busy = true;
		for (const item of items.slice(shown, shown + 8)) sentinel.before(await build(item));
		shown += 8;
		busy = false;
		if (shown < items.length && sentinel.getBoundingClientRect().top < window.innerHeight + 600) more();
		else if (shown >= items.length) sentinel.textContent = 'end';
	}
	observer = new IntersectionObserver((e) => { if (e[0].isIntersecting) more(); }, {rootMargin: '600px'});
	observer.observe(sentinel);
	more();
}

async function reportsPage() {
	if (!adminGuard()) return;
	const reports = await api('/api/admin/reports');
	const p = page(`<h1>Reports</h1><p class="dim">${reports.length} open</p><div id="list"></div>`);
	lazyGroups($('#list', p), reports, async (r) => {
		const a = r.exists ? await fetchArt(r.art) : null;
		const el = document.createElement('div');
		el.className = 'group';
		el.innerHTML = `<h3>${esc(r.reason_text)} · <a href="${artLink(r.art)}">${esc(r.art)}</a> <span class="dim">by ${esc(r.user)} ${when(r.created)}</span></h3>
			<div class="side"><div class="pane">${r.note ? `<div>Note: ${esc(r.note)}</div>` : ''}${a ? `<div class="box"><pre class="art">${a.html}</pre></div>` : '<p class="error">file no longer exists</p>'}<div class="row"><button data-s="resolved" class="primary">Resolved</button><button data-s="dismissed">Dismiss</button></div></div></div>`;
		$$('[data-s]', el).forEach((b) => b.onclick = async () => { await api(`/api/admin/reports/${r.id}`, {status: b.dataset.s}); el.remove(); loadMe(); });
		return el;
	});
}

function pane(name, a, dirs) {
	return `<div class="pane" data-name="${esc(name)}"><div class="head"><a href="${artLink(name)}"><b>${esc(name)}</b></a> <span class="dim">${a ? `${a.meta.lines} lines · ${a.meta.cols} cols · ${a.meta.size.toLocaleString()} B` : 'missing'}</span></div>
		<div class="box"><pre class="art">${a ? a.html : ''}</pre></div>
		<div class="row">${moveControls(name, dirs)}<button data-act="move">Move/rename</button><button data-act="delete" class="danger">Delete</button></div></div>`;
}

function wirePanes(el, onChange) {
	$$('.pane', el).forEach((p) => {
		const name = p.dataset.name;
		$('[data-act=move]', p).onclick = async () => { if (await doMove(name, readMove(p))) onChange(); };
		$('[data-act=delete]', p).onclick = async () => { if (!confirm(`Delete ${name}.txt?`)) return; try { await api('/api/admin/delete', {art: name}); filesCache = {}; onChange(); } catch (ex) { toast(ex.message, true); } };
	});
}

async function dupesPage() {
	if (!adminGuard()) return;
	const [groups, dirs] = await Promise.all([api('/api/admin/dupes'), mainDirs()]);
	const p = page(`<h1>Same-name files</h1><p class="dim">${groups.length} names are used by more than one file.</p><div id="list"></div>`);
	lazyGroups($('#list', p), groups, async (g) => {
		const arts = await Promise.all(g.files.map(fetchArt));
		const el = document.createElement('div');
		el.className = 'group';
		el.innerHTML = `<h3>${esc(g.name)} <span class="dim">(${g.files.length} files)</span></h3><div class="side">${g.files.map((n, i) => pane(n, arts[i], dirs)).join('')}</div>`;
		wirePanes(el, () => el.remove());
		return el;
	});
}

async function nearPage() {
	if (!adminGuard()) return;
	const p = page('<h1>Near duplicates</h1><div class="controls"><span id="ns" class="dim"></span><button id="rescan">Rescan</button></div><div id="list"></div>');
	$('#rescan').onclick = async () => { await api('/api/admin/near/rescan', {}); nearPage(); };
	const data = await api('/api/admin/near');
	if (data.status !== 'done') { $('#ns').textContent = `scan ${data.status} ${data.progress}%`; setTimeout(() => { if (location.pathname === '/admin/near') nearPage(); }, 3000); return; }
	$('#ns').textContent = `${data.pairs.length} pairs at least 95% similar`;
	const dirs = await mainDirs();
	lazyGroups($('#list', p), data.pairs, async (pair) => {
		const [a, b] = await Promise.all([fetchArt(pair.a), fetchArt(pair.b)]);
		const el = document.createElement('div');
		el.className = 'group';
		el.innerHTML = `<h3><span class="sim">${pair.sim}%</span> ${esc(pair.a)} vs ${esc(pair.b)} <button data-act="ignore" style="float:right">Not a dupe</button></h3><div class="side">${pane(pair.a, a, dirs)}${pane(pair.b, b, dirs)}</div>`;
		$('[data-act=ignore]', el).onclick = async () => { await api('/api/admin/ignore', {a: pair.a, b: pair.b}); el.remove(); };
		wirePanes(el, () => el.remove());
		return el;
	});
}

// ---- boot ----

$('#clash-close').onclick = () => { $('#clash').hidden = true; };
$('#menu').onclick = () => { const open = $('nav').classList.toggle('open'); $('#menu').setAttribute('aria-expanded', String(open)); };
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('#clash').hidden = true; });
loadMe().then(route);

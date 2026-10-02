#!/usr/bin/env python3
# IRCart - the central hub for IRC formatted ascii/ansi art (https://git.supernets.org/ircart/ircart)

import base64
import json
import io
import os
import random
import re
import secrets
import subprocess
import threading
import time

from functools import lru_cache, wraps
from html import escape
from urllib.parse import quote

try:
	from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request, send_file, session
	from werkzeug.middleware.proxy_fix import ProxyFix
	from werkzeug.security import check_password_hash, generate_password_hash
except ImportError:
	raise SystemExit('missing required flask library (pip install flask)')

try:
	from PIL import Image
except ImportError:
	raise SystemExit('missing required Pillow library (pip install Pillow)')

import art
import captcha
import db


HERE = os.path.dirname(os.path.abspath(__file__))


def load_env(path: str) -> dict:
	'''Read KEY=value pairs from a .env file.

	:param path: .env file path
	'''

	env = {}
	if os.path.exists(path):
		with open(path) as fd:
			for line in fd:
				if '=' in line and not line.lstrip().startswith('#'):
					key, value = line.strip().split('=', 1)
					env[key.strip()] = value.strip().strip('\'"')
	return env


ENV          = {**load_env(os.path.join(HERE, '.env')), **os.environ}
REPO         = os.path.join(HERE, os.path.expanduser(ENV.get('REPO', '~/dev/git/ircart/ircart')))
ART          = os.path.realpath(os.path.join(REPO, 'ircart'))
DATA         = os.path.join(HERE, os.path.expanduser(ENV.get('DATA', 'data')))
SITE         = ENV.get('SITE_URL', 'https://ircart.supernets.org').rstrip('/')
MAX_BYTES    = 3 * 1024 * 1024
MAX_LINES    = 10_000
AVATAR_BYTES = 512 * 1024
AVATAR_PX    = 512
NAME_RE      = re.compile(r'^[A-Za-z0-9_-]{3,20}$')
ART_RE       = re.compile(r'^[A-Za-z0-9_-]{1,40}$')
REASONS      = {'broken': 'Broken / renders wrong', 'wrong_dir': 'Wrong directory', 'wrong_name': 'Wrong name', 'wrong_author': 'Wrong author'}

os.makedirs(os.path.join(DATA, 'avatars'), exist_ok=True)

app = Flask(__name__)
app.secret_key = ENV['SECRET_KEY']
app.config.update(MAX_CONTENT_LENGTH=MAX_BYTES + 65536, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=ENV.get('SECURE_COOKIES') == '1', PERMANENT_SESSION_LENGTH=30 * 86400)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

state = {'index': {}, 'ready': False, 'progress': 0, 'near': [], 'near_status': 'waiting', 'near_progress': 0, 'git': 'never pulled', 'pulling': False}
lock  = threading.RLock()


def admin_only(func):
	'''Decorator that rejects requests from non-admin accounts.'''

	@wraps(func)
	def wrapper(*args, **kwargs):
		user = current_user()
		if not user or not user['admin']:
			return jsonify({'error': 'admin only'}), 403
		return func(*args, **kwargs)
	return wrapper


def art_path(name: str) -> str:
	'''Turn an art name into a safe absolute .txt path inside the art directory.

	:param name: art name relative to the art directory, without .txt
	'''

	path = os.path.realpath(os.path.join(ART, name + '.txt'))
	if not name or not path.startswith(ART + os.sep) or name.startswith('.') or '/.' in name:
		raise ValueError(f'invalid name: {name}')
	return path


def build_index():
	'''Scan the art directory, follow renamed files & refresh the database hashes.'''

	index = art.scan(ART, os.path.join(DATA, 'index.pickle'), lambda p: state.update(progress=p))
	con   = db.connect(os.path.join(DATA, 'ircart.db'))
	old   = {r['art']: r['sha'] for r in con.execute('SELECT art, sha FROM hashes')}
	by_sha = {}
	for name, entry in index.items():
		by_sha.setdefault(entry['sha'], []).append(name)
	for name, sha in old.items():
		if name not in index:
			targets = [n for n in by_sha.get(sha, []) if n not in old]
			if len(targets) == 1:
				db.move_art(con, name, targets[0])
				print(f'followed {name} -> {targets[0]}', flush=True)
	con.execute('DELETE FROM hashes')
	con.executemany('INSERT INTO hashes (art, sha) VALUES (?, ?)', [(n, e['sha']) for n, e in index.items()])
	con.commit()
	con.close()
	with lock:
		state['index'], state['ready'], state['progress'] = index, True, 100
	full_html.cache_clear()
	print(f'indexed {len(index):,} files', flush=True)


def check_captcha(data: dict) -> str:
	'''Verify (and consume) a captcha answer plus its proof-of-work, returning an error or empty string.

	:param data: request data holding captcha_id, captcha & nonce
	'''

	row = con().execute('SELECT * FROM captchas WHERE id = ?', (str(data.get('captcha_id', '')),)).fetchone()
	con().execute('DELETE FROM captchas WHERE id = ? OR expires < ?', (str(data.get('captcha_id', '')), int(time.time())))
	con().commit()
	if not row or row['expires'] < time.time():
		return 'captcha expired, try again'
	if not captcha.check_pow(row['salt'], str(data.get('nonce', '')), row['bits']):
		return 'captcha verification failed'
	if captcha.hash_answer(str(data.get('captcha', ''))) != row['answer']:
		return 'wrong captcha'
	return ''


def con():
	'''Return the database connection for the current request.'''

	if 'db' not in g:
		g.db = db.connect(os.path.join(DATA, 'ircart.db'))
	return g.db


def current_user():
	'''Return the logged in user row or None.'''

	if 'user' not in g:
		uid    = session.get('uid')
		g.user = con().execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone() if uid else None
	return g.user


def ensure_admin():
	'''Create or update the admin account from the .env credentials.'''

	c = db.connect(os.path.join(DATA, 'ircart.db'))
	row = c.execute('SELECT * FROM users WHERE name = ?', (ENV['ADMIN_USER'],)).fetchone()
	if not row:
		c.execute('INSERT INTO users (name, pw, admin, created) VALUES (?, ?, 1, ?)', (ENV['ADMIN_USER'], generate_password_hash(ENV['ADMIN_PASS']), int(time.time())))
	elif not check_password_hash(row['pw'], ENV['ADMIN_PASS']) or not row['admin']:
		c.execute('UPDATE users SET pw = ?, admin = 1 WHERE id = ?', (generate_password_hash(ENV['ADMIN_PASS']), row['id']))
	c.commit()
	c.close()


def entry_meta(name: str, stats: dict = None, authors: dict = None) -> dict:
	'''Public metadata for one indexed art file.

	:param name: art name
	:param stats: optional {art: (avg, votes)} rating stats
	:param authors: optional {art: author} mapping
	'''

	e = state['index'][name]
	avg, votes = (stats or {}).get(name, (0, 0))
	return {'name': name, 'dir': e['dir'], 'lines': e['lines'], 'cols': e['cols'], 'size': e['size'], 'mtime': e['mtime'], 'avg': avg, 'votes': votes, 'author': (authors or {}).get(name, '')}


def file_changed(removed: str = None, added: str = None):
	'''Update the in-memory index after a file change & regenerate the repository .list.

	:param removed: art name that no longer exists
	:param added: art name that was created or moved into place
	'''

	with lock:
		if removed:
			state['index'].pop(removed, None)
			state['near'] = [p for p in state['near'] if removed not in (p['a'], p['b'])]
		if added:
			state['index'][added] = art.load(ART, added)
			con().execute('INSERT OR REPLACE INTO hashes (art, sha) VALUES (?, ?)', (added, state['index'][added]['sha']))
	if removed:
		con().execute('DELETE FROM hashes WHERE art = ?', (removed,))
	con().commit()
	full_html.cache_clear()
	subprocess.run(['sh', '.genlist'], cwd=ART, check=False)


@lru_cache(maxsize=256)
def full_html(name: str) -> str:
	'''Render a complete art file to HTML.

	:param name: art name
	'''

	with open(art_path(name), 'rb') as fd:
		return art.render_html(art.decode(fd.read()).replace('\r', '').rstrip('\n').split('\n'))


def git(*args) -> subprocess.CompletedProcess:
	'''Run a git command inside the art repository.

	:param args: git arguments
	'''

	return subprocess.run(['git', '-c', f'safe.directory={REPO}', '-C', REPO, *args], capture_output=True, text=True, timeout=300)


def git_pull():
	'''Pull the art repository & re-index when it changed (run in the background by the admin pull button).'''

	try:
		head = git('rev-parse', 'HEAD').stdout.strip()
		pull = git('pull', '--ff-only', '-q')
		if pull.returncode:
			state['git'] = f'pull failed {time.strftime("%Y-%m-%d %H:%M")}: {pull.stderr.strip()[:300]}'
		elif git('rev-parse', 'HEAD').stdout.strip() == head:
			state['git'] = f'already up to date {time.strftime("%Y-%m-%d %H:%M")}'
		else:
			state['git'] = f'pulled {head[:8]}..{git("rev-parse", "--short", "HEAD").stdout.strip()} at {time.strftime("%Y-%m-%d %H:%M")}, re-indexing'
			build_index()
			state['git'] = state['git'].replace(', re-indexing', '')
			near_scan()
	except Exception as ex:
		state['git'] = f'pull error: {ex}'
	finally:
		state['pulling'] = False


def is_main(name: str) -> bool:
	'''Whether an art name belongs to the main gallery (not an upload).

	:param name: art name
	'''

	return not name.startswith('uploads/')


def near_scan():
	'''Run the near duplicate scan over the current index.'''

	while not state['ready']:
		time.sleep(1)
	state['near_status'], state['near_progress'] = 'scanning', 0
	state['near'] = art.near_pairs(ART, dict(state['index']), 0.95, lambda p: state.update(near_progress=p))
	state['near_status'], state['near_progress'] = 'done', 100
	print(f'near scan found {len(state["near"]):,} pairs', flush=True)


def rating_stats() -> dict:
	'''Return {art: (average, votes)} for every rated art.'''

	return {r['art']: (round(r['avg'], 2), r['n']) for r in con().execute('SELECT art, AVG(stars) avg, COUNT(*) n FROM ratings GROUP BY art')}


def user_json(user) -> dict:
	'''Public fields of a user row.

	:param user: user row
	'''

	return {'name': user['name'], 'admin': bool(user['admin']), 'avatar': bool(user['avatar']), 'created': user['created']}


@app.before_request
def csrf_check():
	'''Reject state changing requests without the session CSRF token.'''

	if 'csrf' not in session:
		session['csrf'] = secrets.token_hex(16)
	if request.method == 'POST' and request.headers.get('X-CSRF') != session['csrf']:
		return jsonify({'error': 'bad csrf token, reload the page'}), 400


@app.teardown_appcontext
def close_db(_):
	'''Close the request database connection.'''

	c = g.pop('db', None)
	if c:
		c.close()


@app.post('/api/admin/delete')
@admin_only
def api_admin_delete():
	'''Delete any art file.'''

	name = request.json.get('art', '')
	try:
		os.remove(art_path(name))
	except Exception as ex:
		return jsonify({'error': str(ex)}), 400
	db.delete_art(con(), name)
	file_changed(removed=name)
	return jsonify({'ok': True})


@app.get('/api/admin/dupes')
@admin_only
def api_admin_dupes():
	'''Groups of different main gallery files that share the same name.'''

	groups = {}
	for name in state['index']:
		if is_main(name):
			groups.setdefault(name.rsplit('/', 1)[-1], []).append(name)
	return jsonify([{'name': k, 'files': sorted(v)} for k, v in sorted(groups.items()) if len(v) > 1])


@app.post('/api/admin/ignore')
@admin_only
def api_admin_ignore():
	'''Mark a near duplicate pair as not a duplicate.'''

	a, b = sorted([request.json.get('a', ''), request.json.get('b', '')])
	con().execute('INSERT OR IGNORE INTO ignored (a, b) VALUES (?, ?)', (a, b))
	con().commit()
	return jsonify({'ok': True})


@app.post('/api/admin/move')
@admin_only
def api_admin_move():
	'''Move, rename or promote an art file, refusing any name clash.'''

	name, dest = request.json.get('art', ''), request.json.get('dest', '').strip().removesuffix('.txt')
	base       = dest.rsplit('/', 1)[-1]
	clashes    = sorted(n for n in state['index'] if n.rsplit('/', 1)[-1] == base and n != name and is_main(n) == is_main(dest))
	if clashes:
		return jsonify({'error': f'name clash: {base}', 'clashes': clashes}), 409
	try:
		src, dst = art_path(name), art_path(dest)
		if os.path.exists(dst):
			raise ValueError(f'{dest} already exists')
		if not os.path.isdir(os.path.dirname(dst)):
			raise ValueError(f'directory does not exist: {os.path.dirname(dest) or "(root)"}')
		os.rename(src, dst)
	except Exception as ex:
		return jsonify({'error': str(ex)}), 400
	upload = con().execute('SELECT u.name FROM uploads p JOIN users u ON u.id = p.user_id WHERE p.art = ?', (name,)).fetchone()
	db.move_art(con(), name, dest)
	if upload and is_main(dest):
		con().execute('DELETE FROM uploads WHERE art = ?', (dest,))
		con().execute('INSERT OR IGNORE INTO authors (art, author) VALUES (?, ?)', (dest, upload['name']))
		con().commit()
	file_changed(removed=name, added=dest)
	return jsonify({'ok': True})


@app.get('/api/admin/near')
@admin_only
def api_admin_near():
	'''Near duplicate pairs not marked as ignored.'''

	ignored = {(r['a'], r['b']) for r in con().execute('SELECT a, b FROM ignored')}
	pairs   = [p for p in state['near'] if tuple(sorted([p['a'], p['b']])) not in ignored and p['a'] in state['index'] and p['b'] in state['index']]
	return jsonify({'status': state['near_status'], 'progress': state['near_progress'], 'pairs': pairs})


@app.post('/api/admin/near/rescan')
@admin_only
def api_admin_near_rescan():
	'''Start a new near duplicate scan in the background.'''

	if state['near_status'] != 'scanning':
		threading.Thread(target=near_scan, daemon=True).start()
	return jsonify({'ok': True})


@app.post('/api/admin/pull')
@admin_only
def api_admin_pull():
	'''Pull the latest art from git, refusing while the clone has uncommitted changes.'''

	dirty = git('status', '--porcelain').stdout.strip().splitlines()
	if dirty:
		return jsonify({'error': f'{len(dirty)} uncommitted change(s) in the art repo, commit & push them first', 'changes': dirty[:50]}), 409
	if state['pulling']:
		return jsonify({'error': 'a pull is already running'}), 409
	state['pulling'], state['git'] = True, 'pulling...'
	threading.Thread(target=git_pull, daemon=True).start()
	return jsonify({'ok': True})


@app.get('/api/admin/reports')
@admin_only
def api_admin_reports():
	'''Open reports with reporter names.'''

	rows = con().execute("SELECT r.*, u.name user FROM reports r JOIN users u ON u.id = r.user_id WHERE r.status = 'open' ORDER BY r.created").fetchall()
	return jsonify([{**dict(r), 'reason_text': REASONS.get(r['reason'], r['reason']), 'exists': r['art'] in state['index']} for r in rows])


@app.post('/api/admin/reports/<int:rid>')
@admin_only
def api_admin_report_status(rid: int):
	'''Resolve or dismiss a report.'''

	status = request.json.get('status')
	if status not in ('resolved', 'dismissed'):
		return jsonify({'error': 'bad status'}), 400
	con().execute('UPDATE reports SET status = ? WHERE id = ?', (status, rid))
	con().commit()
	return jsonify({'ok': True})


@app.get('/api/admin/status')
@admin_only
def api_admin_status():
	'''Git sync & index status for the admin page.'''

	dirty = git('status', '--porcelain').stdout.strip().splitlines()
	return jsonify({'git': state['git'], 'pulling': state['pulling'], 'dirty': dirty[:50], 'dirty_count': len(dirty), 'files': len(state['index']), 'open_reports': con().execute("SELECT COUNT(*) FROM reports WHERE status = 'open'").fetchone()[0]})


@app.get('/api/art/<path:name>')
def api_art(name: str):
	'''Everything the art page needs: render, metadata, rating, author, uploader & comments.'''

	if name not in state['index']:
		return jsonify({'error': 'not found'}), 404
	user   = current_user()
	stats  = con().execute('SELECT AVG(stars) avg, COUNT(*) n FROM ratings WHERE art = ?', (name,)).fetchone()
	author = con().execute('SELECT author FROM authors WHERE art = ?', (name,)).fetchone()
	linked = con().execute('SELECT name FROM users WHERE name = ?', (author['author'],)).fetchone() if author else None
	upload = con().execute('SELECT u.name, p.created FROM uploads p JOIN users u ON u.id = p.user_id WHERE p.art = ?', (name,)).fetchone()
	mine   = con().execute('SELECT stars FROM ratings WHERE art = ? AND user_id = ?', (name, user['id'])).fetchone() if user else None
	notes  = con().execute('SELECT c.body, c.created, u.name, u.avatar FROM comments c JOIN users u ON u.id = c.user_id WHERE c.art = ? ORDER BY c.created', (name,)).fetchall()
	return jsonify({
		'meta'     : entry_meta(name),
		'html'     : full_html(name),
		'avg'      : round(stats['avg'] or 0, 2),
		'votes'    : stats['n'],
		'mine'     : mine['stars'] if mine else 0,
		'author'   : author['author'] if author else '',
		'author_user': linked['name'] if linked else '',
		'uploader' : upload['name'] if upload else '',
		'comments' : [{'user': c['name'], 'avatar': bool(c['avatar']), 'body': c['body'], 'created': c['created']} for c in notes],
		'reasons'  : REASONS})


@app.post('/api/author')
@admin_only
def api_author():
	'''Set or clear the author tag of an art file.'''

	name, author = request.json.get('art', ''), request.json.get('author', '').strip()[:40]
	if name not in state['index']:
		return jsonify({'error': 'not found'}), 404
	if author:
		con().execute('INSERT OR REPLACE INTO authors (art, author) VALUES (?, ?)', (name, author))
	else:
		con().execute('DELETE FROM authors WHERE art = ?', (name,))
	con().commit()
	return jsonify({'ok': True})


@app.get('/api/author/<name>')
def api_author_page(name: str):
	'''All art tagged with an author, plus a linked account if one has the same name.'''

	rows   = con().execute('SELECT art, author FROM authors WHERE author = ? COLLATE NOCASE', (name,)).fetchall()
	linked = con().execute('SELECT name FROM users WHERE name = ?', (name,)).fetchone()
	stats  = rating_stats()
	return jsonify({'author': rows[0]['author'] if rows else name, 'user': linked['name'] if linked else '', 'files': [entry_meta(r['art'], stats, {r['art']: r['author']}) for r in rows if r['art'] in state['index']]})


@app.get('/api/authors')
def api_authors():
	'''Every author name with its art count.'''

	return jsonify([{'author': r['author'], 'count': r['n']} for r in con().execute('SELECT author, COUNT(*) n FROM authors GROUP BY author COLLATE NOCASE ORDER BY author COLLATE NOCASE')])


@app.post('/api/avatar')
def api_avatar():
	'''Upload a profile picture (JPG/PNG, re-encoded server side).'''

	user = current_user()
	if not user:
		return jsonify({'error': 'login required'}), 403
	fd = request.files.get('avatar')
	if not fd:
		return jsonify({'error': 'no file'}), 400
	raw = fd.read(AVATAR_BYTES + 1)
	if len(raw) > AVATAR_BYTES:
		return jsonify({'error': f'max {AVATAR_BYTES // 1024} KB'}), 400
	try:
		img = Image.open(io.BytesIO(raw), formats=('JPEG', 'PNG'))
		img.load()
	except Exception:
		return jsonify({'error': 'only jpg/jpeg/png images'}), 400
	if img.width > AVATAR_PX or img.height > AVATAR_PX:
		return jsonify({'error': f'max {AVATAR_PX}x{AVATAR_PX} pixels (yours is {img.width}x{img.height})'}), 400
	img.convert('RGBA').save(os.path.join(DATA, 'avatars', f'{user["id"]}.png'), 'PNG')
	con().execute('UPDATE users SET avatar = 1 WHERE id = ?', (user['id'],))
	con().commit()
	return jsonify({'ok': True})


@app.get('/api/captcha')
def api_captcha():
	'''Issue a new captcha image & proof-of-work challenge.'''

	if db.limited(con(), f'captcha:{request.remote_addr}', 120, 3600):
		return jsonify({'error': 'too many captchas, slow down'}), 429
	c   = captcha.challenge()
	cid = secrets.token_hex(16)
	con().execute('INSERT INTO captchas (id, answer, salt, bits, expires) VALUES (?, ?, ?, ?, ?)', (cid, captcha.hash_answer(c['answer']), c['salt'], c['bits'], int(time.time()) + 600))
	con().commit()
	return jsonify({'id': cid, 'image': 'data:image/png;base64,' + base64.b64encode(c['image']).decode(), 'salt': c['salt'], 'bits': c['bits']})


@app.post('/api/comment')
def api_comment():
	'''Post a plain text comment on an art file.'''

	user, data = current_user(), request.json
	body = str(data.get('body', '')).strip()
	if not user:
		return jsonify({'error': 'login required'}), 403
	if data.get('art') not in state['index']:
		return jsonify({'error': 'not found'}), 404
	if not 1 <= len(body) <= 1000:
		return jsonify({'error': 'comments must be 1-1000 characters'}), 400
	if error := check_captcha(data):
		return jsonify({'error': error}), 400
	if db.limited(con(), f'comment:{user["id"]}', 20, 3600):
		return jsonify({'error': 'comment limit reached (20 per hour)'}), 429
	con().execute('INSERT INTO comments (art, user_id, body, created) VALUES (?, ?, ?, ?)', (data['art'], user['id'], body, int(time.time())))
	con().commit()
	return jsonify({'ok': True})


@app.get('/api/dirs')
def api_dirs():
	'''Main gallery directories with their file counts.'''

	counts = {}
	for name, e in state['index'].items():
		if is_main(name):
			counts[e['dir']] = counts.get(e['dir'], 0) + 1
	return jsonify([{'dir': d, 'count': n} for d, n in sorted(counts.items())])


@app.get('/api/export/<path:name>')
def api_export(name: str):
	'''Export art as irc, ansi24, ansi256 or html.'''

	fmt = request.args.get('fmt', 'irc')
	if name not in state['index'] or fmt not in ('irc', 'ansi24', 'ansi256', 'html'):
		return jsonify({'error': 'not found'}), 404
	with open(art_path(name), 'rb') as fd:
		return jsonify({'text': art.export(art.decode(fd.read()), fmt)})


@app.get('/api/files')
def api_files():
	'''Metadata for every file in the main gallery or the uploads.'''

	uploads = request.args.get('scope') == 'uploads'
	stats   = rating_stats()
	authors = {r['art']: r['author'] for r in con().execute('SELECT art, author FROM authors')}
	files   = [entry_meta(n, stats, authors) for n in state['index'] if is_main(n) != uploads]
	return jsonify({'ready': state['ready'], 'progress': state['progress'], 'files': files})


@app.post('/api/login')
def api_login():
	'''Log into an account.'''

	data = request.json
	if db.limited(con(), f'login:{request.remote_addr}', 10, 900):
		return jsonify({'error': 'too many login attempts, wait 15 minutes'}), 429
	if error := check_captcha(data):
		return jsonify({'error': error}), 400
	user = con().execute('SELECT * FROM users WHERE name = ?', (str(data.get('name', '')),)).fetchone()
	if not user or not check_password_hash(user['pw'], str(data.get('password', ''))):
		return jsonify({'error': 'wrong username or password'}), 403
	session.clear()
	session.permanent = True
	session['uid'], session['csrf'] = user['id'], secrets.token_hex(16)
	return jsonify({'ok': True})


@app.post('/api/logout')
def api_logout():
	'''Log out.'''

	session.clear()
	return jsonify({'ok': True})


@app.get('/api/me')
def api_me():
	'''The logged in account (if any) & the CSRF token.'''

	user = current_user()
	return jsonify({'user': user_json(user) if user else None, 'csrf': session['csrf']})


@app.post('/api/rate')
def api_rate():
	'''Rate an art file 1-5 stars (changing an earlier rating).'''

	user, data = current_user(), request.json
	if not user:
		return jsonify({'error': 'login required'}), 403
	if data.get('art') not in state['index'] or data.get('stars') not in (1, 2, 3, 4, 5):
		return jsonify({'error': 'bad rating'}), 400
	con().execute('INSERT OR REPLACE INTO ratings (art, user_id, stars, updated) VALUES (?, ?, ?, ?)', (data['art'], user['id'], data['stars'], int(time.time())))
	con().commit()
	return jsonify({'ok': True})


@app.get('/api/recent')
def api_recent():
	'''Latest comments, ratings & uploads site wide.'''

	q = lambda sql: [dict(r) for r in con().execute(sql)]
	return jsonify({
		'comments': q('SELECT c.art, c.body, c.created, u.name user, u.avatar FROM comments c JOIN users u ON u.id = c.user_id ORDER BY c.created DESC LIMIT 40'),
		'ratings' : q('SELECT r.art, r.stars, r.updated created, u.name user FROM ratings r JOIN users u ON u.id = r.user_id ORDER BY r.updated DESC LIMIT 40'),
		'uploads' : q('SELECT p.art, p.created, u.name user FROM uploads p JOIN users u ON u.id = p.user_id ORDER BY p.created DESC LIMIT 40')})


@app.post('/api/register')
def api_register():
	'''Create an account (username & password only).'''

	data = request.json
	name, password = str(data.get('name', '')), str(data.get('password', ''))
	if not NAME_RE.match(name):
		return jsonify({'error': 'usernames are 3-20 letters, digits, _ or -'}), 400
	if len(password) < 8:
		return jsonify({'error': 'passwords must be at least 8 characters'}), 400
	if db.limited(con(), f'register:{request.remote_addr}', 5, 3600):
		return jsonify({'error': 'too many accounts from your address, try later'}), 429
	if error := check_captcha(data):
		return jsonify({'error': error}), 400
	if con().execute('SELECT 1 FROM users WHERE name = ?', (name,)).fetchone():
		return jsonify({'error': 'username taken'}), 400
	cur = con().execute('INSERT INTO users (name, pw, created) VALUES (?, ?, ?)', (name, generate_password_hash(password), int(time.time())))
	con().commit()
	session.clear()
	session.permanent = True
	session['uid'], session['csrf'] = cur.lastrowid, secrets.token_hex(16)
	return jsonify({'ok': True})


@app.post('/api/report')
def api_report():
	'''Report an art file as broken, misplaced, misnamed or mis-credited.'''

	user, data = current_user(), request.json
	if not user:
		return jsonify({'error': 'login required'}), 403
	if data.get('art') not in state['index'] or data.get('reason') not in REASONS:
		return jsonify({'error': 'bad report'}), 400
	if error := check_captcha(data):
		return jsonify({'error': error}), 400
	if db.limited(con(), f'report:{user["id"]}', 30, 86400):
		return jsonify({'error': 'report limit reached (30 per day)'}), 429
	con().execute('INSERT INTO reports (art, user_id, reason, note, created) VALUES (?, ?, ?, ?, ?)', (data['art'], user['id'], data['reason'], str(data.get('note', '')).strip()[:500], int(time.time())))
	con().commit()
	return jsonify({'ok': True})


@app.get('/api/thumbs')
def api_thumbs():
	'''Thumbnail HTML for a batch of art files.'''

	return jsonify({n: state['index'][n]['thumb'] if n in state['index'] else '' for n in request.args.getlist('n')})


@app.post('/api/upload')
def api_upload():
	'''Upload art into uploads/<account>/<name>.txt.'''

	user = current_user()
	if not user:
		return jsonify({'error': 'login required'}), 403
	form = request.form
	name = form.get('name', '').strip().removesuffix('.txt')
	if not ART_RE.match(name):
		return jsonify({'error': 'names are 1-40 letters, digits, _ or -'}), 400
	fd  = request.files.get('file')
	raw = fd.read(MAX_BYTES + 1) if fd and fd.filename else form.get('text', '').encode()
	if not raw.strip():
		return jsonify({'error': 'no art given'}), 400
	if len(raw) > MAX_BYTES:
		return jsonify({'error': f'max {MAX_BYTES // 1024 // 1024} MB'}), 400
	text = art.decode(raw).replace('\r', '').rstrip('\n')
	if text.count('\n') + 1 > MAX_LINES:
		return jsonify({'error': f'max {MAX_LINES:,} lines'}), 400
	if not ''.join(c for c, _, _, _ in art.parse(text.replace('\n', ''))).strip() and '\x03' not in text:
		return jsonify({'error': 'that file has nothing visible in it'}), 400
	if error := check_captcha(form):
		return jsonify({'error': error}), 400
	if db.limited(con(), f'upload:{user["id"]}', 20, 86400):
		return jsonify({'error': 'upload limit reached (20 per day)'}), 429
	art_name = f'uploads/{user["name"]}/{name}'
	path     = art_path(art_name)
	if os.path.exists(path):
		return jsonify({'error': f'you already have an upload named {name}'}), 400
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, 'w', encoding='utf-8') as out:
		out.write(text + '\n')
	con().execute('INSERT OR REPLACE INTO uploads (art, user_id, created) VALUES (?, ?, ?)', (art_name, user['id'], int(time.time())))
	con().commit()
	file_changed(added=art_name)
	return jsonify({'ok': True, 'art': art_name})


@app.post('/api/upload/delete')
def api_upload_delete():
	'''Delete one of your own uploads (admins can delete any upload).'''

	user, name = current_user(), request.json.get('art', '')
	row = con().execute('SELECT user_id FROM uploads WHERE art = ?', (name,)).fetchone()
	if not user or not row or (row['user_id'] != user['id'] and not user['admin']):
		return jsonify({'error': 'not allowed'}), 403
	try:
		os.remove(art_path(name))
	except FileNotFoundError:
		pass
	db.delete_art(con(), name)
	file_changed(removed=name)
	return jsonify({'ok': True})


@app.get('/api/user/<name>')
def api_user(name: str):
	'''Public profile: uploads, authored art & recent comments.'''

	user = con().execute('SELECT * FROM users WHERE name = ?', (name,)).fetchone()
	if not user:
		return jsonify({'error': 'no such user'}), 404
	stats    = rating_stats()
	uploads  = [r['art'] for r in con().execute('SELECT art FROM uploads WHERE user_id = ? ORDER BY created DESC', (user['id'],)) if r['art'] in state['index']]
	authored = [r['art'] for r in con().execute('SELECT art FROM authors WHERE author = ? COLLATE NOCASE', (user['name'],)) if r['art'] in state['index']]
	comments = [dict(r) for r in con().execute('SELECT art, body, created FROM comments WHERE user_id = ? ORDER BY created DESC LIMIT 30', (user['id'],))]
	counts   = {k: con().execute(f'SELECT COUNT(*) FROM {t} WHERE user_id = ?', (user['id'],)).fetchone()[0] for k, t in (('comments', 'comments'), ('ratings', 'ratings'))}
	return jsonify({'user': user_json(user), 'uploads': [entry_meta(n, stats) for n in uploads], 'authored': [entry_meta(n, stats) for n in authored], 'comments': comments, 'counts': counts})


@app.get('/avatar/<name>')
def avatar(name: str):
	'''Serve a user's profile picture.'''

	user = con().execute('SELECT id, avatar FROM users WHERE name = ?', (name,)).fetchone()
	if not user or not user['avatar']:
		abort(404)
	return send_file(os.path.join(DATA, 'avatars', f'{user["id"]}.png'), mimetype='image/png', max_age=300)


@app.get('/favicon.ico')
def favicon():
	'''Serve the favicon from the site root where browsers look for it.'''

	return send_file(os.path.join(HERE, 'static', 'favicon.ico'), mimetype='image/x-icon', max_age=86400)


@app.get('/robots.txt')
def robots():
	'''Allow search engines, keep AI crawlers & scrapers out.'''

	ai = ('GPTBot', 'ChatGPT-User', 'OAI-SearchBot', 'ClaudeBot', 'Claude-Web', 'Claude-User', 'Claude-SearchBot', 'anthropic-ai', 'CCBot', 'Google-Extended', 'GoogleOther', 'Applebot-Extended', 'PerplexityBot', 'Perplexity-User', 'Bytespider', 'Amazonbot', 'meta-externalagent', 'meta-externalfetcher', 'FacebookBot', 'cohere-ai', 'cohere-training-data-crawler', 'Diffbot', 'ImagesiftBot', 'Omgilibot', 'Omgili', 'YouBot', 'AI2Bot', 'Ai2Bot-Dolma', 'DeepSeekBot', 'MistralAI-User', 'PetalBot', 'Timpibot', 'VelenPublicWebCrawler', 'Webzio-Extended', 'iaskspider', 'Kangaroo Bot', 'Scrapy', 'img2dataset', 'DuckAssistBot', 'xAI-Bot', 'GrokBot', 'TikTokSpider', 'SemrushBot', 'AhrefsBot', 'DataForSeoBot', 'MJ12bot', 'DotBot')
	lines = [f'User-agent: {bot}\nDisallow: /\n' for bot in ai]
	lines.append('User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /admin\nDisallow: /login\nDisallow: /register\nDisallow: /upload$\n')
	lines.append(f'Sitemap: {SITE}/sitemap.xml\n')
	return Response('\n'.join(lines), mimetype='text/plain')


@app.get('/sitemap.xml')
def sitemap():
	'''Every public page for search engines.'''

	urls = [(f'{SITE}{p}', None) for p in ('/', '/uploads', '/authors', '/recent', '/about')]
	dirs = sorted({e['dir'] for n, e in state['index'].items() if is_main(n)})
	urls += [(f'{SITE}/dir/{quote(d)}', None) for d in dirs]
	urls += [(f'{SITE}/art/{quote(n)}', time.strftime('%Y-%m-%d', time.gmtime(e['mtime']))) for n, e in sorted(state['index'].items())]
	urls += [(f'{SITE}/author/{quote(r["author"])}', None) for r in con().execute('SELECT DISTINCT author FROM authors')]
	urls += [(f'{SITE}/user/{quote(r["name"])}', None) for r in con().execute('SELECT name FROM users')]
	body = ''.join(f'<url><loc>{escape(u)}</loc>{f"<lastmod>{m}</lastmod>" if m else ""}</url>' for u, m in urls)
	return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>', mimetype='application/xml')


@app.get('/dirs')
def dirs_page():
	'''The directory list lives in the gallery's dir filter now.'''

	return redirect('/', 301)


@app.get('/random')
def random_art():
	'''Redirect to a random main gallery art page.'''

	names = [n for n in state['index'] if is_main(n)]
	return redirect('/art/' + random.choice(names)) if names else redirect('/')


@app.get('/')
@app.get('/<path:page>')
def index(page: str = ''):
	'''Serve the single page app with server rendered content & meta tags for search engines.'''

	if page.startswith(('api/', 'static/')):
		abort(404)
	ctx = seo(page)
	return render_template('index.html', site=SITE, **ctx), ctx.get('status', 200)


def seo(page: str) -> dict:
	'''Title, description, robots, structured data & crawler readable HTML for a page.

	:param page: request path without the leading slash
	'''

	link  = lambda n: f'<li><a href="/art/{quote(n)}">{escape(n)}</a></li>'
	desc  = 'IRCart is the central hub for IRC formatted ASCII & ANSI art: browse, rate & copy thousands of mIRC color art pieces as IRC, ANSI or HTML.'
	ctx   = {'title': 'IRCart - IRC ASCII & ANSI art archive', 'description': desc, 'canonical': f'{SITE}/{quote(page)}', 'robots': 'index, follow', 'jsonld': '', 'body': ''}
	main  = [n for n in state['index'] if is_main(n)]
	dirs  = sorted({state['index'][n]['dir'] for n in main})
	parts = page.split('/', 1)
	if page == '':
		ctx['jsonld'] = json.dumps({'@context': 'https://schema.org', '@type': 'WebSite', 'name': 'IRCart', 'url': SITE + '/', 'description': desc})
		ctx['body']   = f'<h1>IRCart</h1><p>{escape(desc)}</p><h2>Directories</h2><ul>' + ''.join(f'<li><a href="/dir/{quote(d)}">/{escape(d or "(root)")}</a></li>' for d in dirs) + '</ul>'
	elif parts[0] == 'art' and len(parts) == 2:
		name = parts[1]
		if name not in state['index']:
			return {**ctx, 'title': 'Not found - IRCart', 'robots': 'noindex', 'status': 404, 'body': '<h1>Not found</h1>'}
		e      = state['index'][name]
		row    = con().execute('SELECT author FROM authors WHERE art = ?', (name,)).fetchone()
		author = row['author'] if row else ''
		where  = 'user uploads' if not is_main(name) else f'/{e["dir"] or "(root)"}'
		ctx['title']       = f'{name.rsplit("/", 1)[-1]} - IRC art{" by " + author if author else ""} - IRCart'
		ctx['description'] = f'"{name}" IRC ASCII art in {where}{" by " + author if author else ""}: {e["lines"]} lines, {e["cols"]} columns of mIRC colors. View, rate & copy it as IRC, ANSI or HTML.'
		ctx['jsonld']      = json.dumps({'@context': 'https://schema.org', '@type': 'VisualArtwork', 'name': name, 'url': f'{SITE}/art/{quote(name)}', 'artform': 'IRC ASCII art', 'dateModified': time.strftime('%Y-%m-%d', time.gmtime(e['mtime'])), **({'creator': {'@type': 'Person', 'name': author}} if author else {})})
		with open(art_path(name), 'rb') as fd:
			lines = art.decode(fd.read()).replace('\r', '').rstrip('\n').split('\n')
		ctx['body'] = f'<h1>{escape(name)}</h1><p>{escape(ctx["description"])}</p><pre class="art">{art.render_html(lines[:150])}</pre><p><a href="/dir/{quote(e["dir"])}">More art in /{escape(e["dir"] or "(root)")}</a></p>'
	elif parts[0] == 'dir' and len(parts) == 2:
		files = sorted(n for n in main if state['index'][n]['dir'] == parts[1])
		ctx['title']       = f'/{parts[1] or "(root)"} - IRC art directory - IRCart'
		ctx['description'] = f'{len(files)} IRC ASCII & ANSI art pieces in the /{parts[1] or "(root)"} directory of IRCart.'
		ctx['body']        = f'<h1>/{escape(parts[1] or "(root)")}</h1><ul>' + ''.join(link(n) for n in files) + '</ul>'
	elif page == 'uploads':
		ups = sorted(n for n in state['index'] if not is_main(n))
		ctx.update(title='Uploads - IRCart', description='IRC art uploaded by the IRCart community.', body='<h1>Uploads</h1><ul>' + ''.join(link(n) for n in ups) + '</ul>')
	elif page == 'authors':
		rows = con().execute('SELECT DISTINCT author FROM authors ORDER BY author COLLATE NOCASE').fetchall()
		ctx.update(title='Authors - IRCart', description='Artists credited on IRCart.', body='<h1>Authors</h1><ul>' + ''.join(f'<li><a href="/author/{quote(r["author"])}">{escape(r["author"])}</a></li>' for r in rows) + '</ul>')
	elif parts[0] == 'author' and len(parts) == 2:
		rows = [r['art'] for r in con().execute('SELECT art FROM authors WHERE author = ? COLLATE NOCASE', (parts[1],)) if r['art'] in state['index']]
		ctx.update(title=f'{parts[1]} - IRC art by {parts[1]} - IRCart', description=f'{len(rows)} IRC ASCII art pieces by {parts[1]} on IRCart.', body=f'<h1>{escape(parts[1])}</h1><ul>' + ''.join(link(n) for n in rows) + '</ul>')
	elif parts[0] == 'user' and len(parts) == 2:
		ctx.update(title=f'{parts[1]} - IRCart profile', description=f'{parts[1]} on IRCart: uploads, credited art & comments.', body=f'<h1>{escape(parts[1])}</h1>')
	elif page == 'about':
		ctx.update(title='About - IRCart', body=f'<h1>About IRCart</h1><p>{escape(desc)}</p><p>Made by acidvegas for SuperNETs. Source art: <a href="https://git.supernets.org/ircart/ircart">git.supernets.org/ircart/ircart</a>.</p>')
	elif page == 'recent':
		ctx.update(title='Recent activity - IRCart', robots='noindex, follow')
	elif page in ('login', 'register', 'upload') or page.startswith('admin'):
		ctx.update(title=f'{page.split("/")[0].title()} - IRCart', robots='noindex, nofollow')
	else:
		ctx.update(title='Not found - IRCart', robots='noindex', status=404, body='<h1>Not found</h1>')
	return ctx


def startup():
	'''Prepare the admin account & start the background workers.'''

	ensure_admin()
	threading.Thread(target=lambda: (build_index(), near_scan()), daemon=True).start()


startup()



if __name__ == '__main__':
	app.run(host='0.0.0.0', port=int(ENV.get('PORT', '20008')), threaded=True)

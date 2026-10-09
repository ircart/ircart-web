#!/usr/bin/env python3
# IRCart - IRC art parsing, rendering, exporting & indexing

import hashlib
import itertools
import os
import pickle
import re

from html import escape

try:
	import chardet
except ImportError:
	raise SystemExit('missing required chardet library (pip install chardet)')


CODES   = re.compile(r'\x03(\d{1,2})?(?:,(\d{1,2}))?|([\x02\x0f\x11\x16\x1d\x1e\x1f])|(.)')
PALETTE = 'ffffff 000000 00007f 009300 ff0000 7f0000 9c009c fc7f00 ffff00 00fc00 009393 00ffff 0000fc ff00ff 7f7f7f d2d2d2 470000 472100 474700 324700 004700 00472c 004747 002747 000047 2e0047 470047 47002a 740000 743a00 747400 517400 007400 007449 007474 004074 000074 4b0074 740074 740045 b50000 b56300 b5b500 7db500 00b500 00b571 00b5b5 0063b5 0000b5 7500b5 b500b5 b5006b ff0000 ff8c00 ffff00 b2ff00 00ff00 00ffa0 00ffff 008cff 0000ff a500ff ff00ff ff0098 ff5959 ffb459 ffff71 cfff60 6fff6f 65ffc9 6dffff 59b4ff 5959ff c459ff ff66ff ff59bc ff9c9c ffd39c ffff9c e2ff9c 9cff9c 9cffdb 9cffff 9cd3ff 9c9cff dc9cff ff9cff ff94d3 000000 131313 282828 363636 4d4d4d 656565 818181 9f9f9f bcbcbc e2e2e2 ffffff'.split()
RGB     = [(int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)) for c in PALETTE]
THUMB   = (40, 120) # Max lines & columns shown in a thumbnail
CACHE_V = 4 # Bump when the cached index format changes


def ansi256(index: int) -> int:
	'''Find the closest xterm 256 color for an IRC color.

	:param index: IRC color index (0-98)
	'''

	r, g, b = RGB[index]
	cube    = lambda v: 0 if v < 48 else 1 if v < 115 else (v - 35) // 40
	cr, cg, cb = cube(r), cube(g), cube(b)
	levels  = [0, 95, 135, 175, 215, 255]
	cube_c  = 16 + 36 * cr + 6 * cg + cb
	cube_d  = (levels[cr] - r) ** 2 + (levels[cg] - g) ** 2 + (levels[cb] - b) ** 2
	gray    = max(0, min(23, round(((r + g + b) / 3 - 8) / 10)))
	gray_v  = 8 + gray * 10
	gray_d  = (gray_v - r) ** 2 + (gray_v - g) ** 2 + (gray_v - b) ** 2
	return 232 + gray if gray_d < cube_d else cube_c


def ansi_run(key: tuple, text: str, fmt: str) -> str:
	'''Wrap a text run in ANSI escape codes.

	:param key: tuple of (fg, bg, (bold, italic, underline, strike))
	:param text: characters in the run
	:param fmt: ansi24 or ansi256
	'''

	fg, bg, (bold, italic, underline, strike) = key
	codes = ['0']
	for idx, base in ((fg, 38), (bg, 48)):
		if idx is not None and idx != 99:
			codes.append(f'{base};2;{RGB[idx][0]};{RGB[idx][1]};{RGB[idx][2]}' if fmt == 'ansi24' else f'{base};5;{ansi256(idx)}')
	codes += [c for c, on in (('1', bold), ('3', italic), ('4', underline), ('9', strike)) if on]
	return f'\x1b[{";".join(codes)}m{text}'


def decode(raw: bytes) -> str:
	'''Decode an art file the same way the scroll bot does (with UTF-16 support).

	:param raw: raw file contents
	'''

	if b'\x00' in raw:
		return raw.decode('utf-16', errors='replace')
	try:
		return raw.decode('utf-8-sig')
	except UnicodeDecodeError:
		return raw.decode(chardet.detect(raw)['encoding'] or 'utf-8', errors='replace')


def export(text: str, fmt: str) -> str:
	'''Export IRC art as irc (original), ansi24, ansi256 or html (inline styles).

	:param text: decoded IRC art
	:param fmt: export format
	'''

	lines = text.replace('\r', '').rstrip('\n').split('\n')
	if fmt == 'irc':
		return '\n'.join(lines) + '\n'
	out = []
	for line in lines:
		runs, prev = [], None
		for c, f, b, style in parse(line):
			key = (f, b, style)
			if key != prev:
				runs.append([key, ''])
				prev = key
			runs[-1][1] += c
		if fmt == 'html':
			out.append(''.join(html_inline(key, txt) for key, txt in runs))
		else:
			out.append(''.join(ansi_run(key, txt, fmt) for key, txt in runs) + '\x1b[0m')
	if fmt == 'html':
		return '<pre style="background:#000;color:#d2d2d2;font-family:\'DejaVu Sans Mono\',monospace;line-height:normal;margin:0;padding:8px">' + '\n'.join(out) + '</pre>\n'
	return '\n'.join(out) + '\n'


def grid_of(lines: list) -> list:
	'''Turn IRC lines into visible cells (char, fg, bg) used for similarity checks.

	:param lines: list of IRC formatted lines
	'''

	grid = []
	for line in lines:
		cells = []
		for c, f, b, _ in parse(line):
			if c == '\u2588': # a full block is just a background in its foreground color
				c, b = ' ', f
			elif f is not None and f == b: # text in its own background color is invisible
				c = ' '
			cells.append((c, None if c == ' ' else f, b))
		while cells and cells[-1][0] == ' ' and cells[-1][2] in (None, 1, 99):
			cells.pop()
		grid.append(tuple(cells))
	while grid and not grid[-1]:
		grid.pop()
	while grid and not grid[0]:
		grid.pop(0)
	return grid


def html_inline(key: tuple, text: str) -> str:
	'''Wrap a text run in a span with inline styles for standalone HTML.

	:param key: tuple of (fg, bg, (bold, italic, underline, strike))
	:param text: characters in the run
	'''

	fg, bg, (bold, italic, underline, strike) = key
	css = []
	if fg is not None and fg != 99: css.append(f'color:#{PALETTE[fg]}')
	if bg is not None and bg != 99: css.append(f'background:#{PALETTE[bg]}')
	if bold:      css.append('font-weight:bold')
	if italic:    css.append('font-style:italic')
	if underline or strike: css.append('text-decoration:' + ' '.join(d for d, on in (('underline', underline), ('line-through', strike)) if on))
	return f'<span style="{";".join(css)}">{escape(text)}</span>' if css else escape(text)


def load(root: str, name: str) -> dict:
	'''Read an art file & return its metadata, thumbnail HTML & content hash.

	:param root: art directory
	:param name: art name relative to the art directory, without .txt
	'''

	path = os.path.join(root, name + '.txt')
	with open(path, 'rb') as fd:
		raw = fd.read()
	lines = decode(raw).replace('\r', '').rstrip('\n').split('\n')
	grid  = grid_of(lines)
	stat  = os.stat(path)
	return {'name': name, 'dir': name.rsplit('/', 1)[0] if '/' in name else '', 'lines': len(lines), 'cols': max((len(r) for r in grid), default=0), 'size': len(raw), 'mtime': int(stat.st_mtime), 'height': len(grid), 'sha': hashlib.sha1(raw).hexdigest(), 'thumb': render_html(lines[:THUMB[0]], THUMB[1]), 'key': (stat.st_mtime_ns, stat.st_size)}


def near_pairs(root: str, index: dict, threshold: float = 0.95, progress=None) -> list:
	'''Find pairs of files whose rendered art matches at least the threshold.

	Files can only match others with the same rendered height, so grids are built one height group at a time to keep memory low.

	:param root: art directory
	:param index: mapping of art name to index entry
	:param threshold: minimum similarity (0-1)
	:param progress: optional callback receiving a 0-100 percentage
	'''

	groups = {}
	for name, entry in index.items():
		if entry['height'] >= 3:
			groups.setdefault(entry['height'], []).append(name)
	groups = [g for g in groups.values() if len(g) > 1]
	total  = sum(len(g) * (len(g) - 1) // 2 for g in groups) or 1
	pairs, done = [], 0
	for names in groups:
		grids = {}
		for n in names:
			try:
				with open(os.path.join(root, n + '.txt'), 'rb') as fd:
					grids[n] = grid_of(decode(fd.read()).replace('\r', '').rstrip('\n').split('\n'))
			except FileNotFoundError: # deleted or moved since the index snapshot
				continue
		names  = list(grids)
		widths = {n: max(map(len, grids[n]), default=0) for n in names}
		for a, b in itertools.combinations(names, 2):
			done += 1
			if progress and done % 50_000 == 0:
				progress(done * 100 // total)
			if abs(widths[a] - widths[b]) > 2:
				continue
			if (sim := similarity(grids[a], grids[b])) >= threshold:
				pairs.append({'a': a, 'b': b, 'sim': round(sim * 100, 2)})
	return sorted(pairs, key=lambda p: -p['sim'])


def similarity(ga: list, gb: list) -> float:
	'''Fraction of non blank cells that match between two grids of the same height (0 when clearly different).

	:param ga: first grid
	:param gb: second grid
	'''

	blank = lambda c: c is None or (c[0] == ' ' and c[2] in (None, 1, 99))
	tot = same = 0
	for la, lb in zip(ga, gb):
		for i in range(max(len(la), len(lb))):
			ca = la[i] if i < len(la) else None
			cb = lb[i] if i < len(lb) else None
			if blank(ca) and blank(cb):
				continue
			tot  += 1
			same += ca == cb
		if tot > 200 and same / tot < 0.6:
			return 0
	return same / tot if tot else 0


def matches(root: str, index: dict, text: str, threshold: float = 0.95) -> list:
	'''Existing art that new art matches at least the threshold, best first.

	:param root: art directory
	:param index: mapping of art name to index entry
	:param text: decoded art with LF line endings
	:param threshold: minimum similarity (0-1)
	'''

	grid  = grid_of(text.rstrip('\n').split('\n'))
	width = max(map(len, grid), default=0)
	found = []
	if len(grid) < 3:
		return found
	for name, entry in index.items():
		if entry['height'] != len(grid) or abs(entry['cols'] - width) > 2:
			continue
		try:
			with open(os.path.join(root, name + '.txt'), 'rb') as fd:
				other = grid_of(decode(fd.read()).replace('\r', '').rstrip('\n').split('\n'))
		except FileNotFoundError:
			continue
		if (sim := similarity(grid, other)) >= threshold:
			found.append({'name': name, 'cols': entry['cols'], 'sim': round(sim * 100, 2)})
	return sorted(found, key=lambda m: -m['sim'])[:5]


def parse(line: str) -> list:
	'''Parse one IRC formatted line into cells of (char, fg, bg, style).

	:param line: IRC formatted line
	'''

	fg = bg = None
	bold = italic = underline = strike = reverse = False
	cells = []
	for m in CODES.finditer(line):
		if m.group(4) is not None:
			f, b = (bg, fg) if reverse else (fg, bg)
			cells.append((m.group(4), f, b, (bold, italic, underline, strike)))
		elif m.group(3):
			c = m.group(3)
			if c == '\x0f':
				fg = bg = None
				bold = italic = underline = strike = reverse = False
			elif c == '\x02': bold      = not bold
			elif c == '\x1d': italic    = not italic
			elif c == '\x1f': underline = not underline
			elif c == '\x1e': strike    = not strike
			elif c == '\x16': reverse   = not reverse
		elif m.group(1) is None and m.group(2) is None:
			fg = bg = None
		else:
			if m.group(1) is not None:
				fg = int(m.group(1)) % 100
			if m.group(2) is not None:
				bg = int(m.group(2)) % 100
	return cells


def render_html(lines: list, max_cols: int = None) -> str:
	'''Render IRC formatted lines to HTML spans using palette classes.

	:param lines: list of IRC formatted lines
	:param max_cols: optional column limit for thumbnails
	'''

	out = []
	for line in lines:
		html, run, key = [], [], None
		for c, f, b, style in parse(line)[:max_cols]:
			k = (f, b, style)
			if k != key:
				if run:
					html.append(span(key, ''.join(run)))
				run, key = [], k
			run.append(c)
		if run:
			html.append(span(key, ''.join(run)))
		out.append(''.join(html))
	return '\n'.join(out)


def scan(root: str, cache_file: str, progress=None) -> dict:
	'''Index every art file under root, reusing cached entries for unchanged files.

	:param root: art directory
	:param cache_file: pickle file holding the previous index
	:param progress: optional callback receiving a 0-100 percentage
	'''

	cache = {}
	if os.path.exists(cache_file):
		try:
			with open(cache_file, 'rb') as fd:
				data = pickle.load(fd)
			if data.get('v') == CACHE_V:
				cache = data['index']
		except Exception:
			cache = {}
	names = sorted(os.path.relpath(os.path.join(r, f), root)[:-4] for r, d, fs in os.walk(root) for f in fs if f.endswith('.txt') and not f.startswith('.') and '/.' not in r + '/')
	index = {}
	for count, name in enumerate(names, 1):
		path = os.path.join(root, name + '.txt')
		try:
			stat = os.stat(path)
			old  = cache.get(name)
			index[name] = old if old and old['key'] == (stat.st_mtime_ns, stat.st_size) else load(root, name)
		except Exception as ex:
			print(f'failed to load {name}: {ex}', flush=True)
		if progress and count % 200 == 0:
			progress(count * 100 // len(names))
	tmp = cache_file + '.tmp'
	with open(tmp, 'wb') as fd:
		pickle.dump({'v': CACHE_V, 'index': index}, fd)
	os.replace(tmp, cache_file)
	return index


def span(key: tuple, text: str) -> str:
	'''Wrap a text run in a span with the classes for its colors & style.

	:param key: tuple of (fg, bg, (bold, italic, underline, strike))
	:param text: the characters in the run
	'''

	fg, bg, (bold, italic, underline, strike) = key
	cls = [f'f{fg}' if fg is not None and fg != 99 else '', f'b{bg}' if bg is not None and bg != 99 else '', 'B' if bold else '', 'I' if italic else '', 'U' if underline else '', 'S' if strike else '']
	cls = ' '.join(c for c in cls if c)
	return f'<span class="{cls}">{escape(text)}</span>' if cls else escape(text)

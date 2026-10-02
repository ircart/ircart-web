#!/usr/bin/env python3
# IRCart - SQLite storage for accounts, comments, ratings, reports, authors & uploads

import sqlite3
import time


SCHEMA = '''
CREATE TABLE IF NOT EXISTS users    (id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE NOT NULL, pw TEXT NOT NULL, admin INTEGER DEFAULT 0, avatar INTEGER DEFAULT 0, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS comments (id INTEGER PRIMARY KEY, art TEXT NOT NULL, user_id INTEGER NOT NULL, body TEXT NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ratings  (art TEXT NOT NULL, user_id INTEGER NOT NULL, stars INTEGER NOT NULL, updated INTEGER NOT NULL, PRIMARY KEY (art, user_id));
CREATE TABLE IF NOT EXISTS reports  (id INTEGER PRIMARY KEY, art TEXT NOT NULL, user_id INTEGER NOT NULL, reason TEXT NOT NULL, note TEXT, created INTEGER NOT NULL, status TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS authors  (art TEXT PRIMARY KEY, author TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS uploads  (art TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS hashes   (art TEXT PRIMARY KEY, sha TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ignored  (a TEXT NOT NULL, b TEXT NOT NULL, PRIMARY KEY (a, b));
CREATE TABLE IF NOT EXISTS captchas (id TEXT PRIMARY KEY, answer TEXT NOT NULL, salt TEXT NOT NULL, bits INTEGER NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS hits     (key TEXT NOT NULL, at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS comments_art  ON comments (art);
CREATE INDEX IF NOT EXISTS comments_user ON comments (user_id);
CREATE INDEX IF NOT EXISTS ratings_user  ON ratings (user_id);
CREATE INDEX IF NOT EXISTS reports_art   ON reports (art);
CREATE INDEX IF NOT EXISTS authors_name  ON authors (author COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS hits_key      ON hits (key, at);
'''
ART_TABLES = ('comments', 'ratings', 'reports', 'authors', 'uploads', 'hashes') # Tables keyed by an art name


def connect(path: str) -> sqlite3.Connection:
	'''Open the database with sane defaults & make sure the schema exists.

	:param path: sqlite database file
	'''

	con = sqlite3.connect(path, timeout=15, check_same_thread=False)
	con.row_factory = sqlite3.Row
	con.execute('PRAGMA journal_mode=WAL')
	con.execute('PRAGMA foreign_keys=ON')
	con.executescript(SCHEMA)
	return con


def delete_art(con: sqlite3.Connection, art: str):
	'''Remove every row that belongs to an art name.

	:param con: database connection
	:param art: art name
	'''

	for table in ART_TABLES:
		con.execute(f'DELETE FROM {table} WHERE art = ?', (art,))
	con.execute('DELETE FROM ignored WHERE a = ? OR b = ?', (art, art))
	con.commit()


def limited(con: sqlite3.Connection, key: str, limit: int, window: int) -> bool:
	'''Record a hit for a rate limit key & report whether the limit is exceeded.

	:param con: database connection
	:param key: rate limit bucket (e.g. login:1.2.3.4)
	:param limit: max hits allowed in the window
	:param window: window length in seconds
	'''

	now = int(time.time())
	con.execute('DELETE FROM hits WHERE at < ?', (now - 86400,))
	count = con.execute('SELECT COUNT(*) FROM hits WHERE key = ? AND at > ?', (key, now - window)).fetchone()[0]
	if count >= limit:
		con.commit()
		return True
	con.execute('INSERT INTO hits (key, at) VALUES (?, ?)', (key, now))
	con.commit()
	return False


def move_art(con: sqlite3.Connection, old: str, new: str):
	'''Re-key every row from an old art name to a new one.

	:param con: database connection
	:param old: previous art name
	:param new: new art name
	'''

	for table in ART_TABLES:
		con.execute(f'UPDATE OR REPLACE {table} SET art = ? WHERE art = ?', (new, old))
	con.execute('UPDATE OR IGNORE ignored SET a = ? WHERE a = ?', (new, old))
	con.execute('UPDATE OR IGNORE ignored SET b = ? WHERE b = ?', (new, old))
	con.commit()

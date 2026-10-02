#!/usr/bin/env python3
# IRCart - self-hosted image captcha with a proof-of-work challenge

import glob
import hashlib
import io
import math
import os
import random
import secrets

try:
	from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:
	raise SystemExit('missing required Pillow library (pip install Pillow)')


ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789' # No 0/O, 1/I/L lookalikes
LENGTH   = 6
POW_BITS = 16 # Leading zero bits required in sha256(salt + nonce)
SIZE     = (280, 96)
FONTS    = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts', '*.ttf')))


def challenge() -> dict:
	'''Create a new captcha: the answer, a PNG image & a proof-of-work salt.'''

	answer = ''.join(secrets.choice(ALPHABET) for _ in range(LENGTH))
	return {'answer': answer, 'image': render(answer), 'salt': secrets.token_hex(16), 'bits': POW_BITS}


def check_pow(salt: str, nonce: str, bits: int) -> bool:
	'''Verify that sha256(salt + nonce) starts with the required number of zero bits.

	:param salt: challenge salt
	:param nonce: nonce found by the browser
	:param bits: required leading zero bits
	'''

	digest = int.from_bytes(hashlib.sha256((salt + nonce).encode()).digest(), 'big')
	return len(nonce) < 32 and digest >> (256 - bits) == 0


def hash_answer(answer: str) -> str:
	'''Normalize & hash a captcha answer for storage.

	:param answer: captcha text
	'''

	return hashlib.sha256(answer.strip().upper().encode()).hexdigest()


def render(text: str) -> bytes:
	'''Draw the captcha text with per-character fonts, rotation, warping & noise.

	:param text: captcha answer
	'''

	rnd = random.SystemRandom()
	w, h = SIZE
	img = Image.new('RGB', (w, h))
	px  = img.load()
	c1, c2 = [tuple(rnd.randint(20, 70) for _ in range(3)) for _ in range(2)]
	for x in range(w):
		t = x / w
		for y in range(h):
			px[x, y] = tuple(int(a + (b - a) * t) + rnd.randint(-12, 12) for a, b in zip(c1, c2))
	draw = ImageDraw.Draw(img)
	for _ in range(6):
		x0, y0 = rnd.randint(-80, w - 40), rnd.randint(-60, h - 20)
		draw.arc([x0, y0, x0 + rnd.randint(40, 200), y0 + rnd.randint(20, 120)], rnd.randint(0, 360), rnd.randint(0, 360), fill=tuple(rnd.randint(60, 140) for _ in range(3)), width=rnd.randint(1, 3))
	x = rnd.randint(8, 22)
	for ch in text:
		font  = ImageFont.truetype(rnd.choice(FONTS), rnd.randint(40, 54)) if FONTS else ImageFont.load_default(size=46)
		glyph = Image.new('RGBA', (80, 80))
		ImageDraw.Draw(glyph).text((15, 5), ch, font=font, fill=tuple(rnd.randint(170, 255) for _ in range(3)) + (255,))
		glyph = glyph.rotate(rnd.uniform(-35, 35), resample=Image.BICUBIC, expand=False)
		img.paste(glyph, (x, rnd.randint(-2, 22)), glyph)
		x += rnd.randint(30, 40)
	amp, period, phase = rnd.uniform(4, 7), rnd.uniform(40, 70), rnd.uniform(0, 6.28)
	warped = Image.new('RGB', (w, h))
	for col in range(w):
		shift = int(amp * math.sin(col / period * 6.28 + phase))
		warped.paste(img.crop((col, 0, col + 1, h)), (col, shift))
	draw = ImageDraw.Draw(warped)
	for _ in range(3):
		pts = [(rnd.randint(0, w // 4), rnd.randint(10, h - 10))] + [(rnd.randint(w * i // 4, w * (i + 1) // 4), rnd.randint(10, h - 10)) for i in range(1, 4)]
		draw.line(pts, fill=tuple(rnd.randint(150, 230) for _ in range(3)), width=2, joint='curve')
	for _ in range(500):
		draw.point((rnd.randrange(w), rnd.randrange(h)), fill=tuple(rnd.randint(80, 255) for _ in range(3)))
	warped = warped.filter(ImageFilter.SMOOTH)
	buf = io.BytesIO()
	warped.save(buf, 'PNG')
	return buf.getvalue()

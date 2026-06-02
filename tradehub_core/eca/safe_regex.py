"""SafeRegex — ECA condition'larında kullanılan güvenli re wrapper.

ECA Rule.condition Python ifadesinde re modülü yerine bu sınıf inject edilir.
Satıcı kötü niyetli regex yazarsa (örn. `(a+)+` ReDoS) worker tıkanmaz.
"""

import re
import signal

MAX_PATTERN_LENGTH = 200
MATCH_TIMEOUT_SECONDS = 0.1

_CATASTROPHIC = [
	re.compile(r"\([^)]*[+*][^)]*\)[+*]"),
	re.compile(r"\([^|)]+\|[^)]+\)[+*]"),
]


class RegexError(Exception):
	pass


class SafeRegex:
	IGNORECASE = re.IGNORECASE
	I = re.IGNORECASE
	MULTILINE = re.MULTILINE
	M = re.MULTILINE
	UNICODE = re.UNICODE
	U = re.UNICODE
	DOTALL = re.DOTALL
	S = re.DOTALL

	@staticmethod
	def search(pattern, string, flags=0):
		_validate(pattern)
		return _with_timeout(lambda: re.search(pattern, string, flags))

	@staticmethod
	def match(pattern, string, flags=0):
		_validate(pattern)
		return _with_timeout(lambda: re.match(pattern, string, flags))

	@staticmethod
	def fullmatch(pattern, string, flags=0):
		_validate(pattern)
		return _with_timeout(lambda: re.fullmatch(pattern, string, flags))

	@staticmethod
	def findall(pattern, string, flags=0):
		_validate(pattern)
		return _with_timeout(lambda: re.findall(pattern, string, flags))

	@staticmethod
	def sub(pattern, repl, string, count=0, flags=0):
		_validate(pattern)
		return _with_timeout(lambda: re.sub(pattern, repl, string, count=count, flags=flags))


def _validate(pattern):
	if not isinstance(pattern, str):
		raise RegexError("Pattern bir string olmalı")
	if len(pattern) > MAX_PATTERN_LENGTH:
		raise RegexError(f"Pattern çok uzun (max {MAX_PATTERN_LENGTH})")
	for cat in _CATASTROPHIC:
		if cat.search(pattern):
			raise RegexError("Catastrophic backtracking riski tespit edildi")


def _with_timeout(fn, timeout=MATCH_TIMEOUT_SECONDS):
	"""Unix signal.alarm tabanlı timeout. Worker process'te ana thread'de çalışır."""

	def _handler(signum, frame):
		raise RegexError("Regex match timeout")

	try:
		old = signal.signal(signal.SIGALRM, _handler)
	except (ValueError, AttributeError):
		return fn()
	signal.setitimer(signal.ITIMER_REAL, timeout)
	try:
		return fn()
	finally:
		signal.setitimer(signal.ITIMER_REAL, 0)
		try:
			signal.signal(signal.SIGALRM, old)
		except ValueError:
			pass

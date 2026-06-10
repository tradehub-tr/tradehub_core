"""Feed indirme guvenligi: SSRF korumasi ve boyut limiti.

Kullanici tarafindan saglanan feed URL'leri sunucu tarafindan cekildigi icin
SSRF (Server-Side Request Forgery) riski tasir. Bu modul, hedef hostname'i
cozer ve ortaya cikan tum IP adreslerini dahili/ozel araliklara karsi dogrular;
ayrica indirilen icerigi sabit bir bayt limitiyle sinirlar.
"""

import ipaddress
import socket
from urllib.parse import urlparse

import frappe
import requests

# Bulut metadata endpoint'i (AWS/GCP/Azure link-local). is_link_local zaten
# 169.254.0.0/16'yi kapsar, ancak okunabilirlik icin acikca tutuluyor.
_METADATA_IP = "169.254.169.254"


def validate_feed_url(url):
	"""URL'yi SSRF'e karsi dogrula; guvensizse frappe.throw eder.

	- Yalnizca http/https semasina izin verilir (file://, gopher://, ftp:// vb. bloklu).
	- Hostname socket.getaddrinfo ile cozulur; cozulen TUM IP'ler kontrol edilir.
	  Tek bir IP'yi onaylayip baska bir IP'ye baglanmak (DNS rebinding yuzeyi)
	  yerine her aday adres dogrulanir.
	- Ozel/loopback/link-local/reserved/multicast adresler ve 0.0.0.0 reddedilir;
	  bu sayede localhost, ic ag ve bulut metadata servisi engellenir.
	"""
	if not url or not isinstance(url, str):
		frappe.throw("Gecersiz feed URL.")

	parsed = urlparse(url.strip())

	if parsed.scheme not in ("http", "https"):
		# Yalnizca http/https; diger semalar SSRF/dosya okuma vektorudur.
		frappe.throw("Feed URL yalnizca http veya https olabilir.")

	hostname = parsed.hostname
	if not hostname:
		frappe.throw("Feed URL gecerli bir host icermiyor.")

	try:
		# Tum A/AAAA kayitlarini cozer; round-robin DNS'te birden cok IP gelebilir.
		addr_infos = socket.getaddrinfo(hostname, parsed.port or None, proto=socket.IPPROTO_TCP)
	except socket.gaierror:
		frappe.throw("Feed host adresi cozumlenemedi.")

	resolved_ips = {info[4][0] for info in addr_infos}
	if not resolved_ips:
		frappe.throw("Feed host adresi cozumlenemedi.")

	for raw_ip in resolved_ips:
		try:
			ip = ipaddress.ip_address(raw_ip)
		except ValueError:
			# Cozulen deger gecerli bir IP degilse guvenli tarafta kal.
			frappe.throw("Feed host adresi dogrulanamadi.")

		# 0.0.0.0 (ve "::") bazi yiginlarda yerel servislere yonlenir.
		if ip.is_unspecified or raw_ip == "0.0.0.0":
			frappe.throw("Feed URL dahili bir adrese isaret ediyor.")

		if (
			ip.is_private
			or ip.is_loopback
			or ip.is_link_local
			or ip.is_reserved
			or ip.is_multicast
			or raw_ip == _METADATA_IP
		):
			# Ozel ag, loopback (localhost), link-local (bulut metadata) vb. bloklu.
			frappe.throw("Feed URL dahili veya ayrilmis bir adrese isaret ediyor.")


def fetch_feed(url, max_bytes=52428800, timeout=30):
	"""Feed'i guvenli sekilde indirir ve ham bayt olarak dondurur.

	- Once validate_feed_url ile SSRF kontrolu yapilir.
	- requests stream=True ile cekilir; tum icerik bellege alinmaz, parca parca okunur.
	- Content-Length basligi veya akis sirasinda biriken boyut max_bytes'i asarsa
	  throw edilir (decompression/bellek tuketim saldirilarina karsi sinir).
	"""
	validate_feed_url(url)

	try:
		response = requests.get(url, timeout=timeout, stream=True)
	except requests.RequestException:
		frappe.throw("Feed indirilemedi.")

	with response:
		if not (200 <= response.status_code < 300):
			# 2xx disindaki yanitlar (yonlendirme/hata) icerik olarak kabul edilmez.
			frappe.throw(f"Feed sunucusu {response.status_code} dondurdu.")

		# Sunucu bildiriyorsa Content-Length'i indirmeden once kontrol et.
		content_length = response.headers.get("Content-Length")
		if content_length:
			try:
				declared = int(content_length)
			except ValueError:
				declared = None
			if declared is not None and declared > max_bytes:
				frappe.throw("Feed boyutu izin verilen siniri asiyor.")

		chunks = []
		total = 0
		for chunk in response.iter_content(chunk_size=65536):
			if not chunk:
				continue
			total += len(chunk)
			if total > max_bytes:
				# Content-Length yalan soylese bile akis sirasinda hard limit uygulanir.
				frappe.throw("Feed boyutu izin verilen siniri asiyor.")
			chunks.append(chunk)

	return b"".join(chunks)

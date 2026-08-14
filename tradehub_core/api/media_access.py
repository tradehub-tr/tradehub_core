"""İmzalı süreli private medya erişimi — TUR-126 §3.

Private dosya (`/private/files/`) bugün **yalnız oturumla** erişilebiliyor.
Bu modül girişsiz, süreli, imzalı bir paylaşım linki ekliyor — kendi kriptosu
YAZILMAZ, Frappe'nin `frappe.utils.verified_command` primitifi (site secret
ile HMAC-SHA512) kullanılır.

İki uçnokta:

  - `get_signed_url` — çağıranın dosyaya READ yetkisi olduğunu
    (`File.has_permission("read")`) doğrular, sonra `file=<url>&exp=<ts>`
    parametrelerini imzalar. **Yetkisiz kullanıcı için imza üretilmez** —
    bu modülün tek kritik güvenlik kuralı. Guest çağıramaz.
  - `download` (`allow_guest=True`) — imzayı (`verify_request`) ve süreyi
    (`exp`) doğrular, yalnız `/private/files/` altındaki dosyayı serve eder.
    `frappe.utils.response.download_private_file` KULLANILMAZ — o oturum
    zorunlu kılıyor (`frappe.session.user == "Guest"` → Forbidden), imzalı
    link tam olarak oturumsuz erişim için var. Bunun yerine alt seviye
    `send_private_file` (aynı X-Accel-Redirect deseni) + kendi path-safety
    kontrolümüz kullanılır (`check_path_safety` — Frappe'nin backup indirme
    uçnoktasının izlediği aynı desen, `frappe/utils/response.py:
    download_backup`).

İmza yalnız imza anındaki yetkilendirmeyi taşır: link'i alan, süre boyunca
o dosyaya erişir (bilinçli — paylaşım özelliğinin amacı bu). Bu yüzden TTL
üst sınırla clamp'lenir (varsayılan sınırsız DEĞİL).

Detay: docs/MEDYA-ERISIM-MODELI.md §3.
"""

from __future__ import annotations

import time

import frappe
from frappe import _
from frappe.core.doctype.file.utils import check_path_safety
from frappe.utils.response import send_private_file
from frappe.utils.verified_command import get_signed_params, verify_request

from tradehub_core.media import audit

# Yalnız private dosyalar imzalanabilir — public zaten girişsiz açık
# (docs/MEDYA-ERISIM-MODELI.md §2.1), imza gereksiz + güvenlik riski
# (public path'i "private" gibi imzalatıp meşrulaştırmak anlamsız).
PRIVATE_PREFIX = "/private/files/"

DEFAULT_TTL_SECONDS = 900
MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 86400


def _clamp_ttl(ttl_seconds: int | str | None) -> int:
	"""TTL'i [MIN_TTL_SECONDS, MAX_TTL_SECONDS] aralığına sıkıştır.

	Üst sınır olmadan link isteyen taraf pratikte sınırsız süreli bir kapı
	açabilir — TUR-126 tasarımının açık kararı (§3.2: "üst sınır sabit").
	"""
	try:
		ttl = int(ttl_seconds) if ttl_seconds not in (None, "") else DEFAULT_TTL_SECONDS
	except (TypeError, ValueError):
		ttl = DEFAULT_TTL_SECONDS
	return max(MIN_TTL_SECONDS, min(ttl, MAX_TTL_SECONDS))


def _require_private_path(file_url: str) -> str:
	"""`file_url`'ün güvenli, `/private/files/` altında bir yol olduğunu doğrula.

	İki ayrı reddediş nedeni TEK fonksiyonda: path traversal (`..`) ve
	public path (`/files/...`) — ikisi de "bu uçnokta bu dosyayı imzalamaz/
	servis etmez" demek, çağıran taraf için tek bir doğrulama noktası yeterli.
	"""
	file_url = (file_url or "").strip()
	if not file_url or ".." in file_url or not file_url.startswith(PRIVATE_PREFIX):
		frappe.throw(_("Yalnız private dosyalar için imzalı bağlantı üretilebilir."))
	return file_url


def _log_denied(reason: str, file_url: str = "") -> None:
	"""`download()`'da reddedilen bir denemeyi denetime yaz.

	`download` guest'e açık — imzasız/süresi geçmiş/bozuk link denemeleri
	(brute-force, probe) bugüne kadar HİÇ iz bırakmadan geçiyordu (yalnız
	başarılı indirme `media.signed_access` ile kaydediliyordu). Reddedilen
	istekler her zaman tekil kaydedilir kuralı burada da geçerli (bkz.
	`media/audit.py` modül dokümanı: "kapsam ihlali güvenlik olayıdır").

	`file_url` doğrulanmamış/iddia edilen değer olabilir (örn. imza henüz
	kontrol edilmeden önce) — `sensitive=True` ile fingerprint'e çevrilir,
	ham yol denetim kaydına düşmez. `log_media_event` zaten best-effort
	(hata patlarsa yutar) — red akışını bozmaz.
	"""
	audit.log_media_event(
		action=audit.ACTION_ACCESS_DENIED,
		file_url=file_url,
		allowed=False,
		reason=reason,
		sensitive=bool(file_url),
	)


@frappe.whitelist()
def get_signed_url(file_url: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict:
	"""Çağıranın read yetkisi olan bir private dosya için imzalı süreli link üret.

	Args:
	    file_url: `File.file_url`, `/private/files/...` ile başlamalı.
	    ttl_seconds: Linkin geçerlilik süresi. `MAX_TTL_SECONDS`'ı aşarsa
	        sessizce clamp edilir (üst sınır asla aşılamaz).

	Returns:
	    `{"url": "...", "exp": <unix ts>, "ttl_seconds": <clamp'lenmiş>}`

	Güvenlik: yetkisiz kullanıcı için imza ÜRETİLMEZ — `File.has_permission
	("read")` (owner / DocShare / bağlı-doküman delegasyonu) reddederse
	`frappe.PermissionError` fırlatılır, reddediş denetime yazılır.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Bu işlem için giriş yapmalısınız."), frappe.PermissionError)

	file_url = _require_private_path(file_url)

	file_doc = frappe.get_doc("File", {"file_url": file_url})
	if not file_doc.has_permission("read"):
		audit.log_media_event(
			action=audit.ACTION_ACCESS_DENIED,
			file_url=file_url,
			allowed=False,
			reason="signed_url_denied",
		)
		frappe.throw(_("Bu dosyaya erişim yetkiniz yok."), frappe.PermissionError)

	ttl = _clamp_ttl(ttl_seconds)
	exp = int(time.time()) + ttl
	signed = get_signed_params({"file": file_url, "exp": exp})

	return {
		"url": "/api/method/tradehub_core.api.media_access.download?" + signed,
		"exp": exp,
		"ttl_seconds": ttl,
	}


@frappe.whitelist(allow_guest=True)
def download():
	"""İmzalı süreli link ile private dosya indir — oturum GEREKMEZ.

	Sıra: imza doğrula → path doğrula (defansif) → süre doğrula → path
	tekrar doğrula (disk'e inmeden hemen önce, ikinci savunma katmanı) →
	serve et → audit'e yaz. **Her red dalı da denetime yazılır** (`_log_
	denied`) — guest'e açık bir uçnokta olduğu için aksi hâlde brute-force/
	probe denemeleri hiç iz bırakmadan geçer.
	"""
	# Denetim amaçlı: imza/exp geçersiz çıksa bile hangi dosyanın hedeflendiği
	# soruşturma değeri taşır. Yalnız KAYIT amaçlı — serve kararı asla bu ham
	# değere dayanmaz, aşağıdaki her adım kendi başına yeniden doğrular.
	claimed_file = (frappe.form_dict.get("file") or "").strip()

	if not verify_request():
		_log_denied("invalid_signature", claimed_file)
		frappe.throw(_("Bağlantı geçersiz."), frappe.PermissionError)

	try:
		file_url = _require_private_path(claimed_file)
	except Exception:
		_log_denied("bad_path", claimed_file)
		raise

	exp_raw = frappe.form_dict.get("exp")
	try:
		exp = int(exp_raw)
	except (TypeError, ValueError):
		# `exp_raw` sayısal değilse (`"abc"`) ya da hiç gelmediyse (`None`)
		# — ikisi de aynı `int()` çağrısında patlar, aynı red yoluna düşer.
		_log_denied("malformed_exp", file_url)
		frappe.throw(_("Geçersiz bağlantı parametresi."), frappe.PermissionError)

	if exp <= int(time.time()):
		_log_denied("expired", file_url)
		frappe.throw(_("Bağlantının süresi doldu."), frappe.PermissionError)

	# `file_url` imza tarafından kapsandığı için burada değiştirilemez, ama
	# servis katmanı yine de kendi path-safety kontrolünü yapar — imza
	# doğrulamasındaki olası bir gelecekteki regresyon disk erişimine kadar
	# sızmasın (bkz. `frappe/utils/response.py:download_backup` aynı desen).
	private_root = frappe.get_site_path("private")
	relative = file_url[len("/private/") :]  # "files/ab/xyz.jpg"
	target = frappe.get_site_path("private", relative)
	if not check_path_safety(base_path=private_root, requested_path=target):
		_log_denied("bad_path", file_url)
		frappe.throw(_("Geçersiz dosya yolu."), frappe.PermissionError)

	response = send_private_file(relative)

	audit.log_media_event(
		action=audit.ACTION_SIGNED_ACCESS,
		file_url=file_url,
		allowed=True,
		context={"signed": True},
	)

	return response

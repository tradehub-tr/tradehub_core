"""Medya motoru hata sözleşmesi — tek hiyerarşi, kodlu ret (FR-060, FR-061).

Neden ayrı bir hiyerarşi
------------------------
Çalışan motorda ret sözleşmesi `tradehub_core/media/upload_policy.py` içinde
`Kod(kod, retryable)` ikilisi olarak zaten var ve **çalışıyor** — istemci hata
METNİNE değil koda bakıyor (FR-060). Ama o hiyerarşi `frappe.ValidationError`
türevi: `import frappe` gerektiriyor, dolayısıyla site/bench olmadan test
edilemiyor ve motorun saf katmanında (`engine.py`, `gates.py` — bilinçli olarak
frappe'siz) kullanılamıyor.

Bu modül aynı sözleşmeyi **frappe'siz** yeniden ifade eder. `upload_policy`
YENİDEN YAZILMAZ: adaptasyon tek yönlüdür ve `to_response()` çıktısı bugünkü
`frappe.local.response["upload_error"]` alanıyla birebir uyumludur —
`upload_policy.reddet()` ne yazıyorsa `MediaEngineError.kod` da onu taşır.

`retryable` kuralı (upload_policy.py:90-96 ile AYNI)
----------------------------------------------------
Kullanıcının dosyasıyla ilgili hatalar tekrar denenmez (aynı dosya aynı sonucu
verir); geçici sistem hataları denenir. Bu ayrım istemcinin otomatik yeniden
deneme davranışını belirler, dolayısıyla sözleşmenin parçasıdır.

Kod adlandırma
--------------
`<slot_error_code_prefix>_<sebep>` — prefix slot politikasının
`on_violation.error_code_prefix` alanından gelir (ör. `product_image`), sebep
bu modüldeki `SEBEP_*` sabitlerinden biridir. Slot bağlamı olmayan hatalarda
prefix `media` olur.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# ── İhlal sebepleri ─────────────────────────────────────────────────────
#
# Bu sabitler kod ÜRETİMİNDE kullanılır (`kod_uret`). Serbest metin yazmak
# yerine sabit kullanmak, aynı sebebin iki slotta iki farklı yazımla
# görünmesini engeller (NFR-046: aynı kural iki yerde tekrar yazılmaz).

SEBEP_MIME_NOT_ALLOWED = "mime_not_allowed"
SEBEP_EXT_NOT_ALLOWED = "ext_not_allowed"
SEBEP_EXT_CONTENT_MISMATCH = "ext_content_mismatch"
SEBEP_TOO_LARGE = "too_large"
SEBEP_EMPTY = "empty"
SEBEP_DANGEROUS_CONTENT = "dangerous_content"
SEBEP_MEGAPIXEL_BOMB = "megapixel_bomb"
SEBEP_ANIMATED_NOT_ALLOWED = "animated_not_allowed"
SEBEP_SHORT_EDGE_TOO_SMALL = "short_edge_too_small"
SEBEP_AREA_TOO_SMALL = "area_too_small"
SEBEP_RATIO_NOT_ALLOWED = "ratio_not_allowed"
SEBEP_COUNT_EXCEEDED = "count_exceeded"
SEBEP_SAFE_AREA_VIOLATION = "safe_area_violation"
SEBEP_ALPHA_LOST = "alpha_lost"
SEBEP_COLORSPACE_UNCONVERTIBLE = "colorspace_unconvertible"
SEBEP_UNDER_SPEC = "under_spec"
SEBEP_DURATION_OUT_OF_RANGE = "duration_out_of_range"
SEBEP_BITRATE_EXCEEDED = "bitrate_exceeded"
SEBEP_EXTERNAL_URL = "external_url"
SEBEP_DECODE_FAILED = "decode_failed"
SEBEP_ENCODE_FAILED = "encode_failed"
SEBEP_UNSUPPORTED_FORMAT = "unsupported_format"
SEBEP_NOT_FOUND = "not_found"
SEBEP_CONFLICT = "conflict"
SEBEP_PROBE_UNAVAILABLE = "probe_unavailable"
SEBEP_TRANSCODE_FAILED = "transcode_failed"
SEBEP_POLICY_NOT_FOUND = "policy_not_found"
SEBEP_POLICY_INVALID = "policy_invalid"
SEBEP_NO_PROFILE = "no_profile"

VARSAYILAN_PREFIX = "media"


def kod_uret(prefix: str, sebep: str) -> str:
	"""`<prefix>_<sebep>` kodunu üretir; prefix boşsa `media` kullanılır.

	Saf fonksiyon — aynı girdi her zaman aynı kodu verir (idempotent).
	"""
	return f"{(prefix or VARSAYILAN_PREFIX).strip('_')}_{sebep}"


class MediaEngineError(Exception):
	"""Motorun tüm hatalarının ortak atası.

	Args:
	    mesaj: Kullanıcıya gösterilebilir metin. FR-062 gereği NEDEN + NASIL
	        düzeltilir sorularını birlikte yanıtlamalıdır; bu sınıf metni
	        doğrulamaz, sözleşmeyi taşır.
	    kod: İstemcinin karar vereceği makine-okunur kod (FR-060).
	    retryable: İstemci aynı isteği yeniden denemeli mi.
	    detay: Ek bağlam (ölçülen değer, beklenen değer, slot anahtarı...).
	        Denetim kaydına ve hata mesajı interpolasyonuna girer.

	Hiçbir alt sınıf hassas değer (dosya yolu, kullanıcı e-postası) taşımaz —
	maskeleme çağıranın değil, üretenin sorumluluğudur (NFR-035).
	"""

	varsayilan_sebep: str = SEBEP_DECODE_FAILED
	varsayilan_retryable: bool = False

	def __init__(
		self,
		mesaj: str,
		*,
		kod: Optional[str] = None,
		retryable: Optional[bool] = None,
		detay: Optional[Dict[str, Any]] = None,
	) -> None:
		super().__init__(mesaj)
		self.mesaj: str = mesaj
		self.kod: str = kod or kod_uret(VARSAYILAN_PREFIX, self.varsayilan_sebep)
		self.retryable: bool = self.varsayilan_retryable if retryable is None else retryable
		self.detay: Dict[str, Any] = dict(detay or {})

	def to_response(self) -> Dict[str, Any]:
		"""İstemciye dönecek sözlük — `upload_policy` yanıt biçimiyle uyumlu.

		`error_code` anahtarı bilinçli: bugünkü istemci
		`frappe.local.response["upload_error"]` okuyor, yeni uçlar bu sözlüğü
		döndürecek. İki ad arasındaki köprü uç katmanının işidir; sözleşme
		tek kodu taşır.
		"""
		return {
			"error_code": self.kod,
			"retryable": self.retryable,
			"message": self.mesaj,
			"details": dict(self.detay),
		}

	def __repr__(self) -> str:
		return f"{type(self).__name__}(kod={self.kod!r}, retryable={self.retryable!r})"


# ── Politika ────────────────────────────────────────────────────────────


class PolicyError(MediaEngineError):
	"""Politika kayıt defteriyle ilgili hatalar."""

	varsayilan_sebep = SEBEP_POLICY_INVALID


class PolicyNotFound(PolicyError):
	"""İstenen `slot_key` kayıt defterinde yok.

	FR-001: slot verilmeden gelen çağrı "slotsuz" (L0) davranışa düşer ve
	loglanır — bu hata yalnız BİLİNMEYEN bir slot adı verildiğinde atılır.
	"""

	varsayilan_sebep = SEBEP_POLICY_NOT_FOUND


class PolicyViolation(MediaEngineError):
	"""Dosya slot politikasını ihlal etti — kullanıcı hatası, tekrar denenmez.

	`detay` içinde en az `slot_key`, `alan` (`accept`/`require`/`master`/
	`quality`/`content_rules`) ve ölçülen/beklenen değerler bulunur; hata
	mesajının somut çözüm cümlesi (FR-063) bu değerlerden üretilir.
	"""

	varsayilan_sebep = SEBEP_RATIO_NOT_ALLOWED


# ── Depolama ────────────────────────────────────────────────────────────


class StorageError(MediaEngineError):
	"""Depolama katmanı hatası — çoğu geçicidir, varsayılan `retryable=True`."""

	varsayilan_sebep = SEBEP_CONFLICT
	varsayilan_retryable = True


class ObjectNotFound(StorageError):
	"""Anahtar depoda yok. Tekrar denemek sonucu değiştirmez."""

	varsayilan_sebep = SEBEP_NOT_FOUND
	varsayilan_retryable = False


class StorageConflict(StorageError):
	"""İçerik-adresli anahtar AYNI, içerik FARKLI.

	Bu bir hash çakışması değil, neredeyse her zaman çağıranın anahtarı elle
	üretmesinden doğar. Sessizce üzerine yazmak, iki farklı dosyanın tek
	fiziksel dosyaya çökmesi demek olurdu (NFR-050'nin tersi yönde ihlali).
	"""

	varsayilan_retryable = False


# ── Görsel ──────────────────────────────────────────────────────────────


class ImageError(MediaEngineError):
	"""Görsel işleme hatası."""

	varsayilan_sebep = SEBEP_DECODE_FAILED


class DecodeError(ImageError):
	"""Baytlar geçerli bir görsel değil ya da açılamıyor.

	`engine.probe()`'un `readable=False` çıktısının sözleşme karşılığı.
	"""

	varsayilan_sebep = SEBEP_DECODE_FAILED


class EncodeError(ImageError):
	"""Çıktı üretilemedi ya da üretilen çıktı doğrulanamadı.

	NFR-041: yarım dosya asla yazılmaz — bu hata atıldığında depoya HİÇBİR
	ŞEY yazılmamış olmalıdır.
	"""

	varsayilan_sebep = SEBEP_ENCODE_FAILED
	varsayilan_retryable = True


class UnsupportedFormat(ImageError):
	"""Biçim motorun desteklediği kümede değil (`engine.SUPPORTED_FORMATS`)."""

	varsayilan_sebep = SEBEP_UNSUPPORTED_FORMAT


class OversizedImage(ImageError):
	"""Piksel sayısı `accept.max_megapixels_hard` tavanını aşıyor (FR-011, FR-143).

	Görselin TAMAMI açılmadan, yalnız başlıktan karar verilir — decompression
	bomb korumasının anlamı budur.
	"""

	varsayilan_sebep = SEBEP_MEGAPIXEL_BOMB


# ── Video ───────────────────────────────────────────────────────────────


class VideoError(MediaEngineError):
	"""Video işleme hatası."""

	varsayilan_sebep = SEBEP_TRANSCODE_FAILED
	varsayilan_retryable = True


class ProbeUnavailable(VideoError):
	"""`ffprobe` yok ya da metadata okunamadı.

	NFR-043 gereği çağıran GÜVENLİ TARAFA düşmelidir: ölçemediğin videoyu
	"kurallara uygun" saymak yerine işlenmemiş kabul et.
	"""

	varsayilan_sebep = SEBEP_PROBE_UNAVAILABLE


class TranscodeFailed(VideoError):
	"""ffmpeg başarısız oldu. `detay["attempts"]` deneme sayısını taşır.

	`retryable=True`: `media/jobs.py` politikası (MAX_ATTEMPTS=3, backoff
	300/900 sn) uygulanır; hak dolunca çağıran dead-letter'a düşürür.
	"""

	varsayilan_sebep = SEBEP_TRANSCODE_FAILED


# ── Teslim ──────────────────────────────────────────────────────────────


class DeliveryError(MediaEngineError):
	"""Teslim manifestosu üretilemedi."""

	varsayilan_sebep = SEBEP_NO_PROFILE


class NoProfileAvailable(DeliveryError):
	"""İstenen genişliğe hizmet edebilecek türev profili yok.

	FR-033: master `min_long_edge` altındaysa dosya REDDEDİLMEZ, hangi
	profillerin üretilemediği işaretlenir — bu hata o işaretin sert biçimidir
	ve yalnız manifest üretimi hiçbir varyant bulamadığında atılır.
	"""

	varsayilan_sebep = SEBEP_NO_PROFILE


__all__ = [
	"MediaEngineError",
	"PolicyError",
	"PolicyNotFound",
	"PolicyViolation",
	"StorageError",
	"ObjectNotFound",
	"StorageConflict",
	"ImageError",
	"DecodeError",
	"EncodeError",
	"UnsupportedFormat",
	"OversizedImage",
	"VideoError",
	"ProbeUnavailable",
	"TranscodeFailed",
	"DeliveryError",
	"NoProfileAvailable",
	"kod_uret",
]

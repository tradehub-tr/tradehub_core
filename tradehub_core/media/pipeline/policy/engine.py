"""PolicyEngine — slot politikalarını VERİ olarak okuyup karar veren tek yer.

    evaluate(slot, probe, role) → Decision(allow, violations[], normalized_targets)

TASARIM SÖZÜ
------------
Yeni bir slot eklemek `policy/slots/` altına bir JSON dosyası koymaktır. BU
DOSYA DEĞİŞMEZ. Kod yalnız şemada olmayan YENİ BİR KISIT TÜRÜ eklenirken
değişir; yeni bir slot, yeni bir eşik, yeni bir oran, yeni bir mesaj kod
değişikliği gerektirmez. `test_policy_engine.py` bunu makine olarak doğrular:
`slots/` altındaki her JSON, motorda o slota özel tek bir `if` olmadan
değerlendirilebiliyor mu.

NEDEN VAR
---------
Bugün sunucu bir yüklemenin hangi slota ait olduğunu BİLMİYOR:
`tradehub_core/media/upload_policy.py:306-312` `check()` imzasında slot
parametresi yok (docs/reports/00-upload-slot-envanteri.md §7-B B1). Sonuç
canlıda ölçüldü: `product.image` yüklemelerinin %48,6'sı, `document.attachment`
yüklemelerinin %91,8'i slot politikasına uymuyor. Bu modül o eksik kimliğin
karar karşılığıdır.

MEVCUT MOTORLA İLİŞKİ (yeniden yazılan hiçbir şey yok)
------------------------------------------------------
    upload_policy.check()   platform tabanı: ad/uzantı/deny-list/boyut. KALIR.
                            PolicyEngine ONUN ÜSTÜNE slot katmanı koyar; iki
                            kapıdan ikisi de geçilmelidir.
    gates.check_before()    optimizasyon kapıları (dosyaya dokunulsun mu).
                            PolicyEngine "kabul edilsin mi"ye cevap verir;
                            farklı soru, çakışma yok.
    engine.probe()          künye — `core/probe.py` ÇAĞIRIR, kopyalamaz.

AKSİYON SÖZLEŞMESİ
------------------
Her ihlalin aksiyonu politikadaki `on_violation` bloğundan gelir; blok bazında
(`accept`, `require`, `master`, `quality`, `content_rules`) tanımlıdır ve
tanımsızsa `on_violation.default` kullanılır. Aynı dosyada birden çok ihlal
varsa EN YÜKSEK aksiyon kazanır (content_rules.json `decision_model.aggregation`
ile aynı kural). `allow`, engelleyici (reject/review) ihlal yoksa True'dur —
yani `warn` ve `auto_fix` yüklemeyi DURDURMAZ.

ÖLÇÜLMEYEN EŞİKLER
------------------
`content_rules` bloğundaki bulanıklık/entropi/kenar-oranı gibi kurallar piksel
analizi ister. `MediaProbe` bu metrikleri taşımıyorsa kural DEĞERLENDİRİLMEZ ve
`Decision.skipped` içine `not_measurable` olarak yazılır. Sessizce "geçti"
saymak, kalibre edilmemiş bir eşiğin çalıştığı yanılsamasını üretirdi —
content_rules.json'ın kendi `calibration_status` alanı da "UNCALIBRATED".
"""

from __future__ import annotations

import json
import math
import os
import string
from dataclasses import dataclass, field
from pathlib import Path

from typing import Tuple

from tradehub_core.media.pipeline.contracts import errors as sozlesme_hata
from tradehub_core.media.pipeline.contracts import policy as sozlesme
from tradehub_core.media.pipeline.contracts.image import ImageProbe, MasterSpec, RenditionSpec

# `Decision` adı bu modülde ZATEN DOLU (aşağıdaki `evaluate()` çıktısı).
# Sözleşme kararı ayrı bir addır ve öyle kalmalı: iki tip iki farklı soruya
# cevap veriyor — `Decision.allow` yüklemeyi durdurur mu, `PolicyDecision`
# katman bazında ret/uyarı kovalarını taşır.
from tradehub_core.media.pipeline.contracts.policy import Decision as PolicyDecision
from tradehub_core.media.pipeline.contracts.policy import EffectiveLimits, SlotPolicy
from tradehub_core.media.pipeline.contracts.video import VideoProbe, VideoRenditionSpec
from tradehub_core.media.pipeline.core.errors import (
	ACTION_AUTO_FIX,
	ACTION_IGNORE,
	ACTION_MANUAL_REVIEW,
	ACTION_PASS,
	ACTION_REJECT,
	ACTION_REVIEW,
	ACTION_WARN,
	SILENT_ACTIONS,
	SkippedRule,
	Violation,
	highest_action,
)
from tradehub_core.media.pipeline.core.probe import EXTENSION_KINDS, KIND_VIDEO, MediaProbe
from tradehub_core.media.pipeline.policy import SLOT_DIR

# ── Mesaj çözümü ────────────────────────────────────────────────────────
#
# Politikalar mesajlarını KENDİ anahtar adlarıyla yazmış: `product-image.json`
# `short_edge_too_small` derken `seller-logo.json` `too_small`,
# `product-video.json` `cozunurluk_dusuk` diyor. Anahtarları tek isme zorlamak
# dokuz dosyayı elle düzenlemek demekti; bunun yerine her kural, aday anahtar
# listesi taşır ve slotun `messages.tr` sözlüğünde İLK BULUNAN kazanır.
# Hiçbiri yoksa aşağıdaki gömülü TR/EN kataloğuna düşülür.
MESSAGE_KEYS: dict[str, tuple[str, ...]] = {
	"short_edge_too_small": ("short_edge_too_small", "too_small", "cozunurluk_dusuk"),
	"short_edge_too_large": ("short_edge_too_large",),
	"long_edge_too_large": ("long_edge_too_large", "max_edge_exceeded"),
	"area_too_small": ("area_too_small",),
	"ratio_not_allowed": ("ratio_not_allowed", "oran_16_9_degil"),
	"aspect_out_of_band": ("aspect_out_of_band",),
	"too_many_pixels": ("too_many_pixels",),
	"too_large_bytes": ("too_large_bytes", "too_large", "cok_buyuk"),
	"format_not_supported": ("format_not_supported", "bicim_desteklenmiyor"),
	"mime_not_supported": ("mime_not_supported", "format_not_supported"),
	"extension_rejected": ("extension_rejected", "format_not_supported"),
	"extension_conditional_closed": ("svg_dtd_forbidden", "format_not_supported"),
	"animated": ("animated", "format_animated"),
	"unreadable": ("unreadable", "ffprobe_okunamadi"),
	"truncated": ("unreadable",),
	"data_uri_forbidden": ("data_uri_forbidden",),
	"content_type_mismatch": ("content_type_mismatch",),
	"container_invalid": ("container_invalid",),
	"executable_content": ("executable_content",),
	"appended_payload": ("appended_payload",),
	"low_resolution": ("low_resolution",),
	"master_under_spec": ("master_under_spec",),
	"too_many_items": ("too_many_items",),
	"too_few_items": ("too_few_items",),
	"duration_too_long": ("sure_uzun", "duration_too_long"),
	"duration_too_short": ("duration_too_short",),
	"bitrate_too_high": ("bitrate_isleniyor", "bitrate_too_high"),
	"frame_rate_not_allowed": ("frame_rate_not_allowed",),
	"role_not_allowed": ("role_not_allowed",),
}

#: Gömülü katalog. TR mesajı politikada varsa POLİTİKA kazanır; EN her zaman
#: buradan gelir (politikalarda `messages.en` yok — 9/9 dosyada yalnız `tr`).
#: `hint` ayrı tutulur: mesaj NE olduğunu, ipucu NE YAPILACAĞINI söyler.
FALLBACK: dict[str, dict[str, str]] = {
	"short_edge_too_small": {
		"tr": "Kısa kenar {kisa_kenar} piksel; en az {gerekli_kisa_kenar} piksel gerekiyor.",
		"en": "Short edge is {kisa_kenar}px; at least {gerekli_kisa_kenar}px is required.",
		"hint_tr": "Orijinal (kırpılmamış, sıkıştırılmamış) dosyayı yükleyin.",
		"hint_en": "Upload the original file instead of a resized or messaging-app copy.",
	},
	"short_edge_too_large": {
		"tr": "Kısa kenar {kisa_kenar} piksel; üst sınır {gerekli_kisa_kenar} piksel.",
		"en": "Short edge is {kisa_kenar}px; the maximum is {gerekli_kisa_kenar}px.",
		"hint_tr": "Dosyayı yüklemeden önce küçültün.",
		"hint_en": "Downscale the file before uploading.",
	},
	"long_edge_too_large": {
		"tr": "Uzun kenar {uzun_kenar} piksel; üst sınır {gerekli_uzun_kenar} piksel.",
		"en": "Long edge is {uzun_kenar}px; the maximum is {gerekli_uzun_kenar}px.",
		"hint_tr": "Uzun kenarı {gerekli_uzun_kenar} piksele indirip yeniden yükleyin.",
		"hint_en": "Resize the long edge down to {gerekli_uzun_kenar}px and upload again.",
	},
	"area_too_small": {
		"tr": "Toplam piksel alanı {mp} MP; en az {max_mp} MP gerekiyor.",
		"en": "Total pixel area is {mp} MP; at least {max_mp} MP is required.",
		"hint_tr": "Ekran görüntüsü değil, orijinal fotoğraf dosyasını yükleyin.",
		"hint_en": "Upload the original photo, not a screenshot or thumbnail.",
	},
	"ratio_not_allowed": {
		"tr": "En-boy oranı {oran}; kabul edilen oranlar {izinli_oranlar}.",
		"en": "Aspect ratio is {oran}; accepted ratios are {izinli_oranlar}.",
		"hint_tr": "Görseli izinli oranlardan birine kırpın; boşluğu düz renkle tamamlamak da geçerlidir.",
		"hint_en": "Crop to one of the accepted ratios, or pad with a flat background colour.",
	},
	"aspect_out_of_band": {
		"tr": "Oran bandı dışında ({oran}); izinli bant {izinli_oranlar}.",
		"en": "Aspect ratio {oran} is outside the accepted band {izinli_oranlar}.",
		"hint_tr": "Geniş bir kelime markanız varsa kare (simge) sürümünü yükleyin.",
		"hint_en": "If you have a wide wordmark, upload its square (icon) variant instead.",
	},
	"too_many_pixels": {
		"tr": "Görsel {mp} MP; işlenebilir üst sınır {max_mp} MP.",
		"en": "Image is {mp} MP; the processable maximum is {max_mp} MP.",
		"hint_tr": "Uzun kenarı {gerekli_uzun_kenar} piksele indirip yeniden yükleyin.",
		"hint_en": "Downscale the long edge to {gerekli_uzun_kenar}px and upload again.",
	},
	"too_large_bytes": {
		"tr": "Dosya {mb} MB; bu slot için üst sınır {max_mb} MB.",
		"en": "File is {mb} MB; the limit for this slot is {max_mb} MB.",
		"hint_tr": "JPEG veya WebP olarak kaydedin; bu slotta {max_mb} MB altı beklenir.",
		"hint_en": "Save as JPEG or WebP; this slot expects under {max_mb} MB.",
	},
	"format_not_supported": {
		"tr": "{bicim} biçimi bu slotta kabul edilmiyor. Kabul edilenler: {izinli_bicimler}.",
		"en": "Format {bicim} is not accepted here. Accepted: {izinli_bicimler}.",
		"hint_tr": "Dosyayı {izinli_bicimler} biçimlerinden birine dönüştürüp yükleyin.",
		"hint_en": "Convert the file to one of {izinli_bicimler} and upload again.",
	},
	"mime_not_supported": {
		"tr": "Dosya türü ({bicim}) bu slotta kabul edilmiyor.",
		"en": "Content type ({bicim}) is not accepted in this slot.",
		"hint_tr": "Kabul edilen türler: {izinli_bicimler}.",
		"hint_en": "Accepted types: {izinli_bicimler}.",
	},
	"extension_rejected": {
		"tr": "{bicim} uzantısı bu slotta açıkça reddediliyor.",
		"en": "Extension {bicim} is explicitly rejected in this slot.",
		"hint_tr": "Kabul edilen uzantılar: {izinli_bicimler}.",
		"hint_en": "Accepted extensions: {izinli_bicimler}.",
	},
	"extension_conditional_closed": {
		"tr": "{bicim} uzantısı yalnız koşullu kabul ediliyor ve koşul bugün açık değil.",
		"en": "Extension {bicim} is only conditionally accepted, and the condition is not met.",
		"hint_tr": "Dosyayı PNG veya WebP olarak dışa aktarıp yükleyin.",
		"hint_en": "Export the file as PNG or WebP and upload that instead.",
	},
	"animated": {
		"tr": "Hareketli görsel bu slotta kullanılamaz.",
		"en": "Animated images are not allowed in this slot.",
		"hint_tr": "Tek kareli bir görsel yükleyin; hareket için video alanını kullanın.",
		"hint_en": "Upload a single-frame image; use the video field for motion.",
	},
	"unreadable": {
		"tr": "Dosya bir medya dosyası olarak açılamadı.",
		"en": "The file could not be opened as a media file.",
		"hint_tr": "Dosyayı açıp görüntülenebildiğini doğrulayın, 'Farklı kaydet' ile yeniden kaydedin.",
		"hint_en": "Open the file to confirm it renders, then re-save it and upload again.",
	},
	"truncated": {
		"tr": "Dosya eksik aktarılmış; başlığı sağlam ama verisi kesik.",
		"en": "The file is truncated: the header is intact but the pixel data is incomplete.",
		"hint_tr": "Yüklemeyi tekrarlayın; sorun sürerse dosyayı yeniden dışa aktarın.",
		"hint_en": "Retry the upload; if it persists, re-export the file.",
	},
	"data_uri_forbidden": {
		"tr": "Gömülü veri (data: URI) kabul edilmiyor; dosya olarak yükleyin.",
		"en": "Embedded data (data: URI) is not accepted; upload an actual file.",
		"hint_tr": "Görseli diske kaydedip dosya seçicisinden yükleyin.",
		"hint_en": "Save the image to disk and upload it through the file picker.",
	},
	"content_type_mismatch": {
		"tr": "Dosya uzantısı içeriğiyle uyuşmuyor (uzantı {bicim}, içerik {gercek}).",
		"en": "The extension does not match the content (extension {bicim}, content {gercek}).",
		"hint_tr": "Dosyayı gerçek biçimine uygun uzantıyla yeniden kaydedin.",
		"hint_en": "Re-save the file with the extension matching its real format.",
	},
	"container_invalid": {
		"tr": "Dosyanın içi beklenen belge yapısında değil.",
		"en": "The file's internal structure is not the expected document format.",
		"hint_tr": "Belgeyi kaynak programından yeniden dışa aktarın.",
		"hint_en": "Re-export the document from its source application.",
	},
	"executable_content": {
		"tr": "Dosya çalıştırılabilir ya da betik içerik taşıyor.",
		"en": "The file carries executable or script content.",
		"hint_tr": "Yalnız görsel/belge dosyası yükleyin.",
		"hint_en": "Upload an image or document file only.",
	},
	"appended_payload": {
		"tr": "Görselin sonuna dosya dışı içerik eklenmiş.",
		"en": "Content has been appended after the end of the image data.",
		"hint_tr": "Görseli bir düzenleyicide açıp 'Farklı kaydet' ile temiz bir kopya üretin.",
		"hint_en": "Open the image in an editor and re-save it to produce a clean copy.",
	},
	"low_resolution": {
		"tr": "Çözünürlük düşük ({w}×{h}); önerilen en az {gerekli_kisa_kenar} piksel.",
		"en": "Resolution is low ({w}×{h}); at least {gerekli_kisa_kenar}px is recommended.",
		"hint_tr": "Bu bir engel değil — dosya kaydedildi.",
		"hint_en": "This is not blocking — the file was saved.",
	},
	"master_under_spec": {
		"tr": "Uzun kenar {uzun_kenar} piksel; tam kalite için {gerekli_uzun_kenar} piksel öneriliyor.",
		"en": "Long edge is {uzun_kenar}px; {gerekli_uzun_kenar}px is recommended for full quality.",
		"hint_tr": "Görsel kabul edildi; büyütme yapılmaz, yakınlaştırmada yumuşak görünebilir.",
		"hint_en": "Accepted as-is; no upscaling is performed, so zoom may look soft.",
	},
	"too_many_items": {
		"tr": "Bu slotta en fazla {max_adet} dosya olabilir; şu an {adet} var.",
		"en": "This slot accepts at most {max_adet} files; {adet} are present.",
		"hint_tr": "Önce mevcut dosyalardan silin.",
		"hint_en": "Remove an existing file first.",
	},
	"too_few_items": {
		"tr": "Bu slot en az {min_adet} dosya ister; şu an {adet} var.",
		"en": "This slot requires at least {min_adet} files; {adet} are present.",
		"hint_tr": "Eksik dosyaları yükleyin.",
		"hint_en": "Upload the missing files.",
	},
	"duration_too_long": {
		"tr": "Video {sure} saniye; üst sınır {max_sure} saniye.",
		"en": "The video is {sure}s long; the maximum is {max_sure}s.",
		"hint_tr": "Süreyi kısaltmak dosyayı küçültmenin en etkili yoludur.",
		"hint_en": "Trimming the duration is the most effective way to shrink the file.",
	},
	"duration_too_short": {
		"tr": "Video {sure} saniye; en az {min_sure} saniye gerekiyor.",
		"en": "The video is {sure}s long; at least {min_sure}s is required.",
		"hint_tr": "Daha uzun bir çekim yükleyin.",
		"hint_en": "Upload a longer clip.",
	},
	"bitrate_too_high": {
		"tr": "Bit hızı {bitrate} kbps; tavan {max_bitrate} kbps — sunucuda yeniden sıkıştırılacak.",
		"en": "Bitrate is {bitrate} kbps; the cap is {max_bitrate} kbps — it will be re-encoded.",
		"hint_tr": "Yükleme kabul edildi; işlem arka planda tamamlanıyor.",
		"hint_en": "The upload was accepted; processing continues in the background.",
	},
	"frame_rate_not_allowed": {
		"tr": "Kare hızı {fps}; kabul edilenler {izinli_fps} — {max_fps} fps'e indirilecek.",
		"en": "Frame rate is {fps}; accepted are {izinli_fps} — it will be capped at {max_fps} fps.",
		"hint_tr": "Yükleme kabul edildi.",
		"hint_en": "The upload was accepted.",
	},
	"role_not_allowed": {
		"tr": "'{rol}' rolü bu slota dosya yükleyemez.",
		"en": "Role '{rol}' is not allowed to upload to this slot.",
		"hint_tr": "Yetkili bir hesapla deneyin.",
		"hint_en": "Try again with an authorised account.",
	},
	"no_alpha_channel": {
		"tr": "Dosya saydam zeminli değil.",
		"en": "The file has no transparent background.",
		"hint_tr": "Saydam zeminli PNG ya da WebP olarak yeniden kaydedip yükleyin; bu bir engel değil.",
		"hint_en": "Re-save as PNG or WebP with transparency; this is a warning, not a block.",
	},
	"frame_width": {
		"tr": "Video genişliği {w} piksel; sunucu {max_genislik} piksele küçültecek.",
		"en": "Video width is {w}px; the server will downscale it to {max_genislik}px.",
		"hint_tr": "Yükleme kabul edildi; işlem arka planda tamamlanıyor.",
		"hint_en": "The upload was accepted; processing continues in the background.",
	},
	"bitrate_bps": {
		"tr": "Bit hızı yüksek; sunucuda yeniden sıkıştırılacak.",
		"en": "The bitrate is high; the file will be re-encoded on the server.",
		"hint_tr": "Yükleme kabul edildi; hazır olunca sayfada görünecek.",
		"hint_en": "The upload was accepted; it will appear once processing finishes.",
	},
	"duration_seconds": {
		"tr": "Video süresi uzun.",
		"en": "The video duration is long.",
		"hint_tr": "Süreyi kısaltmak dosyayı küçültmenin en etkili yoludur.",
		"hint_en": "Trimming the duration is the most effective way to shrink the file.",
	},
	"is_private": {
		"tr": "Dosya gizli (private) kaydedildi; sunucu sıkıştırma adımı atlanır.",
		"en": "The file was stored as private; the server compression step is skipped.",
		"hint_tr": "Bu slota herkese açık (public) yükleyin.",
		"hint_en": "Upload to this slot as public instead.",
	},
	"ffprobe_readable": {
		"tr": "Dosyanın teknik bilgileri okunamadı.",
		"en": "The file's technical metadata could not be read.",
		"hint_tr": "Dosya bozuk olabilir; kaynak programından yeniden dışa aktarın.",
		"hint_en": "The file may be corrupt; re-export it from its source application.",
	},
	"_default": {
		"tr": "Kural ihlali: {kural}.",
		"en": "Policy violation: {kural}.",
		"hint_tr": "Ayrıntı için slot kurallarına bakın; dosyayı düzeltip yeniden yükleyin.",
		"hint_en": "See the slot rules for details, then fix the file and upload again.",
	},
}


class _SafeDict(dict):
	"""Bilinmeyen yer tutucuyu OLDUĞU GİBİ bırakır.

	Politika metinleri `{kisa_kenar}` gibi kendi yer tutucularını taşıyor ve her
	mesaj farklı bir küme kullanıyor. `str.format` eksik anahtarda KeyError
	fırlatır; bir mesajın anahtarını yanlış tahmin etmek yüklemeyi 500 ile
	düşürürdü. Eksik anahtar metinde kalır — görünür ama zararsız.
	"""

	def __missing__(self, key):  # noqa: D105
		return "{" + key + "}"


def _fmt(text: str, params: dict) -> str:
	try:
		return string.Formatter().vformat(text, (), _SafeDict(params))
	except Exception:
		return text


def parse_ratio(text: str) -> float:
	"""'4:5' → 0.8. Bozuk girdide 0.0 — kural o zaman değerlendirilmez."""
	try:
		w, h = str(text).split(":", 1)
		w, h = float(w), float(h)
		return (w / h) if h else 0.0
	except Exception:
		return 0.0


@dataclass(frozen=True)
class Decision:
	"""`evaluate()` çıktısı.

	`allow` engelleyici ihlal yoksa True'dur; `warn`/`auto_fix` engellemez.
	`normalized_targets` kabul edilen dosyanın NEYE dönüştürüleceğidir —
	`tradehub_core/media/pipeline/image/` ve `tradehub_core/media/pipeline/video/` bunu uygular, yeniden
	hesaplamaz.
	"""

	allow: bool
	slot: str
	role: str
	action: str
	violations: tuple[Violation, ...] = ()
	normalized_targets: dict = field(default_factory=dict)
	skipped: tuple[SkippedRule, ...] = ()
	policy_version: str = ""
	policy_status: str = ""

	@property
	def codes(self) -> tuple[str, ...]:
		return tuple(v.code for v in self.violations)

	def blocking(self) -> tuple[Violation, ...]:
		return tuple(v for v in self.violations if v.blocking)

	def to_dict(self) -> dict:
		return {
			"allow": self.allow,
			"slot": self.slot,
			"role": self.role,
			"action": self.action,
			"violations": [v.to_dict() for v in self.violations],
			"normalized_targets": self.normalized_targets,
			"skipped": [s.to_dict() for s in self.skipped],
			"policy_version": self.policy_version,
			"policy_status": self.policy_status,
		}


class PolicyNotFound(KeyError):
	"""İstenen slot anahtarı kayıt defterinde yok."""


class PolicyRegistry:
	"""`slots/*.json` dosyalarını slot anahtarına göre tutan kayıt defteri.

	Dosya ADI değil, içindeki `slot_key` anahtardır: dosyayı yeniden
	adlandırmak politikayı bozmasın. İki dosya aynı anahtarı taşırsa yükleme
	hata verir — sessizce biri diğerini ezmesin.
	"""

	def __init__(self, directory: Path | str | None = None) -> None:
		self.directory = Path(directory) if directory else SLOT_DIR
		self._by_key: dict[str, dict] = {}
		self._source: dict[str, Path] = {}
		self.load()

	def load(self) -> "PolicyRegistry":
		"""Diskten oku — YA HEP YA HİÇ.

		Önceki sürüm sözlükleri okumadan ÖNCE temizliyordu: dokuzuncu dosya
		bozuksa istisna dışarı çıkıyor ve kayıt defteri sekiz politikayla
		yarım kalıyordu. Yarım yüklenmiş bir defter, hangi slotun eski hangisinin
		yeni olduğu bilinmeyen bir sistemdir. Yeni sözlükler ayrı kurulur ve
		HEPSİ okunduktan sonra tek atamayla takas edilir; hata hâlinde eski
		defter olduğu gibi kalır (contracts/policy.py `reload()` sözleşmesi).
		"""
		yeni: dict[str, dict] = {}
		kaynak: dict[str, Path] = {}
		for path in sorted(self.directory.glob("*.json")):
			with open(path, encoding="utf-8") as fh:
				data = json.load(fh)
			key = data.get("slot_key")
			if not key:
				raise ValueError(f"slot_key yok: {path}")
			if key in yeni:
				raise ValueError(
					f"slot_key iki dosyada: {key} ({kaynak[key].name} / {path.name})"
				)
			yeni[key] = data
			kaynak[key] = path
		self._by_key = yeni
		self._source = kaynak
		return self

	def keys(self) -> tuple[str, ...]:
		return tuple(sorted(self._by_key))

	def source_of(self, slot: str) -> Path:
		return self._source[slot]

	def get(self, slot: str) -> dict:
		try:
			return self._by_key[slot]
		except KeyError as exc:
			raise PolicyNotFound(
				f"Bilinmeyen slot: {slot!r}. Tanımlı slotlar: {', '.join(self.keys())}"
			) from exc

	def __contains__(self, slot: object) -> bool:
		return slot in self._by_key

	def __len__(self) -> int:
		return len(self._by_key)


class PolicyEngine:
	"""Slot politikalarını uygulayan karar motoru.

	Kullanım:

	    from tradehub_core.media.pipeline.core.probe import probe_file
	    from tradehub_core.media.pipeline.policy.engine import PolicyEngine

	    engine = PolicyEngine()
	    karar = engine.evaluate("product.image", probe_file(yol), role="seller")
	    if not karar.allow:
	        for ihlal in karar.blocking():
	            print(ihlal.code, ihlal.message["tr"], ihlal.hint["tr"])
	"""

	def __init__(self, registry: PolicyRegistry | None = None) -> None:
		self.registry = registry or PolicyRegistry()
		#: `contracts.policy.SlotPolicy` önbelleği — sözleşme `load()`'un aynı
		#: anahtar için aynı nesneyi vermesini istiyor (idempotensi).
		self._slot_policy_cache: dict[str, sozlesme.SlotPolicy] = {}

	# ── genel yardımcılar ────────────────────────────────────────────

	@staticmethod
	def _action_for(policy: dict, block: str) -> str:
		on_violation = policy.get("on_violation") or {}
		return on_violation.get(block) or on_violation.get("default") or ACTION_REJECT

	@staticmethod
	def _code(policy: dict, rule: str) -> str:
		prefix = (policy.get("on_violation") or {}).get("error_code_prefix") or "media"
		return f"{prefix}_{rule}"

	@staticmethod
	def _message(policy: dict, rule: str, params: dict) -> tuple[dict, dict]:
		"""(mesaj, ipucu) — politika TR metnini ezer, EN her zaman katalogdan."""
		tr = ""
		policy_tr = ((policy.get("messages") or {}).get("tr") or {})
		for key in MESSAGE_KEYS.get(rule, (rule,)):
			if policy_tr.get(key):
				tr = policy_tr[key]
				break
		cat = FALLBACK.get(rule) or FALLBACK["_default"]
		if not tr:
			tr = cat["tr"]
		message = {"tr": _fmt(tr, params), "en": _fmt(cat["en"], params)}
		hint = {
			"tr": _fmt(cat.get("hint_tr", ""), params),
			"en": _fmt(cat.get("hint_en", ""), params),
		}
		return message, hint

	def _violation(
		self,
		policy: dict,
		*,
		rule: str,
		block: str,
		params: dict,
		observed=None,
		expected=None,
		action: str | None = None,
		source: str = "",
	) -> Violation:
		params = dict(params)
		params.setdefault("kural", rule)
		message, hint = self._message(policy, rule, params)
		return Violation(
			code=self._code(policy, rule),
			rule=rule,
			block=block,
			action=action or self._action_for(policy, block),
			message=message,
			hint=hint,
			observed=observed,
			expected=expected,
			retryable=False,
			source=source,
		)

	# ── giriş noktası ────────────────────────────────────────────────

	def evaluate(self, slot: str, probe: MediaProbe | dict, role: str = "") -> Decision:
		"""Slot + künye + rol → karar.

		`probe` sözlük verilebilir; `MediaProbe` alanlarına çevrilir. Böylece
		ffprobe/manifest çıktısı doğrudan beslenebilir.
		"""
		if isinstance(probe, dict):
			bilinen = MediaProbe.__dataclass_fields__
			probe = MediaProbe(**{k: v for k, v in probe.items() if k in bilinen})

		policy = self.registry.get(slot)
		violations: list[Violation] = []
		skipped: list[SkippedRule] = []
		p = self._params(policy, probe, role)

		self._check_role(policy, role, p, violations)
		self._check_security(policy, probe, p, violations, skipped)
		self._check_accept(policy, probe, p, violations, skipped)
		self._check_require(policy, probe, p, violations, skipped)
		self._check_video(policy, probe, p, violations, skipped)
		self._check_master(policy, probe, p, violations)
		self._check_content_rules(policy, probe, p, violations, skipped)

		# `ignore` aksiyonlu ihlaller listeden DÜŞER: politika o kuralı
		# bilinçli olarak önemsizleştirmiş, kullanıcıya göstermek gürültüdür.
		# `skipped` ile karıştırılmaz — orası "ölçülemedi", burası "ölçüldü,
		# umursanmadı" (category-banner.json `bottom_third_text_overlap`).
		violations = [v for v in violations if v.action not in SILENT_ACTIONS]
		action = highest_action(v.action for v in violations) if violations else ACTION_PASS
		allow = not any(v.blocking for v in violations)
		targets = self.normalized_targets(policy, probe) if allow else {}

		return Decision(
			allow=allow,
			slot=slot,
			role=role,
			action=action,
			violations=tuple(violations),
			normalized_targets=targets,
			skipped=tuple(skipped),
			policy_version=policy.get("schema_version", ""),
			policy_status=policy.get("status", ""),
		)

	# ── mesaj değişkenleri ───────────────────────────────────────────

	@staticmethod
	def _params(policy: dict, probe: MediaProbe, role: str) -> dict:
		accept = policy.get("accept") or {}
		require = policy.get("require") or {}
		master = policy.get("master") or {}
		w, h = probe.display_size
		izinli = accept.get("extensions") or []
		return {
			"rol": role or "-",
			"w": w,
			"h": h,
			"kisa_kenar": min(w, h) if w and h else 0,
			"uzun_kenar": max(w, h) if w and h else 0,
			"gerekli_kisa_kenar": require.get("min_short_edge", ""),
			"gerekli_uzun_kenar": master.get("max_long_edge", ""),
			"mp": round(probe.megapixels, 2),
			"max_mp": accept.get("max_megapixels_hard", ""),
			"mb": round(probe.byte_size / 1_048_576, 2),
			"max_mb": round((accept.get("max_bytes") or 0) / 1_048_576, 2),
			"oran": f"{(w / h):.3f}".rstrip("0").rstrip(".") if h else "-",
			"izinli_oranlar": ", ".join(require.get("allowed_ratios") or []) or "-",
			"bicim": (probe.extension or probe.fmt or probe.detected or "-"),
			"gercek": probe.detected or "-",
			"izinli_bicimler": ", ".join(izinli) or "-",
			"adet": probe.existing_count if probe.existing_count is not None else "-",
			"max_adet": require.get("max_count", ""),
			"min_adet": require.get("min_count", ""),
			"sure": probe.duration_s if probe.duration_s is not None else "-",
			"bitrate": int(probe.bitrate_bps / 1000) if probe.bitrate_bps else "-",
			"fps": round(probe.frame_rate, 2) if probe.frame_rate else "-",
			"max_genislik": master.get("max_long_edge", ""),
		}

	# ── bloklar ──────────────────────────────────────────────────────

	def _check_role(self, policy, role, p, out) -> None:
		roles = policy.get("roles") or []
		# Rol verilmediyse kural ATLANMAZ ama uygulanmaz: çağıran rolü bilmiyorsa
		# bunu kararla değil, kendi yetki katmanıyla çözmelidir.
		if role and roles and role not in roles:
			out.append(
				self._violation(
					policy,
					rule="role_not_allowed",
					block="policy",
					params=p,
					observed=role,
					expected=roles,
					action=ACTION_REJECT,
					source="policy.roles",
				)
			)

	def _check_security(self, policy, probe: MediaProbe, p, out, skipped) -> None:
		"""Güvenlik bayrakları — blok adı `accept` (aksiyonu oradan alır)."""
		block = "accept"
		if probe.leading_marker:
			out.append(
				self._violation(
					policy,
					rule="executable_content",
					block=block,
					params=p,
					observed="leading_marker",
					action=ACTION_REJECT,
					source="core/probe.py DANGEROUS_MARKERS (upload_policy.py:187 aynası)",
				)
			)
		if probe.detected == "executable":
			out.append(
				self._violation(
					policy,
					rule="executable_content",
					block=block,
					params=p,
					observed=probe.detected,
					action=ACTION_REJECT,
					source="core/probe.py sniff() MZ/ELF",
				)
			)
		if probe.appended_payload:
			out.append(
				self._violation(
					policy,
					rule="appended_payload",
					block=block,
					params=p,
					observed="appended_payload",
					action=ACTION_REJECT,
					source="ÜRETİMDE YOK: upload_policy.is_dangerous() yalnız dosya başına bakıyor",
				)
			)
		if probe.container_valid is False:
			out.append(
				self._violation(
					policy,
					rule="container_invalid",
					block=block,
					params=p,
					observed=probe.detected,
					action=ACTION_REJECT,
					source="kyb.py:46-53 referans uygulaması",
				)
			)
		if probe.scan_clean is False:
			out.append(
				self._violation(
					policy,
					rule="executable_content",
					block=block,
					params=p,
					observed="av_scan",
					action=ACTION_REJECT,
					source="tradehub_core/media/av.py karantina sonucu",
				)
			)
		elif probe.scan_clean is None:
			skipped.append(
				SkippedRule(
					rule="av_scan",
					block=block,
					reason="not_measurable",
					missing_input="scan_clean",
				)
			)

	def _check_accept(self, policy, probe: MediaProbe, p, out, skipped) -> None:
		accept = policy.get("accept") or {}
		block = "accept"
		ext = (probe.extension or "").lower()

		rejected = [e.lower() for e in (accept.get("rejected_extensions") or [])]
		allowed = [e.lower() for e in (accept.get("extensions") or [])]
		conditional = [e.lower() for e in (accept.get("conditional_extensions") or [])]

		if ext and ext in rejected:
			out.append(
				self._violation(
					policy, rule="extension_rejected", block=block, params=p,
					observed=ext, expected=allowed, action=ACTION_REJECT,
					source="accept.rejected_extensions",
				)
			)
		elif ext and ext in conditional and ext not in allowed:
			# Koşullu uzantı: koşul politikanın kendi alt bloğunda ilan edilir.
			# Bugün tek örnek SVG (`logo.svg_policy.enabled`) ve KAPALI.
			if not self._conditional_open(policy, ext):
				out.append(
					self._violation(
						policy, rule="extension_conditional_closed", block=block, params=p,
						observed=ext, expected=allowed, action=ACTION_REJECT,
						source="accept.conditional_extensions + logo.svg_policy.enabled",
					)
				)
		elif ext and allowed and ext not in allowed:
			out.append(
				self._violation(
					policy, rule="format_not_supported", block=block, params=p,
					observed=ext, expected=allowed, source="accept.extensions",
				)
			)

		mimes = accept.get("mime") or []
		if probe.mime and mimes and probe.mime not in mimes:
			out.append(
				self._violation(
					policy, rule="mime_not_supported", block=block, params=p,
					observed=probe.mime, expected=mimes, source="accept.mime",
				)
			)
		elif not probe.mime and mimes:
			skipped.append(
				SkippedRule(rule="mime", block=block, reason="not_measurable", missing_input="mime")
			)

		if probe.extension_matches_content is False:
			out.append(
				self._violation(
					policy, rule="content_type_mismatch", block=block, params=p,
					observed=probe.detected, expected=ext, action=ACTION_REJECT,
					source="FR-009 magic_byte_matches_extension",
				)
			)

		# SVG'nin kendi bayt tavanı var; genel tavandan ayrı okunur.
		max_bytes = accept.get("max_bytes")
		if ext == ".svg" and accept.get("max_bytes_svg"):
			max_bytes = accept["max_bytes_svg"]
		if max_bytes and probe.byte_size > max_bytes:
			pp = dict(p, max_mb=round(max_bytes / 1_048_576, 2))
			out.append(
				self._violation(
					policy, rule="too_large_bytes", block=block, params=pp,
					observed=probe.byte_size, expected=max_bytes, source="accept.max_bytes",
				)
			)

		hard_mp = accept.get("max_megapixels_hard")
		if hard_mp and probe.width and probe.height and probe.megapixels > hard_mp:
			out.append(
				self._violation(
					policy, rule="too_many_pixels", block=block, params=p,
					observed=round(probe.megapixels, 3), expected=hard_mp,
					source="accept.max_megapixels_hard",
				)
			)

		if probe.animated and not accept.get("allow_animated", False):
			out.append(
				self._violation(
					policy, rule="animated", block=block, params=p,
					observed=True, expected=False, source="accept.allow_animated",
				)
			)

		if probe.is_data_uri and accept.get("allow_data_uri") is False:
			out.append(
				self._violation(
					policy, rule="data_uri_forbidden", block=block, params=p,
					observed=True, expected=False, action=ACTION_REJECT,
					source="accept.allow_data_uri",
				)
			)

		# Okunabilirlik: başlık ve piksel ayrı iki soru (fixture truncated.jpg).
		if not probe.readable:
			out.append(
				self._violation(
					policy, rule="unreadable", block=block, params=p,
					observed=False, expected=True, action=ACTION_REJECT,
					source="engine.probe(readable=False)",
				)
			)
		elif probe.loadable is False:
			out.append(
				self._violation(
					policy, rule="truncated", block=block, params=p,
					observed=False, expected=True, action=ACTION_REJECT,
					source="ÖLÇÜLDÜ: engine.probe True der, optimize OSError ile düşer",
				)
			)

	@staticmethod
	def _conditional_open(policy: dict, ext: str) -> bool:
		"""Koşullu uzantının koşulu açık mı — VERİDEN okunur, kodda liste yok."""
		if ext in (".svg", ".svgz"):
			return bool(((policy.get("logo") or {}).get("svg_policy") or {}).get("enabled"))
		return False

	def _check_require(self, policy, probe: MediaProbe, p, out, skipped) -> None:
		require = policy.get("require") or {}
		block = "require"
		w, h = probe.display_size
		if not (w and h):
			skipped.append(
				SkippedRule(
					rule="geometry", block=block, reason="not_measurable", missing_input="width/height"
				)
			)
			self._check_counts(policy, probe, p, out, skipped)
			return

		short, long = min(w, h), max(w, h)

		if require.get("min_short_edge") and short < require["min_short_edge"]:
			out.append(
				self._violation(
					policy, rule="short_edge_too_small", block=block, params=p,
					observed=short, expected=require["min_short_edge"],
					source="require.min_short_edge",
				)
			)
		elif require.get("low_resolution_warn_below") and short < require["low_resolution_warn_below"]:
			pp = dict(p, gerekli_kisa_kenar=require["low_resolution_warn_below"])
			out.append(
				self._violation(
					policy, rule="low_resolution", block=block, params=pp,
					observed=short, expected=require["low_resolution_warn_below"],
					action=ACTION_WARN, source="require.low_resolution_warn_below",
				)
			)

		if require.get("max_short_edge") and short > require["max_short_edge"]:
			pp = dict(p, gerekli_kisa_kenar=require["max_short_edge"])
			out.append(
				self._violation(
					policy, rule="short_edge_too_large", block=block, params=pp,
					observed=short, expected=require["max_short_edge"],
					source="require.max_short_edge",
				)
			)

		if require.get("max_edge") and long > require["max_edge"]:
			pp = dict(p, gerekli_uzun_kenar=require["max_edge"])
			out.append(
				self._violation(
					policy, rule="long_edge_too_large", block=block, params=pp,
					observed=long, expected=require["max_edge"], source="require.max_edge",
				)
			)

		if require.get("min_area") and (w * h) < require["min_area"]:
			pp = dict(p, max_mp=round(require["min_area"] / 1_000_000, 3))
			out.append(
				self._violation(
					policy, rule="area_too_small", block=block, params=pp,
					observed=w * h, expected=require["min_area"], source="require.min_area",
				)
			)

		ratios = require.get("allowed_ratios") or []
		if ratios:
			tol = require.get("ratio_tolerance")
			tol = 0.0 if tol is None else float(tol)
			gercek = w / h
			hedefler = [(r, parse_ratio(r)) for r in ratios]
			en_yakin = min(
				(abs(gercek - v) / v for _, v in hedefler if v), default=float("inf")
			)
			if en_yakin > tol:
				out.append(
					self._violation(
						policy, rule="ratio_not_allowed", block=block, params=p,
						observed=round(gercek, 4), expected=ratios,
						source="require.allowed_ratios + ratio_tolerance",
					)
				)

		band = require.get("aspect_band") or {}
		if band:
			gercek = w / h
			alt = band.get("min_w_over_h")
			ust = band.get("max_w_over_h")
			if (alt is not None and gercek < alt) or (ust is not None and gercek > ust):
				pp = dict(p, izinli_oranlar=f"{alt}–{ust}")
				out.append(
					self._violation(
						policy, rule="aspect_out_of_band", block=block, params=pp,
						observed=round(gercek, 4), expected=[alt, ust],
						source="require.aspect_band",
					)
				)

		self._check_counts(policy, probe, p, out, skipped)

	def _check_counts(self, policy, probe: MediaProbe, p, out, skipped) -> None:
		require = policy.get("require") or {}
		block = "require"
		if probe.existing_count is None:
			if require.get("max_count") or require.get("min_count"):
				skipped.append(
					SkippedRule(
						rule="count", block=block, reason="not_measurable",
						missing_input="existing_count",
					)
				)
			return
		# `existing_count` YÜKLEMEDEN SONRAKİ toplamı ifade eder; çağıran mevcut
		# sayıya +1 ekleyerek geçer. Sözleşme burada yazılı, çünkü "12 mi 13 mü"
		# hatası sessizce bir fazla dosya kabul ettirir.
		if require.get("max_count") and probe.existing_count > require["max_count"]:
			out.append(
				self._violation(
					policy, rule="too_many_items", block=block, params=p,
					observed=probe.existing_count, expected=require["max_count"],
					source="require.max_count",
				)
			)
		if require.get("min_count") and probe.existing_count < require["min_count"]:
			out.append(
				self._violation(
					policy, rule="too_few_items", block=block, params=p,
					observed=probe.existing_count, expected=require["min_count"],
					action=ACTION_WARN, source="require.min_count",
				)
			)

	def _check_video(self, policy, probe: MediaProbe, p, out, skipped) -> None:
		video = policy.get("video") or {}
		if not video:
			return
		block = "require"
		if probe.kind != KIND_VIDEO:
			return

		if probe.duration_s is None:
			skipped.append(
				SkippedRule(
					rule="duration", block=block, reason="not_measurable", missing_input="duration_s"
				)
			)
		else:
			if video.get("duration_max_s") and probe.duration_s > video["duration_max_s"]:
				pp = dict(p, max_sure=video["duration_max_s"])
				out.append(
					self._violation(
						policy, rule="duration_too_long", block=block, params=pp,
						observed=probe.duration_s, expected=video["duration_max_s"],
						source="video.duration_max_s",
					)
				)
			if video.get("duration_min_s") and probe.duration_s < video["duration_min_s"]:
				pp = dict(p, min_sure=video["duration_min_s"])
				out.append(
					self._violation(
						policy, rule="duration_too_short", block=block, params=pp,
						observed=probe.duration_s, expected=video["duration_min_s"],
						source="video.duration_min_s",
					)
				)

		cap = video.get("bitrate_cap_kbps")
		if cap and probe.bitrate_bps:
			if probe.bitrate_bps > cap * 1000:
				pp = dict(p, max_bitrate=cap)
				out.append(
					self._violation(
						policy, rule="bitrate_too_high", block=block, params=pp,
						observed=probe.bitrate_bps, expected=cap * 1000,
						action=ACTION_AUTO_FIX, source="video.bitrate_cap_kbps",
					)
				)
		elif cap:
			skipped.append(
				SkippedRule(
					rule="bitrate", block=block, reason="not_measurable", missing_input="bitrate_bps"
				)
			)

		fr = video.get("frame_rate") or {}
		kabul = fr.get("accepted") or []
		if kabul and probe.frame_rate:
			if not any(abs(probe.frame_rate - float(k)) < 0.5 for k in kabul):
				pp = dict(p, izinli_fps=", ".join(str(k) for k in kabul), max_fps=fr.get("output_cap", ""))
				out.append(
					self._violation(
						policy, rule="frame_rate_not_allowed", block=block, params=pp,
						observed=probe.frame_rate, expected=kabul,
						action=ACTION_AUTO_FIX, source="video.frame_rate.accepted",
					)
				)

	def _check_master(self, policy, probe: MediaProbe, p, out) -> None:
		"""Master hedefi girdiden BÜYÜKSE uyarı — büyütme yapılmaz.

		`engine.optimize()` `im.thumbnail()` kullanır ve upscale YAPMAZ
		(`tests/test_policy_dpi.py::test_thumbnail_upscale_yapmaz`). Dolayısıyla
		`master.min_long_edge` altındaki bir girdi kabul edilir ama hedefe
		ulaşamaz; bunu sessiz bırakmak "2400 üretiyoruz" yanılsaması yaratır.
		"""
		master = policy.get("master") or {}
		w, h = probe.display_size
		if not (w and h):
			return
		min_long = master.get("min_long_edge")
		if min_long and max(w, h) < min_long and not master.get("allow_upscale"):
			pp = dict(p, gerekli_uzun_kenar=min_long)
			out.append(
				self._violation(
					policy, rule="master_under_spec", block="master", params=pp,
					observed=max(w, h), expected=min_long,
					action=self._action_for(policy, "master") if self._action_for(policy, "master") != ACTION_REJECT else ACTION_WARN,
					source="master.min_long_edge (upscale yok)",
				)
			)

	# content_rules kural adı → künye alanı. Alan `None` ise kural
	# DEĞERLENDİRİLMEZ. Burada olmayan bir kural adı da değerlendirilmez:
	# piksel analizi isteyen kurallar (entropi, bulanıklık, kenar oranı)
	# bilerek dışarıda — content_rules.json `calibration_status=UNCALIBRATED`.
	CONTENT_METRICS: dict[str, str] = {
		"animated": "animated",
		"unreadable": "_unreadable",
		"ffprobe_readable": "readable",
		"no_alpha_channel": "_no_alpha",
		"frame_width": "width",
		"bitrate_bps": "bitrate_bps",
		"duration_seconds": "duration_s",
		"is_private": "is_private",
	}

	@staticmethod
	def _metric_value(probe: MediaProbe, name: str):
		if name == "_unreadable":
			return not probe.readable if probe.readable is not None else None
		if name == "_no_alpha":
			return (not probe.has_alpha) if probe.has_alpha is not None else None
		return getattr(probe, name, None)

	@staticmethod
	def _compare(value, comparator: str, threshold) -> bool:
		try:
			if comparator == "eq":
				return value == threshold
			if comparator == "ne":
				return value != threshold
			if comparator == "gt":
				return value > threshold
			if comparator == "gte":
				return value >= threshold
			if comparator == "lt":
				return value < threshold
			if comparator == "lte":
				return value <= threshold
		except TypeError:
			return False
		return False

	def _check_content_rules(self, policy, probe: MediaProbe, p, out, skipped) -> None:
		block = "content_rules"
		for rule in policy.get("content_rules") or []:
			name = rule.get("rule")
			if not name:
				continue
			alan = self.CONTENT_METRICS.get(name)
			if alan is None:
				skipped.append(
					SkippedRule(
						rule=name, block=block, reason="not_measurable",
						missing_input="künyede karşılığı yok (piksel analizi gerekir)",
					)
				)
				continue
			value = self._metric_value(probe, alan)
			if value is None:
				skipped.append(
					SkippedRule(rule=name, block=block, reason="not_measurable", missing_input=alan)
				)
				continue
			if not self._compare(value, rule.get("comparator", "eq"), rule.get("threshold")):
				continue

			# `accept` bloğu bu kuralı zaten söylediyse tekrarlamayalım: aynı
			# şey iki kez yazılırsa kullanıcı iki hata görür, ikisi de aynı.
			mesaj_kural = {"animated": "animated", "unreadable": "unreadable"}.get(name)
			if mesaj_kural and any(v.rule == mesaj_kural for v in out):
				continue

			pp = dict(p)
			mk = rule.get("message_key") or name
			message_tr = ((policy.get("messages") or {}).get("tr") or {}).get(mk, "")
			if message_tr:
				message = {
					"tr": _fmt(message_tr, pp),
					"en": _fmt(
						(FALLBACK.get(mesaj_kural or name) or FALLBACK["_default"])["en"],
						dict(pp, kural=name),
					),
				}
				hint_cat = FALLBACK.get(mesaj_kural or name) or FALLBACK["_default"]
				hint = {
					"tr": _fmt(hint_cat.get("hint_tr", ""), pp),
					"en": _fmt(hint_cat.get("hint_en", ""), pp),
				}
				out.append(
					Violation(
						code=self._code(policy, name),
						rule=name,
						block=block,
						action=rule.get("action") or self._action_for(policy, block),
						message=message,
						hint=hint,
						observed=value,
						expected=rule.get("threshold"),
						source=rule.get("source", ""),
					)
				)
			else:
				out.append(
					self._violation(
						policy, rule=mesaj_kural or name, block=block, params=pp,
						observed=value, expected=rule.get("threshold"),
						action=rule.get("action") or self._action_for(policy, block),
						source=rule.get("source", ""),
					)
				)

	# ── hedef üretimi ────────────────────────────────────────────────

	def normalized_targets(self, policy: dict, probe: MediaProbe) -> dict:
		"""Kabul edilen dosya NEYE dönüşecek — master + türevler (+ video).

		DPI KURALI (docs/standards/dpi-ve-cozunurluk.md): DPI düşürmek
		çözünürlüğü DÜŞÜRMEZ. 3000×3000@300dpi → 2400×2400@72dpi doğrudur,
		720×720@72dpi YASAKTIR. Bu fonksiyon ölçeği YALNIZ uzun kenar tavanı ve
		megapiksel tavanından türetir; `dpi_out` çıktı metadatasıdır, ölçeğe
		hiç girmez.
		"""
		master = policy.get("master") or {}
		w, h = probe.display_size
		out: dict = {
			"slot": policy.get("slot_key", ""),
			"master": {},
			"derivatives": [],
		}
		if not (w and h):
			return out

		scale = 1.0
		cap = master.get("max_long_edge")
		if cap and max(w, h) > cap:
			scale = cap / max(w, h)
		max_mp = master.get("max_megapixels")
		if max_mp:
			alan = (w * scale) * (h * scale)
			if alan > max_mp * 1_000_000:
				scale *= math.sqrt((max_mp * 1_000_000) / alan)
		if not master.get("allow_upscale", False):
			scale = min(scale, 1.0)

		tw, th = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
		fit = master.get("fit") or "contain"
		hedef_oran = master.get("target_ratio")
		if fit == "pad" and hedef_oran:
			r = parse_ratio(hedef_oran)
			if r:
				kutu = max(tw, th)
				tw, th = (kutu, int(round(kutu / r))) if r >= 1 else (int(round(kutu * r)), kutu)

		out["master"] = {
			"width": tw,
			"height": th,
			"scale": round(scale, 6),
			"resize_needed": scale < 1.0,
			"format": master.get("format", "preserve"),
			"encoding": master.get("encoding", ""),
			"colorspace": master.get("colorspace", "preserve"),
			"dpi_out": master.get("dpi_out"),
			"fit": fit,
			"pad_color": master.get("pad_color"),
			"orientation": master.get("orientation", "apply_exif"),
			"strip_metadata": master.get("strip_metadata") or {},
			"allow_upscale": bool(master.get("allow_upscale", False)),
			"source_size": [w, h],
		}

		for profile in policy.get("profiles") or []:
			pw = profile.get("width")
			if not pw:
				continue
			ph = profile.get("height")
			if not ph:
				r = parse_ratio(profile.get("target_ratio") or "") or (tw / th if th else 1.0)
				ph = int(round(pw / r)) if r else pw
			out["derivatives"].append(
				{
					"name": profile.get("name", f"w{pw}"),
					"width": pw,
					"height": ph,
					"formats": profile.get("formats") or [master.get("format", "webp")],
					"encoder_quality": profile.get("encoder_quality") or {},
					"fit": profile.get("fit") or fit,
					"pad_color": profile.get("pad_color") or master.get("pad_color"),
					"max_bytes": profile.get("max_bytes"),
					# Türev masterdan büyükse büyütme YOK; işaretlenir ki
					# `image/` katmanı sessizce upscale etmesin.
					"upscale": pw > tw,
					"serves": profile.get("serves") or [],
				}
			)

		video = policy.get("video") or {}
		if video:
			fr = video.get("frame_rate") or {}
			ses = video.get("audio_policy") or {}
			out["video"] = {
				"max_width": master.get("max_long_edge"),
				"container": master.get("format"),
				"fps_cap": fr.get("output_cap"),
				"bitrate_cap_kbps": video.get("bitrate_cap_kbps"),
				"audio_codec": ses.get("codec"),
				"audio_bitrate_kbps": ses.get("bitrate_kbps"),
				"autoplay_mute_mandatory": ses.get("autoplay_mute_mandatory"),
			}
		return out

	# ══════════════════════════════════════════════════════════════════
	# contracts/policy.py `PolicyEngine` Protocol UYGULAMASI  (T-033)
	# ══════════════════════════════════════════════════════════════════
	#
	# NEDEN BURADA: Protokolün 13 metodu ile bu sınıfın yüzeyi arasındaki
	# kesişim ÖLÇÜLDÜ ve BOŞTU (`isinstance(PolicyEngine(), Proto)` → False).
	# Protokolün tek uygulayıcısı `fakes/policy.py` olduğu için 69 sözleşme
	# testi sahteyi doğruluyordu, üretim kodunu değil.
	#
	# NASIL: aşağıdaki kapılar KURAL MANTIĞINI YENİDEN YAZMAZ. `check_accept`
	# / `check_geometry` / `check_video`, `evaluate()`'in çağırdığı AYNI özel
	# metotları (`_check_accept`, `_check_require`, `_check_video`) çağırır ve
	# yalnız çıktıyı sözleşme tiplerine çevirir. Sözleşme testi geçtiğinde
	# geçen şey üretimin kendi kural kodudur — sahtenin değil.
	#
	# `evaluate()` ve `normalized_targets()` DEĞİŞMEDİ; bu bölüm eklemedir.

	#: Motorun kural adı → sözleşme sebep sabiti. Tabloda OLMAYAN kural adı
	#: OLDUĞU GİBİ kullanılır (kimlik eşlemesi). Bu tablo bir KARAR tablosu
	#: değil, sözlük tablosudur: hangi kuralın tetiklendiğine motor karar
	#: verir, burada yalnız kodun adı sözleşme sözlüğüne çevrilir.
	#: İki sözlüğün yan yana durması R-03 olarak raporda kayıtlı.
	_SEBEP_BY_RULE: dict[str, str] = {
		"extension_rejected": sozlesme_hata.SEBEP_EXT_NOT_ALLOWED,
		"extension_conditional_closed": sozlesme_hata.SEBEP_EXT_NOT_ALLOWED,
		"format_not_supported": sozlesme_hata.SEBEP_EXT_NOT_ALLOWED,
		"mime_not_supported": sozlesme_hata.SEBEP_MIME_NOT_ALLOWED,
		"content_type_mismatch": sozlesme_hata.SEBEP_EXT_CONTENT_MISMATCH,
		"too_large_bytes": sozlesme_hata.SEBEP_TOO_LARGE,
		"too_many_pixels": sozlesme_hata.SEBEP_MEGAPIXEL_BOMB,
		"animated": sozlesme_hata.SEBEP_ANIMATED_NOT_ALLOWED,
		"data_uri_forbidden": sozlesme_hata.SEBEP_DANGEROUS_CONTENT,
		"executable_content": sozlesme_hata.SEBEP_DANGEROUS_CONTENT,
		"appended_payload": sozlesme_hata.SEBEP_DANGEROUS_CONTENT,
		"container_invalid": sozlesme_hata.SEBEP_DANGEROUS_CONTENT,
		"unreadable": sozlesme_hata.SEBEP_DECODE_FAILED,
		"truncated": sozlesme_hata.SEBEP_DECODE_FAILED,
		"low_resolution": sozlesme_hata.SEBEP_SHORT_EDGE_TOO_SMALL,
		"aspect_out_of_band": sozlesme_hata.SEBEP_RATIO_NOT_ALLOWED,
		"too_many_items": sozlesme_hata.SEBEP_COUNT_EXCEEDED,
		"too_few_items": sozlesme_hata.SEBEP_COUNT_EXCEEDED,
		"duration_too_long": sozlesme_hata.SEBEP_DURATION_OUT_OF_RANGE,
		"duration_too_short": sozlesme_hata.SEBEP_DURATION_OUT_OF_RANGE,
		"bitrate_too_high": sozlesme_hata.SEBEP_BITRATE_EXCEEDED,
		"master_under_spec": sozlesme_hata.SEBEP_UNDER_SPEC,
	}

	#: Motorun blok adı → sözleşme katmanı. `security` ve `policy` blokları
	#: sözleşmede ayrı katman değil: ikisi de dosya AÇILMADAN verilen karardır.
	_LAYER_BY_BLOCK: dict[str, str] = {
		"accept": sozlesme.LAYER_ACCEPT,
		"security": sozlesme.LAYER_ACCEPT,
		"policy": sozlesme.LAYER_ACCEPT,
		"require": sozlesme.LAYER_REQUIRE,
		"video": sozlesme.LAYER_REQUIRE,
		"master": sozlesme.LAYER_MASTER,
		"quality": sozlesme.LAYER_QUALITY,
		"content_rules": sozlesme.LAYER_CONTENT,
	}

	#: Motor aksiyonu → sözleşme aksiyonu. `review` ile `manual_review` aynı
	#: şeydir (core/errors.py'de gerekçesi yazılı); `ignore` sözleşmede yok ve
	#: zaten SILENT_ACTIONS ile listeden düşer.
	_ACTION_MAP: dict[str, str] = {
		ACTION_PASS: sozlesme.ACTION_PASS,
		ACTION_IGNORE: sozlesme.ACTION_PASS,
		ACTION_WARN: sozlesme.ACTION_WARN,
		ACTION_AUTO_FIX: sozlesme.ACTION_AUTO_FIX,
		ACTION_REVIEW: sozlesme.ACTION_MANUAL_REVIEW,
		ACTION_MANUAL_REVIEW: sozlesme.ACTION_MANUAL_REVIEW,
		ACTION_REJECT: sozlesme.ACTION_REJECT,
	}

	@staticmethod
	def _num(deger, varsayilan: float = 0.0) -> float:
		"""`None`/boş güvenli sayı okuma — politika alanları isteğe bağlı."""
		if deger is None or deger == "":
			return varsayilan
		try:
			return float(deger)
		except (TypeError, ValueError):
			return varsayilan

	def _sozlesme_ihlali(self, policy: dict, v: Violation) -> sozlesme.Violation:
		"""Motor ihlali → sözleşme ihlali. Yalnız BİÇİM çevirisi."""
		sebep = self._SEBEP_BY_RULE.get(v.rule, v.rule)
		prefix = (policy.get("on_violation") or {}).get("error_code_prefix") or "media"
		return sozlesme.Violation(
			code=sozlesme_hata.kod_uret(prefix, sebep),
			layer=self._LAYER_BY_BLOCK.get(v.block, sozlesme.LAYER_ACCEPT),
			sebep=sebep,
			action=self._ACTION_MAP.get(v.action, sozlesme.ACTION_REJECT),
			retryable=bool(v.retryable),
			message_key=v.rule,
			measured=v.observed,
			expected=v.expected,
			detay={"engine_code": v.code, "block": v.block, "source": v.source},
		)

	def _sozlesme_karari(
		self,
		policy: dict,
		ihlaller,
		skipped=(),
		ek: tuple = (),
	) -> PolicyDecision:
		"""İhlal listesini sözleşme kararına çevir.

		Kovalama sözleşmenin tanımına göre: `violations` YALNIZ `reject`
		aksiyonlu olanlardır (`Decision.allowed = action != reject`), gerisi
		`warnings`. `evaluate()`'in `allow` alanı `review`/`manual_review`'i de
		engelleyici sayar — iki tanımın farkı raporda R-01.
		"""
		cevrilmis = [
			self._sozlesme_ihlali(policy, v) for v in ihlaller if v.action not in SILENT_ACTIONS
		]
		cevrilmis.extend(ek)
		retler = tuple(v for v in cevrilmis if v.action == sozlesme.ACTION_REJECT)
		uyarilar = tuple(v for v in cevrilmis if v.action != sozlesme.ACTION_REJECT)
		aksiyon = (
			sozlesme.en_yuksek_aksiyon([v.action for v in cevrilmis])
			if cevrilmis
			else sozlesme.ACTION_PASS
		)
		return PolicyDecision(
			slot_key=str(policy.get("slot_key") or ""),
			action=aksiyon,
			violations=retler,
			warnings=uyarilar,
			# Ölçülemeyen kural sessizce "geçti" sayılmaz; karara iliştirilir.
			notes=tuple(f"{s.block}.{s.rule}: {s.reason} ({s.missing_input})" for s in skipped),
		)

	# ── kayıt defteri ─────────────────────────────────────────────────

	def source_root(self) -> str:
		"""FR-147 — hangi politika seti yürürlükte, sessiz kalınmaz."""
		return str(self.registry.directory)

	def slots(self) -> Tuple[str, ...]:
		return self.registry.keys()

	def load(self, slot_key: str) -> SlotPolicy:
		"""Sözleşme tipli slot politikası. Bilinmeyen slot → `PolicyNotFound`.

		`PolicyRegistry.get()` `KeyError` türevi kendi `PolicyNotFound`'unu
		atar (uçlar buna dayanıyor, `api/upload.py:206`); sözleşme yüzeyi
		`contracts.errors.PolicyNotFound` ister. İkisi ayrı hiyerarşi olduğu
		için çeviri BURADA yapılır — kayıt defterinin davranışı değişmez.
		"""
		onbellek = self._slot_policy_cache.get(slot_key)
		if onbellek is not None:
			return onbellek
		try:
			ham = self.registry.get(slot_key)
		except PolicyNotFound as exc:
			raise sozlesme_hata.PolicyNotFound(
				str(exc), detay={"slot_key": slot_key}
			) from exc
		politika = SlotPolicy(
			slot_key=str(ham.get("slot_key") or slot_key),
			schema_version=str(ham.get("schema_version") or ""),
			status=str(ham.get("status") or sozlesme.STATUS_DRAFT),
			roles=tuple(ham.get("roles") or ()),
			accept=dict(ham.get("accept") or {}),
			require=dict(ham.get("require") or {}),
			master=dict(ham.get("master") or {}),
			quality=dict(ham.get("quality") or {}),
			profiles=tuple(ham.get("profiles") or ()),
			video=dict(ham.get("video") or {}),
			on_violation=dict(ham.get("on_violation") or {}),
			messages=dict(ham.get("messages") or {}),
			bound_to=tuple(ham.get("bound_to") or ()),
			raw=ham,
		)
		self._slot_policy_cache[slot_key] = politika
		return politika

	def reload(self) -> int:
		"""Diskten yeniden oku; yüklenen politika sayısını döndür.

		`PolicyRegistry.load()` ya hep ya hiç çalışır: bozuk bir dosya
		istisnası eski defteri OLDUĞU GİBİ bırakır.
		"""
		self.registry.load()
		self._slot_policy_cache.clear()
		return len(self.registry)

	def effective_limits(self, slot_key: str, *, plan_max_bytes: int = 0) -> EffectiveLimits:
		"""Slot × plan kesişimi (FR-007, FR-076) — slot tavanı GEVŞETEMEZ."""
		p = self.load(slot_key)
		slot_bytes = int(self._num(p.accept.get("max_bytes")))
		adaylar = [b for b in (slot_bytes, int(plan_max_bytes or 0)) if b > 0]
		return EffectiveLimits(
			max_bytes=min(adaylar) if adaylar else 0,
			max_megapixels_hard=self._num(p.accept.get("max_megapixels_hard")),
			max_count=int(self._num(p.require.get("max_count"))),
			source={"slot": str(slot_bytes or "-"), "plan": str(plan_max_bytes or "-")},
		)

	# ── kapılar (üretim kural koduna DELEGE eder) ─────────────────────

	def check_accept(
		self,
		slot_key: str,
		*,
		file_name: str,
		size_bytes: int,
		sniffed_type: str = "",
		declared_mime: str = "",
	) -> PolicyDecision:
		"""L1 — dosya AÇILMADAN. `_check_accept` (üretim kodu) çağrılır.

		Sentetik künyede `readable=True`: bu kapı dosyayı AÇMAZ, dolayısıyla
		okunabilirlik hakkında bir iddiası da yoktur. `readable=False`
		bırakmak, hiç ölçülmemiş bir şeyi "bozuk" ilan etmek olurdu.
		"""
		self.load(slot_key)  # bilinmeyen slot → sözleşme PolicyNotFound
		policy = self.registry.get(slot_key)
		uzanti = os.path.splitext(file_name or "")[1].lower()
		beklenen = EXTENSION_KINDS.get(uzanti)
		probe = MediaProbe(
			filename=file_name or "",
			extension=uzanti,
			byte_size=int(size_bytes or 0),
			detected=sniffed_type or "",
			mime=declared_mime or "",
			readable=True,
			extension_matches_content=(
				None if (not sniffed_type or beklenen is None) else sniffed_type in beklenen
			),
		)
		ihlaller: list[Violation] = []
		skipped: list[SkippedRule] = []
		p = self._params(policy, probe, "")
		self._check_accept(policy, probe, p, ihlaller, skipped)
		return self._sozlesme_karari(policy, ihlaller, skipped)

	def check_geometry(self, slot_key: str, probe: ImageProbe, *, count: int = 1) -> PolicyDecision:
		"""L2 — görsel AÇILDIKTAN sonra. `_check_accept` + `_check_require`.

		`_check_accept` de çağrılır çünkü megapiksel tavanı ve `allow_animated`
		motorda o blokta yaşıyor ve ancak künye okunduktan sonra ölçülebilir.
		Uzantı/MIME/bayt alanları boş bırakıldığı için o kurallar tetiklenmez.
		"""
		self.load(slot_key)
		policy = self.registry.get(slot_key)
		m = MediaProbe(
			kind="image",
			width=int(probe.width or 0),
			height=int(probe.height or 0),
			animated=bool(probe.animated),
			has_alpha=bool(probe.has_alpha),
			readable=bool(probe.readable),
			exif_orientation=probe.exif_orientation,
			fmt=probe.fmt or "",
			existing_count=int(count),
		)
		ihlaller: list[Violation] = []
		skipped: list[SkippedRule] = []
		p = self._params(policy, m, "")
		self._check_accept(policy, m, p, ihlaller, skipped)
		self._check_require(policy, m, p, ihlaller, skipped)
		return self._sozlesme_karari(policy, ihlaller, skipped)

	def check_video(self, slot_key: str, probe: VideoProbe) -> PolicyDecision:
		"""L2 — video kapısı. `_check_require` + `_check_video`.

		NFR-043 + FR-134: ffprobe ölçemediğinde karar RET değil
		`manual_review`'dır. Motorun kendisi bunu `SkippedRule` olarak
		raporlar ama `evaluate()` aksiyonu `pass`'ta bırakır — sözleşme
		yüzeyi o atlanan ölçümü açık bir `manual_review` uyarısına çevirir.
		Farkın `evaluate()` tarafındaki karşılığı raporda R-02.
		"""
		p_sozlesme = self.load(slot_key)
		if not p_sozlesme.is_video:
			raise sozlesme_hata.PolicyError(
				f"Video olmayan slotta video kapısı: {slot_key}", detay={"slot_key": slot_key}
			)
		policy = self.registry.get(slot_key)
		m = MediaProbe(
			kind=KIND_VIDEO,
			width=int(probe.width or 0),
			height=int(probe.height or 0),
			readable=bool(probe.measured),
			duration_s=probe.duration_s if probe.measured else None,
			bitrate_bps=probe.bitrate_bps if probe.measured else None,
			frame_rate=probe.frame_rate if probe.measured else None,
			has_audio=probe.has_audio,
			video_codec=probe.video_codec or "",
			audio_codec=probe.audio_codec or "",
		)
		ihlaller: list[Violation] = []
		skipped: list[SkippedRule] = []
		p = self._params(policy, m, "")
		self._check_require(policy, m, p, ihlaller, skipped)
		self._check_video(policy, m, p, ihlaller, skipped)
		ek: tuple = ()
		if not probe.measured:
			prefix = (policy.get("on_violation") or {}).get("error_code_prefix") or "media"
			ek = (
				sozlesme.Violation(
					code=sozlesme_hata.kod_uret(prefix, sozlesme_hata.SEBEP_PROBE_UNAVAILABLE),
					layer=sozlesme.LAYER_REQUIRE,
					sebep=sozlesme_hata.SEBEP_PROBE_UNAVAILABLE,
					action=sozlesme.ACTION_MANUAL_REVIEW,
					message_key="ffprobe_readable",
					detay={"slot_key": slot_key},
				),
			)
		return self._sozlesme_karari(policy, ihlaller, skipped, ek=ek)

	# ── üretim parametreleri ──────────────────────────────────────────

	def master_spec(self, slot_key: str) -> MasterSpec:
		p = self.load(slot_key)
		if not p.master:
			raise sozlesme_hata.PolicyError(
				f"`master` bloğu yok: {slot_key}", detay={"slot_key": slot_key}
			)
		m = p.master
		return MasterSpec(
			max_long_edge=int(self._num(m.get("max_long_edge"))),
			format=str(m.get("format") or "webp"),
			min_long_edge=int(self._num(m.get("min_long_edge"))),
			max_megapixels=self._num(m.get("max_megapixels")),
			dpi_out=int(self._num(m.get("dpi_out"), 72)),
			colorspace=str(m.get("colorspace") or "srgb"),
			orientation=str(m.get("orientation") or "apply_exif"),
			fit=str(m.get("fit") or "contain"),
			target_ratio=str(m.get("target_ratio") or ""),
			pad_color=str(m.get("pad_color") or ""),
			allow_crop=bool(m.get("allow_crop")),
			allow_upscale=bool(m.get("allow_upscale")),
			strip_metadata=dict(m.get("strip_metadata") or {}),
		)

	def rendition_specs(self, slot_key: str) -> Tuple[RenditionSpec, ...]:
		"""Türev merdiveni, genişliğe göre ARTAN sırada (FR-036)."""
		p = self.load(slot_key)
		cikti = []
		for profil in p.profiles:
			bicimler = [str(f) for f in (profil.get("formats") or ())] or ["webp"]
			kaliteler = profil.get("encoder_quality") or {}
			for bicim in bicimler:
				ad = profil.get("name") or "profil"
				cikti.append(
					RenditionSpec(
						name=ad if len(bicimler) == 1 else f"{ad}.{bicim}",
						width=int(self._num(profil.get("width"))),
						format=bicim,
						quality=int(self._num(kaliteler.get(bicim))),
						fit=str(profil.get("fit") or "contain"),
						target_ratio=str(profil.get("target_ratio") or ""),
						pad_color=str(profil.get("pad_color") or ""),
						lossless=bool(profil.get("lossless")),
						derived_from=str(profil.get("derived_from") or ""),
					)
				)
		return tuple(sorted(cikti, key=lambda s: (s.width, s.format)))

	def video_rendition_specs(self, slot_key: str) -> Tuple[VideoRenditionSpec, ...]:
		p = self.load(slot_key)
		if not p.is_video:
			return ()
		return tuple(
			VideoRenditionSpec(
				id=str(r.get("id") or "rendition"),
				width=int(self._num(r.get("width"))),
				height=int(self._num(r.get("height"))),
				container=str(r.get("container") or "webm"),
				video_codec=str(r.get("video_codec") or "libvpx-vp9"),
				crf=int(self._num(r.get("crf"), 32)),
				maxrate_kbps=int(self._num(r.get("maxrate_kbps"))),
				bufsize_kbps=int(self._num(r.get("bufsize_kbps"))),
				audio_codec=str(r.get("audio_codec") or "libopus"),
				audio_bitrate_kbps=int(self._num(r.get("audio_bitrate_kbps"), 96)),
				audio_channels=int(self._num(r.get("audio_channels"), 2)),
				max_bytes=int(self._num(r.get("max_bytes"))),
				role=str(r.get("role") or "primary"),
			)
			for r in (p.video.get("renditions") or ())
		)

	def quality_threshold(self, slot_key: str, content_class: str) -> float:
		"""Sınıf tanımsızsa 0.0 — ölçülmemiş eşikle reddetmek yerine kapı yok."""
		p = self.load(slot_key)
		return self._num((p.quality.get("target_ssim_per_class") or {}).get(content_class))

	# ── kendi kendini doğrulama ───────────────────────────────────────

	def validate(self, slot_key: str = "") -> PolicyDecision:
		"""D1–D5 değişmezleri (docs/standards/README.md §6).

		Boş `slot_key` tüm kayıt defterini doğrular. FR-148: tek çıkış kodu
		`Decision.allowed`.
		"""
		anahtarlar = (slot_key,) if slot_key else self.slots()
		ihlaller: list[sozlesme.Violation] = []
		uyarilar: list[sozlesme.Violation] = []
		for anahtar in anahtarlar:
			p = self.load(anahtar)
			prefix = str(p.on_violation.get("error_code_prefix") or "media")
			m = p.master
			mle = self._num(m.get("max_long_edge"))
			mmp = self._num(m.get("max_megapixels"))
			mnle = self._num(m.get("min_long_edge"))
			if mmp and mle and (mle * mle) / 1e6 < mmp:
				ihlaller.append(
					sozlesme.Violation(
						code=sozlesme_hata.kod_uret(prefix, "invariant_d1"),
						layer=sozlesme.LAYER_MASTER,
						sebep="invariant_d1",
						action=sozlesme.ACTION_REJECT,
						measured=(mle * mle) / 1e6,
						expected=mmp,
						detay={"slot_key": anahtar},
					)
				)
			if mnle and mle and mnle > mle:
				ihlaller.append(
					sozlesme.Violation(
						code=sozlesme_hata.kod_uret(prefix, "invariant_d2"),
						layer=sozlesme.LAYER_MASTER,
						sebep="invariant_d2",
						action=sozlesme.ACTION_REJECT,
						measured=mnle,
						expected=mle,
						detay={"slot_key": anahtar},
					)
				)
			uzantilar = {str(e).lower() for e in (p.accept.get("extensions") or ())}
			mimeler = {str(x).lower() for x in (p.accept.get("mime") or ())}
			if uzantilar and mimeler and not self._ext_mime_ortusuyor(uzantilar, mimeler):
				ihlaller.append(
					sozlesme.Violation(
						code=sozlesme_hata.kod_uret(prefix, "invariant_d3"),
						layer=sozlesme.LAYER_ACCEPT,
						sebep="invariant_d3",
						action=sozlesme.ACTION_REJECT,
						measured=sorted(uzantilar),
						expected=sorted(mimeler),
						detay={"slot_key": anahtar},
					)
				)
			for profil in p.profiles:
				if not (profil.get("derived_from") or ""):
					ihlaller.append(
						sozlesme.Violation(
							code=sozlesme_hata.kod_uret(prefix, "invariant_d4"),
							layer=sozlesme.LAYER_MASTER,
							sebep="invariant_d4",
							action=sozlesme.ACTION_REJECT,
							detay={"slot_key": anahtar, "profile": profil.get("name")},
						)
					)
			acik = p.raw.get("open_questions") or ()
			bos_kalite = any(
				q is None
				for profil in p.profiles
				for q in (profil.get("encoder_quality") or {}).values()
			)
			if p.status == sozlesme.STATUS_ACTIVE and (acik or bos_kalite):
				ihlaller.append(
					sozlesme.Violation(
						code=sozlesme_hata.kod_uret(prefix, "invariant_d5"),
						layer=sozlesme.LAYER_QUALITY,
						sebep="invariant_d5",
						action=sozlesme.ACTION_REJECT,
						detay={"slot_key": anahtar, "open_questions": len(acik)},
					)
				)
			elif acik:
				uyarilar.append(
					sozlesme.Violation(
						code=sozlesme_hata.kod_uret(prefix, "draft_open_questions"),
						layer=sozlesme.LAYER_QUALITY,
						sebep="invariant_d5",
						action=sozlesme.ACTION_WARN,
						detay={"slot_key": anahtar, "open_questions": len(acik)},
					)
				)
		return PolicyDecision(
			slot_key=slot_key or "*",
			action=(
				sozlesme.ACTION_REJECT
				if ihlaller
				else (sozlesme.ACTION_WARN if uyarilar else sozlesme.ACTION_PASS)
			),
			violations=tuple(ihlaller),
			warnings=tuple(uyarilar),
		)

	@staticmethod
	def _ext_mime_ortusuyor(uzantilar: set, mimeler: set) -> bool:
		"""D3 (FR-008) — `accept.extensions` ile `accept.mime` AYRIŞMAMALI.

		Tam eşleme aranmaz: `.jpg`/`.jpeg` tek MIME'a düşer, `.docx` uzun bir
		OOXML MIME'ına. Aranan şey en az bir uzantının bir MIME karşılığının
		listede bulunmasıdır; hiçbiri tutmuyorsa iki liste farklı biçim
		kümelerini tarif ediyordur ve bu sessiz kalamaz.
		"""
		for uzanti in uzantilar:
			for tur in EXTENSION_KINDS.get(uzanti, frozenset()):
				if any(tur in m or m.endswith(uzanti.lstrip(".")) for m in mimeler):
					return True
		return False


#: Modül düzeyinde tek örnek — politika dosyaları süreç ömrü boyunca sabittir.
#: Testler kendi `PolicyEngine(PolicyRegistry(dizin))` örneğini kurar.
_default_engine: PolicyEngine | None = None


def default_engine() -> PolicyEngine:
	global _default_engine
	if _default_engine is None:
		_default_engine = PolicyEngine()
	return _default_engine


def evaluate(slot: str, probe, role: str = "") -> Decision:
	"""Kısayol — `default_engine().evaluate(...)`."""
	return default_engine().evaluate(slot, probe, role)

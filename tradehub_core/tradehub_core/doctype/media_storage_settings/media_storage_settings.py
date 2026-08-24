# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-051 (şartname) — Medya Depolama Ayarları: beş bölüm, tek Single DocType.

NE OKUNUR, NEREYE GİDER
-----------------------
Bu DocType'ın alan adları UYDURULMADI. Üç mevcut okuyucunun anahtarlarıyla
birebir eşleşirler:

    backend, s3_endpoint, s3_region, s3_bucket, s3_access_key,
    s3_secret_key, cdn_base_url, signed_url_ttl_seconds
        → `media/pipeline/storage/__init__.py` :: StorageSettings.from_doctype
          (o da `s3.S3Config` alanlarını doldurur)

    keep_originals, original_local_days, original_then_action,
    derivative_unused_days, derivative_action,
    derivative_regenerate_on_demand, trash_retention_days,
    archive_retention_days, backup_keep_sets
        → `media/pipeline/storage/retention.py` :: RetentionPolicy.from_mapping
          (iç içe sözlüğe `retention_mapping()` çevirir)

    imgproxy_base_url, imgproxy_key, imgproxy_salt
        → BUGÜN YALNIZ `test_connection` okur. `imgproxy` geçen başka satır
          yok (ölçüldü). Bu yüzden `imgproxy_enabled` diye bir şalter
          KOYULMADI: açılınca hiçbir şey değişmeyen bir şalter, kapalı bir
          kapıya "açık" yazmaktır.

`storage/*.py` bu görevde DEĞİŞTİRİLMEDİ; bu modül onları yalnız çağırır.

SIR YÖNETİMİ
------------
`s3_secret_key`, `imgproxy_key`, `imgproxy_salt` **Password** fieldtype'ıdır.
Frappe onları `__Auth` tablosunda şifreli tutar, `tabSingles`'a yalnız yıldız
yazar ve REST çıktısında maskeler. Kendi şifrelememizi yazmadık — yazsaydık
anahtar yönetimi, rotasyon ve `bench set-config encryption_key` ile uyum
bizim borcumuz olurdu.

Sırlar buradan DIŞARI ÇIKMAZ: `_maskele()` her dönüş değerini ve her hata
metnini süzer. Bağlantı testi bir istisna metnini olduğu gibi döndürseydi
boto3'ün `SignatureDoesNotMatch` hatası imzalanan dizeyi, bazı sürümlerde de
anahtarı yanıta taşırdı.

ERİŞİM
------
DocType izinleri yalnız `Media Superadmin`. System Manager, satıcı/alıcı
rolleri listede HİÇ YOK — Frappe'de listede olmayan rol hiçbir hak almaz,
yani okuma dahi yok. `hooks.py`'deki `has_permission` kaydı ikinci kattır
(`permissions.media_storage_settings_has_permission`): ileride biri DocPerm
satırı eklerse bile rol kapısı ayakta kalır.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.media import audit as media_audit
from tradehub_core.media.pipeline.storage import (
	MODE_LOCAL,
	MODE_MIRROR,
	MODE_S3,
	MODE_S3_PRIMARY,
	MODE_TIERED,
	S3_MODES,
	StorageSettings,
	build_storage,
	normalize_mode,
)
from tradehub_core.media.pipeline.storage.retention import RetentionPolicy

DOCTYPE: str = "Media Storage Settings"

#: Ayarı okuyabilen/yazabilen roller. DocType JSON'daki `permissions` listesi
#: ile AYNI küme olmak zorunda — testi ikisini karşılaştırır.
ALLOWED_ROLES: frozenset[str] = frozenset({"Media Superadmin"})

#: Password fieldtype'lı alanlar. Maskeleme ve "değişti mi" karşılaştırması
#: bu listeden yürür; yeni bir sır eklenirse buraya da eklenmeli.
SECRET_FIELDS: tuple[str, ...] = (
	"s3_secret_access_key",
	"cdn_signing_key",
	"cdn_purge_token",
	"imgproxy_key",
	"imgproxy_salt",
)
LEGACY_SECRET_FIELDS: tuple[str, ...] = ("s3_secret_key",)

#: `StorageSettings.from_doctype`'ın okuduğu alanlar (sır hariç).
STORAGE_FIELDS: tuple[str, ...] = (
	"storage_mode",
	"local_root",
	"local_free_space_alarm_gb",
	"local_max_usage_gb",
	"s3_enabled",
	"s3_provider",
	"s3_endpoint_url",
	"s3_region",
	"s3_bucket",
	"s3_access_key_id",
	"s3_path_style",
	"s3_prefix",
	"s3_storage_class",
	"s3_server_side_encryption",
	"s3_multipart_threshold_mb",
	"s3_max_concurrency",
	"s3_upload_originals",
	"s3_upload_renditions",
	"s3_delete_local_after_upload",
	"cdn_enabled",
	"cdn_provider",
	"cdn_base_url",
	"cdn_signed_urls",
	"cdn_signed_ttl_seconds",
	"cdn_cache_control_public",
	"cdn_cache_control_private",
	"cdn_purge_api_url",
	"cdn_purge_zone_id",
	"cdn_purge_on_reprocess",
	"imgproxy_enabled",
	"imgproxy_base_url",
	"imgproxy_max_source_mp",
)

#: Saklama bölümünün alanları — denetim karşılaştırmasında kullanılır.
RETENTION_FIELDS: tuple[str, ...] = (
	"keep_originals",
	"original_local_days",
	"original_then_action",
	"original_delete_requires_approval",
	"derivative_unused_days",
	"derivative_regenerate_on_demand",
	"soft_delete_grace_days",
	"legal_hold_overrides_all",
)


#: Denetim kaydı eylem adı. `media/audit.py::MEDIA_ACTIONS` tuple'ında YOK —
#: o dosya bu görevde değiştirilmedi (dokunulabilir dosya listesi dışında).
#: Sonuç: kayıt Authorization Decision Log'a YAZILIR ve sorgulanabilir, ama
#: panelin Medya Denetimi ekranı `MEDIA_ACTIONS` ile süzdüğü için orada
#: GÖRÜNMEZ. Tek satırlık kapanış: sabiti `MEDIA_ACTIONS`'a eklemek
#: (docs/reports/25-t051-depolama-ayarlari.md §6).
ACTION_STORAGE_SETTINGS: str = "media.storage_settings_changed"

#: `docs/reports/23-t051-s3-adaptor.md` §7 — bugün hiçbir S3 kipini açtırmayan
#: engeller. Ekranda görünür, kayıtta da görünür.
OPEN_BLOCKERS: tuple[str, ...] = ()

_TEST_TARGETS: tuple[str, ...] = ("s3", "cdn", "imgproxy")


# ── sır maskeleme ────────────────────────────────────────────────────────


def _maskele(deger: Any, sirlar: tuple[str, ...]) -> Any:
	"""`deger` içindeki her sır dizesini `***` ile değiştir (özyinelemeli).

	Yanıt gövdesi, hata metni ve denetim bağlamı bu süzgeçten GEÇMEDEN
	kullanılmaz. Kısa/boş sırlar atlanır: 3 karakterlik bir "sır" metnin
	yarısını yıldıza çevirirdi ve maskeleme kendisi bir bilgi sızıntısına
	dönerdi.
	"""
	gecerli = tuple(s for s in sirlar if s and len(s) >= 4)
	if not gecerli:
		return deger
	if isinstance(deger, str):
		sonuc = deger
		for sir in gecerli:
			sonuc = sonuc.replace(sir, "***")
		return sonuc
	if isinstance(deger, dict):
		return {k: _maskele(v, sirlar) for k, v in deger.items()}
	if isinstance(deger, (list, tuple)):
		return [_maskele(v, sirlar) for v in deger]
	return deger


def _require_superadmin(ptype: str = "read") -> None:
	"""Rol kapısı + DocType izin kapısı. İkisi de geçilmeden dönülmez.

	`frappe.only_for` BİLEREK kullanılmadı: çekirdekteki uygulaması
	`frappe.flags.in_test` iken hiçbir şey yapmadan döner, yani testte
	kapı kendiliğinden açılır ve negatif testler boşa çıkardı.
	"""
	kullanici = frappe.session.user
	if kullanici == "Administrator":
		return
	if not (set(frappe.get_roles(kullanici)) & ALLOWED_ROLES):
		frappe.throw(
			_("Bu ekran yalnızca Media Superadmin rolüne açıktır."),
			frappe.PermissionError,
		)
	if not frappe.has_permission(DOCTYPE, ptype=ptype, user=kullanici):
		frappe.throw(
			_("{0} üzerinde {1} yetkiniz yok.").format(_(DOCTYPE), ptype),
			frappe.PermissionError,
		)


# ── controller ───────────────────────────────────────────────────────────


class MediaStorageSettings(Document):
	# -- doğrulama --------------------------------------------------------

	def validate(self) -> None:
		# Frappe v15'te Document.validate yok; varsa çağır (repo konvansiyonu).
		super().validate() if hasattr(super(), "validate") else None
		self._legacy_aliases_import()
		self._kip_dogrula()
		self._cdn_dogrula()
		self._imgproxy_dogrula()
		self._saklama_dogrula()
		self._legacy_aliases_sync()

	def _kip_dogrula(self) -> None:
		raw_mode = str(self.storage_mode or MODE_LOCAL).strip().lower()
		if raw_mode not in {MODE_LOCAL, MODE_MIRROR, MODE_S3_PRIMARY, MODE_TIERED}:
			frappe.throw(
				_("Bilinmeyen depolama kipi: {0}. Geçerli kipler: {1}").format(
					raw_mode, "local, mirror, s3_primary, tiered"
				)
			)
		kip = normalize_mode(raw_mode)
		if kip in S3_MODES and not int(self.s3_enabled or 0):
			frappe.throw(
				_("{0} kipi seçiliyken S3 Etkin kapatılamaz.").format(raw_mode)
			)
		if int(self.s3_enabled or 0) and not str(self.s3_bucket or "").strip():
			frappe.throw(_("S3 etkinken bucket zorunludur."))
		if int(self.s3_multipart_threshold_mb or 0) < 5:
			frappe.throw(_("S3 multipart eşiği en az 5 MB olmalıdır."))
		if int(self.s3_max_concurrency or 0) < 1:
			frappe.throw(_("S3 eşzamanlı transfer sayısı en az 1 olmalıdır."))
		if raw_mode == MODE_TIERED and int(self.original_local_days or 0) < 1:
			frappe.throw(_("tiered kipinde original_local_days en az 1 olmalıdır."))
		for fieldname in ("local_free_space_alarm_gb", "local_max_usage_gb"):
			if int(self.get(fieldname) or 0) < 0:
				frappe.throw(_("{0} negatif olamaz.").format(fieldname))

	def _cdn_dogrula(self) -> None:
		if int(self.cdn_enabled or 0) and not str(self.cdn_base_url or "").strip():
			frappe.throw(_("CDN etkinken cdn_base_url zorunludur."))
		if int(self.cdn_signed_urls or 0):
			key = self.get_password("cdn_signing_key", raise_exception=False) or ""
			_denetle_sir_okuma(("cdn_signing_key",), (key,), service="cdn")
			if not key:
				frappe.throw(_("İmzalı CDN URL'leri için cdn_signing_key zorunludur."))
		if int(self.cdn_signed_ttl_seconds or 0) < 60:
			frappe.throw(_("İmzalı CDN URL ömrü en az 60 saniye olmalıdır."))
		if int(self.cdn_purge_on_reprocess or 0):
			token = self.get_password("cdn_purge_token", raise_exception=False) or ""
			_denetle_sir_okuma(("cdn_purge_token",), (token,), service="cdn_purge")
			if not (str(self.cdn_purge_api_url or "").strip() and token):
				frappe.throw(_("Reprocess purge için API URL ve purge token zorunludur."))

	def _imgproxy_dogrula(self) -> None:
		"""Anahtar ve tuz ya birlikte ya da hiç. Hex olmayan değer erken düşer."""
		anahtar = self.get_password("imgproxy_key", raise_exception=False) or ""
		tuz = self.get_password("imgproxy_salt", raise_exception=False) or ""
		_denetle_sir_okuma(("imgproxy_key", "imgproxy_salt"), (anahtar, tuz), service="imgproxy")
		if int(self.imgproxy_enabled or 0) and not str(self.imgproxy_base_url or "").strip():
			frappe.throw(_("imgproxy etkinken kök adres zorunludur."))
		if bool(anahtar) != bool(tuz) or (int(self.imgproxy_enabled or 0) and not (anahtar and tuz)):
			frappe.throw(
				_("imgproxy imza anahtarı ve tuzu birlikte verilmelidir; biri boş bırakılamaz.")
			)
		for ad, deger in (("anahtar", anahtar), ("tuz", tuz)):
			if deger and not _hex_mi(deger):
				frappe.throw(_("imgproxy imza {0} hex kodlu olmalıdır.").format(ad))
		if float(self.imgproxy_max_source_mp or 0) <= 0:
			frappe.throw(_("imgproxy_max_source_mp pozitif olmalıdır."))

	def _saklama_dogrula(self) -> None:
		"""Politikayı GERÇEKTEN kurarak doğrula — kendi kuralımızı yazmıyoruz."""
		politika = RetentionPolicy.from_mapping(self.retention_mapping())
		if not int(self.legal_hold_overrides_all or 0):
			frappe.throw(_("legal_hold_overrides_all güvenlik güvencesi kapatılamaz."))
		if int(self.soft_delete_grace_days or 0) < 1:
			frappe.throw(_("Soft-delete bekleme süresi en az 1 gün olmalıdır."))
		hatalar = politika.validate()
		if hatalar:
			frappe.throw(_("Saklama politikası geçersiz:\n{0}").format("\n".join(hatalar)))
		for uyari in politika.warnings():
			frappe.msgprint(uyari, title=_("Saklama uyarısı"), indicator="orange")

	def _legacy_aliases_import(self) -> None:
		"""Bu kayıtta değiştirilen eski alanı canonical alana bir kez taşı.

		Canonical alan aynı kayıtta değiştirildiyse o kazanır. Böylece eski API
		istemcileri geçiş boyunca çalışırken yeni panelin seçimi eski alias'ın
		varsayılan değeriyle ezilmez.
		"""
		before = self.get_doc_before_save()
		if not before:
			return

		def changed(fieldname: str) -> bool:
			return _normalize(before.get(fieldname)) != _normalize(self.get(fieldname))

		def canonical_unchanged(fieldname: str) -> bool:
			return not changed(fieldname)

		if changed("backend") and canonical_unchanged("storage_mode"):
			legacy_mode = normalize_mode(self.backend)
			self.storage_mode = MODE_S3_PRIMARY if legacy_mode == MODE_S3 else legacy_mode
		if changed("blocker_ack") and canonical_unchanged("s3_enabled"):
			self.s3_enabled = int(self.blocker_ack or 0)
		for legacy, canonical in (
			("s3_endpoint", "s3_endpoint_url"),
			("s3_access_key", "s3_access_key_id"),
			("signed_url_ttl_seconds", "cdn_signed_ttl_seconds"),
			("trash_retention_days", "soft_delete_grace_days"),
		):
			if changed(legacy) and canonical_unchanged(canonical):
				self.set(canonical, self.get(legacy))
		# Eski arşiv süresi ayrıydı; canonical politika tek grace penceresi
		# kullanıyor. Trash alias aynı kayıtta verildiyse o daha doğrudan niyettir.
		if (
			changed("archive_retention_days")
			and not changed("trash_retention_days")
			and canonical_unchanged("soft_delete_grace_days")
		):
			self.soft_delete_grace_days = self.archive_retention_days

	def _legacy_aliases_sync(self) -> None:
		"""Eski okuyucular geçiş boyunca aynı etkin değeri görsün."""
		self.backend = normalize_mode(self.storage_mode)
		self.s3_endpoint = self.s3_endpoint_url
		self.s3_access_key = self.s3_access_key_id
		self.signed_url_ttl_seconds = self.cdn_signed_ttl_seconds
		self.trash_retention_days = self.soft_delete_grace_days
		self.derivative_action = "delete"

	# -- denetim ----------------------------------------------------------

	def on_update(self) -> None:
		"""Değişikliği `media/audit.py` üzerinden Authorization Decision Log'a yaz.

		Yeni bir denetim mekanizması kurulmadı: `log_media_event` zaten hash
		zincirli ADL'ye yazıyor, aktör/zaman/IP'yi kendisi çözüyor.
		"""
		degisenler = self._degisen_alanlar()
		if not degisenler:
			return
		media_audit.log_media_event(
			action=ACTION_STORAGE_SETTINGS,
			allowed=True,
			reason=(self.change_reason or "")[:500],
			context={
				"changed": degisenler,
				"storage_mode": self.storage_mode,
				"s3_enabled": int(self.s3_enabled or 0),
			},
		)

	def _degisen_alanlar(self) -> dict[str, Any]:
		"""{alan: {"eski": ..., "yeni": ...}} — sırlar için yalnız "değişti".

		Password alanlarının eski/yeni değeri KAYDA GİRMEZ. Frappe zaten
		belgeye yıldız yazıyor ama ona güvenmek yetmez: `get_password` ile
		çözülmüş bir değerin yanlışlıkla context'e düşmesi bu fonksiyonun
		tek gerçek riski.
		"""
		onceki = self.get_doc_before_save()
		izlenen = STORAGE_FIELDS + RETENTION_FIELDS
		degisenler: dict[str, Any] = {}
		for alan in izlenen:
			yeni = self.get(alan)
			eski = onceki.get(alan) if onceki else None
			if _normalize(eski) != _normalize(yeni):
				degisenler[alan] = {"old": _normalize(eski), "new": _normalize(yeni)}
		for alan in SECRET_FIELDS:
			if not onceki:
				if self.get(alan):
					degisenler[alan] = "set"
				continue
			if _normalize(onceki.get(alan)) != _normalize(self.get(alan)):
				# Değer DEĞİL, yalnız olay.
				degisenler[alan] = "changed"
		return degisenler

	# -- okuyucular için sözlükler ----------------------------------------

	def storage_mapping(self) -> dict[str, Any]:
		"""`StorageSettings.from_doctype`'ın beklediği düz sözlük (sır çözülmüş)."""
		veri: dict[str, Any] = {alan: self.get(alan) for alan in STORAGE_FIELDS}
		for alan in ("s3_secret_access_key", "cdn_signing_key"):
			veri[alan] = self.get_password(alan, raise_exception=False) or ""
		if not veri["s3_secret_access_key"]:
			veri["s3_secret_access_key"] = (
				self.get_password("s3_secret_key", raise_exception=False) or ""
			)
		_denetle_sir_okuma(
			("s3_secret_access_key", "cdn_signing_key"),
			(veri["s3_secret_access_key"], veri["cdn_signing_key"]),
			service="storage",
		)
		return veri

	def retention_mapping(self) -> dict[str, Any]:
		"""`RetentionPolicy.from_mapping`'in beklediği iç içe sözlük."""
		return {
			"original_retention": {
				"keep_forever": bool(self.keep_originals),
				"local_days": int(self.original_local_days or 0) or None,
				"then": self.original_then_action or "keep_local",
			},
			"derivative_retention": {
				"unused_after_days": int(self.derivative_unused_days or 90),
				"action": "delete",
				"regenerate_on_demand": bool(self.derivative_regenerate_on_demand),
				"always_keep_profiles": [
					str(row.profile)
					for row in (self.derivative_always_keep_profiles or [])
					if str(row.profile or "").strip()
				],
			},
			"legal_hold": {"enabled": True, "field": "legal_hold"},
			"soft_delete": {
				"trash_retention_days": int(self.soft_delete_grace_days or 30),
				"archive_retention_days": int(self.soft_delete_grace_days or 30),
			},
			"backup": {"keep_sets": int(self.backup_keep_sets or 14)},
		}

	def secrets(self) -> tuple[str, ...]:
		"""Maskelemede kullanılacak çözülmüş sır değerleri. Dışarı SIZMAZ."""
		fields = SECRET_FIELDS + LEGACY_SECRET_FIELDS
		cozulmus = tuple((self.get_password(alan, raise_exception=False) or "") for alan in fields)
		_denetle_sir_okuma(fields, cozulmus, service="media_storage")
		return cozulmus


def _denetle_sir_okuma(alanlar: tuple[str, ...], degerler: tuple[str, ...], *, service: str) -> None:
	"""T-134 §2 — dolu olan her sır alanının okunduğunu denetime yazar (değer YOK).

	Yalnız DOLU alanlar denetlenir: boş bir Password slotunu "okundu" diye
	yazmak gürültü olurdu (servis hiç yapılandırılmamış). Bu okuyucular
	(`storage_mapping`/`secrets`/`_imgproxy_dogrula`) yalnız superadmin ayar/test
	uçlarından çağrılır — per-URL imzalama yolu (`_imgproxy`) burada DEĞİL.
	"""
	try:
		from tradehub_core.audit.secret_access import log_secret_access

		for alan, deger in zip(alanlar, degerler):
			if deger:
				log_secret_access(
					service=service,
					field=alan,
					object_doctype=DOCTYPE,
					object_name=DOCTYPE,
				)
	except Exception:  # noqa: BLE001 — denetim hatası ayar okumasını bozmaz
		frappe.log_error(
			"Sır okuma denetimi yazılamadı", "media_storage_settings._denetle_sir_okuma"
		)


def _normalize(deger: Any) -> Any:
	"""None/"" ve 0/"0" farkını denetim gürültüsüne çevirme."""
	if deger is None:
		return ""
	if isinstance(deger, bool):
		return int(deger)
	return deger


def _hex_mi(deger: str) -> bool:
	try:
		bytes.fromhex(deger)
	except ValueError:
		return False
	return True


# ── uçlar ────────────────────────────────────────────────────────────────


@frappe.whitelist()
def get_storage_status() -> dict[str, Any]:
	"""Ayardan kurulan gerçek depo planını döndür. SIR İÇERMEZ.

	Fabrikanın `StoragePlan`'ı, istenen kip ile kurulan kip ayrıştıysa
	sebebini de söyler (`s3_enabled=0`, `boto3 kurulu değil`, `s3_bucket boş`).
	Panelin "neden hâlâ yerel diskteyim" sorusunun tek dürüst cevabı budur.
	"""
	_require_superadmin("read")
	ayar = frappe.get_cached_doc(DOCTYPE)
	try:
		plan = build_storage(
			StorageSettings.from_doctype(ayar.storage_mapping(), site_path=frappe.get_site_path())
		)
		kunye = plan.to_dict()
	except Exception as hata:  # noqa: BLE001 - plan kurulamazsa ekran boş kalmamalı
		# Mesaj sırları taşıyabilir (endpoint/anahtar içeren boto3 hataları);
		# maskelenmeden ne yanıta ne log'a gider.
		guvenli = _maskele(str(hata), ayar.secrets())
		frappe.log_error(title="media_storage_settings.status", message=guvenli)
		kunye = {"error": guvenli}
	return {
		"plan": _maskele(kunye, ayar.secrets()),
		"blockers": [],
		"storage_mode": ayar.storage_mode,
		"s3_enabled": int(ayar.s3_enabled or 0),
		"cdn_enabled": int(ayar.cdn_enabled or 0),
		"retention": RetentionPolicy.from_mapping(ayar.retention_mapping()).to_dict(),
		"boto3_available": _boto3_var_mi(),
	}


def _boto3_var_mi() -> bool:
	from tradehub_core.media.pipeline.storage.s3 import boto3_available  # noqa: PLC0415

	return boto3_available()


def _cdn_purge_client(ayar: "MediaStorageSettings") -> Any:
	from tradehub_core.media.pipeline.delivery.cdn import CdnPurgeClient, CdnPurgeConfig

	token = ayar.get_password("cdn_purge_token", raise_exception=False) or ""
	_denetle_sir_okuma(("cdn_purge_token",), (token,), service="cdn_purge")
	config = CdnPurgeConfig(
		provider=str(ayar.cdn_provider or "custom").lower(),
		api_url=str(ayar.cdn_purge_api_url or "").strip(),
		token=token,
		zone_id=str(ayar.cdn_purge_zone_id or "").strip(),
	)
	return CdnPurgeClient(config)


def _url_list(value: Any) -> list[str]:
	if isinstance(value, str):
		try:
			parsed = json.loads(value)
		except ValueError:
			parsed = [part.strip() for part in value.split(",")]
	else:
		parsed = value
	if not isinstance(parsed, (list, tuple)):
		frappe.throw(_("urls JSON dizisi olmalıdır."))
	clean = [str(url).strip() for url in parsed if str(url).strip()]
	if len(clean) > 100:
		frappe.throw(_("Tek purge çağrısında en fazla 100 URL olabilir."))
	return clean


@frappe.whitelist()
def purge_cdn_cache(urls: Any) -> dict[str, Any]:
	"""Media Superadmin için gerçek CDN purge turu; token hiçbir yanıta girmez."""
	_require_superadmin("write")
	ayar = frappe.get_cached_doc(DOCTYPE)
	if not int(ayar.cdn_enabled or 0):
		frappe.throw(_("CDN kapalıyken purge çalıştırılamaz."))
	clean = _url_list(urls)
	started = time.monotonic()
	try:
		result = _cdn_purge_client(ayar).purge(clean)
		payload = {
			"ok": result.ok,
			"provider": result.provider,
			"requested": result.requested,
			"purged": result.purged,
			"statuses": [batch.status for batch in result.batches],
			"ms": round((time.monotonic() - started) * 1000, 1),
		}
	except Exception as exc:
		message = _maskele(f"{type(exc).__name__}: {exc}", ayar.secrets())
		frappe.log_error(title="media.cdn_purge", message=message)
		payload = {
			"ok": False,
			"provider": str(ayar.cdn_provider or "custom"),
			"requested": len(clean),
			"purged": 0,
			"error": message,
			"ms": round((time.monotonic() - started) * 1000, 1),
		}
	media_audit.log_media_event(
		action=ACTION_STORAGE_SETTINGS,
		allowed=bool(payload["ok"]),
		reason="cdn_purge",
		context={k: payload[k] for k in ("provider", "requested", "purged", "ms")},
	)
	return payload


def enqueue_reprocess_purge(
	old_urls: list[str] | tuple[str, ...],
	new_urls: list[str] | tuple[str, ...],
) -> dict[str, Any]:
	"""Yalnız aynı URL overwrite edildiğinde purge kuyruğuna iş bırak.

	İçerik-adresli normal reprocess yeni version_hash ürettiği için eşleşme
	boş olur ve ağ çağrısı yapılmaz. Bu davranış purge API'sini kullanılabilir
	tutarken immutable URL stratejisinin gereksiz purge maliyetini önler.
	"""
	from tradehub_core.media.pipeline.delivery.cdn import should_purge

	ayar = frappe.get_cached_doc(DOCTYPE)
	if not (int(ayar.cdn_enabled or 0) and int(ayar.cdn_purge_on_reprocess or 0)):
		return {"queued": 0, "reason": "disabled"}
	urls = [old for old, new in zip(old_urls, new_urls) if should_purge(old_url=old, new_url=new)]
	if not urls:
		return {"queued": 0, "reason": "immutable_url_changed"}
	frappe.enqueue(
		"tradehub_core.tradehub_core.doctype.media_storage_settings.media_storage_settings._run_cdn_purge",
		queue="short",
		enqueue_after_commit=True,
		urls=urls,
	)
	return {"queued": len(urls), "reason": "same_url_overwrite"}


def _run_cdn_purge(urls: list[str]) -> dict[str, Any]:
	"""Sistem kuyruğu CDN purge worker'ı; kullanıcı rol kapısı uygulanmaz."""
	ayar = frappe.get_cached_doc(DOCTYPE)
	result = _cdn_purge_client(ayar).purge(urls)
	return {"ok": result.ok, "requested": result.requested, "purged": result.purged}


@frappe.whitelist()
def test_connection(target: str = "s3") -> dict[str, Any]:
	"""Yapılandırılmış hedefe GERÇEK bir bağlantı dene.

	Args:
	    target: `s3` (yaz/oku/sil turu), `cdn` (HEAD), `imgproxy` (imzalı
	        örnek URL + HEAD).

	Returns:
	    `{"target", "ok", "steps": [{"step","ok","ms","detail"}], "ms"}`.
	    Hiçbir alanda sır YOKTUR: dönüş `_maskele`'den geçer.

	Yazma yetkisi aranır: test bir S3 kovasına nesne yazıp siler ve dış
	ağa istek atar; okuma yetkisi olan biri bunu tetikleyememeli.
	"""
	_require_superadmin("write")
	hedef = (target or "s3").strip().lower()
	if hedef not in _TEST_TARGETS:
		frappe.throw(_("Bilinmeyen test hedefi: {0}").format(hedef))

	ayar = frappe.get_cached_doc(DOCTYPE)
	sirlar = ayar.secrets()
	baslangic = time.monotonic()
	if hedef == "s3":
		adimlar = _s3_testi(ayar)
	elif hedef == "cdn":
		adimlar = _http_testi(ayar.cdn_base_url, "cdn")
	else:
		adimlar = _imgproxy_testi(ayar)
	sonuc = {
		"target": hedef,
		"ok": all(a.get("ok") for a in adimlar) and bool(adimlar),
		"steps": adimlar,
		"ms": round((time.monotonic() - baslangic) * 1000, 1),
	}
	guvenli = _maskele(sonuc, sirlar)

	# Testin kendisi de denetlenir: kim, ne zaman, hangi hedefe bağlandı.
	media_audit.log_media_event(
		action=ACTION_STORAGE_SETTINGS,
		allowed=bool(guvenli["ok"]),
		reason=f"connection_test:{hedef}",
		context={"target": hedef, "ok": guvenli["ok"], "ms": guvenli["ms"]},
	)
	return guvenli


def _adim(ad: str, ok: bool, ms: float, detay: str = "") -> dict[str, Any]:
	return {"step": ad, "ok": bool(ok), "ms": round(ms, 1), "detail": detay}


def _s3_testi(ayar: "MediaStorageSettings") -> list[dict[str, Any]]:
	"""Gerçek yaz → oku → sil turu. Adaptörün kendisi kullanılır."""
	from tradehub_core.media.pipeline.storage.s3 import S3Config, S3Storage  # noqa: PLC0415

	veri = ayar.storage_mapping()
	konf = S3Config(
		enabled=True,  # test bilinçli bir tetikleme; kip local olsa da denenebilmeli
		bucket=str(veri.get("s3_bucket") or ""),
		region=str(veri.get("s3_region") or ""),
		endpoint_url=str(veri.get("s3_endpoint_url") or ""),
		prefix=str(veri.get("s3_prefix") or "media").strip("/"),
		access_key_id=str(veri.get("s3_access_key_id") or ""),
		secret_access_key=str(veri.get("s3_secret_access_key") or ""),
		storage_class={
			"INFREQUENT": "STANDARD_IA",
			"COLD": "GLACIER_IR",
			"ARCHIVE": "DEEP_ARCHIVE",
		}.get(str(veri.get("s3_storage_class") or "STANDARD"), str(veri.get("s3_storage_class") or "STANDARD")),
		server_side_encryption=str(veri.get("s3_server_side_encryption") or "none"),
		multipart_threshold_bytes=max(
			5 * 1024 * 1024,
			int(veri.get("s3_multipart_threshold_mb") or 64) * 1024 * 1024,
		),
		max_concurrency=max(1, int(veri.get("s3_max_concurrency") or 4)),
		addressing_style="path" if int(veri.get("s3_path_style") or 0) else "auto",
		public_base_url=str(veri.get("cdn_base_url") or "").rstrip("/"),
	)
	eksik = [p for p in konf.problems()]
	if eksik:
		return [_adim("config", False, 0.0, "; ".join(eksik))]

	icerik = f"tradehub-storage-probe-{frappe.generate_hash(length=16)}".encode()
	adimlar: list[dict[str, Any]] = []
	depo = None
	ref = None
	try:
		t0 = time.monotonic()
		depo = S3Storage(konf)
		adimlar.append(_adim("connect", True, (time.monotonic() - t0) * 1000, konf.bucket))

		t0 = time.monotonic()
		sonuc = depo.put(icerik, ".txt")
		ref = sonuc.ref
		adimlar.append(_adim("write", True, (time.monotonic() - t0) * 1000, ref.key.relative))

		t0 = time.monotonic()
		okunan = depo.get(ref)
		adimlar.append(
			_adim("read", okunan == icerik, (time.monotonic() - t0) * 1000, f"{len(okunan)} bayt")
		)
	except Exception as hata:  # noqa: BLE001 - test ucu; her hata KULLANICIYA sonuç olarak döner
		adimlar.append(_adim("error", False, 0.0, f"{type(hata).__name__}: {hata}"))
	finally:
		if depo is not None and ref is not None:
			try:
				t0 = time.monotonic()
				depo.delete(ref)
				adimlar.append(_adim("delete", True, (time.monotonic() - t0) * 1000))
			except Exception as hata:  # noqa: BLE001 - sonda kalan nesne raporlanmalı
				adimlar.append(_adim("delete", False, 0.0, f"{type(hata).__name__}: {hata}"))
	return adimlar


def _http_testi(url: str, ad: str) -> list[dict[str, Any]]:
	"""HEAD isteği + önbellek başlıkları. Yalnız http/https."""
	import requests  # noqa: PLC0415

	hedef = (url or "").strip()
	if not hedef:
		return [_adim(ad, False, 0.0, "adres tanımlı değil")]
	if not hedef.startswith(("http://", "https://")):
		return [_adim(ad, False, 0.0, "yalnız http/https adres denenir")]
	t0 = time.monotonic()
	try:
		yanit = requests.head(hedef, timeout=8, allow_redirects=True)
	except requests.RequestException as hata:
		return [_adim(ad, False, (time.monotonic() - t0) * 1000, f"{type(hata).__name__}: {hata}")]
	sure = (time.monotonic() - t0) * 1000
	basliklar = {
		k: yanit.headers.get(k, "")
		for k in ("cache-control", "age", "cf-cache-status", "x-cache", "content-type")
		if yanit.headers.get(k)
	}
	return [
		_adim(
			ad,
			200 <= yanit.status_code < 400,
			sure,
			f"HTTP {yanit.status_code} · " + (", ".join(f"{k}={v}" for k, v in basliklar.items()) or "başlık yok"),
		)
	]


def _imgproxy_testi(ayar: "MediaStorageSettings") -> list[dict[str, Any]]:
	"""Anahtar+tuz ile imzalı örnek URL üret, sonra HEAD ile doğrula."""
	taban = (ayar.imgproxy_base_url or "").strip().rstrip("/")
	anahtar = ayar.get_password("imgproxy_key", raise_exception=False) or ""
	tuz = ayar.get_password("imgproxy_salt", raise_exception=False) or ""
	if not taban:
		return [_adim("imgproxy", False, 0.0, "imgproxy kök adresi tanımlı değil")]
	if not (anahtar and tuz):
		return [_adim("imgproxy", False, 0.0, "imza anahtarı/tuzu tanımlı değil")]
	try:
		imza_yolu = _imgproxy_imzali_yol(anahtar, tuz)
	except ValueError as hata:
		return [_adim("imgproxy", False, 0.0, str(hata))]
	return _http_testi(f"{taban}{imza_yolu}", "imgproxy")


def _imgproxy_imzali_yol(anahtar_hex: str, tuz_hex: str) -> str:
	"""imgproxy imza şeması: base64url(HMAC-SHA256(key, salt + path)) + path.

	Örnek kaynak `example.com/probe.png` gerçek olmayabilir; testin ölçtüğü
	şey imgproxy'nin imzayı KABUL edip etmediğidir (imza yanlışsa 403,
	doğruysa 404/422 gibi imza SONRASI bir kod döner).
	"""
	anahtar = bytes.fromhex(anahtar_hex)
	tuz = bytes.fromhex(tuz_hex)
	if not anahtar or not tuz:
		raise ValueError("imza anahtarı/tuzu hex çözümünde boş çıktı")
	yol = "/rs:fit:64:64/plain/https://example.com/probe.png@png"
	ozet = hmac.new(anahtar, tuz + yol.encode(), hashlib.sha256).digest()
	imza = base64.urlsafe_b64encode(ozet).rstrip(b"=").decode()
	return f"/{imza}{yol}"

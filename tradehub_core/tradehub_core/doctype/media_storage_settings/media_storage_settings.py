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
DocType izinleri yalnız `Media Superadmin` + `System Manager`. Satıcı/alıcı
rolleri listede HİÇ YOK — Frappe'de listede olmayan rol hiçbir hak almaz,
yani okuma dahi yok. `hooks.py`'deki `has_permission` kaydı ikinci kattır
(`permissions.media_storage_settings_has_permission`): ileride biri DocPerm
satırı eklerse bile rol kapısı ayakta kalır.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.media import audit as media_audit
from tradehub_core.media.pipeline.storage import (
	MODE_LOCAL,
	MODES,
	S3_MODES,
	StorageSettings,
	build_storage,
)
from tradehub_core.media.pipeline.storage.retention import RetentionPolicy

DOCTYPE: str = "Media Storage Settings"

#: Ayarı okuyabilen/yazabilen roller. DocType JSON'daki `permissions` listesi
#: ile AYNI küme olmak zorunda — testi ikisini karşılaştırır.
ALLOWED_ROLES: frozenset[str] = frozenset({"Media Superadmin", "System Manager"})

#: Password fieldtype'lı alanlar. Maskeleme ve "değişti mi" karşılaştırması
#: bu listeden yürür; yeni bir sır eklenirse buraya da eklenmeli.
SECRET_FIELDS: tuple[str, ...] = ("s3_secret_key", "imgproxy_key", "imgproxy_salt")

#: `StorageSettings.from_doctype`'ın okuduğu alanlar (sır hariç).
STORAGE_FIELDS: tuple[str, ...] = (
	"backend",
	"s3_endpoint",
	"s3_region",
	"s3_bucket",
	"s3_access_key",
	"cdn_base_url",
	"signed_url_ttl_seconds",
)

#: Saklama bölümünün alanları — denetim karşılaştırmasında kullanılır.
RETENTION_FIELDS: tuple[str, ...] = (
	"keep_originals",
	"original_local_days",
	"original_then_action",
	"trash_retention_days",
	"derivative_unused_days",
	"derivative_action",
	"derivative_regenerate_on_demand",
	"archive_retention_days",
	"backup_keep_sets",
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
OPEN_BLOCKERS: tuple[str, ...] = (
	"B-02: S3Storage.exists() ağ hatasında istisna atıyor; tiered kipinde render kırar.",
	"B-04: TieredStorage.delete() sıcaktan siler, soğuk düşükken istisna atar (KVKK silme talebi).",
	"B-05: media_mirror_queue=inline üretim ayarında henüz reddedilmiyor.",
	"boto3 imaja alınmadı — bugünkü kurulum konteyner ömürlü.",
	"mirror.reconcile() hiçbir zamanlayıcıya bağlı değil; düşen ayna görevlerinin telafisi yok.",
	"tiered için age_days ölçülmedi (DEFAULT_AGE_DAYS=90 bir varsayılan seçimi).",
)

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
		self._kip_dogrula()
		self._imgproxy_dogrula()
		self._saklama_dogrula()

	def _kip_dogrula(self) -> None:
		kip = (self.backend or MODE_LOCAL).strip().lower()
		if kip not in MODES:
			frappe.throw(
				_("Bilinmeyen depolama kipi: {0}. Geçerli kipler: {1}").format(
					kip, ", ".join(MODES)
				)
			)
		if kip == MODE_LOCAL:
			return

		# local dışı kip = S3 gerektiren kip. Üç kapı sırayla.
		if not self.blocker_ack:
			frappe.throw(
				_("{0} kipi bugün üretime alınamaz. Açık kapılar:\n\n{1}\n\n"
				  "Yine de açmak için 'Açık Kapıları Okudum' kutusunu işaretleyin.").format(
					kip, "\n".join(f"• {b}" for b in OPEN_BLOCKERS)
				)
			)
		if not (self.s3_bucket or "").strip():
			frappe.throw(
				_("{0} kipi için S3 kovası zorunlu — boşken fabrika yerel diske düşer.").format(kip)
			)
		if kip in S3_MODES:
			frappe.msgprint(
				_("UYARI: {0} kipi açık kapılarla devrede. {1} engel kaydedildi ve "
				  "denetim kaydına yazıldı.").format(kip, len(OPEN_BLOCKERS)),
				title=_("Depolama kipi değişti"),
				indicator="orange",
			)

	def _imgproxy_dogrula(self) -> None:
		"""Anahtar ve tuz ya birlikte ya da hiç. Hex olmayan değer erken düşer."""
		anahtar = self.get_password("imgproxy_key", raise_exception=False) or ""
		tuz = self.get_password("imgproxy_salt", raise_exception=False) or ""
		_denetle_sir_okuma(("imgproxy_key", "imgproxy_salt"), (anahtar, tuz), service="imgproxy")
		if bool(anahtar) != bool(tuz):
			frappe.throw(
				_("imgproxy imza anahtarı ve tuzu birlikte verilmelidir; biri boş bırakılamaz.")
			)
		for ad, deger in (("anahtar", anahtar), ("tuz", tuz)):
			if deger and not _hex_mi(deger):
				frappe.throw(_("imgproxy imza {0} hex kodlu olmalıdır.").format(ad))

	def _saklama_dogrula(self) -> None:
		"""Politikayı GERÇEKTEN kurarak doğrula — kendi kuralımızı yazmıyoruz."""
		politika = RetentionPolicy.from_mapping(self.retention_mapping())
		hatalar = politika.validate()
		if hatalar:
			frappe.throw(_("Saklama politikası geçersiz:\n{0}").format("\n".join(hatalar)))
		for uyari in politika.warnings():
			frappe.msgprint(uyari, title=_("Saklama uyarısı"), indicator="orange")

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
				"backend": self.backend,
				"blocker_ack": int(self.blocker_ack or 0),
				# Kipi açanın hangi engelleri kabul ettiği kayıtta dursun.
				"acknowledged_blockers": list(OPEN_BLOCKERS)
				if (self.backend or MODE_LOCAL) != MODE_LOCAL
				else [],
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
		izlenen = STORAGE_FIELDS + RETENTION_FIELDS + ("blocker_ack",)
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
		veri["s3_secret_key"] = self.get_password("s3_secret_key", raise_exception=False) or ""
		_denetle_sir_okuma(("s3_secret_key",), (veri["s3_secret_key"],), service="s3")
		return veri

	def retention_mapping(self) -> dict[str, Any]:
		"""`RetentionPolicy.from_mapping`'in beklediği iç içe sözlük."""
		return {
			"original_retention": {
				"keep_forever": bool(self.keep_originals),
				"local_days": int(self.original_local_days or 0) or None,
				"then": self.original_then_action or "notify_only",
			},
			"derivative_retention": {
				"unused_after_days": int(self.derivative_unused_days or 90),
				"action": self.derivative_action or "notify_only",
				"regenerate_on_demand": bool(self.derivative_regenerate_on_demand),
				"always_keep_profiles": [],
			},
			"soft_delete": {
				"trash_retention_days": int(self.trash_retention_days or 30),
				"archive_retention_days": int(self.archive_retention_days or 30),
			},
			"backup": {"keep_sets": int(self.backup_keep_sets or 14)},
		}

	def secrets(self) -> tuple[str, ...]:
		"""Maskelemede kullanılacak çözülmüş sır değerleri. Dışarı SIZMAZ."""
		cozulmus = tuple(
			(self.get_password(alan, raise_exception=False) or "") for alan in SECRET_FIELDS
		)
		_denetle_sir_okuma(SECRET_FIELDS, cozulmus, service="media_storage")
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
		"blockers": list(OPEN_BLOCKERS),
		"blocker_ack": int(ayar.blocker_ack or 0),
		"retention": RetentionPolicy.from_mapping(ayar.retention_mapping()).to_dict(),
		"boto3_available": _boto3_var_mi(),
	}


def _boto3_var_mi() -> bool:
	from tradehub_core.media.pipeline.storage.s3 import boto3_available  # noqa: PLC0415

	return boto3_available()


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
		endpoint_url=str(veri.get("s3_endpoint") or ""),
		access_key_id=str(veri.get("s3_access_key") or ""),
		secret_access_key=str(veri.get("s3_secret_key") or ""),
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

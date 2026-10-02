"""Ürün görsellerini tek düğmeyle optimize et (2026-09-30, Sistem → Medya).

Ayrı kartlarda duran işler (kare WebP master, eski ad → SEO adı, dosya/varlık
künyesi, WebP türevleri) tek bir arka plan işinde sırayla koşar. **Bu modülde
dönüşüm mantığı YOK**: her adım mevcut fonksiyonu çağırır ve sonucunu tek bir
özet satırına çevirir.

Adımlar (sıra bilinçli):

0. ``on_kontrol`` — profiller açık mı, bayraklar, medya worker'ları, kill switch.
   2026-09-28'de bir test koşusu yedi `product.image` profilini `enabled=0`
   bıraktı ve türev üretimi sessizce durdu; aynı durum işi en başta düşürür.
1. ``kare`` — `kare.toplu_donustur`: kare olmayan ya da WebP olmayan master'lar
   kare WebP'ye, eski adres 301, orijinal 30 gün arşiv.
2. ``seo_ad`` — yalnız rapor. Ürün görsellerinin eski adları 1. adımda zaten
   hash'li adrese taşınıyor; ayrı bir retro-rename koşusu ürün dışı dosyaları da
   taşırdı (kapsam dışı). Bekleyen ürün görseli varsa sayılır.
3. ``meta`` — `kare.backfill_eski_varliklar` (bayat varlık arşivi) +
   `seo_generate.backfill_dimensions` (ölçüsü boş ürün dosyaları).
4. ``turev`` — güncel WebP politikasında olmayan ürün görsellerinin türevleri
   `media-image-bulk` kuyruğunda yeniden üretilir; iş bitene kadar beklenir ve
   hazır/başarısız sayılır. Türevler SONA konuldu: 1. ve 3. adımın tetiklediği
   üretimler de bu adımın hazır/başarısız sayımına girsin.

Mağaza görselleri (2026-09-30, `magaza_gorseli`): kare DEĞİL — oran ve şeffaflık
korunur, master WebP ≤ 2000 px.

1b. ``magaza`` — logo, kapak, vitrin slaytı, galeri master'ları WebP'ye; taşıma
    kare ile aynı (301 + 30 gün arşiv + geri alma). 301 satırları `<iş>-mg`
    etiketiyle yazılır; geri alma bu adımı kare adımından AYRI geri alır.
5.  ``magaza_turev`` — `seller.logo` (64/128/256) ve `company.cover_image`
    (384…1920) WebP türevleri, 4. adımla aynı yöntem.

Kilit: retro-rename/kare kartlarıyla ORTAK (`retro_rename.ACTIVE_KEY`). İş
anahtarı `kare-` önekli; böylece kare adımının 301 satırları bu anahtarla
etiketlenir ve Kare kartının geri alma ucu da onları tanır.

Son koşular `tabDefaultValue`'da (`__global`) tutulur: Redis ilerlemesi 1 saatte
düşüyor, geri alma ise günler sonra istenebilir. `frappe.db.set_global` BİLEREK
kullanılmıyor: `__global` yazımı `frappe.clear_cache()` çağırıyor ve site
önbelleğini silerken ortak iş kilidini ve durdurma bayrağını da siliyordu
(testte ölçüldü: kilit düştü, Kare kartı aynı anda başlayabildi).
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

from tradehub_core.media import kare, pipeline_flags, rendition_backfill, retro_rename, seo_generate
from tradehub_core.media.pipeline.core.queues import IMAGE_BULK, IMAGE_LIVE

SLOT = "product.image"
JOB_PREFIX = f"{kare.JOB_PREFIX}opt-"
KILL_SWITCH = "urun_gorseli_kare_kapali"
RUNS_KEY = "tradehub_media_urun_optimize_runs"
MAX_RUNS = 10
PROVA_GECERLILIK_SAAT = 24
MAGAZA_SLOTLARI = ("seller.logo", "company.cover_image")
MAGAZA_ETIKETI = "-mg"
ADIMLAR = ("on_kontrol", "kare", "magaza", "seo_ad", "meta", "turev", "magaza_turev")
#: Geri alma bu sıranın TERSİYLE koşar (önce mağaza, sonra kare).
GERI_ALINABILIR = ("kare", "magaza")
TERMINAL = frozenset({"completed", "partial", "stopped", "error"})
KUYRUK_BEKLEME_SN = 15 * 60
TUREV_BEKLEME_SN = 3 * 3600
BEKLEME_ARALIGI_SN = 5
IN_PARCA = 400


# ─── Kayıt (son koşular) ────────────────────────────────────────────────────


def _kosular() -> list[dict]:
	# `get_global` süreç-içi önbellekten okuyabilir; durum her poll'da taze olmalı.
	ham = frappe.db.get_value("DefaultValue", {"parent": "__global", "defkey": RUNS_KEY}, "defvalue")
	try:
		veri = json.loads(ham or "[]")
	except ValueError:
		return []
	return veri if isinstance(veri, list) else []


def _kosulari_yaz(ham: str | None) -> None:
	"""Satırı doğrudan yaz — önbellek temizliği YOK (modül başlığı)."""
	ad = frappe.db.get_value("DefaultValue", {"parent": "__global", "defkey": RUNS_KEY}, "name")
	if ad:
		frappe.db.set_value("DefaultValue", ad, "defvalue", ham, update_modified=False)
		return
	if ham is None:
		return
	simdi = now_datetime()
	dv = frappe.qb.DocType("DefaultValue")
	frappe.qb.into(dv).columns(
		dv.name, dv.parent, dv.parenttype, dv.parentfield, dv.defkey, dv.defvalue, dv.creation, dv.modified
	).insert(
		frappe.generate_hash(length=10),
		"__global",
		"__default",
		"system_defaults",
		RUNS_KEY,
		ham,
		simdi,
		simdi,
	).run()


def _kaydet(durum: dict) -> None:
	kosular = [k for k in _kosular() if k.get("job_key") != durum["job_key"]]
	kosular.insert(0, durum)
	_kosulari_yaz(json.dumps(kosular[:MAX_RUNS], default=str, ensure_ascii=False))
	frappe.db.commit()


def kosu(job_key: str) -> dict | None:
	return next((k for k in _kosular() if k.get("job_key") == job_key), None)


def _yeni_adim(anahtar: str) -> dict:
	return {
		"key": anahtar,
		"state": "pending",
		"changed": 0,
		"ok": 0,
		"skipped": 0,
		"failed": 0,
		"reasons": {},
		"message": "",
	}


def _yeni_durum(job_key: str, dry_run: bool, mode: str = "optimize", **ek) -> dict:
	# Geri alma adımları koşacakları sırada (tersten) listelenir.
	adimlar = tuple(reversed(GERI_ALINABILIR)) if mode == "rollback" else ADIMLAR
	return {
		"job_key": job_key,
		"mode": mode,
		"dry_run": bool(dry_run),
		"state": "queued",
		"current_step": None,
		"started_at": str(now_datetime()),
		"finished_at": None,
		"owner": frappe.session.user,
		"message": "",
		"steps": [_yeni_adim(a) for a in adimlar],
		**ek,
	}


def _adim(durum: dict, anahtar: str) -> dict:
	return next(a for a in durum["steps"] if a["key"] == anahtar)


def _neden(adim: dict, kod: str, adet: int = 1) -> None:
	if kod and adet:
		adim["reasons"][kod] = adim["reasons"].get(kod, 0) + int(adet)


# ─── 0. Ön kontroller ───────────────────────────────────────────────────────


def _politika_profilleri(slot: str = SLOT) -> set[str]:
	from tradehub_core.media.pipeline.policy.engine import PolicyRegistry

	return {
		str(p.get("name") or "").strip()
		for p in (PolicyRegistry().get(slot).get("profiles") or ())
		if p.get("name")
	}


def _profil_kontrolu(slot: str) -> dict:
	politika = _politika_profilleri(slot)
	acik = {
		str(r.policy_profile or "")
		for r in frappe.get_all(
			"Media Profile", filters={"slot_key": slot, "enabled": 1}, fields=["policy_profile"]
		)
	}
	kapali = sorted(politika - acik)
	return {
		"key": "profiles_enabled" if slot == SLOT else f"profiles_enabled_{slot.replace('.', '_')}",
		"ok": bool(politika) and not kapali,
		"message": (
			_("{0} türev profili kapalı ya da eksik: {1}").format(slot, ", ".join(kapali))
			if kapali
			else _("{0} türev profilinin hepsi açık ({1}).").format(slot, len(politika))
		),
	}


def _worker_sayisi(kuyruk: str) -> int:
	from frappe.utils.background_jobs import get_queue, get_workers

	return len(get_workers(get_queue(kuyruk)))


def on_kontroller() -> list[dict]:
	"""`[{key, ok, message}]` — hiçbir şey yazmaz."""
	kontroller: list[dict] = [_profil_kontrolu(slot) for slot in (SLOT, *MAGAZA_SLOTLARI)]

	pipeline_flags.clear_cache()
	bayrak = pipeline_flags.is_enabled("rendition_on_upload")
	kapali_slotlar = [s for s in (SLOT, *MAGAZA_SLOTLARI) if not pipeline_flags.is_slot_enabled(s)]
	kontroller.append(
		{
			"key": "rendition_flag",
			"ok": bool(bayrak) and not kapali_slotlar,
			"message": (
				_("Türev üretimi açık (rendition_on_upload, {0}).").format(
					", ".join((SLOT, *MAGAZA_SLOTLARI))
				)
				if bayrak and not kapali_slotlar
				else _("Türev üretimi kapalı: rendition_on_upload={0}, kapalı slotlar: {1}.").format(
					int(bool(bayrak)), ", ".join(kapali_slotlar) or "-"
				)
			),
		}
	)

	for kuyruk in (IMAGE_LIVE.name, IMAGE_BULK.name):
		try:
			adet = _worker_sayisi(kuyruk)
		except Exception:
			frappe.log_error(title=f"Tek düğme: worker sayılamadı {kuyruk}", message=frappe.get_traceback())
			adet = 0
		kontroller.append(
			{
				"key": f"workers_{kuyruk.replace('-', '_')}",
				"ok": adet > 0,
				"message": (
					_("{0} kuyruğunda {1} worker çalışıyor.").format(kuyruk, adet)
					if adet
					else _("{0} kuyruğunu dinleyen worker yok.").format(kuyruk)
				),
			}
		)

	kapali_mi = bool(frappe.conf.get(KILL_SWITCH))
	kontroller.append(
		{
			"key": "kill_switch",
			"ok": not kapali_mi,
			"message": (
				_("site_config'te {0} açık; kareleme kapatılmış.").format(KILL_SWITCH)
				if kapali_mi
				else _("Kareleme kill switch'i kapalı ({0} yok).").format(KILL_SWITCH)
			),
		}
	)
	return kontroller


def _on_kontrol_adimi(durum: dict) -> bool:
	adim = _adim(durum, "on_kontrol")
	kontroller = on_kontroller()
	adim["checks"] = kontroller
	adim["ok"] = sum(1 for k in kontroller if k["ok"])
	adim["failed"] = sum(1 for k in kontroller if not k["ok"])
	for k in kontroller:
		if not k["ok"]:
			_neden(adim, k["key"])
	adim["message"] = "; ".join(k["message"] for k in kontroller if not k["ok"])
	adim["state"] = "done" if not adim["failed"] else "error"
	return not adim["failed"]


# ─── Ortak yardımcılar ──────────────────────────────────────────────────────


def _urun_adresleri() -> list[str]:
	return kare.aday_urls()


def _parcala(liste: list, boy: int = IN_PARCA):
	for i in range(0, len(liste), boy):
		yield liste[i : i + boy]


def _urun_dosyalari(urls: list[str]) -> list[dict]:
	"""Ürün adreslerinin public `File` satırları (adres+sahip başına tek satır)."""
	gorulen: set[tuple[str, str]] = set()
	cikti: list[dict] = []
	for parca in _parcala(urls):
		# Sistem işi: tüm ürün dosyaları taranıyor, kullanıcı kapsamı yok.
		for f in frappe.get_all(
			"File",
			filters={"file_url": ["in", parca], "is_folder": 0, "is_private": 0},
			fields=["name", "file_url", "owner"],
			order_by="name asc",
		):
			anahtar = (f.file_url, f.owner or "")
			if anahtar in gorulen:
				continue
			gorulen.add(anahtar)
			cikti.append(f)
	return cikti


def _durdu_mu(job_key: str) -> bool:
	return retro_rename._stop_requested(job_key)


def _kilidi_tazele(job_key: str) -> None:
	if not retro_rename.acquire_or_refresh_active(job_key):
		raise RuntimeError(_("Ortak medya iş kilidi kaybedildi."))


# ─── 1. Kare ────────────────────────────────────────────────────────────────


def _kare_adimi(durum: dict) -> None:
	adim = _adim(durum, "kare")
	sonuc = kare.toplu_donustur(durum["job_key"], dry_run=durum["dry_run"])
	_donusum_ozeti(adim, sonuc, "already_square")


def magaza_satir_anahtari(job_key: str) -> str:
	"""Mağaza adımının 301 satırlarının etiketi — kare satırlarından ayrı geri alınır."""
	return f"{job_key}{MAGAZA_ETIKETI}"


def _magaza_adimi(durum: dict) -> None:
	from tradehub_core.media import magaza_gorseli

	adim = _adim(durum, "magaza")
	sonuc = magaza_gorseli.toplu_donustur(
		durum["job_key"],
		dry_run=durum["dry_run"],
		satir_anahtari=magaza_satir_anahtari(durum["job_key"]),
	)
	_donusum_ozeti(adim, sonuc, "already_webp")


def _donusum_ozeti(adim: dict, sonuc: dict, zaten_kodu: str) -> None:
	nedenler = dict(sonuc.get("skip_reasons") or {})
	zaten = int(nedenler.pop(zaten_kodu, 0))
	adim.update(
		changed=int(sonuc.get("renamed") or 0),
		ok=zaten,
		skipped=max(0, int(sonuc.get("skipped") or 0) - zaten),
		failed=int(sonuc.get("errors") or 0),
		reasons=nedenler,
		total=int(sonuc.get("total") or 0),
		refs_updated=int(sonuc.get("refs_updated") or 0),
		message=str(sonuc.get("message") or ""),
	)
	adim["state"] = {"stopped": "stopped", "partial": "partial"}.get(sonuc.get("state"), "done")


# ─── 2. SEO adı (retro-rename) — yalnız rapor ───────────────────────────────


def _seo_ad_adimi(durum: dict) -> None:
	adim = _adim(durum, "seo_ad")
	urun = set(_urun_adresleri())
	eski = [u for u in retro_rename.legacy_urls() if u in urun]
	adim["ok"] = len(urun) - len(eski)
	if eski:
		# Provada: bunları 1. adım hash'li adrese taşıyacak. Gerçek koşuda (1. adım
		# bitti): kalanlar kare adımının atladıkları (diskte yok, karantina...).
		_neden(adim, "handled_by_kare" if durum["dry_run"] else "kare_skipped", len(eski))
		adim["skipped"] = len(eski)
	adim["state"] = "done"


# ─── 3. Dosya / varlık künyesi ──────────────────────────────────────────────


def _meta_adimi(durum: dict) -> None:
	adim = _adim(durum, "meta")
	dry = durum["dry_run"]
	eski = kare.backfill_eski_varliklar(dry_run=int(dry), ortak_kilit_bende=True)
	nedenler = dict(eski.get("skipped_reasons") or {})
	adim["ok"] += int(nedenler.pop("already_new_format", 0)) + int(eski.get("fresh_assets_kept") or 0)
	adim["changed"] += int(eski.get("stale_assets_found" if dry else "archived") or 0)
	for kod, adet in nedenler.items():
		if kod.startswith("error_"):
			adim["failed"] += int(adet)
		else:
			adim["skipped"] += int(adet)
		_neden(adim, kod, adet)

	urls = _urun_adresleri()
	toplam = 0
	for parca in _parcala(urls):
		toplam += frappe.db.count("File", {"file_url": ["in", parca], "is_folder": 0})
		olcu = seo_generate.backfill_dimensions(limit=2000, file_urls=parca, dry_run=dry)
		adim["changed"] += int(olcu.get("written") or 0)
		for kod in ("missing", "unreadable"):
			adet = int(olcu.get(kod) or 0)
			adim["skipped"] += adet
			_neden(adim, f"dimensions_{kod}", adet)
		toplam -= int(olcu.get("scanned") or 0)
		_kilidi_tazele(durum["job_key"])
	adim["ok"] += max(0, toplam)
	adim["state"] = "done" if not adim["failed"] else "partial"


# ─── 4. WebP türevleri ──────────────────────────────────────────────────────


def _kuyruk_yuku() -> int:
	"""media-image-live + bulk: bekleyen + çalışan iş sayısı."""
	from frappe.utils.background_jobs import get_queue
	from rq.registry import StartedJobRegistry

	toplam = 0
	for ad in (IMAGE_LIVE.name, IMAGE_BULK.name):
		q = get_queue(ad)
		toplam += int(q.count) + len(StartedJobRegistry(queue=q))
	return toplam


def _kuyrugun_bosalmasini_bekle(job_key: str, sure: int = KUYRUK_BEKLEME_SN) -> bool:
	"""Önceki adımların tetiklediği türev işleri bitsin. `False` = durdurma istendi."""
	bitis = time.monotonic() + sure
	while time.monotonic() < bitis:
		if _durdu_mu(job_key):
			return False
		try:
			if _kuyruk_yuku() == 0:
				return True
		except Exception:
			frappe.log_error(title="Tek düğme: kuyruk okunamadı", message=frappe.get_traceback())
			return True
		_kilidi_tazele(job_key)
		time.sleep(BEKLEME_ARALIGI_SN)
	return True


def _is_kimligi(job_key: str, url: str) -> str:
	return f"media-optimize::{job_key}::{hashlib.sha1(url.encode()).hexdigest()}"  # noqa: S324


def _is_bitti_mi(is_kimligi: str) -> bool:
	from frappe.utils.background_jobs import get_job

	is_ = get_job(is_kimligi)
	if is_ is None:
		return True
	return is_.get_status(refresh=True) not in ("queued", "started", "deferred", "scheduled")


def _bekleyenleri_iptal_et(kimlikler: list[str]) -> None:
	from frappe.utils.background_jobs import get_job

	for kimlik in kimlikler:
		try:
			is_ = get_job(kimlik)
			if is_ is not None and is_.get_status(refresh=True) == "queued":
				is_.cancel()
		except Exception:
			frappe.log_error(title="Tek düğme: iş iptal edilemedi", message=frappe.get_traceback())


def _turev_adimi(durum: dict) -> None:
	_turevleri_uret(durum, "turev", _urun_adresleri(), (SLOT,))


def _magaza_turev_adimi(durum: dict) -> None:
	from tradehub_core.media import magaza_gorseli

	_turevleri_uret(durum, "magaza_turev", magaza_gorseli.aday_urls(), MAGAZA_SLOTLARI)


def _slotta_mi(f: dict, slotlar: tuple[str, ...]) -> tuple[str, str]:
	"""`rendition_backfill._process_file` provası; dosya birden çok slottan birinde olabilir."""
	sonuc, neden = rendition_backfill._process_file(f.name, dry_run=True, slot_only=slotlar)
	return sonuc, neden


def _turevleri_uret(durum: dict, anahtar: str, urls: list[str], slotlar: tuple[str, ...]) -> None:
	adim = _adim(durum, anahtar)
	job_key = durum["job_key"]
	dry = durum["dry_run"]
	if not dry and not _kuyrugun_bosalmasini_bekle(job_key):
		adim.update(state="stopped", message=_("Operatör durdurdu."))
		return

	dosyalar = _urun_dosyalari(urls)
	adim["total"] = len(dosyalar)
	bekleyen: list[dict] = []
	for i, f in enumerate(dosyalar):
		if i % 100 == 0:
			if _durdu_mu(job_key):
				adim.update(state="stopped", message=_("Operatör durdurdu."))
				return
			_kilidi_tazele(job_key)
		try:
			sonuc, neden = _slotta_mi(f, slotlar)
		except Exception:
			frappe.log_error(title=f"Tek düğme: türev kontrolü {f.name}", message=frappe.get_traceback())
			sonuc, neden = "failed", "check_error"
		if sonuc == "already_ready":
			adim["ok"] += 1
		elif sonuc == "would_generate":
			bekleyen.append(f)
		elif sonuc == "skipped":
			adim["skipped"] += 1
			_neden(adim, neden)
		else:
			adim["failed"] += 1
			_neden(adim, neden or "failed")

	if dry:
		adim["changed"] = len(bekleyen)
		adim["state"] = "done"
		return

	from tradehub_core.media import pipeline_bridge

	kimlikler: dict[str, dict] = {}
	for f in bekleyen:
		kimlik = _is_kimligi(job_key, f"{f.file_url}|{f.owner}")
		frappe.enqueue(
			"tradehub_core.media.pipeline_bridge._run_rendition_job",
			queue=pipeline_bridge.RQ_QUEUE_BULK,
			timeout=pipeline_bridge.QUEUE_TIMEOUT_BULK_SECONDS,
			enqueue_after_commit=False,
			job_id=kimlik,
			deduplicate=True,
			file_url=f.file_url,
			file_name=f.name,
			force=True,
			backfill=True,
		)
		kimlikler[kimlik] = f
	adim["queued"] = len(kimlikler)
	_kaydet(durum)

	acik = list(kimlikler)
	bitis = time.monotonic() + TUREV_BEKLEME_SN
	while acik and time.monotonic() < bitis:
		if _durdu_mu(job_key):
			_bekleyenleri_iptal_et(acik)
			adim["message"] = _("Operatör durdurdu; kuyruktaki türev işleri iptal edildi.")
			adim["state"] = "stopped"
			break
		acik = [k for k in acik if not _is_bitti_mi(k)]
		adim["processed"] = len(kimlikler) - len(acik)
		_kilidi_tazele(job_key)
		_kaydet(durum)
		if acik:
			time.sleep(BEKLEME_ARALIGI_SN)
	if acik and adim["state"] != "stopped":
		_neden(adim, "timeout", len(acik))

	for kimlik, f in kimlikler.items():
		if kimlik in acik:
			adim["failed"] += 1
			continue
		sonuc, neden = _slotta_mi(f, slotlar)
		if sonuc == "already_ready":
			adim["changed"] += 1
		else:
			adim["failed"] += 1
			_neden(adim, "not_ready_after_generation")
	if adim["state"] != "stopped":
		adim["state"] = "partial" if adim["failed"] else "done"


_ADIM_FONKSIYONLARI = {
	"kare": _kare_adimi,
	"magaza": _magaza_adimi,
	"seo_ad": _seo_ad_adimi,
	"meta": _meta_adimi,
	"turev": _turev_adimi,
	"magaza_turev": _magaza_turev_adimi,
}


# ─── İş ─────────────────────────────────────────────────────────────────────


def run_job(job_key: str, dry_run: int = 1) -> None:
	"""Kuyruk girişi (`long`). Ortak kilit `start` ucunda `job_key` adına alındı."""
	durum = kosu(job_key) or _yeni_durum(job_key, bool(int(dry_run)))
	durum["dry_run"] = bool(int(dry_run))
	if not retro_rename.acquire_or_refresh_active(job_key):
		durum.update(state="error", message=_("Başka bir medya işi aktif; bu iş çalıştırılmadı."))
		durum["finished_at"] = str(now_datetime())
		_kaydet(durum)
		return
	try:
		durum["state"] = "running"
		_calistir(durum)
	except Exception:
		frappe.db.rollback()
		durum["state"] = "error"
		durum["message"] = _("İşlem tamamlanamadı.")
		adim = durum.get("current_step")
		if adim:
			_adim(durum, adim).update(state="error")
		frappe.log_error(title=f"Tek düğme optimize başarısız: {job_key}", message=frappe.get_traceback())
	finally:
		retro_rename.release_active(job_key)
		frappe.cache.delete_value(retro_rename._stop_key(job_key))
		retro_rename._clear_404_cache()
		durum["current_step"] = None
		durum["finished_at"] = str(now_datetime())
		_kaydet(durum)
	if not durum["dry_run"]:
		from tradehub_core.media import audit

		audit.log_media_batch(action=audit.ACTION_BULK, job_key=job_key, summary=_audit_ozeti(durum))


def _calistir(durum: dict) -> None:
	durum["current_step"] = "on_kontrol"
	_adim(durum, "on_kontrol")["state"] = "running"
	_kaydet(durum)
	if not _on_kontrol_adimi(durum) and not durum["dry_run"]:
		# Prova ön kontrol hatasında da tüm adımları sayar (ne olacağını görmek
		# için); gerçek koşu hiçbir şeye dokunmadan durur.
		durum["state"] = "error"
		durum["message"] = _("Ön kontrol başarısız: {0}").format(_adim(durum, "on_kontrol")["message"])
		for a in durum["steps"][1:]:
			a["state"] = "skipped"
		return
	for anahtar in ADIMLAR[1:]:
		adim = _adim(durum, anahtar)
		if _durdu_mu(durum["job_key"]):
			durum["state"] = "stopped"
			durum["message"] = _("Operatör durdurdu.")
			for kalan in durum["steps"]:
				if kalan["state"] == "pending":
					kalan["state"] = "skipped"
			return
		durum["current_step"] = anahtar
		adim["state"] = "running"
		_kaydet(durum)
		_ADIM_FONKSIYONLARI[anahtar](durum)
		_kaydet(durum)
		if adim["state"] == "stopped":
			durum["state"] = "stopped"
			durum["message"] = _("Operatör durdurdu.")
			for kalan in durum["steps"]:
				if kalan["state"] == "pending":
					kalan["state"] = "skipped"
			return
	hatali = any(a["state"] in ("partial", "error") or a["failed"] for a in durum["steps"][1:])
	if _adim(durum, "on_kontrol")["state"] == "error":
		hatali = True
	durum["state"] = "partial" if hatali else "completed"


def _audit_ozeti(durum: dict) -> dict:
	return {
		"operation": "urun_gorseli_optimize",
		"mode": durum.get("mode"),
		"state": durum.get("state"),
		"errors": sum(int(a.get("failed") or 0) for a in durum["steps"]),
		"steps": {
			a["key"]: {k: a.get(k) for k in ("state", "changed", "ok", "skipped", "failed")}
			for a in durum["steps"]
		},
	}


# ─── Geri alma — adımların kendi geri almaları, ters sırada ────────────────


def _geri_alma_anahtari(job_key: str, adim: str) -> str:
	return magaza_satir_anahtari(job_key) if adim == "magaza" else job_key


def run_rollback(job_key: str, rollback_key: str) -> None:
	"""Tersten: türev ve künye adımlarının geri alınacak yazısı yok (eski sürümler
	ve ölçüler kalıcı, bayat varlık arşivi kare satırlarında tutulur); önce mağaza,
	sonra kare adımı `kare.run_rollback` ile geri alınır (satır etiketleri ayrı).
	Kilit `rollback_key` adına ucu tarafından alındı; her `kare.run_rollback`
	aynı anahtarla sürdürüp bırakır, sonraki adım yeniden alır."""
	kaynak = kosu(job_key) or {}
	durum = kosu(rollback_key) or _yeni_durum(rollback_key, False, "rollback", source_job_key=job_key)
	durum["state"] = "running"
	_kaydet(durum)
	try:
		for anahtar in reversed(GERI_ALINABILIR):
			adim = _adim(durum, anahtar)
			durum["current_step"] = anahtar
			adim["state"] = "running"
			_kaydet(durum)
			retro_rename.acquire_or_refresh_active(rollback_key)
			kare.run_rollback(_geri_alma_anahtari(job_key, anahtar), rollback_key)
			sonuc = retro_rename.read_progress(rollback_key)
			adim.update(
				changed=int(sonuc.get("renamed") or 0),
				failed=int(sonuc.get("errors") or 0),
				reasons=dict(sonuc.get("skip_reasons") or {}),
				message=str(sonuc.get("message") or ""),
				state="error"
				if sonuc.get("state") == "error"
				else ("partial" if sonuc.get("errors") else "done"),
			)
			_kaydet(durum)
		durumlar = {a["state"] for a in durum["steps"]}
		durum["state"] = (
			"error" if "error" in durumlar else ("partial" if "partial" in durumlar else "completed")
		)
		if kaynak:
			kaynak["rolled_back_by"] = rollback_key
			_kaydet(kaynak)
	except Exception:
		frappe.db.rollback()
		retro_rename.release_active(rollback_key)
		durum["state"] = "error"
		durum["message"] = _("Geri alma tamamlanamadı.")
		frappe.log_error(title=f"Tek düğme geri alma başarısız: {job_key}", message=frappe.get_traceback())
	finally:
		retro_rename.release_active(rollback_key)
		durum["current_step"] = None
		durum["finished_at"] = str(now_datetime())
		_kaydet(durum)


# ─── Uçların çağırdığı iş mantığı ───────────────────────────────────────────


def _prova_gecerli_mi(prova_key: str) -> bool:
	prova = kosu(prova_key) if prova_key else None
	if not prova or not prova.get("dry_run") or prova.get("mode") != "optimize":
		return False
	if prova.get("state") not in ("completed", "partial") or not prova.get("finished_at"):
		return False
	return get_datetime(prova["finished_at"]) >= add_to_date(now_datetime(), hours=-PROVA_GECERLILIK_SAAT)


def baslat(dry_run: bool = True, prova_key: str = "") -> dict:
	if not dry_run:
		if not _prova_gecerli_mi(prova_key):
			frappe.throw(
				_("Önce Prova çalıştırın; gerçek iş yalnız son 24 saatteki bir provadan sonra başlar.")
			)
		hatali = [k["message"] for k in on_kontroller() if not k["ok"]]
		if hatali:
			frappe.throw(_("Ön kontrol başarısız: {0}").format("; ".join(hatali)))
	job_key = f"{JOB_PREFIX}{frappe.generate_hash(length=10)}"
	if not retro_rename.claim_active(job_key):
		frappe.throw(_("Zaten çalışan bir medya işi var; bitmesini bekleyin."))
	try:
		_kaydet(_yeni_durum(job_key, dry_run, prova_key=prova_key or None))
		frappe.enqueue(
			"tradehub_core.media.urun_gorseli_optimize.run_job",
			queue="long",
			timeout=4 * 3600,
			enqueue_after_commit=True,
			job_id=f"urun-gorseli-optimize::{job_key}",
			job_key=job_key,
			dry_run=int(bool(dry_run)),
		)
	except Exception:
		retro_rename.release_active(job_key)
		raise
	return {"job_key": job_key, "dry_run": bool(dry_run)}


def durdur(job_key: str) -> dict:
	if not kosu(job_key):
		frappe.throw(_("İş bulunamadı."))
	retro_rename.request_stop(job_key)
	return {"ok": True}


def geri_alinabilir(durum: dict | None) -> bool:
	if not durum or durum.get("dry_run") or durum.get("mode") != "optimize":
		return False
	if durum.get("state") not in TERMINAL or durum.get("rolled_back_by"):
		return False
	return any(
		a["key"] in GERI_ALINABILIR and int(a.get("changed") or 0) > 0 for a in durum.get("steps") or ()
	)


def geri_al(job_key: str) -> dict:
	kaynak = kosu(job_key)
	if not geri_alinabilir(kaynak):
		frappe.throw(_("Bu iş geri alınamaz (prova, bitmemiş, zaten geri alınmış ya da değişiklik yok)."))
	rollback_key = f"opt-rb-{frappe.generate_hash(length=10)}"
	if not retro_rename.claim_active(rollback_key):
		frappe.throw(_("Zaten çalışan bir medya işi var; bitmesini bekleyin."))
	try:
		_kaydet(_yeni_durum(rollback_key, False, "rollback", source_job_key=job_key))
		frappe.enqueue(
			"tradehub_core.media.urun_gorseli_optimize.run_rollback",
			queue="long",
			timeout=4 * 3600,
			enqueue_after_commit=True,
			job_key=job_key,
			rollback_key=rollback_key,
		)
	except Exception:
		retro_rename.release_active(rollback_key)
		raise
	return {"job_key": rollback_key, "source_job_key": job_key}


def durum_oku(job_key: str = "") -> dict[str, Any]:
	"""Tek koşu (ya da anahtar yoksa son koşu) + canlı alt ilerleme + son geri alınabilir iş."""
	kosular = _kosular()
	durum = kosu(job_key) if job_key else (kosular[0] if kosular else None)
	son_gercek = next((k for k in kosular if not k.get("dry_run") and k.get("mode") == "optimize"), None)
	cikti: dict[str, Any] = {
		"run": durum,
		"last_real": son_gercek,
		"rollback_available": geri_alinabilir(son_gercek),
		"kill_switch": bool(frappe.conf.get(KILL_SWITCH)),
	}
	if durum and durum.get("state") in ("queued", "running"):
		# Kare adımı ve kare geri alması ilerlemeyi Redis'e yazıyor; tabloya canlı ekle.
		if durum.get("current_step") in ("kare", "magaza"):
			cikti["live"] = retro_rename.read_progress(job_key or durum["job_key"])
	return cikti

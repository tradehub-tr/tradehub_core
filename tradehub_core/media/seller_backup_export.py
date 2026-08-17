"""Satıcı yedeğini indirilebilir pakete dönüştür (TUR-131).

Yedek sunucuda duruyor; satıcının onu kendi elinde tutabilmesi için tek dosyaya
paketlenmesi gerekiyor. "Yedeğim var" demek, yedeğe ULAŞABİLİYORSAN doğrudur.

**Pakette veritabanı YOKTUR.** İçinde üç şey var:

    dosyalar/<yol>   satıcının medya dosyaları, yedekteki hâliyle
    kunye.csv        satıcının KENDİ kayıtlarının okunabilir künyesi
    ozet.txt         ne zaman alındı, ne kadar, neler eksik

Ham veritabanı çıktısı bilerek verilmiyor: `File` tablosu tüm kiracıların
verisi ve iç işleyişe ait alanlar taşıyor. Satıcının ihtiyacı "hangi dosya
neydi, nerede kullanılıyordu" bilgisidir; onu CSV karşılıyor ve bir insan
okuyabiliyor.

Paketleme kuyrukta çalışır: dolu bir mağazanın medyası yüzlerce MB olabilir ve
istek bunu bekleyemez. Durum, paketin yanında bir dosyada tutulur — ayrı
düşerse yetim paket kalırdı (`media/jobs.py` §taşıma katmanları).
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import zipfile

import frappe

from tradehub_core.media import seller_backup

EXPORTS = "exports"

STATE_WORKING: str = "hazirlaniyor"
STATE_READY: str = "hazir"
STATE_ERROR: str = "hata"

# Bu kadar süredir "hazırlanıyor" görünen paket bırakılmış sayılır — worker
# ölmüşse kullanıcı sonsuza kadar bekleyemez, yeniden başlatabilmeli.
_STALE_HOURS: int = 2

# Paket, yedeğin kendisi kadar yer kaplıyor. Payla birlikte yer yoksa
# başlamamak, yarıda dolu diskle durmaktan iyidir.
_SPACE_MARGIN: float = 1.2

# Hazır paketler ne kadar dursun. İndirildikten sonra sunucuda tutmanın değeri
# yok; yedeğin kendisi zaten duruyor, paket yalnız taşıma biçimi.
_KEEP_HOURS: int = 24


def _exports_dir(store: str) -> str:
	yol = os.path.join(seller_backup._store_root(store), EXPORTS)
	os.makedirs(yol, exist_ok=True)
	return yol


def _check_id(store: str, set_id: str) -> str:
	"""Kimliği doğrula — kalıp ve kök kontrolü yedek modülünde, tek yerde.

	Doğrulamayı burada yeniden yazmak, iki kopyanın zamanla ayrışması demekti.
	"""
	seller_backup._set_path(store, set_id)
	return set_id


def _status_path(store: str, set_id: str) -> str:
	return os.path.join(_exports_dir(store), f"{_check_id(store, set_id)}.json")


def _package_name(set_id: str, token: str) -> str:
	return f"medya-yedegim-{set_id}-{token}.zip"


def _cok_eski(zaman: str | None) -> bool:
	if not zaman:
		return True
	try:
		return frappe.utils.time_diff_in_hours(frappe.utils.now(), zaman) > _STALE_HOURS
	except Exception:
		return True


def status(store: str, set_id: str) -> dict:
	"""Bu yedeğin paketi ne durumda — yoksa boş durum."""
	yol = _status_path(store, set_id)
	if not os.path.isfile(yol):
		return {"set_id": set_id, "state": "", "exists": False}

	try:
		d = seller_backup._oku(yol)
	except Exception:
		return {"set_id": set_id, "state": "", "exists": False}

	# Paket dosyası elle silinmiş ya da süresi dolmuş olabilir; "hazır" demeye
	# devam etmek kullanıcıyı çalışmayan bir indirme bağlantısına yollardı.
	if d.get("state") == STATE_READY:
		d["exists"] = os.path.isfile(os.path.join(_exports_dir(store), d.get("file_name") or ""))
		if not d["exists"]:
			d["state"] = ""
	else:
		d["exists"] = False

	d["stale"] = bool(d.get("state") == STATE_WORKING and _cok_eski(d.get("started")))
	return d


def _write_status(store: str, set_id: str, **alanlar) -> dict:
	mevcut = {}
	yol = _status_path(store, set_id)
	if os.path.isfile(yol):
		try:
			mevcut = seller_backup._oku(yol)
		except Exception:
			mevcut = {}
	mevcut.update({"set_id": set_id, **alanlar})
	seller_backup._yaz(yol, mevcut)
	return mevcut


def _drop_package(store: str, set_id: str) -> None:
	"""Varsa eski paketi kaldır — iki sürüm yan yana durmamalı."""
	d = status(store, set_id)
	ad = d.get("file_name")
	if ad:
		try:
			os.remove(os.path.join(_exports_dir(store), ad))
		except OSError:
			pass


def start(store: str, set_id: str) -> dict:
	"""Paketlemeyi kuyruğa at — hazırlık arkada sürer."""
	m = seller_backup.manifest_of(store, set_id)  # yoksa burada durur

	mevcut = status(store, set_id)
	if mevcut.get("state") == STATE_WORKING and not mevcut.get("stale"):
		frappe.throw(frappe._("Bu yedeğin paketi zaten hazırlanıyor."))

	istatistik = m.get("stats") or {}
	gereken = int(istatistik.get("total_bytes") or 0) * _SPACE_MARGIN
	bos = shutil.disk_usage(_exports_dir(store)).free
	if gereken and bos < gereken:
		frappe.throw(frappe._("Paket için yeterli disk alanı yok."))

	_drop_package(store, set_id)
	durum = _write_status(
		store,
		set_id,
		state=STATE_WORKING,
		started=frappe.utils.now(),
		finished=None,
		actor=frappe.session.user,
		done=0,
		total=int(istatistik.get("file_count") or 0),
		file_name=None,
		bytes=0,
		error=None,
	)

	frappe.enqueue(
		"tradehub_core.media.seller_backup_export.build",
		queue="long",
		timeout=1800,
		enqueue_after_commit=True,
		store=store,
		set_id=set_id,
		actor=frappe.session.user,
	)
	return durum


def build(store: str, set_id: str, actor: str = "") -> dict:
	"""Paketi üret — kuyruk işçisi buradan çağırır.

	Hata yutulmuyor ama ekran da sessiz bırakılmıyor: sorun durum dosyasına
	yazılıyor, kullanıcı "hazırlanıyor"da asılı kalmak yerine ne olduğunu
	görüyor.
	"""
	try:
		return _build(store, set_id, actor)
	except Exception as e:
		_write_status(
			store,
			set_id,
			state=STATE_ERROR,
			finished=frappe.utils.now(),
			error=str(e)[:500],
		)
		frappe.log_error(
			title=f"Satici medya yedegi paketlenemedi: {store}/{set_id}",
			message=frappe.get_traceback(with_context=True),
		)
		raise


def _build(store: str, set_id: str, actor: str) -> dict:
	m = seller_backup.manifest_of(store, set_id)
	kayitlar = seller_backup.records_of(store, set_id)

	token = frappe.generate_hash(length=10)
	ad = _package_name(set_id, token)
	hedef = os.path.join(_exports_dir(store), ad)
	gecici = f"{hedef}.partial"

	dosyalar = m.get("files") or []
	atlanan: list[str] = []
	yazilan = 0

	# Görseller zaten sıkıştırılmış; yeniden sıkıştırmak süreyi katlar, boyutu
	# neredeyse hiç düşürmez. Metin (CSV) küçük olduğu için fark etmez.
	with zipfile.ZipFile(gecici, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
		for i, d in enumerate(dosyalar, 1):
			blob = seller_backup._blob_path(store, d["hash"])
			if not os.path.isfile(blob):
				# Havuzda yoksa pakete konamaz. Sessizce atlamak paketi eksik
				# ama "tam" görünür yapardı; sayı özete yazılıyor.
				atlanan.append(d["path"])
				continue
			zf.write(blob, arcname=os.path.join("dosyalar", d["path"]))
			yazilan += 1
			if i % 50 == 0:
				_write_status(store, set_id, done=i)

		zf.writestr("kunye.csv", _kunye_csv(dosyalar, kayitlar))
		zf.writestr("ozet.txt", _ozet(m, kayitlar, yazilan, atlanan))

	os.replace(gecici, hedef)
	boyut = os.path.getsize(hedef)

	durum = _write_status(
		store,
		set_id,
		state=STATE_READY,
		finished=frappe.utils.now(),
		file_name=ad,
		bytes=boyut,
		done=len(dosyalar),
		skipped=len(atlanan),
		error=None,
	)

	from tradehub_core.media import audit

	audit.log_media_event(
		action=audit.ACTION_EXPORT,
		tenant=store,
		context={
			"set_id": set_id,
			"files": yazilan,
			"skipped": len(atlanan),
			"bytes": boyut,
			"actor": actor or frappe.session.user,
		},
	)
	return durum


def _kunye_csv(dosyalar: list[dict], kayitlar: list[dict]) -> str:
	"""Künye — DOSYA başına bir satır.

	Kayıt başına yazmak yanıltıyordu: aynı içerik birden çok kez yüklendiğinde
	tek fiziksel dosyaya birden çok `File` kaydı düşüyor (ölçüldü: 20 dosyaya
	27 kayıt, bir görsel 5 kez yüklenmiş). Künyede 27 satır görünce satıcı
	"20 dosyam vardı, 27 nereden çıktı" diyor — kütüphanesi de 20 gösteriyor.
	Omurga artık manifest'teki dosya listesi; kayıtlar onun ÜSTÜNE bindiriliyor.

	Ham veritabanı çıktısı DEĞİL: sütunlar satıcının anlayacağı şeyler. Kayıt
	kimlikleri yine de var — destek ekibiyle konuşulduğunda tek eşleşme noktası.
	"""
	adrese_gore: dict[str, list[dict]] = {}
	for r in kayitlar:
		adrese_gore.setdefault(r.get("file_url") or "", []).append(r)

	basliklar = [
		"Dosya adı",
		"Adres",
		"Boyut (bayt)",
		"İlk yüklenme",
		"Durum",
		"Başlık",
		"Alternatif metin",
		"Etiketler",
		"Kullanıldığı kayıtlar",
		"Kaç kez yüklenmiş",
		"Kayıt kimlikleri",
	]

	def _ilk(grup: list[dict], alan: str) -> str:
		"""Gruptaki ilk DOLU değer — kopyalardan biri boş bırakılmış olabilir."""
		for r in grup:
			if r.get(alan):
				return str(r[alan])
		return ""

	satirlar = []
	for d in dosyalar:
		grup = adrese_gore.get(d.get("file_url") or "", [])
		kullanim = sorted(
			{
				f"{r.get('attached_to_doctype')}: {r.get('attached_to_name')}"
				for r in grup
				if r.get("attached_to_doctype") and r.get("attached_to_name")
			}
		)
		satirlar.append(
			[
				_ilk(grup, "file_name") or os.path.basename(d.get("path") or ""),
				d.get("file_url") or "",
				d.get("size") or 0,
				min((r.get("creation") or "" for r in grup), default="") or "",
				_ilk(grup, "th_media_state"),
				_ilk(grup, "th_media_title"),
				_ilk(grup, "th_media_alt"),
				_ilk(grup, "th_media_tags"),
				" | ".join(kullanim),
				len(grup),
				" | ".join(r.get("name") or "" for r in grup),
			]
		)

	tampon = io.StringIO()
	# Excel Türkçe yerelde virgülü ayraç saymıyor; noktalı virgül kullanılıyor.
	yazici = csv.writer(tampon, delimiter=";", quoting=csv.QUOTE_MINIMAL)
	yazici.writerow(basliklar)
	yazici.writerows(satirlar)
	# BOM: Excel bu olmadan UTF-8 Türkçe karakterleri bozuk gösteriyor.
	return "﻿" + tampon.getvalue()


def _ozet(m: dict, kayitlar: list[dict], yazilan: int, atlanan: list[str]) -> str:
	istatistik = m.get("stats") or {}
	satirlar = [
		"MEDYA YEDEĞİ",
		"",
		f"Yedek kimliği : {m.get('set_id')}",
		f"Alındığı zaman: {m.get('created')}",
		f"Etiket        : {m.get('label') or '-'}",
		"",
		f"Dosya sayısı  : {istatistik.get('file_count', 0)}",
		f"Toplam boyut  : {_mb(int(istatistik.get('total_bytes') or 0))}",
		f"Pakete konan  : {yazilan}",
		"",
		f"Not: {len(kayitlar)} kayıt {istatistik.get('file_count', 0)} dosyaya işaret ediyor —",
		"     aynı görseli birden çok kez yüklediyseniz diskte tek kopya tutulur.",
		"",
		"İÇİNDEKİLER",
		"  dosyalar/   medya dosyalarınız, yedekteki hâliyle",
		"  kunye.csv   dosyaların künyesi (Excel ile açılabilir)",
		"",
		"Not: Bu pakette veritabanı çıktısı yoktur. Dosyalarınız ve künyeleri",
		"     yeterlidir; geri yükleme paneldeki yedek ekranından yapılır.",
	]
	if atlanan:
		satirlar += [
			"",
			f"UYARI: {len(atlanan)} dosya pakete konamadı (yedek deposunda bulunamadı):",
			*[f"  - {y}" for y in atlanan[:50]],
		]
		if len(atlanan) > 50:
			satirlar.append(f"  ... ve {len(atlanan) - 50} dosya daha")
	return "\n".join(satirlar) + "\n"


def _mb(bayt: int) -> str:
	return f"{bayt / (1024 * 1024):.1f} MB"


def package_path(store: str, set_id: str) -> str:
	"""İndirilecek paketin tam yolu — yoksa ya da hazır değilse durur."""
	d = status(store, set_id)
	if d.get("state") != STATE_READY or not d.get("file_name"):
		frappe.throw(frappe._("İndirilebilir bir paket yok."))

	kok = os.path.realpath(_exports_dir(store))
	tam = os.path.realpath(os.path.join(kok, d["file_name"]))
	# Dosya adı durum dosyasından geliyor; o dosya elle kurcalanmış olabilir.
	if not tam.startswith(kok + os.sep) or not os.path.isfile(tam):
		frappe.throw(frappe._("İndirilebilir bir paket yok."))
	return tam


def discard(store: str, set_id: str) -> dict:
	"""Paketi sunucudan kaldır — yedeğin kendisine DOKUNULMAZ."""
	_drop_package(store, set_id)
	_write_status(store, set_id, state="", file_name=None, bytes=0, finished=frappe.utils.now())
	return {"set_id": set_id, "state": ""}

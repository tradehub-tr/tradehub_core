"""Yedeği sunucudan dışarı çıkarma — dosyalar ve bilgileri tek pakette (TUR-131).

**Neden var.** Yedek, koruduğu medyayla AYNI DİSKTE duruyor. Disk giderse yedek
de gider; TUR-131'in karşılanmayan tek maddesi buydu. Paketi indirip başka bir
yere koyduğun anda yedek gerçekten ikinci bir yerde olur.

**Paket kendi kendine yeter.** İçinde yalnız dosyalar yok; her dosyanın kime
ait olduğu, imzası, boyutu, hangi belgeye bağlı olduğu da var. Sadece dosyaları
vermek işe yaramazdı: dosyalar geri gelir ama hangi mağazanın oldukları
kaybolur ve satıcı onları kütüphanesinde göremez. Geri yüklemede `owner`
alanının kaybolması tam olarak bu hataydı; dayanıklılık koşumu yakalamıştı.

**Arkada hazırlanır.** Dolu bir yedek ~1 GB. İsteğin içinde paketlemek hem
zaman aşımına uğrar hem belleği şişirir. İş kuyruğa atılır, ekran durumu sorar,
paket bitince indirme bağlantısı belirir.

**Paket yedek deposunun içine yazılır**, `private/files` altına DEĞİL. Oraya
yazılsaydı iki şey olurdu: bir sonraki yedek 1 GB'lık paketi de yedekler ve
depo her dışa aktarmada katlanarak büyürdü; ayrıca paket bir `File` kaydı
gerektirir, o kayıt da envantere düşerdi.

**Özel belgeler de pakete girer** (satıcı doğrulama evrakı dahil). Yedek onları
zaten kapsıyor; dışarıda bırakmak "yedeğim var" demeyi yalan yapardı. Karşılığı
şu: uç en yüksek yetkiye kilitli ve her dışa aktarma denetime yazılıyor.
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import zipfile
from datetime import datetime

import frappe

from tradehub_core.media import backup

EXPORTS = "exports"

# Hazır paket bu süre sonunda silinir. Paket yedeğin ikinci bir kopyası;
# sunucuda süresiz durması hem yer yer, hem de "dışarı çıksın" diye üretilen
# veriyi gereksiz yere sunucuda tutmak demek.
KEEP_HOURS: int = 48

# İlerleme bu sıklıkta diske yazılır. Her dosyada yazmak 4200 küçük yazma
# demekti; ekran zaten saniyede bir soruyor.
_PROGRESS_EVERY: int = 100

# Boş alan payı: görseller zaten sıkıştırılmış, paket kabaca yedeğin kendisi
# kadar yer kaplıyor. Yer yokken başlamak, yarım paket bırakıp diski doldururdu.
_SPACE_MARGIN: float = 1.15

# İş kuyruğa atılıp bir daha haber vermezse (kuyruk durmuş, süreç ölmüş) ekran
# sonsuza kadar "hazırlanıyor" gösterirdi. Bu süreden eskiyen bir hazırlık
# bayat sayılır ve yeniden başlatılabilir.
_STALE_HOURS: int = 3

STATE_WORKING: str = "hazirlaniyor"
STATE_READY: str = "hazir"
STATE_ERROR: str = "hata"


def _exports_dir() -> str:
	yol = os.path.join(backup._root(), EXPORTS)
	os.makedirs(yol, exist_ok=True)
	return yol


def _check_id(set_id: str) -> str:
	"""Kimliği doğrula — kalıp ve kök kontrolü yedek modülünde, tek yerde.

	Kimlik istekten geliyor ve dosya yoluna giriyor. Doğrulamayı burada
	yeniden yazmak, iki kopyanın zamanla ayrışması demekti.
	"""
	backup._set_path(set_id)
	return set_id


def _status_path(set_id: str) -> str:
	return os.path.join(_exports_dir(), f"{_check_id(set_id)}.json")


def _package_name(set_id: str, token: str) -> str:
	return f"medya-yedek-{set_id}-{token}.zip"


def status(set_id: str) -> dict:
	"""Bu yedeğin paketi ne durumda — yoksa boş durum."""
	yol = _status_path(set_id)
	if not os.path.isfile(yol):
		return {"set_id": set_id, "state": "", "exists": False}

	try:
		d = backup._oku(yol)
	except Exception:
		return {"set_id": set_id, "state": "", "exists": False}

	# Paket dosyası elle silinmiş olabilir; "hazır" demeye devam etmek
	# kullanıcıyı çalışmayan bir indirme bağlantısına yollardı.
	if d.get("state") == STATE_READY:
		d["exists"] = os.path.isfile(os.path.join(_exports_dir(), d.get("file_name") or ""))
		if not d["exists"]:
			d["state"] = ""
	else:
		d["exists"] = False

	d["stale"] = bool(d.get("state") == STATE_WORKING and _cok_eski(d.get("started")))
	return d


def _cok_eski(zaman: str | None) -> bool:
	if not zaman:
		return True
	try:
		gecen = frappe.utils.time_diff_in_hours(frappe.utils.now(), zaman)
	except Exception:
		return True
	return gecen > _STALE_HOURS


def _write_status(set_id: str, **alanlar) -> dict:
	mevcut = {}
	yol = _status_path(set_id)
	if os.path.isfile(yol):
		try:
			mevcut = backup._oku(yol)
		except Exception:
			mevcut = {}
	mevcut.update({"set_id": set_id, **alanlar})
	backup._yaz(yol, mevcut)
	return mevcut


def _drop_package(set_id: str) -> None:
	"""Bu yedeğe ait eski paketi sil — iki kopya tutmanın anlamı yok."""
	try:
		eski = backup._oku(_status_path(set_id))
	except Exception:
		return
	ad = eski.get("file_name")
	if ad:
		try:
			os.remove(os.path.join(_exports_dir(), ad))
		except OSError:
			pass


def start(set_id: str) -> dict:
	"""Paketlemeyi kuyruğa at — hazırlık arkada sürer.

	Doğrudan paketlemiyor: dolu bir yedek ~1 GB ve istek bunu bekleyemez.
	"""
	_check_id(set_id)
	m = backup.manifest_of(set_id)  # yoksa burada durur

	mevcut = status(set_id)
	if mevcut.get("state") == STATE_WORKING and not mevcut.get("stale"):
		frappe.throw(frappe._("Bu yedeğin paketi zaten hazırlanıyor."))

	istatistik = m.get("stats") or {}
	gereken = int(istatistik.get("total_bytes") or 0) * _SPACE_MARGIN
	bos = shutil.disk_usage(_exports_dir()).free
	if gereken and bos < gereken:
		frappe.throw(
			frappe._("Paket için yeterli disk alanı yok: {0} gerekiyor, {1} boş.").format(
				frappe.format_value(gereken, {"fieldtype": "Float"}),
				frappe.format_value(bos, {"fieldtype": "Float"}),
			)
		)

	_drop_package(set_id)
	durum = _write_status(
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
		"tradehub_core.media.backup_export.build",
		queue="long",
		timeout=3600,
		set_id=set_id,
		actor=frappe.session.user,
	)
	return durum


def build(set_id: str, actor: str = "") -> dict:
	"""Paketi üret — kuyruk işçisi buradan çağırır.

	Hata yutulmaz ama ekranı da sessiz bırakmaz: sorun durum dosyasına yazılır,
	kullanıcı "hazırlanıyor"da asılı kalmak yerine ne olduğunu görür.
	"""
	try:
		return _build(set_id, actor)
	except Exception as e:
		_write_status(
			set_id,
			state=STATE_ERROR,
			finished=frappe.utils.now(),
			error=str(e)[:500],
		)
		frappe.log_error(
			title=f"Medya yedegi paketlenemedi: {set_id}",
			message=frappe.get_traceback(with_context=True),
		)
		raise


def _build(set_id: str, actor: str) -> dict:
	m = backup.manifest_of(set_id)
	kayitlar = backup.records_of(set_id)

	token = frappe.generate_hash(length=10)
	ad = _package_name(set_id, token)
	hedef = os.path.join(_exports_dir(), ad)
	gecici = f"{hedef}.partial"

	dosyalar = m.get("files") or []
	atlanan: list[str] = []
	yazilan = 0

	# Görseller zaten sıkıştırılmış; onları yeniden sıkıştırmak süreyi katlar,
	# boyutu neredeyse hiç düşürmez. Metin listeleri ise çok iyi sıkışıyor.
	with zipfile.ZipFile(gecici, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
		for i, d in enumerate(dosyalar, 1):
			blob = backup._blob_path(d["hash"])
			if not os.path.isfile(blob):
				# Havuzda yoksa pakete konamaz. Sessizce atlamak paketi eksik
				# ama "tam" görünür yapardı; sayı özete yazılıyor.
				atlanan.append(f"{d['scope']}/{d['path']}")
				continue
			zf.write(blob, f"dosyalar/{d['scope']}/{d['path']}")
			yazilan += 1
			if i % _PROGRESS_EVERY == 0:
				_write_status(set_id, done=i, total=len(dosyalar))

		zf.writestr("dosya-listesi.csv", _dosya_csv(dosyalar), zipfile.ZIP_DEFLATED)
		zf.writestr("kayit-listesi.csv", _kayit_csv(kayitlar), zipfile.ZIP_DEFLATED)
		zf.writestr(
			"ozet.txt",
			_ozet(m, kayitlar, yazilan, atlanan, actor),
			zipfile.ZIP_DEFLATED,
		)

	os.replace(gecici, hedef)
	boyut = os.path.getsize(hedef)

	durum = _write_status(
		set_id,
		state=STATE_READY,
		finished=frappe.utils.now(),
		done=len(dosyalar),
		total=len(dosyalar),
		file_name=ad,
		bytes=boyut,
		files=yazilan,
		records=len(kayitlar),
		skipped=len(atlanan),
		error=None,
	)

	from tradehub_core.media import audit

	audit.log_media_event(
		action=audit.ACTION_EXPORT,
		# Paket özel belgeleri de içeriyor; denetimde sıradan bir okuma gibi
		# görünmemeli.
		sensitive=True,
		context={
			"set_id": set_id,
			"files": yazilan,
			"records": len(kayitlar),
			"skipped": len(atlanan),
			"bytes": boyut,
			"actor": actor or frappe.session.user,
		},
	)
	return durum


def _csv_metni(basliklar: list[str], satirlar: list[list]) -> str:
	"""CSV metni üret — Excel'in Türkçe karakterleri bozmaması için BOM ile.

	BOM olmadan Excel dosyayı yerel kod sayfasıyla açıyor ve "Görüntü" gibi
	adlar bozuk çıkıyor. Liste okunamıyorsa paketin yarısı işe yaramaz.
	"""
	tampon = io.StringIO()
	yazici = csv.writer(tampon, lineterminator="\n")
	yazici.writerow(basliklar)
	yazici.writerows(satirlar)
	return "﻿" + tampon.getvalue()


def _dosya_csv(dosyalar: list[dict]) -> str:
	satirlar = [
		[
			d.get("scope") or "",
			d.get("path") or "",
			d.get("hash") or "",
			d.get("size") or 0,
			_zaman(d.get("mtime")),
		]
		for d in dosyalar
	]
	return _csv_metni(
		["kapsam", "yol", "imza", "boyut_bayt", "son_degisim"],
		satirlar,
	)


def _kayit_csv(kayitlar: list[dict]) -> str:
	"""Kayıt listesi — dosyanın kime ait olduğu burada.

	Mağaza kullanıcıdan türetiliyor ve türetme kullanıcı başına bir kez
	yapılıyor: 4900 satır için satır başına sorgu 4900 sorgu demekti, oysa
	farklı yükleyen sayısı onlarla ölçülüyor.
	"""
	magaza_of: dict[str, str] = {}
	magaza_adi: dict[str, str] = {}

	def _magaza(kullanici: str) -> tuple[str, str]:
		if not kullanici:
			return "", ""
		if kullanici not in magaza_of:
			from tradehub_core.media import ownership

			try:
				kod = ownership.store_of(kullanici) or ""
			except Exception:
				kod = ""
			magaza_of[kullanici] = kod
			if kod and kod not in magaza_adi:
				magaza_adi[kod] = (
					frappe.db.get_value("Admin Seller Profile", kod, "seller_name") or ""
				)
		kod = magaza_of[kullanici]
		return kod, magaza_adi.get(kod, "")

	satirlar = []
	for r in kayitlar:
		kod, isim = _magaza(r.get("owner") or "")
		satirlar.append(
			[
				r.get("file_url") or "",
				r.get("file_name") or "",
				r.get("owner") or "",
				kod,
				isim,
				r.get("content_hash") or "",
				r.get("file_size") or 0,
				"evet" if r.get("is_private") else "hayır",
				r.get("th_media_state") or "",
				r.get("th_media_title") or "",
				r.get("th_media_alt") or "",
				r.get("th_media_tags") or "",
				r.get("th_media_width") or "",
				r.get("th_media_height") or "",
				r.get("attached_to_doctype") or "",
				r.get("attached_to_name") or "",
				r.get("creation") or "",
			]
		)

	return _csv_metni(
		[
			"adres",
			"dosya_adi",
			"yukleyen",
			"sahip_magaza",
			"magaza_adi",
			"imza",
			"boyut_bayt",
			"ozel_mi",
			"durum",
			"baslik",
			"alt_metin",
			"etiketler",
			"genislik",
			"yukseklik",
			"bagli_belge_turu",
			"bagli_belge",
			"yuklenme",
		],
		satirlar,
	)


def _zaman(damga) -> str:
	if not damga:
		return ""
	try:
		return datetime.fromtimestamp(int(damga)).strftime("%Y-%m-%d %H:%M:%S")
	except (ValueError, OSError, TypeError):
		return ""


def _mb(bayt: int) -> str:
	return f"{(bayt or 0) / 1024 / 1024:.1f} MB"


def _ozet(m: dict, kayitlar: list[dict], yazilan: int, atlanan: list[str], actor: str) -> str:
	"""Paketin içindeki okunabilir künye.

	Paket aylar sonra başka bir makinede açılabilir. O anda "bu ne, ne zaman
	alındı, içinde ne var" sorusunun cevabı paketin İÇİNDE olmalı; dosya adına
	güvenmek yetmez, ad değişebilir.
	"""
	istatistik = m.get("stats") or {}
	ozel = sum(1 for r in kayitlar if r.get("is_private"))

	satirlar = [
		"İSTOÇ MEDYA YEDEĞİ — DIŞA AKTARMA",
		"=" * 52,
		"",
		f"Yedek kimliği   : {m.get('set_id')}",
		f"Yedeğin alındığı: {m.get('created')}",
		f"Etiket          : {m.get('label') or '—'}",
		f"Site            : {m.get('site')}",
		f"Paketlendiği an : {frappe.utils.now()}",
		f"Paketleyen      : {actor or frappe.session.user}",
		"",
		"İÇERİK",
		"  dosyalar/          Görsellerin ve belgelerin kendisi",
		"  dosya-listesi.csv  Her dosyanın yolu, imzası, boyutu",
		"  kayit-listesi.csv  Her dosyanın adresi, SAHİP MAĞAZASI, imzası, tarihi",
		"",
		"SAYILAR",
		f"  Yedekteki dosya : {istatistik.get('file_count') or 0}",
		f"  Pakete giren    : {yazilan}",
		f"  Pakete girmeyen : {len(atlanan)}",
		f"  Kayıt           : {len(kayitlar)}",
		f"  Toplam boyut    : {_mb(istatistik.get('total_bytes') or 0)}",
		"",
		"UYARI",
		f"  Bu paket ÖZEL BELGELER de içeriyor ({ozel} kayıt) — satıcı doğrulama",
		"  evrakı gibi. Güvenli bir yerde saklayın, paylaşmayın.",
	]

	if atlanan:
		satirlar += [
			"",
			"PAKETE GİRMEYENLER (içeriği depoda bulunamadı)",
			*[f"  {a}" for a in atlanan[:200]],
		]
		if len(atlanan) > 200:
			satirlar.append(f"  … ve {len(atlanan) - 200} tane daha")

	return "\n".join(satirlar) + "\n"


def package_path(set_id: str) -> str:
	"""İndirilecek paketin tam yolu — hazır değilse açıkça reddedilir."""
	d = status(set_id)
	if d.get("state") != STATE_READY or not d.get("file_name"):
		frappe.throw(frappe._("Bu yedeğin hazır bir paketi yok."))

	kok = os.path.realpath(_exports_dir())
	tam = os.path.realpath(os.path.join(kok, d["file_name"]))
	# Durum dosyası diskte duruyor; elle değiştirilirse ad da değişebilir.
	# Kök kontrolü olmadan bu, sunucudaki herhangi bir dosyayı indirmenin yolu
	# olurdu — yedek kimliğindeki yol kaçışıyla aynı hata.
	if not tam.startswith(kok + os.sep) or not os.path.isfile(tam):
		frappe.throw(frappe._("Paket bulunamadı."))
	return tam


def discard(set_id: str) -> dict:
	"""Hazır paketi sunucudan kaldır — indirdikten sonra tutmaya gerek yok."""
	_drop_package(set_id)
	yol = _status_path(set_id)
	if os.path.isfile(yol):
		os.remove(yol)
	return {"set_id": set_id, "state": ""}


def cleanup(*, hours: int | None = None) -> dict:
	"""Süresi geçen paketleri sil — günlük görev buradan çağırır.

	Paketler yedeğin ikinci kopyası; birikirlerse depo iki katına çıkar.

	`hours=None` yapılandırılmış süreyi kullanır. `hours=0` "hepsi dolmuş
	say" demektir; sıfırı "varsayılanı kullan" diye okumak, hepsini silmek
	isteyen çağrıya sessizce hiçbir şey yapmazdı.
	"""
	sinir = KEEP_HOURS if hours is None else max(0, int(hours))
	kok = _exports_dir()
	silinen = 0
	kazanilan = 0

	for ad in os.listdir(kok):
		if not ad.endswith(".json"):
			continue
		set_id = ad[:-5]
		try:
			d = backup._oku(os.path.join(kok, ad))
		except Exception:
			continue

		damga = d.get("finished") or d.get("started")
		if damga and frappe.utils.time_diff_in_hours(frappe.utils.now(), damga) < sinir:
			continue

		paket = d.get("file_name")
		if paket:
			try:
				p = os.path.join(kok, paket)
				kazanilan += os.path.getsize(p)
				os.remove(p)
				silinen += 1
			except OSError:
				pass
		try:
			os.remove(os.path.join(kok, ad))
		except OSError:
			pass
		frappe.logger().info(f"Medya yedek paketi suresi doldu, silindi: {set_id}")

	# Yarım kalmış paketler: işçi ölürse `.partial` kalır ve yer tutar.
	for ad in os.listdir(kok):
		if not ad.endswith(".partial"):
			continue
		try:
			p = os.path.join(kok, ad)
			kazanilan += os.path.getsize(p)
			os.remove(p)
			silinen += 1
		except OSError:
			pass

	return {"removed": silinen, "freed_bytes": kazanilan}

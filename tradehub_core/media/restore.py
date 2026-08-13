"""Medya geri yükleme — önce plan, sonra uygulama (TUR-131).

Geri yükleme yedeklemeden daha tehlikeli bir iştir: yanlış çalışırsa bugünkü
veriyi dünkiyle ezer. Bu yüzden burada üç kural var ve hiçbiri isteğe bağlı
değil:

**1. Önce plan.** `plan()` hiçbir şeye dokunmadan ne olacağını satır satır
söyler. Uygulama ayrı bir çağrı; kimse yanlışlıkla geri yükleme başlatamaz.

**2. Asla silmez.** Yedekte olmayan ama bugün var olan bir dosya `extra` diye
işaretlenir ve DOKUNULMAZ. Yedekten sonra yüklenmiş yeni dosyaları silmek,
"geri yükleme" adı altında veri kaybı olurdu.

**3. Değişmiş dosyanın üzerine yazmaz.** Aynı yolda farklı içerik varsa bu bir
ÇATIŞMADIR (`conflict`), sessizce çözülmez. Dosya optimize edilmiş ya da
değiştirilmiş olabilir; yedekteki eski hâlini geri yazmak sessiz bir gerileme
demektir. Ancak `overwrite=True` ile ve açıkça istenerek yazılır.

Durum sınıfları:

    ok             yol var, içerik yedekle aynı            → dokunma
    missing_file   kayıt/yedek var, dosya diskte yok       → geri yaz
    conflict       yol var ama içerik farklı               → sorma olmadan dokunma
    missing_record dosya var, `File` kaydı yok             → kaydı yeniden kur
    extra          bugün var, yedekte yok                  → dokunma

Dosya ile kayıt AYRI ele alınıyor çünkü ayrı kaybolabiliyorlar: dosya silinip
kayıt kalabilir (üründe kırık görsel), kayıt silinip dosya kalabilir (diskte
sahipsiz dosya). İkisinin de karşılığı var.
"""

from __future__ import annotations

import os
import shutil

import frappe

from tradehub_core.media import backup

# Kayıt yeniden kurulurken yazılmayacak alanlar: bunlar Frappe'nin kendi
# yönettiği ya da yeniden hesaplanması gereken alanlar.
_SKIP_ON_INSERT: frozenset[str] = frozenset({"modified"})


def _target_root(scope: str) -> str:
	return (
		frappe.get_site_path("public", "files")
		if scope == "public"
		else frappe.get_site_path("private", "files")
	)


def _live_path(scope: str, rel: str) -> str:
	return os.path.join(_target_root(scope), rel)


def plan(set_id: str) -> dict:
	"""Ne olacağını söyle — HİÇBİR ŞEYE DOKUNMA.

	Kabul kriteri "geri yükleme senaryosu test edilebilir şekilde tarif
	edilmiş olmalı" diyor. Bu fonksiyon o tarifin kendisi: çalıştırmadan
	sonucu görebiliyorsan senaryo test edilebilir demektir.
	"""
	m = backup.manifest_of(set_id)
	kayitlar = backup.records_of(set_id)

	ok: list[str] = []
	eksik_dosya: list[dict] = []
	catisma: list[dict] = []

	yedekteki_yollar: set[tuple[str, str]] = set()
	for d in m["files"]:
		yedekteki_yollar.add((d["scope"], d["path"]))
		canli = _live_path(d["scope"], d["path"])
		if not os.path.isfile(canli):
			eksik_dosya.append({"scope": d["scope"], "path": d["path"], "size": d["size"]})
			continue
		# Boyut farklıysa imza hesaplamaya gerek yok — kesin farklı.
		if os.path.getsize(canli) != d["size"] or backup.file_hash(canli) != d["hash"]:
			catisma.append({"scope": d["scope"], "path": d["path"]})
			continue
		ok.append(d["path"])

	# Bugün var, yedekte yok — DOKUNULMAYACAK, yalnız raporlanacak
	fazla: list[dict] = []
	for scope, kok in backup._media_dirs():
		if not os.path.isdir(kok):
			continue
		for dizin, _alt, dosyalar in os.walk(kok):
			for ad in dosyalar:
				rel = os.path.relpath(os.path.join(dizin, ad), kok)
				if (scope, rel) not in yedekteki_yollar:
					fazla.append({"scope": scope, "path": rel})

	# Kayıt tarafı
	mevcut_kayitlar = set(frappe.get_all("File", pluck="name", limit_page_length=0))
	eksik_kayit = [r for r in kayitlar if r.get("name") not in mevcut_kayitlar]

	return {
		"set_id": set_id,
		"created": m.get("created"),
		"ok": len(ok),
		"missing_file": eksik_dosya,
		"missing_file_count": len(eksik_dosya),
		"conflict": catisma,
		"conflict_count": len(catisma),
		"extra": fazla[:200],
		"extra_count": len(fazla),
		"missing_record": [
			{"name": r["name"], "file_url": r.get("file_url")} for r in eksik_kayit[:200]
		],
		"missing_record_count": len(eksik_kayit),
		# Hiçbir şey yapılmadı; bu yalnız rapor.
		"applied": False,
	}


def apply(
	set_id: str,
	*,
	files: bool = True,
	records: bool = True,
	overwrite: bool = False,
	only: list[str] | None = None,
) -> dict:
	"""Planı uygula.

	`overwrite=False` (varsayılan): içeriği değişmiş dosyalara DOKUNULMAZ.
	`only`: yalnız belirtilen yolları geri yükle — tek bir dosyayı kurtarmak
	için tüm yedeği uygulamak gerekmesin.

	Hiçbir durumda dosya ya da kayıt SİLİNMEZ.
	"""
	m = backup.manifest_of(set_id)
	istenen = set(only or [])

	yazilan: list[str] = []
	uzerine: list[str] = []
	atlanan_catisma: list[str] = []

	if files:
		for d in m["files"]:
			if istenen and d["path"] not in istenen:
				continue
			blob = backup._blob_path(d["hash"])
			if not os.path.isfile(blob):
				# Havuzda yoksa geri yüklenemez; `verify` bunu önceden söyler.
				continue

			canli = _live_path(d["scope"], d["path"])
			if os.path.isfile(canli):
				ayni = (
					os.path.getsize(canli) == d["size"] and backup.file_hash(canli) == d["hash"]
				)
				if ayni:
					continue
				if not overwrite:
					atlanan_catisma.append(d["path"])
					continue
				uzerine.append(d["path"])

			os.makedirs(os.path.dirname(canli), exist_ok=True)
			gecici = f"{canli}.restoring"
			shutil.copy2(blob, gecici)
			os.replace(gecici, canli)
			yazilan.append(d["path"])

	kurulan_kayit: list[str] = []
	if records:
		kayitlar = backup.records_of(set_id)
		mevcut = set(frappe.get_all("File", pluck="name", limit_page_length=0))
		for r in kayitlar:
			ad = r.get("name")
			if not ad or ad in mevcut:
				continue
			if istenen and r.get("file_url", "").split("/")[-1] not in istenen:
				continue
			try:
				doc = frappe.get_doc(
					{
						"doctype": "File",
						**{k: v for k, v in r.items() if k not in _SKIP_ON_INSERT and v is not None},
					}
				)
				# Dosya zaten diskte; Frappe'nin yeniden yazmasına gerek yok.
				doc.flags.ignore_file_validate = True
				doc.insert(ignore_permissions=True, set_name=ad)

				# SAHİP VE OLUŞTURMA ZAMANI GERİ YAZILIYOR.
				#
				# Frappe kayıt eklerken `owner` alanını oturumdaki kullanıcıyla
				# eziyor. Sonuç sessiz ve ağırdı: geri yüklenen dosyanın sahibi
				# yönetici oluyor, sahiplik yükleyenden türetildiği için dosya
				# hiçbir mağazaya ait olmuyor ve SATICI onu kütüphanesinde
				# GÖREMİYORDU. Yani "geri yükledim" denen işlem, dosyayı
				# sahibinden koparıyordu.
				#
				# Dayanıklılık koşumu yakaladı; kabul kriteri "dosya ve metadata
				# bütünlüğü korunmalı" tam olarak bunu istiyor.
				geri_yaz = {
					alan: r[alan]
					for alan in ("owner", "creation")
					if r.get(alan)
				}
				if geri_yaz:
					frappe.db.set_value("File", ad, geri_yaz, update_modified=False)

				kurulan_kayit.append(ad)
			except Exception as e:
				frappe.log_error(
					title=f"Media restore: kayit kurulamadi {ad}",
					message=f"{e}\n{frappe.get_traceback(with_context=True)}",
				)

	frappe.db.commit()

	from tradehub_core.media import audit

	audit.log_media_event(
		action=audit.ACTION_RESTORE,
		context={
			"set_id": set_id,
			"files_written": len(yazilan),
			"overwritten": len(uzerine),
			"conflicts_skipped": len(atlanan_catisma),
			"records_created": len(kurulan_kayit),
			"overwrite_allowed": bool(overwrite),
		},
	)

	return {
		"set_id": set_id,
		"files_written": len(yazilan),
		"overwritten": uzerine[:50],
		"overwritten_count": len(uzerine),
		"conflicts_skipped": atlanan_catisma[:50],
		"conflicts_skipped_count": len(atlanan_catisma),
		"records_created": len(kurulan_kayit),
		"applied": True,
	}


def repair_missing_files(set_id: str | None = None) -> dict:
	"""Kaydı olup dosyası kaybolanları en yeni yedekten geri getir.

	Felaket kurtarmanın en sık hâli bu: veritabanı sağlam ama diskten dosya
	gitmiş. Ürün kaydı görseli gösteriyor, görsel yok. Tüm yedeği uygulamaya
	gerek yok, yalnız eksikler yazılır.
	"""
	if not set_id:
		setler = backup.list_sets()
		if not setler:
			frappe.throw(frappe._("Hiç yedek yok."))
		set_id = setler[0]["set_id"]

	p = plan(set_id)
	eksikler = [d["path"] for d in p["missing_file"]]
	if not eksikler:
		return {"set_id": set_id, "missing": 0, "restored": 0}

	sonuc = apply(set_id, files=True, records=False, only=eksikler)
	return {"set_id": set_id, "missing": len(eksikler), "restored": sonuc["files_written"]}

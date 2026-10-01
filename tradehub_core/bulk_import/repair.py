"""Silinmiş Bulk Import Job başlıklarını ilanlardan geri yazar (MOGEM-981).

Eski temizlik görevi job'ları `force=True` ile siliyordu; `Listing.created_by_bulk_job` var olmayan
bir job'ı gösterdiği için o ilanlar artık kaydedilemiyordu (417). Bağlantıyı boşaltmak ilanın
kaynak bilgisini kalıcı yok ederdi (panel rozeti, "toplu yüklemeyle gelenler" süzgeci); onun
yerine job aynı adla, ilanlardan çıkarılabilen bilgiyle yeniden yazılır. Satıcı için bu doğru bir
geçmiş kaydıdır; onarım notu yalnız iç alanda (`error_summary`) durur, panelde gösterilmez.

İdempotent: yalnız hâlâ yetim olan bağlantılar işlenir. İlanlara dokunulmaz.
"""

from __future__ import annotations

import frappe
from frappe.query_builder.functions import Count, Max, Min
from frappe.utils import now_datetime

REPAIR_NOTE = (
	"MOGEM-981: başlık {tarih} tarihinde ilanlardan geri yazıldı; dosya ve hata ayrıntıları saklanmadı."
)


def restore_orphan_jobs() -> dict[str, int]:
	result = {"onarildi": 0, "atlandi": 0, "ilan": 0}
	for row in find_orphan_jobs():
		if row.satici_sayisi != 1:
			# Hangi satıcıya ait olduğunu bilmediğimiz job'ı yazarsak bir satıcının geçmişine
			# başkasının kaydı düşer; tahmin etmek yerine raporlanır.
			_log_skip(row, f"{row.satici_sayisi} farklı satıcının ilanı bağlı")
			result["atlandi"] += 1
			continue
		try:
			_restore(row)
		except Exception as e:
			# Patch migrate içinde koşar; tek bir job'ın hatası (ör. satıcı profili silinmiş)
			# deploy'u durdurmamalı. Atlananlar Error Log'da adıyla durur.
			frappe.db.rollback()
			_log_skip(row, str(e)[:500])
			result["atlandi"] += 1
			continue
		frappe.db.commit()
		result["onarildi"] += 1
		result["ilan"] += row.ilan
	return result


def find_orphan_jobs() -> list[frappe._dict]:
	listing, job = frappe.qb.DocType("Listing"), frappe.qb.DocType("Bulk Import Job")
	ref = listing.created_by_bulk_job
	query = (
		frappe.qb.from_(listing)
		.left_join(job)
		.on(job.name == ref)
		.select(
			ref.as_("job"),
			Count("*").as_("ilan"),
			Count(listing.seller_profile).distinct().as_("satici_sayisi"),
			Min(listing.seller_profile).as_("satici"),
			Min(listing.creation).as_("ilk"),
			Max(listing.creation).as_("son"),
		)
		.where(ref.isnotnull() & (ref != "") & job.name.isnull())
		.groupby(ref)
		.orderby(ref)
	)
	return query.run(as_dict=True)


def _restore(row: frappe._dict) -> None:
	doc = frappe.get_doc(
		{
			"doctype": "Bulk Import Job",
			"seller_profile": row.satici,
			"source": "file",
			"status": "Completed",
			"started_at": row.ilk,
			"completed_at": row.son,
			"total_rows": row.ilan,
			"inserted_count": row.ilan,
			"error_summary": REPAIR_NOTE.format(tarih=now_datetime().strftime("%d.%m.%Y")),
			"artifacts_purged_at": now_datetime(),
		}
	)
	# `data_file` ve `file_format` zorunlu ama kaynak dosya silindi, biçimi de bilinmiyor; uydurmak
	# yerine boş bırakılır. Tamamlanmış job bir daha `save()` edilmiyor (runner yalnız kuyruktakini
	# koşar), indirme/yeniden deneme uçları da `artifacts_purged_at` ile kapalı.
	doc.flags.ignore_mandatory = True
	# Sistem onarımı: oturumda satıcı yok, `seller_profile` ilanlardan açıkça veriliyor.
	doc.insert(set_name=row.job, ignore_permissions=True)
	# Geçmiş ekranı tarihe göre sıralar; kayıt bugünün değil, yüklemenin tarihinde görünmeli.
	frappe.db.set_value(
		"Bulk Import Job", doc.name, {"creation": row.ilk, "modified": row.son}, update_modified=False
	)
	_keep_series_ahead(doc.name)


def _keep_series_ahead(name: str) -> None:
	"""Seri sayacını geri yazılan numaranın gerisinde bırakma.

	Frappe, serinin son kaydı silinince sayacı bir geri alır (`revert_series_if_last`). Tüm job'ları
	silinmiş bir ortamda sayaç geri yazdığımız numaraya düşmüş olabilir; o zaman satıcının bir
	sonraki yüklemesi aynı adı alıp `DuplicateEntryError` ile düşer.
	"""
	prefix, _, number = name.rpartition("-")
	if not number.isdigit():
		return
	prefix, number = f"{prefix}-", int(number)
	series = frappe.qb.Table("tabSeries")
	current = frappe.qb.from_(series).select(series.current).where(series.name == prefix).run()
	if not current:
		frappe.qb.into(series).columns(series.name, series.current).insert(prefix, number).run()
	elif current[0][0] < number:
		frappe.qb.update(series).set(series.current, number).where(series.name == prefix).run()


def _log_skip(row: frappe._dict, reason: str) -> None:
	frappe.log_error(
		title=f"MOGEM-981 onarım atlandı: {row.job}",
		message=f"{row.ilan} ilan bağlı; sebep: {reason}",
	)

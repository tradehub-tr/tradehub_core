"""DALGA A / A1a — Medya motoru çekirdek DocType'larını kur.

Dört DocType: Media Profile, Media Asset, Media Rendition, Media Processing Job.
Şema kaynağı `tradehub_core/media/pipeline/doctype_specs/*.json` (16 spec'in
4'ü); diğer 12'si (Media Policy, Media Source, Media Version, Media Crop Intent,
...) bu dalgada KURULMAZ.

Neden ayrı bir patch: `bench migrate` yeni DocType JSON'larını zaten yükler.
Bu patch iki şey daha yapar ve ikisi de sessiz başarısızlığı kapatır:

  1. Yükleme sırasını GARANTİLER. Media Rendition, `asset` ve `profile`
     Link'leriyle Media Asset ve Media Profile'a bağlıdır; Media Processing Job
     `asset` ile Media Asset'e. Migrate dosya sırasını alfabetik gezerse
     `media_processing_job` (p) `media_rendition`dan (r) önce gelir ama
     `media_profile` (pro) `media_processing_job`dan (proc) sonra gelir —
     Link hedefi henüz yokken DocType kaydı düşer.
  2. Kurulumu DOĞRULAR. Tablolar gerçekten oluşmadıysa patch hata verir;
     "migrate geçti ama tablo yok" durumu sessizce üretime çıkmaz.

Idempotent: `reload_doc` her çalıştırmada aynı JSON'u yeniden okur, yeniden
uygular ve veri yazmaz. Patch ikinci kez koşarsa hiçbir şey değişmez.

Bayrak notu: bu patch yalnız ŞEMA kurar. Yeni hattın DAVRANIŞI
`media_pipeline_enabled` bayrağı arkasındadır ve bayrak kapalıyken bu tablolara
hiçbir şey yazılmaz — mevcut medya akışı (engine.to_webp, transcode,
media/states.py, media/audit.py) DEĞİŞMEDİ.
"""

from __future__ import annotations

import frappe
from frappe import _

# Link bağımlılığı sırası: önce hedefler, sonra onlara bağlananlar.
_DOCTYPES: tuple[tuple[str, str], ...] = (
	("media_profile", "Media Profile"),
	("media_asset", "Media Asset"),
	("media_rendition", "Media Rendition"),
	("media_processing_job", "Media Processing Job"),
)


def execute() -> dict:
	"""Dört çekirdek DocType'ı yükler ve tablolarının varlığını doğrular."""
	yuklenen: list[str] = []
	for dizin, ad in _DOCTYPES:
		frappe.reload_doc("tradehub_core", "doctype", dizin, force=True)
		yuklenen.append(ad)

	eksik: list[str] = [ad for _, ad in _DOCTYPES if not frappe.db.table_exists(ad)]
	if eksik:
		# Sessiz geçmek en kötü sonuç: şemasız bir hat, ilk yazmada patlar.
		frappe.throw(
			_(
				"Medya motoru DocType tabloları oluşmadı: {}. "
				"DocType JSON'larını ve modül adını (Tradehub Core) kontrol edin."
			).format(", ".join(eksik))
		)

	frappe.db.commit()
	return {"loaded": yuklenen, "missing": eksik}

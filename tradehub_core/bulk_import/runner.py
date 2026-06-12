"""Bulk import runner — frappe.enqueue target.

Parse → validate → persist → progress → notify döngüsü.
`frappe.flags.in_bulk_import = True` ile ECA bulk-only filter'ı aktive eder.
"""

import json
import re

import frappe
from frappe import _
from frappe.utils import now, time_diff_in_seconds

from tradehub_core.bulk_import import (
	image_matcher,
	image_url_ingest,
	notifications,
	persister,
	validator,
	value_mapping,
)
from tradehub_core.bulk_import.ingestion import profile_store, resolver
from tradehub_core.bulk_import.parsers import csv_parser, xlsx_parser, xml_parser
from tradehub_core.eca.dispatcher import ECARejectionError

PROGRESS_CACHE_TTL = 3600  # 1 saat
COMMIT_CHUNK_SIZE = 25
MAX_IMAGES_PER_PRODUCT = 10  # plan #1 limiti (ZIP + URL birleşik)

# parent_data içinde uzak görsel URL'i taşıyabilen canonical alan(lar). Tek hücrede
# virgülle çoklu URL olabilir; ayrıca resolver çoklu görsel kolonunu (Image #1/#2/#3)
# primary_image + image_2..image_N slotlarına dağıtır (bkz. resolver._next_image_slot).
_IMAGE_URL_FIELDS = ("primary_image", *(f"image_{i}" for i in range(2, 11)))


def _collect_image_urls(parent_data: dict) -> list[str]:
	"""parent_data'dan http(s) ile başlayan uzak görsel URL'lerini topla.

	Tek bir hücrede virgülle ayrılmış birden çok URL bulunabilir (galeri).
	parent_data'dan ham URL alanı POP edilir — aksi halde uzak URL persister'da
	setattr ile Listing.primary_image'a geri yazılır; biz onun yerine indirilen
	yerel File URL'lerini listing_images olarak geçiriyoruz.
	"""
	urls: list[str] = []
	for field in _IMAGE_URL_FIELDS:
		raw = parent_data.pop(field, None)
		if not raw or not isinstance(raw, str):
			continue
		for part in raw.split(","):
			candidate = part.strip()
			if candidate.lower().startswith(("http://", "https://")):
				urls.append(candidate)
	return urls


def _resolve_images(
	parent_data: dict,
	sku_key: str,
	images_idx: dict[str, list[str]],
	seller_profile: str,
	warnings: list[str],
) -> list[str]:
	"""Satır için nihai görsel listesini üret: ZIP öncelikli, sonra indirilen URL'ler.

	parent_data'daki uzak URL alanı _collect_image_urls içinde pop edilir; URL'ler
	indirilip yerel File URL'lerine çevrilir, ZIP görselleriyle birleştirilir ve
	ürün başına MAX_IMAGES_PER_PRODUCT ile sınırlanır.
	"""
	remote_urls = _collect_image_urls(parent_data)
	zip_urls = images_idx.get(sku_key, [])
	downloaded = (
		image_url_ingest.ingest_image_urls(remote_urls, seller_profile, warnings) if remote_urls else []
	)
	# ZIP öncelikli (satıcı yüklemesi en güvenilir), ardından indirilen URL'ler.
	combined: list[str] = []
	for url in [*zip_urls, *downloaded]:
		if url not in combined:
			combined.append(url)
	return combined[:MAX_IMAGES_PER_PRODUCT]


def _collect_known_skus(rows: list[dict], mapping: dict) -> set[str]:
	"""Veri dosyasındaki ürün SKU'larını (parent + variant) normalize küme olarak
	çıkar — görsel eşleştirici bunları derinlik-bağımsız eşleştirmede sözlük olarak
	kullanır (SKU'yu tahmin etmek yerine gerçek listeye göre doğrular)."""
	keys: set[str] = set()
	for col in (mapping.get("sku"), mapping.get("variant_sku")):
		if not col:
			continue
		for r in rows:
			v = r.get(col)
			if v:
				k = image_matcher.normalize_sku_key(v)
				if k:
					keys.add(k)
	return keys


def _build_orphan_note(orphan_skus: list[str], orphan_files: list[str]) -> str:
	"""Eşleşmeyen ZIP görselleri için kullanıcıya anlaşılır özet satırı.

	orphan_skus: SKU paternine uyan ama satışta karşılığı olmayan anahtarlar.
	orphan_files: görsel uzantılı ama SKU adı paternine hiç uymayan dosyalar.
	"""

	def _fmt(items: list[str]) -> str:
		sample = ", ".join(items[:10])
		return f"{sample} (+{len(items) - 10})" if len(items) > 10 else sample

	parts: list[str] = []
	if orphan_skus:
		parts.append(
			_("{0} SKU için yüklenen görseller hiçbir ürünle eşleşmedi: {1}").format(
				len(orphan_skus), _fmt(orphan_skus)
			)
		)
	if orphan_files:
		parts.append(
			_("{0} görsel dosyası SKU adı paternine uymadı: {1}").format(
				len(orphan_files), _fmt(orphan_files)
			)
		)
	return " ".join(parts)


# canonical alan → kullanıcıya gösterilen TR etiketi (humanize için).
_FIELD_TR_LABELS = {
	"base_price": "Fiyat",
	"selling_price": "Satış Fiyatı",
	"currency": "Para Birimi",
	"condition": "Durum",
	"title": "Ürün Adı",
	"sku": "Stok Kodu",
	"stock_qty": "Stok",
}


def _humanize_exception(e) -> tuple[str, str | None]:
	"""Ham Frappe istisnasını anlaşılır TR mesaja + ilgili alan(lar)a çevir.

	En sık 'system' hatası MandatoryError'dır ("[Listing, X]: base_price,
	selling_price") — zorunlu alan boş kalması, genelde yanlış sütun eşleşmesi.
	Kullanıcı ham mesaj yerine ne yapması gerektiğini görür.
	"""
	raw = str(e)
	if type(e).__name__ == "MandatoryError":
		fields_part = raw.rsplit(":", 1)[-1] if ":" in raw else raw
		field_keys = [f.strip() for f in re.sub(r"<[^>]+>", "", fields_part).split(",") if f.strip()]
		labels = [_FIELD_TR_LABELS.get(f, f) for f in field_keys]
		if labels:
			msg = _(
				"Zorunlu alanlar boş kaldı: {0}. Büyük olasılıkla ilgili sütun(lar) yanlış "
				"eşleşti — yükleme öncesi eşleştirme ekranından düzeltin."
			).format(", ".join(labels))
			return msg[:500], ", ".join(field_keys)[:140]
	return raw[:500], None


def run(bulk_job_name: str) -> None:
	"""Bulk import job'unu çalıştır.

	Args:
	    bulk_job_name: Bulk Import Job.name
	"""
	# frappe.enqueue'un `job_name` parametresi RQ-ID için reserved; kwarg
	# olarak runner'a iletilmediği için api.py `bulk_job_name` ile geçiriyor.
	job_name = bulk_job_name
	job = frappe.get_doc("Bulk Import Job", job_name)
	frappe.flags.in_bulk_import = True
	frappe.flags.bulk_import_job = job_name

	try:
		job.db_set("status", "Running")
		job.db_set("started_at", now())
		_update_progress(job_name, state="running")

		file_path = _get_file_absolute_path(job.data_file)
		header_row = int(job.header_row or 1)

		if job.file_format == "xlsx":
			headers, rows = xlsx_parser.parse_xlsx(file_path, job.sheet_name, header_row)
		elif job.file_format == "csv":
			headers, rows = csv_parser.parse_csv(file_path, header_row)
		elif job.file_format == "xml":
			headers, rows = xml_parser.parse_xml(file_path)
		else:
			raise frappe.ValidationError(_("Desteklenmeyen dosya formatı: {0}").format(job.file_format))

		job.db_set("total_rows", len(rows))

		# Frontend boş eşleşme ("{}") gönderebiliyor — string truthy ama dict
		# boş kalır. Bu durumda da auto-resolve devreye girmeli.
		mapping = None
		if job.column_mapping:
			try:
				mapping = json.loads(job.column_mapping)
			except (ValueError, TypeError):
				mapping = None
		if not mapping:
			# 4 katmanlı resolver (Profile → Regex → Attribute → Semantic):
			# preview ile aynı mapping üretilsin; attr:<code> / product_type /
			# variant_* hedefleri persister'a kadar taşınsın (sessiz veri kaybını
			# önler — yalnız-regex auto-resolve bunları düşürüyordu).
			mapping = resolver.resolve_columns(headers, job.seller_profile).get("mapping", {})

		images_idx: dict[str, list[str]] = {}
		image_orphans: list[str] = []
		matched_img_keys: set[str] = set()
		if job.images_zip:
			zip_path = _get_file_absolute_path(job.images_zip)
			# Gerçek ürün SKU'larını sözlük olarak ver → görsel eşleştirici SKU'yu
			# yolun herhangi bir derinliğinde, bu listeye göre bulur (derin/dağınık
			# klasör yapısı belirsizlik olmadan çözülür).
			known_skus = _collect_known_skus(rows, mapping)
			# Kullanıcının 'Görseller' adımında yaptığı manuel atamalar (varsa).
			overrides = None
			if job.image_overrides:
				try:
					overrides = json.loads(job.image_overrides)
				except (ValueError, TypeError):
					overrides = None
			images_idx, image_orphans = image_matcher.build_image_index(
				zip_path, job.seller_profile, known_skus, overrides
			)

		inserted = updated = skipped = errors = 0
		total = len(rows)

		# Yeniden çalıştırma/retry'de önceki çalıştırmanın hata/atlama satırları
		# kalmasın — liste bu çalıştırmanın sonucunu yansıtsın (aksi halde sayaç
		# 0 ama Hata Listesi eski kayıtla dolu görünür).
		frappe.db.delete("Bulk Import Job Error", {"parent": job_name})

		# ── Mapping ön-kontrolü ──────────────────────────────────────
		# Fiyat/SKU/ad gibi zorunlu sütunlar hiç eşleşmediyse erkenden, tek ve
		# anlaşılır mesajla dur. Aksi halde her satır insert'te ham Frappe
		# "MandatoryError: base_price, selling_price" üretir (eski davranış).
		mapping_errors = validator.validate_mapping(mapping)
		if mapping_errors:
			summary = " ".join(mapping_errors)
			_record_error(job, 0, {}, mapping, "validation", summary)
			job.reload()
			job.inserted_count = job.updated_count = job.skipped_count = 0
			job.error_count = total
			job.status = "Failed"
			job.error_summary = summary
			job.completed_at = now()
			job.save(ignore_permissions=True)
			_update_progress(
				job_name,
				state="done",
				total=total,
				processed=total,
				inserted=0,
				updated=0,
				skipped=0,
				error_count=total,
			)
			notifications.notify("job_failed", {"job": job})
			return

		# ── Öğrenme döngüsü ──────────────────────────────────────────
		# Onaylanan/çözülen eşleştirmeyi satıcı profili olarak hatırla — aynı
		# başlıklı sonraki dosyalar resolver Layer 1'de %100 güvenle otomatik
		# eşlenir, manuel iş tekrarı biter. Profil kaydı kritik değil; hata
		# import'u düşürmesin.
		if job.remember_mapping and mapping:
			try:
				profile_store.save_profile(
					headers,
					job.seller_profile,
					mapping,
					source_format=job.file_format or "xlsx",
					sheet_name=job.sheet_name,
				)
			except Exception:
				frappe.log_error(
					title="Bulk import profile save failed",
					message=frappe.get_traceback(),
				)

		# ── Cluster aşaması ──────────────────────────────────────────
		# Aynı parent_sku altındaki satırları grupla. Varyantsız ürünler:
		# tek satırlı cluster (parent_row + variant_rows=[]). Varyantlı ürünler:
		# parent satır + N variant satır.
		# Değer Eşleştirmelerim — satıcı hücre-değeri normalizasyonu (persist öncesi).
		# Map bir kez kurulur (5dk cache), _canonicalize her satıra uygular.
		value_map = value_mapping.build_value_map(job.seller_profile)
		clusters, cluster_errors = _build_clusters(rows, mapping, value_map)
		for c_idx, raw_row, msg in cluster_errors:
			_record_error(job, c_idx, raw_row, mapping, "validation", msg)
			errors += 1

		# ── İşleme aşaması ───────────────────────────────────────────
		for cluster in clusters:
			parent_idx = cluster["parent_idx"]
			parent_data = cluster["parent_data"]
			variant_data_rows = cluster["variant_data_rows"]
			parent_raw_row = cluster["parent_raw_row"]

			try:
				# Validator (sadece parent satır için; variant'ların kendi validator'ı yok)
				row_errors = validator.validate_row(parent_raw_row, mapping)
				if row_errors:
					# Hangi alan(lar) hatalı — UI vurgusu için field bilgisini koru
					# (önceden yalnız mesaj join ediliyordu, field atılıyordu).
					_record_error(
						job,
						parent_idx,
						parent_raw_row,
						mapping,
						"validation",
						"; ".join(e["message"] for e in row_errors),
						field=", ".join(dict.fromkeys(e["field"] for e in row_errors if e.get("field"))),
					)
					errors += 1
					continue

				sku = parent_data.get("sku")
				if not sku:
					_record_error(job, parent_idx, parent_raw_row, mapping, "validation", "SKU eksik")
					errors += 1
					continue

				sku_key = str(sku).strip()
				# Görsel eşleştirme anahtarı — büyük/küçük & Türkçe bağımsız (DB SKU'su
				# orijinal kalır, yalnız ZIP index lookup'ı normalize edilir).
				img_key = image_matcher.normalize_sku_key(sku_key)
				for _s in (sku_key, *(v.get("variant_sku") for v in variant_data_rows)):
					_k = image_matcher.normalize_sku_key(_s)
					if _k in images_idx:
						matched_img_keys.add(_k)

				if persister.check_sku_exists(sku_key, job.seller_profile):
					if job.update_mode == "insert_only":
						_record_skip(
							job,
							parent_idx,
							sku_key,
							"Mevcut SKU, insert-only modda atlandı",
						)
						skipped += 1
						continue
					# Upsert: variant_items'a şu an dokunmuyoruz (V1: parent fields güncellenir).
					row_warnings: list[str] = []
					imgs = _resolve_images(parent_data, img_key, images_idx, job.seller_profile, row_warnings)
					persister.update_listing(
						sku_key,
						parent_data,
						job.seller_profile,
						job_name,
						imgs,
						row_warnings,
					)
					updated += 1
					_record_warnings(job, parent_idx, parent_raw_row, mapping, row_warnings)
				else:
					row_warnings = []
					if variant_data_rows:
						# Varyantlı ürün — parent'ın indirilen görsellerini images_idx'e
						# overlay et (create_listing_with_variants dict bekliyor).
						parent_imgs = _resolve_images(
							parent_data, img_key, images_idx, job.seller_profile, row_warnings
						)
						variant_images_idx = images_idx
						if parent_imgs:
							variant_images_idx = {**images_idx, img_key: parent_imgs}
						persister.create_listing_with_variants(
							parent_data,
							variant_data_rows,
							job.seller_profile,
							job_name,
							variant_images_idx,
							row_warnings,
						)
					else:
						# Varyantsız ürün — eski tek-satır akış
						imgs = _resolve_images(
							parent_data, img_key, images_idx, job.seller_profile, row_warnings
						)
						persister.create_listing(
							parent_data,
							job.seller_profile,
							job_name,
							imgs,
							row_warnings,
						)
					inserted += 1
					_record_warnings(job, parent_idx, parent_raw_row, mapping, row_warnings)

				processed = inserted + updated + skipped + errors
				if processed % COMMIT_CHUNK_SIZE == 0:
					frappe.db.commit()
					_update_progress(
						job_name,
						state="running",
						total=total,
						processed=processed,
						inserted=inserted,
						updated=updated,
						skipped=skipped,
						error_count=errors,
					)
			except ECARejectionError as e:
				# İş kuralı (ECA reject_row) satırı reddetti — sistem hatası değil,
				# bilinçli skip. Sebebini eca_rejected tipiyle raporla.
				_record_error(job, parent_idx, parent_raw_row, mapping, "eca_rejected", str(e)[:500])
				skipped += 1
			except Exception as e:
				frappe.log_error(
					title=f"Bulk import row {parent_idx} error: {job_name}",
					message=frappe.get_traceback(),
				)
				# Ham Frappe mesajı yerine anlaşılır mesaj + ilgili alan üret.
				human_msg, human_field = _humanize_exception(e)
				_record_error(
					job, parent_idx, parent_raw_row, mapping, "system", human_msg, field=human_field
				)
				errors += 1

		frappe.db.commit()
		job.reload()
		job.inserted_count = inserted
		job.updated_count = updated
		job.skipped_count = skipped
		job.error_count = errors
		job.completed_at = now()
		if job.started_at:
			try:
				job.duration_seconds = time_diff_in_seconds(
					job.completed_at,
					job.started_at,
				)
			except Exception:
				job.duration_seconds = 0

		if total > 0 and errors == total:
			job.status = "Failed"
		elif errors > 0 or skipped > 0:
			job.status = "Partial"
		else:
			job.status = "Completed"
		# Partial/Failed'da üst-düzey özet ver (önceden yalnız fatal except'te
		# set ediliyordu → "1 hata ama özet boş" görünüyordu).
		if errors > 0 and not job.error_summary:
			job.error_summary = _("{0} satır içe aktarılamadı. Ayrıntılar aşağıdaki hata listesinde.").format(
				errors
			)

		# Yetim görsel raporu — hiçbir ürünle eşleşmeyen ZIP görselleri (yanlış SKU
		# adı verildiğinde sessizce kaybolmasınlar). orphan_skus: SKU paternine uyan
		# ama satışta karşılığı olmayan; image_orphans: SKU paternine hiç uymayanlar.
		orphan_skus = [k for k in images_idx if k not in matched_img_keys]
		orphan_note = _build_orphan_note(orphan_skus, image_orphans)
		if orphan_note:
			job.error_summary = f"{job.error_summary or ''}\n{orphan_note}".strip()

		job.save(ignore_permissions=True)

		_update_progress(
			job_name,
			state="done",
			total=total,
			processed=total,
			inserted=inserted,
			updated=updated,
			skipped=skipped,
			error_count=errors,
		)

		if job.status == "Failed":
			notifications.notify("job_failed", {"job": job})
		elif job.status == "Partial":
			notifications.notify("job_completed_with_errors", {"job": job})
		else:
			notifications.notify("job_completed", {"job": job})

	except Exception as e:
		frappe.log_error(
			title=f"Bulk import fatal error: {job_name}",
			message=frappe.get_traceback(),
		)
		try:
			job.db_set("status", "Failed")
			job.db_set("error_summary", str(e)[:500])
			notifications.notify("job_failed", {"job": job})
		except Exception:
			pass
		_update_progress(job_name, state="error", error=str(e)[:500])
	finally:
		frappe.flags.in_bulk_import = False
		frappe.flags.bulk_import_job = None


def _record_error(
	job,
	row_num: int,
	raw_row: dict,
	mapping: dict,
	error_type: str,
	msg: str,
	field: str | None = None,
	severity: str = "error",
) -> None:
	"""Hatalı satırı child table'a ekle.

	field: hangi canonical alan(lar) hatalı (UI vurgusu için).
	severity: "error" | "warning" (uyarılar error sayılmaz).
	"""
	sku = ""
	name = ""
	if mapping:
		sku_col = mapping.get("sku", "")
		name_col = mapping.get("title", "")
		if sku_col:
			sku = raw_row.get(sku_col, "") or ""
		if name_col:
			name = raw_row.get(name_col, "") or ""
	try:
		child = frappe.new_doc("Bulk Import Job Error")
		child.parent = job.name
		child.parenttype = "Bulk Import Job"
		child.parentfield = "error_details"
		# parent.save() bypass edildiği için Frappe idx auto-set etmez; row_num'u
		# child idx'i olarak kullanmazsak reload sonrası sıralama belirsiz olur.
		child.idx = row_num
		child.row_number = row_num
		child.sku = str(sku)[:140] if sku else ""
		child.product_name = str(name)[:250] if name else ""
		child.error_type = error_type
		child.severity = severity
		child.field = (field or "")[:140]
		child.error_message = (msg or "")[:500]
		try:
			child.raw_row_json = json.dumps(raw_row, default=str)[:5000]
		except Exception:
			child.raw_row_json = ""
		child.insert(ignore_permissions=True)
	except Exception as e:
		frappe.log_error(f"_record_error failed: {e}", "bulk_import.runner")


def _record_warnings(
	job,
	row_num: int,
	raw_row: dict,
	mapping: dict,
	warnings: list[str],
) -> None:
	"""Satır başarıyla yazıldı ama persister uyarı topladıysa (örn. geçersiz
	öznitelik kodu) bunları error_details child'ına bilgilendirici satır olarak
	ekle. error counter'ı ARTIRMAZ — satır import edildi, bu yalnızca uyarı.

	severity="warning" ile kaydedilir → UI gerçek hatadan ayırt edebilsin.
	"""
	if not warnings:
		return
	_record_error(job, row_num, raw_row, mapping, "validation", "; ".join(warnings), severity="warning")


def _record_skip(job, row_num: int, sku, reason: str) -> None:
	"""Atlanan satırı child table'a ekle."""
	try:
		child = frappe.new_doc("Bulk Import Job Error")
		child.parent = job.name
		child.parenttype = "Bulk Import Job"
		child.parentfield = "error_details"
		child.idx = row_num
		child.row_number = row_num
		child.sku = str(sku)[:140] if sku else ""
		child.error_type = "duplicate"
		child.error_message = (reason or "")[:500]
		child.insert(ignore_permissions=True)
	except Exception as e:
		frappe.log_error(f"_record_skip failed: {e}", "bulk_import.runner")


def _build_clusters(
	rows: list[dict],
	mapping: dict,
	value_map: dict | None = None,
) -> tuple[list[dict], list[tuple[int, dict, str]]]:
	"""xlsx satırlarını parent-variant cluster'larına böl.

	Kural:
	- parent_sku BOŞ → satır parent (varyantsız veya varyantlı master)
	- parent_sku DOLU → satır variant; parent_sku ile aynı seller_sku'ya sahip
	  parent satırına bağlanır
	- Orphan variant (parent bulunamaz) → cluster_errors'a düşer

	Returns:
	    clusters: [
	        {
	            "parent_idx": int,             # xlsx 1-based satır no
	            "parent_data": dict,           # canonical data (sku, title, …)
	            "parent_raw_row": dict,        # ham parser row (validator için)
	            "variant_data_rows": list[dict],  # canonical variant rows
	        },
	        ...
	    ]
	    cluster_errors: [(idx, raw_row, error_message), ...]
	"""
	clusters_by_sku: dict[str, dict] = {}
	cluster_order: list[str] = []
	orphans: list[tuple[int, dict, str]] = []
	pending_variants: list[tuple[int, dict, dict, str]] = []

	vmap = value_map or {}

	def _canonicalize(raw_row: dict) -> dict:
		out: dict = {}
		for target, source in mapping.items():
			if source in raw_row:
				# Değer eşleştirmesi: gelen hücre değerini satıcı hedef değerine çevir.
				# Kimlik alanları (sku/parent_sku vb.) value_mapping içinde atlanır —
				# cluster bağı map'lenmemiş ham SKU üzerinden kurulur.
				out[target] = value_mapping.apply_value_mapping(target, raw_row[source], vmap)
		return out

	for idx, raw_row in enumerate(rows, 1):
		data = _canonicalize(raw_row)
		seller_sku = str(data.get("sku") or "").strip()
		parent_sku = str(data.get("parent_sku") or "").strip()

		if not parent_sku:
			# Parent satır (varyantsız veya varyantlı master)
			if not seller_sku:
				orphans.append((idx, raw_row, "Stok Kodu eksik"))
				continue
			if seller_sku in clusters_by_sku:
				# Aynı seller_sku ile ikinci parent → ikinci'yi atla (downstream
				# duplicate koruması zaten "Mevcut SKU" diye skip eder)
				orphans.append((idx, raw_row, f"Yinelenen parent SKU: {seller_sku}"))
				continue
			clusters_by_sku[seller_sku] = {
				"parent_idx": idx,
				"parent_data": data,
				"parent_raw_row": raw_row,
				"variant_data_rows": [],
			}
			cluster_order.append(seller_sku)
		else:
			# Varyant satır — parent SKU'ya ekle (parent bu satırdan önce ya da sonra olabilir)
			pending_variants.append((idx, raw_row, data, parent_sku))

	# Tüm parent'lar map'lendikten sonra varyantları bağla
	for idx, raw_row, data, parent_sku in pending_variants:
		cluster = clusters_by_sku.get(parent_sku)
		if not cluster:
			orphans.append(
				(idx, raw_row, f"Parent SKU '{parent_sku}' bulunamadı (önce master satırı ekleyin)")
			)
			continue
		# Varyant ekseni doğrulama: en az 1 eksen değeri olmalı
		if not (data.get("variant_axis_1_value") or "").strip():
			orphans.append((idx, raw_row, "Varyant satırında 'Varyant Eksen 1 Değeri' boş olamaz"))
			continue
		cluster["variant_data_rows"].append(data)

	clusters = [clusters_by_sku[sku] for sku in cluster_order]
	return clusters, orphans


def _update_progress(job_name: str, **fields) -> None:
	"""Redis cache'e progress state yaz."""
	key = f"bulk_import_progress:{job_name}"
	current = frappe.cache.get_value(key) or {}
	current.update(fields)
	frappe.cache.set_value(key, current, expires_in_sec=PROGRESS_CACHE_TTL)


def _get_file_absolute_path(file_url: str) -> str:
	"""File URL → absolute disk path."""
	if not file_url:
		frappe.throw(_("Dosya URL boş"))
	if file_url.startswith("/files/"):
		return frappe.get_site_path("public", file_url.lstrip("/"))
	if file_url.startswith("/private/files/"):
		return frappe.get_site_path(file_url.lstrip("/"))
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	return file_doc.get_full_path()

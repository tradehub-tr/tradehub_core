"""Doküman çıkarım motoru — PDF/Office metadata + metin (Dosya Yöneticisi SEO, Task 2).

Karar belgesi: `.superpowers/sdd/2026-08-27-file-manager-seo/task-2-brief.md`.
Task 1 `File.th_media_page_count` (Int) ve `File.th_media_extracted_text`
(Long Text) kolonlarını açtı; bu modül onları DOLDURUR.

NE YAPAR
--------
Public `.pdf/.docx/.xlsx/.pptx` dosyalarından sayfa sayısı + düz metin çıkarır
(PDF `pypdf`, Office biçimleri stdlib `zipfile` + `xml.etree.ElementTree` ile —
OOXML zaten bir ZIP paketi, ek bağımlılık gerekmez). Metin `th_media_title`
BOŞSA öneri olarak da kullanılır — dolu başlık asla ezilmez.

`th_media_title` NEDEN `seo.set_asset_fields` İLE DEĞİL doğrudan `db.set_value`
İLE YAZILIYOR
-------------------------------------------------------------------------
`title` `media/seo.py::TRANSLATABLE` üyesi — `set_asset_fields` onu dil
kolonuna (`th_media_title_{lang}`) yazar (`seo_generate.py::refresh_alt`'ın
`alt_{DEFAULT_LANG}` için yaptığı gibi). Burada niyet FARKLI: bu bir çeviri
DEĞİL, dosyanın kendi metadata'sından (PDF `/Title`) okunan TEK bir gerçek.
Dil kolonuna yazmak "bu başlık şu dile çevrildi" yalanı söylerdi. Çıplak
`th_media_title` kolonu — `resolve_content_field`'ın son basamağı, eski
tek-dil kolonu — bunun için var; oraya doğrudan yazılır, dil kolonlarına
DOKUNULMAZ.

ANTI-AÇLIK (video_poster.generate ile aynı gerekçe)
----------------------------------------------------
Çıkarım başarısız olursa (şifreli PDF, `.doc` gibi eski biçim, bozuk paket)
`th_media_page_count`/`th_media_extracted_text` BOŞ bırakılırsa
`backfill_docs` aynı dosyayı HER turda yeniden seçerdi (aynen `video_poster`
docstring'inin anlattığı poster/duration açlığı). Bu yüzden başarısızlıkta
`th_media_page_count` -1 damgalanır: "denendi, okunamadı" der. Başarılı
çıkarım her zaman >= 0 sayfa yazdığı için ayrışma net kalır ve
`backfill_docs`'un `IFNULL(th_media_page_count, 0) = 0` süzgeci bu dosyayı
bir daha seçmez. `-1` İÇ bir sözleşmedir — `media/seo.py::_birlestir` dışa
`max(0, ...)` ile clamp'liyor, `fields_for`/`fields_for_many` tüketicileri
(panel, JSON-LD) negatif sayfa sayısı GÖRMEZ (denetim düzeltme turu 1).

ZIP-BOMB VE ENTITY GENİŞLEMESİ (denetim düzeltme turu 1 + 2)
--------------------------------------------------------------
Office biçimleri (docx/xlsx/pptx) ZIP paketi — kullanıcı yüklediği bir
`.docx` sıkışmış hâliyle birkaç KB ama içinde açılınca gigabaytlarca sıfır
barındıran bir üye taşıyabilir (klasik zip-bomb). `ok=False, reason=
"zip_icerik_asiri"` bu durumda döner; üye başına 20 MB, aynı `extract()`
çağrısındaki TÜM üyelerin (pptx'te N slayt) TOPLAMI 40 MB tavan.

**Turu 1'deki bypass (turu 2'de düzeltildi):** İlk sürüm `zf.getinfo(member).
file_size`'a (merkezi dizin/local header'daki BEYAN edilen sıkıştırılmamış
boyut) güveniyordu ve yalnız bu değer tavanı aşarsa `zf.read()`'i hiç
çağırmıyordu. Bu değer SALDIRGAN TARAFINDAN YAZILAN, doğrulanmamış zip
metadata'sıdır — re-review canlıda kanıtladı: header'da `100` bayt beyan
edip gerçek deflate akışını 200 MB sıfıra şişiren bir üye, `file_size`
kontrolünü es geçip `zf.read()`'e giriyor, `zf.read()` de akışı SESSİZCE
tam decompress ediyordu (CRC uyuşmazlığı ancak decompress bittikten SONRA
`BadZipFile` olarak geliyor ve mevcut `except Exception` onu zaten
`container_invalid` diye yutuyordu) — ~200 MB RSS artışı ölçüldü.

**Düzeltme:** `_ZipButce.oku` artık `zf.open(member)` ile AKIŞLI okuyor,
64 KB'lık parçalar halinde (`fh.read(65536)`), her parçadan sonra üye/toplam
GERÇEK okunan bayt sayısını tavanla karşılaştırıyor ve aşılırsa KALAN baytı
hiç okumadan `_ZipIcerikAsiri` fırlatıyor. `getinfo().file_size` kontrolü
hâlâ duruyor ama artık yalnız UCUZ bir ön-eleme (dürüst-büyük beyanı tek
bayt okumadan erken kesmek için) — GÜVENLİK SINIRI DEĞİL, çünkü saldırgan
onu istediği gibi yazabilir. Asıl sınır akışlı okumanın kendisi; bellek
profili bütçe (20/40 MB) + 64 KB ile sınırlı, beyan edilen değerden bağımsız.

Ayrıca `xml.etree.ElementTree` DOCTYPE içinde tanımlı `ENTITY`'leri
genişletebiliyor (billion-laughs — harici varlık çekmez ama iç genişletme
CPU/bellek bombasıdır). stdlib'in "entity'siz parse" modu yok; bu yüzden
ayrıştırmadan ÖNCE ham baytta `<!DOCTYPE`/`<!ENTITY` imzası aranıyor
(`_entity_riskli`) — varsa `reason="xml_entity_reddi"`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile

import frappe

from tradehub_core.media import upload_policy

#: Çıkarım motorunun desteklediği ve `File.after_insert`/`backfill_docs`'un
#: aday seçtiği uzantılar. `upload_policy.EXTENSIONS` haritasında `.pptx` yok
#: (KIND_DOCUMENT yalnız pdf/doc/docx/xls/xlsx'i kapsıyor) — bu yüzden
#: `video_poster.VIDEO_UZANTILAR` deseniyle AYNI şekilde kendi düz uzantı
#: listemiz var; `kind_of()`'a bağlanmadık.
DOC_UZANTILAR: tuple[str, ...] = (".pdf", ".docx", ".xlsx", ".pptx", ".csv", ".txt")

#: Düz metin biçimleri — ZIP/PDF ayrıştırıcısı gerekmez, dosya doğrudan
#: okunur. `DOC_UZANTILAR`'ın parçası ama ayrı sabit: `_extract_plain`
#: dalının koşulu bu küme ve iki yerde iki liste tutmamak için tek kaynak.
#:
#: MOGEM-620 §15 CSV ve TXT'yi açıkça sayıyor; 10 Eyl 2026 denetiminde
#: dördü (pdf/docx/xlsx/pptx) vardı, bu ikisi yoktu.
DUZ_METIN_UZANTILAR: tuple[str, ...] = (".csv", ".txt")

#: Eski ikili biçimler — çıkarım motoru bunları AÇAMAZ (ikisi de OOXML/ZIP
#: değil, ayrı ikili format). `DOC_UZANTILAR`'a girmezler (backfill/kanca
#: bunları hiç aday görmez) ama `extract()` doğrudan çağrılırsa net bir
#: `reason` dönmeli — sessiz "okunamadı" yerine.
_ESKI_BICIMLER: tuple[str, ...] = (".doc", ".xls", ".ppt")

#: Metin tavanı (karakter) — panelde/JSON-LD'de sınırsız Long Text taşımamak
#: için. PDF'te sayfa sınırında KESİLİR (tüm sayfalar okunup sonra kırpılmaz —
#: büyük dosyada gereksiz CPU).
TEXT_TAVAN: int = 64 * 1024


def _bos(reason: str) -> dict:
	return {"ok": False, "reason": reason, "page_count": 0, "text": "", "title": ""}


def _local(tag: str) -> str:
	"""XML etiketinin ad alanından bağımsız yerel adı (`{ns}t` → `t`)."""
	return tag.rsplit("}", 1)[-1] if "}" in tag else tag


#: Zip-bomb koruması — sıkışmış küçük, açılmış devasa üye/dosya. Üye başına
#: 20 MB; aynı `extract()` çağrısındaki TÜM üyelerin (pptx N slayt) TOPLAMI
#: 40 MB. Modül docstring'inde gerekçe (turu 1 bypass + turu 2 düzeltmesi).
_ZIP_MEMBER_LIMIT: int = 20 * 1024 * 1024
_ZIP_TOTAL_LIMIT: int = 40 * 1024 * 1024

#: Akışlı okuma parça boyutu — bellek profilini bütçeyle sınırlı tutar
#: (bütçe + en fazla bir parça, beyan edilen boyuttan bağımsız).
_ZIP_CHUNK_SIZE: int = 64 * 1024


class _ZipIcerikAsiri(Exception):
	"""Zip üyesi ya da dosya toplamı decompress tavanını aştı — zip-bomb şüphesi."""


class _ZipButce:
	"""Tek bir `extract()` çağrısı içindeki TÜM zip okumalarının PAYLAŞTIĞI
	decompress bütçesi.

	GÜVENLİK SINIRI akışlı okumanın KENDİSİ — `zf.getinfo(member).file_size`
	(merkezi dizin/local header'daki BEYAN edilen boyut) yalnız UCUZ bir
	ön-eleme: dürüst-büyük bir beyanı tek bayt okumadan erken keser. Bu değere
	GÜVENİLEMEZ çünkü saldırgan zip dosyasının yazarıdır — header'da küçük bir
	sayı yazıp gerçek deflate akışını devasa şişirebilir (turu 1'de canlı
	kanıtlandı: 100 bayt beyan, 200 MB gerçek içerik; `zf.read()` tavanı hiç
	görmeden akışı SESSİZCE tam decompress ediyordu, CRC hatası iş bittikten
	SONRA geliyordu). Bu yüzden asıl karar GERÇEKTEN okunan bayt üstünden:
	`zf.open(member)` ile 64 KB'lık parçalar okunur, her parçadan sonra
	üye/toplam sayaç tavanla karşılaştırılır — aşılırsa KALAN bayt hiç
	okunmadan `_ZipIcerikAsiri` fırlatılır. Bellek profili bütçe + tek parça
	ile sınırlı, beyan edilen (ve saldırganın kontrolündeki) boyuttan bağımsız.
	"""

	def __init__(self) -> None:
		self.toplam = 0

	def oku(self, zf: zipfile.ZipFile, member: str) -> bytes | None:
		try:
			bilgi = zf.getinfo(member)
		except KeyError:
			return None
		# UCUZ ön-eleme — güvenlik sınırı DEĞİL, sınıf docstring'inde gerekçe.
		if bilgi.file_size > _ZIP_MEMBER_LIMIT:
			raise _ZipIcerikAsiri()

		parcalar: list[bytes] = []
		uye_toplam = 0
		with zf.open(member) as fh:
			while True:
				parca = fh.read(_ZIP_CHUNK_SIZE)
				if not parca:
					break
				uye_toplam += len(parca)
				self.toplam += len(parca)
				if uye_toplam > _ZIP_MEMBER_LIMIT or self.toplam > _ZIP_TOTAL_LIMIT:
					# Kalan baytı OKUMADAN kes — asıl güvenlik sınırı burası.
					raise _ZipIcerikAsiri()
				parcalar.append(parca)
		return b"".join(parcalar)


#: Billion-laughs / entity genişletme önlemi — modül docstring'inde gerekçe.
_ENTITY_IMZALARI: tuple[bytes, ...] = (b"<!DOCTYPE", b"<!ENTITY")


def _entity_riskli(veri: bytes) -> bool:
	return any(imza in veri for imza in _ENTITY_IMZALARI)


def _zip_member(path: str, member: str) -> bytes | None:
	"""Zip içindeki TEK üyeyi decompress tavanını kontrol ederek oku.

	Ayrım önemli: "üye yok" (ör. sharedStrings.xml'siz xlsx — yalnız sayısal
	veri) bozukluk değil, çağıran boş metinle devam eder. Paket açılamıyorsa
	(BadZipFile) ya da tavan aşılırsa (`_ZipIcerikAsiri`) çağıran ayrı ayrı
	yakalayıp uygun `reason`'a çevirir.
	"""
	with zipfile.ZipFile(path) as zf:
		return _ZipButce().oku(zf, member)


# ── PDF ─────────────────────────────────────────────────────────────────


def _extract_pdf(path: str) -> dict:
	from pypdf import PdfReader

	try:
		reader = PdfReader(path)
	except Exception:
		return _bos("unreadable")

	try:
		if reader.is_encrypted:
			return _bos("encrypted")
	except Exception:
		return _bos("encrypted")

	try:
		sayfalar = reader.pages
		page_count = len(sayfalar)
	except Exception:
		return _bos("unreadable")

	parcalar: list[str] = []
	toplam = 0
	try:
		for sayfa in sayfalar:
			if toplam >= TEXT_TAVAN:
				# Sayfa sınırında kes — tavanı aşan sayfaları hiç ayrıştırma.
				break
			metin = sayfa.extract_text() or ""
			parcalar.append(metin)
			toplam += len(metin)
	except Exception:
		# Bir sonraki sayfa patlarsa elimizdeki metinle devam — kısmi sonuç
		# hiç sonuçtan iyidir (§ modül docstring "boş, yanlıştan iyidir" ile
		# aynı ilke).
		pass
	text = "\n".join(parcalar)[:TEXT_TAVAN]

	baslik = ""
	try:
		meta = reader.metadata
		if meta and meta.title:
			baslik = str(meta.title).strip()
	except Exception:
		baslik = ""

	return {"ok": True, "reason": "", "page_count": page_count, "text": text, "title": baslik}


# ── Office (OOXML/ZIP) ──────────────────────────────────────────────────

_DOCX_PARA_TAG = "p"
_TEXT_TAG = "t"


def _extract_docx(path: str) -> dict:
	try:
		veri = _zip_member(path, "word/document.xml")
	except _ZipIcerikAsiri:
		return _bos("zip_icerik_asiri")
	except Exception:
		return _bos("container_invalid")
	if veri is None:
		return _bos("container_invalid")
	if _entity_riskli(veri):
		return _bos("xml_entity_reddi")

	try:
		kok = ET.fromstring(veri)
		parcalar: list[str] = []
		toplam = 0
		for eleman in kok.iter():
			if _local(eleman.tag) != _DOCX_PARA_TAG:
				continue
			paragraf = "".join(t.text or "" for t in eleman.iter() if _local(t.tag) == _TEXT_TAG)
			if paragraf:
				parcalar.append(paragraf)
				toplam += len(paragraf)
			if toplam >= TEXT_TAVAN:
				break
	except Exception:
		return _bos("container_invalid")

	text = "\n".join(parcalar)[:TEXT_TAVAN]
	# Sayfa sayısı docx'te güvenilir değil (yeniden akış motoru gerektirir,
	# XML'de tutulmaz) — 0 bırakılıyor; SEO metni değil fiziksel gerçek
	# olduğu için yanlış sayı uydurmak boş bırakmaktan kötü.
	return {"ok": True, "reason": "", "page_count": 0, "text": text, "title": ""}


def _extract_xlsx(path: str) -> dict:
	try:
		veri = _zip_member(path, "xl/sharedStrings.xml")
	except _ZipIcerikAsiri:
		return _bos("zip_icerik_asiri")
	except Exception:
		return _bos("container_invalid")
	if veri is None:
		# Yalnız sayısal veri içeren xlsx'te bu üye hiç yok — bozukluk değil.
		return {"ok": True, "reason": "", "page_count": 0, "text": "", "title": ""}
	if _entity_riskli(veri):
		return _bos("xml_entity_reddi")

	try:
		kok = ET.fromstring(veri)
		parcalar: list[str] = []
		toplam = 0
		for eleman in kok.iter():
			if _local(eleman.tag) != "si":
				continue
			metin = "".join(t.text or "" for t in eleman.iter() if _local(t.tag) == _TEXT_TAG)
			if metin:
				parcalar.append(metin)
				toplam += len(metin)
			if toplam >= TEXT_TAVAN:
				break
	except Exception:
		return _bos("container_invalid")

	text = "\n".join(parcalar)[:TEXT_TAVAN]
	return {"ok": True, "reason": "", "page_count": 0, "text": text, "title": ""}


def _extract_plain(path: str) -> dict:
	"""CSV/TXT — ZIP ya da PDF ayrıştırıcısı yok, dosya doğrudan okunur.

	NEDEN AYRI DAL: diğer dördü kapsayıcı formatı (ZIP/PDF) çözmek zorunda ve
	zip-bomb/XML-entity savunmalarına ihtiyaç duyuyor. Düz metinde o
	saldırı yüzeyi YOK; tek risk dosyanın büyüklüğü ve o da `TEXT_TAVAN` ile
	zaten sınırlı. Bu dalı ZIP mantığına zorlamak, olmayan bir tehdide karşı
	kod yazmak olurdu.

	OKUMA TAVANDA KESİLİR, dosya tamamı belleğe ALINMAZ: 500 MB'lık bir CSV
	tamamen okunup sonra kırpılsaydı, 64 KB metin için 500 MB bellek harcanırdı.

	SAYFA SAYISI 0 DEĞİL -1: düz metinde "sayfa" kavramı yok. 0 yazmak
	`backfill_docs`'un aday sorgusunda (`page_count = 0`) bu dosyaları HER
	TURDA yeniden seçmesine yol açardı — `apply`'ın anti-açlık damgasıyla
	aynı gerekçe, aynı değer.

	KODLAMA: UTF-8 denenir, olmazsa Windows-1254 (Türkçe Excel CSV'lerinin
	yaygın kodlaması) ve son çare `errors="replace"`. Bir kodlama hatası
	yüzünden metnin tamamını kaybetmek, birkaç bozuk karakterden kötü.
	"""
	try:
		ham = b""
		with open(path, "rb") as fh:
			# Tavan KARAKTER cinsinden; UTF-8'de bir karakter 4 bayta kadar
			# çıkabildiği için okuma bütçesi dört katı alınıyor, sonra
			# çözülmüş metin kırpılıyor.
			ham = fh.read(TEXT_TAVAN * 4)
	except OSError:
		return _bos("unreadable")

	metin = ""
	for kodlama in ("utf-8", "cp1254"):
		try:
			metin = ham.decode(kodlama)
			break
		except UnicodeDecodeError:
			continue
	else:
		metin = ham.decode("utf-8", errors="replace")

	metin = metin.strip()[:TEXT_TAVAN]
	if not metin:
		return _bos("bos_dosya")
	# Başlık: ilk dolu satır. CSV'de bu başlık satırıdır, TXT'de ilk
	# cümledir — ikisi de dosyanın ne olduğunu söyleyen en iyi tek satır.
	# Uydurma yok: satır yoksa başlık da yok.
	ilk = next((s.strip() for s in metin.splitlines() if s.strip()), "")
	return {
		"ok": True,
		"reason": "",
		"page_count": -1,
		"text": metin,
		"title": ilk[:140],
	}


def _extract_pptx(path: str) -> dict:
	try:
		with zipfile.ZipFile(path) as zf:
			isimler = sorted(
				n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")
			)
			if not isimler:
				return _bos("container_invalid")

			butce = _ZipButce()
			parcalar: list[str] = []
			toplam = 0
			for isim in isimler:
				if toplam >= TEXT_TAVAN:
					break
				veri = butce.oku(zf, isim)
				if veri is None:
					continue
				if _entity_riskli(veri):
					return _bos("xml_entity_reddi")
				try:
					kok = ET.fromstring(veri)
					metin = "".join(t.text or "" for t in kok.iter() if _local(t.tag) == _TEXT_TAG)
				except Exception:
					continue
				if metin:
					parcalar.append(metin)
					toplam += len(metin)
	except _ZipIcerikAsiri:
		return _bos("zip_icerik_asiri")
	except Exception:
		return _bos("container_invalid")

	text = "\n".join(parcalar)[:TEXT_TAVAN]
	# Slayt sayısı = slayt XML'i sayısı — pptx'te docx'in aksine güvenilir.
	return {"ok": True, "reason": "", "page_count": len(isimler), "text": text, "title": ""}


# ── Genel giriş noktası ────────────────────────────────────────────────


def extract(file_url: str) -> dict:
	"""Tek dosyanın metadata + metnini çıkar — hata fırlatmaz, `ok=False` döner.

	Dönüş: `{"ok": bool, "reason": str, "page_count": int, "text": str, "title": str}`.
	`reason` yalnız `ok=False` iken anlamlı (`encrypted`, `legacy_format`,
	`container_invalid`, `unreadable`, `unsupported_extension`, `no_file`,
	`zip_icerik_asiri`, `xml_entity_reddi`).
	"""
	ext = upload_policy.extension_of(file_url)
	if ext in _ESKI_BICIMLER:
		return _bos("legacy_format")
	if ext not in DOC_UZANTILAR:
		return _bos("unsupported_extension")

	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		return _bos("no_file")

	try:
		doc = frappe.get_doc("File", name)
		path = doc.get_full_path()
	except Exception:
		return _bos("unreadable")

	if ext == ".pdf":
		return _extract_pdf(path)
	if ext == ".docx":
		return _extract_docx(path)
	if ext == ".xlsx":
		return _extract_xlsx(path)
	if ext in DUZ_METIN_UZANTILAR:
		return _extract_plain(path)
	return _extract_pptx(path)  # ext == ".pptx" — DOC_UZANTILAR'daki son seçenek


def apply(file_url: str) -> bool:
	"""Çıkarımı KARDEŞ `File` kayıtlarının hepsine yaz — `video_poster.generate`
	ile aynı desen (aynı `file_url`'e 39 kayda kadar işaret edebiliyor).

	Hata yutulur (`frappe.log_error` + `False` dönüş) — kullanıcı yüklemesini
	ya da kuyruk işini asla düşürmez.
	"""
	try:
		adlar = frappe.get_all("File", filters={"file_url": file_url}, pluck="name")
		if not adlar:
			return False

		sonuc = extract(file_url)
		if not sonuc.get("ok"):
			# Anti-açlık — modül docstring'inde gerekçesi var.
			frappe.db.set_value(
				"File", {"name": ["in", adlar]}, "th_media_page_count", -1, update_modified=False
			)
			return False

		page_count = int(sonuc.get("page_count") or 0)
		text = (sonuc.get("text") or "")[:TEXT_TAVAN]
		frappe.db.set_value(
			"File",
			{"name": ["in", adlar]},
			{"th_media_page_count": page_count, "th_media_extracted_text": text},
			update_modified=False,
		)

		baslik = (sonuc.get("title") or "").strip()
		if baslik:
			# Yalnız `th_media_title` BOŞ olan kardeşlere yaz — dolu olan
			# ELLE/başka kaynaktan girilmiş başlığı asla ezme.
			bos_olanlar = frappe.get_all(
				"File",
				filters={"name": ["in", adlar], "th_media_title": ["is", "not set"]},
				pluck="name",
			)
			if bos_olanlar:
				frappe.db.set_value(
					"File", {"name": ["in", bos_olanlar]}, "th_media_title", baslik, update_modified=False
				)
		return True
	except Exception:
		frappe.log_error(title="media.doc_meta.apply failed", message=f"{file_url}: {frappe.get_traceback()}")
		return False


def maybe_extract_on_insert(doc, method: str | None = None) -> None:
	"""`File.after_insert` kancası — public + `DOC_UZANTILAR` dosyayı kuyruğa at.

	Kapsam BİLEREK dar (`av.maybe_scan_on_insert`'in aksine): bu bir SEO
	zenginleştirmesi, güvenlik kararı değil — private belge (KYB, sözleşme
	eki) hiçbir görünür sayfada kullanılmıyor, çıkarımı gereksiz iş.

	`video_poster`/`transcode` ile aynı fast-path enqueue deseni:
	`enqueue_after_commit=True` — kayıt commit olmadan worker dosyayı disktebulamaz.
	Best-effort: hata kullanıcının yüklemesini asla düşürmez.
	"""
	try:
		if doc.get("is_folder") or doc.get("is_private"):
			return
		file_url = doc.get("file_url") or ""
		if not file_url:
			return
		if upload_policy.extension_of(file_url) not in DOC_UZANTILAR:
			return
		frappe.enqueue(
			"tradehub_core.media.doc_meta.apply",
			queue="media-maint",
			timeout=180,
			file_url=file_url,
			enqueue_after_commit=True,
		)
	except Exception:
		frappe.log_error(
			title="media.doc_meta maybe_extract_on_insert failed", message=frappe.get_traceback()
		)


def backfill_docs(limit: int = 200) -> int:
	"""Sayfa/metin alanı boş olan mevcut doküman dosyalarını SENKRON doldur.

	`video_poster.backfill_pending`'in aday sorgusuyla AYNI desen (sabit
	uzantı listesi → `LIKE` — kullanıcı girdisi değil, f-string güvenli) ama
	kuyruğa ATMAZ: PDF/Office çıkarımı ffmpeg'ten çok daha ucuz (disk okuma +
	ZIP/metin ayrıştırma, saniyenin çok altında), bu yüzden `apply()` doğrudan
	burada, senkron çağrılır — brief'in sözleşmesi bu.

	`IFNULL(th_media_page_count, 0) = 0` süzgeci NULL'u da 0'ı da yakalar
	(`av.backfill_pending`'in ölçtüğü NULL tuzağıyla aynı gerekçe: alan
	sonradan eklendiği için mevcut kayıtların tamamı NULL). Başarısız
	çıkarımda `apply()` -1 yazdığı için (anti-açlık) bu satır bir daha
	seçilmez — dönüş değeri BAŞARIYLA yazılan dosya sayısıdır.
	"""
	limit = max(1, min(2000, int(limit or 200)))
	kosul = " OR ".join(f"file_url LIKE '%%{u}'" for u in DOC_UZANTILAR)
	satirlar = frappe.db.sql(
		f"""SELECT DISTINCT file_url FROM `tabFile`
		WHERE is_private = 0 AND is_folder = 0 AND ({kosul})
		AND IFNULL(th_media_page_count, 0) = 0
		AND IFNULL(th_media_extracted_text, '') = ''
		ORDER BY creation DESC LIMIT %(limit)s""",
		{"limit": limit},
		as_dict=True,
	)  # sabit uzantı listesi — kullanıcı girdisi değil, f-string güvenli
	yazilan = 0
	for satir in satirlar:
		if apply(satir.file_url):
			yazilan += 1
	return yazilan

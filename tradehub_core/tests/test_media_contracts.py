"""Medya sözleşmeleri ↔ kod kilidi — ortak çatı (21 Ağu 2026).

`docs/MEDYA-*.md` belgelerinde yazan davranışlar burada TEST olarak yaşar.
Gerekçe: 20-21 Ağu'da iki ekip aynı modüllerde çalışırken bir sözleşme
(yükleme: ".png adlı JPEG kabul") kodda tersine döndü ve md'de kalmadı —
kimse fark etmedi. Ahmet'in `pipeline/core/state.py` testi yaşam döngüsü
aynasını kilitliyor; bu dosya aynı deseni diğer sözleşmelere uygular.

Bir test kırılırsa iki yol var ve ikisi de meşru: kodu sözleşmeye döndür, ya da
sözleşmeyi (md'yi) bilinçli değiştir ve testi güncelle — AYNI PR'da
(`scripts/check_media_contract_docs.py`).

Kapsam:
  1. Tarih (TUR-124, MEDYA-TARIH-STANDARDI.md): medya motoru API gövdesinde
     tarih ISO 8601 + kayma — epoch sayı DEĞİL.
  2. Yükleme (TUR-123, MEDYA-YUKLEME-SOZLESMESI.md §3 "Tür uyuşmazlığı",
     21 Ağu revizyonu): görsel uzantısı altında başka bilinen tür varsayılan
     RET; slot politikası "warn" derse ret YOK; tehlikeli içerik her zaman ret.
  3. Yaşam döngüsü (TUR-138): yasal tutma altındaki dosya süresi dolsa da
     çöpten silinmez (`trash.legal_hold_reason`).

Koşum:
    docker exec -w /home/frappe/frappe-bench istoc-backend bench \\
        --site tradehub.localhost run-tests \\
        --module tradehub_core.tests.test_media_contracts
"""

from __future__ import annotations

import io
import re
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import trash, upload_policy
from tradehub_core.media.pipeline.api import envelope
from tradehub_core.media.pipeline.security import content_gate

# ISO 8601, saniye çözünürlüğü, kayma zorunlu: 2026-08-14T09:39:06+03:00
_ISO_KAYMALI = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})$")


def _png_baytlari() -> bytes:
	from PIL import Image

	buf = io.BytesIO()
	Image.new("RGB", (8, 8), (30, 120, 200)).save(buf, "PNG")
	return buf.getvalue()


# ── 1. Tarih sözleşmesi ───────────────────────────────────────────────────


class TestTarihSozlesmesi(FrappeTestCase):
	def test_iso_time_kaymali_iso_uretir(self):
		"""Standart: ISO 8601 + saat dilimi kayması, mikrosaniye yok."""
		deger = envelope.iso_time(1_755_000_000.987)
		self.assertRegex(deger, _ISO_KAYMALI, deger)
		self.assertNotIn(".", deger)  # mikrosaniye kırpıldı

	def test_bos_deger_bos_dize(self):
		"""`None`/0 → "" — JSON'da tür değiştirmez, ekran "—" basabilir."""
		self.assertEqual(envelope.iso_time(None), "")
		self.assertEqual(envelope.iso_time(0), "")

	def test_api_spec_tarih_alanlari_string(self):
		"""OpenAPI belgesi tarih alanlarını sayı değil dize ilan etmeli."""
		from tradehub_core.media.pipeline.api import spec

		belge = spec.build_document()
		metin = frappe.as_json(belge)
		# `expires_at` ve `updated_at` şemada string; epoch için ayrı `expires_epoch`.
		self.assertIn('"expires_epoch"', metin)
		for alan in ("expires_at", "updated_at"):
			desen = r'"' + alan + r'":\s*\{[^{}]*"type":\s*"(\w+)"'
			for m in re.finditer(desen, metin):
				self.assertEqual(m.group(1), "string", f"{alan} epoch sayı olarak ilan edilmiş")


# ── 2. Yükleme sözleşmesi — tür uyuşmazlığı ──────────────────────────────


class TestTurUyusmazligiSozlesmesi(FrappeTestCase):
	def test_varsayilan_ret(self):
		"""21 Ağu: `.jpg` adlı PNG → `upload_type_mismatch` bulgusu (ret)."""
		bulgular = content_gate.inspect("masum.jpg", _png_baytlari())
		self.assertIn(content_gate.KOD_MISMATCH, [b.kod for b in bulgular])

	def test_warn_modunda_bulgu_yok(self):
		"""Slot politikası `warn` derse aynı dosya reddedilmez (ADR-0016)."""
		bulgular = content_gate.inspect("masum.jpg", _png_baytlari(), reject_type_mismatch=False)
		self.assertNotIn(content_gate.KOD_MISMATCH, [b.kod for b in bulgular])

	def test_tehlikeli_icerik_bayraktan_bagimsiz_ret(self):
		"""`warn` modu yalnız ZARARSIZ uyuşmazlığı gevşetir; markup her zaman ret."""
		zararli = b"<svg onload=alert(1)></svg>"
		bulgular = content_gate.inspect("resim.png", zararli, reject_type_mismatch=False)
		self.assertTrue(bulgular, "tehlikeli içerik bayrakla serbest kalmamalı")
		self.assertEqual(bulgular[0].kod, content_gate.KOD_DANGEROUS)

	def test_upload_policy_slotsuz_reddeder(self):
		"""Slot bilinmiyorsa gevşek tarafa düşülmez: varsayılan ret."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			upload_policy.check("masum.jpg", content=_png_baytlari(), media_endpoint=True)
		self.assertIn("upload_type_mismatch", str(ctx.exception))

	def test_upload_policy_warn_slotu_kabul_eder(self):
		"""Politika `accept.type_mismatch=warn` → kabul + denetime uyarı."""
		sahte_politika = {"accept": {"type_mismatch": "warn"}}
		motor = mock.Mock()
		motor.registry.get.return_value = sahte_politika
		with (
			mock.patch.object(upload_policy, "_policy_engine", return_value=motor),
			mock.patch("tradehub_core.media.audit.log_media_event") as kayit,
		):
			karar = upload_policy.check(
				"masum.jpg", content=_png_baytlari(), media_endpoint=True, slot="product.image"
			)
		self.assertTrue(karar)
		kayit.assert_called_once()
		self.assertEqual(kayit.call_args.kwargs.get("reason"), "type_mismatch_warned")

	def test_politika_okunamazsa_ret(self):
		"""Motor patlarsa "reject" — güvenlik kapısı belirsizlikte kapalıdır."""
		with mock.patch.object(upload_policy, "_policy_engine", side_effect=RuntimeError("yok")):
			self.assertEqual(upload_policy._type_mismatch_mode("product.image"), "reject")


# ── 3. Yaşam döngüsü — yasal tutma ────────────────────────────────────────


class TestYasalTutmaSozlesmesi(FrappeTestCase):
	def test_bos_url_tutulmuyor(self):
		self.assertEqual(trash.legal_hold_reason(""), "")

	def test_tablo_yoksa_sessizce_tutulmuyor(self):
		"""Medya motoru tabloları migrate edilmemişse süpürücü eskisi gibi çalışır."""
		with (
			mock.patch("frappe.db.table_exists", return_value=False),
			mock.patch("frappe.db.has_column", return_value=False),
		):
			self.assertEqual(trash.legal_hold_reason("/files/x.jpg"), "")

	def test_media_asset_hold_tutulur(self):
		"""`Media Asset.legal_hold=1` (source_file → File) → sebep döner, süpürücü atlar."""
		if not (frappe.db.table_exists("Media Asset") and frappe.db.has_column("Media Asset", "source_file")):
			self.skipTest("Media Asset.source_file yok")
		tuz = frappe.generate_hash(length=8)
		# Gerçek içerikle aç (diske yazılır); tarama kancası nötr — test_media_av deseni.
		with mock.patch("tradehub_core.media.av.enqueue_scan"):
			dosya = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"hold-{tuz}.txt",
					"is_private": 0,
					"content": f"yasal tutma {tuz}".encode(),
				}
			)
			dosya.insert(ignore_permissions=True)
		url = dosya.file_url
		self.addCleanup(lambda: frappe.delete_doc("File", dosya.name, force=True, ignore_permissions=True))
		asset = frappe.get_doc(
			{"doctype": "Media Asset", "media_type": "image", "legal_hold": 1, "source_file": dosya.name}
		)
		asset.flags.ignore_mandatory = True
		asset.flags.ignore_links = True
		asset.insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.delete_doc("Media Asset", asset.name, force=True, ignore_permissions=True)
		)

		self.assertTrue(trash.legal_hold_reason(url).startswith("media_asset:"), trash.legal_hold_reason(url))
		# tutma kalkınca sebep de kalkar
		frappe.db.set_value("Media Asset", asset.name, "legal_hold", 0)
		self.assertEqual(trash.legal_hold_reason(url), "")

	def test_okuma_hatasinda_silinmez(self):
		"""Tutma bilgisi okunamıyorsa "tutulmuyor" DENMEZ — silme geri alınamaz."""
		with mock.patch("frappe.db.table_exists", side_effect=RuntimeError("db yok")):
			self.assertEqual(trash.legal_hold_reason("/files/x.jpg"), "unknown:lookup_failed")

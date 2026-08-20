"""KVKK medya ayağı testleri — rapor 103 / iş 1 (Ö-K2 + Ö-K3).

ÖLÇÜLEN BOŞLUK (2026-08-20, rapor 92 devir #4)
==============================================
  Ö-K2  Veri-sahibi export'u (`privacy/data_export.py`) kullanıcının yüklediği
        medyayı İÇERMİYORDU (`_EXPORTABLE_DOCTYPES`te File/medya yok).
  Ö-K3  Hesap silme (`privacy/account_deletion.py`) 10 `_anonymize_*` adımının
        HİÇBİRİNDE medya adımı yoktu — silinen hesabın medyası anonimleştirilmiyordu.

Bu dosya iki eklemeyi pinler:
  1a  export'a kullanıcının KENDİ medyası girer, BAŞKASININKİ GİRMEZ. Sınırı
      `ownership.scope` çizer; onu gevşetmek (no-op) başkasının dosyasını export'a
      sızdırır → VACUITY testi bunu kırmızıya çevirir.
  1b  silmede medya anonimleştirme adımı ÇALIŞIR: kullanılmayan medya geri
      alınabilir çöpe taşınır, KULLANIMDAKİ (legal-hold) medya KORUNUR, ve tek
      `privacy.media_anonymized` özet denetim satırı yazılır.

Medya katmanı (inventory/ownership/trash/usage) SAHTE modüllerle ikame edilir —
bu testin konusu privacy fonksiyonlarının SÖZLEŞMESİ (hangi süzgeci/kararı
uyguladığı), medya sorgusunun kendisi değil (o `test_media_access_level` vb.
altında pinli). Denetim satırı için gerçek `log_decision` KOŞULUR (_AdlDoc).

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_privacy_media
"""

from __future__ import annotations

import sys
import types
import unittest

from tradehub_core.tests.test_privacy_audit import _INSERTED, PrivacyAuditStubCase, frappe

from tradehub_core.privacy import account_deletion, data_export


# ── Sahte sorgu katmanı ──────────────────────────────────────────────────────


class _FakeCol:
	def __init__(self, name: str):
		self.name = name

	def __eq__(self, other):  # `f.owner == user` → yüklenebilir yüklem
		return ("eq", self.name, other)


class _FakeFile:
	def __getattr__(self, name):
		return _FakeCol(name)


class _FakeQuery:
	"""Bellek-içi `tabFile` — `_base_query`/`scope`/`where`/`select` modeli."""

	def __init__(self, rows, preds=None, owner_restrict=None):
		self.rows = rows
		self.preds = preds or []
		self.owner_restrict = owner_restrict

	def where(self, pred):
		return _FakeQuery(self.rows, [*self.preds, pred], self.owner_restrict)

	def restrict_owners(self, owners):
		return _FakeQuery(self.rows, self.preds, set(owners))

	def select(self, *cols):
		return self

	def run(self, as_dict=False):
		out = []
		for r in self.rows:
			if any(p[0] == "eq" and r.get(p[1]) != p[2] for p in self.preds):
				continue
			if self.owner_restrict is not None and r.get("owner") not in self.owner_restrict:
				continue
			out.append(
				{
					"file_url": r["file_url"],
					"file_name": r.get("file_name"),
					"file_size": r.get("file_size"),
					"uploaded_at": r.get("creation"),
				}
			)
		return out


class _MediaFakeCase(PrivacyAuditStubCase):
	"""Medya alt-modüllerini sahtelerle ikame eder; teardown'da geri alır."""

	def _inject_module(self, dotted: str, module) -> None:
		parent_name, _, leaf = dotted.rpartition(".")
		parent = sys.modules.get(parent_name)
		self._mod_orijinal.append((dotted, sys.modules.get(dotted)))
		sys.modules[dotted] = module
		if parent is not None:
			self._attr_orijinal.append((parent, leaf, getattr(parent, leaf, self._YOK_ATTR)))
			setattr(parent, leaf, module)

	_YOK_ATTR = object()

	def setUp(self):
		super().setUp()
		self._mod_orijinal: list = []
		self._attr_orijinal: list = []
		# `_collect_user_media`in `Min/Max` çağrıları — alias'ı yutan sahte.
		self._patch_qb_functions()
		self.addCleanup(self._restore_media_fakes)

	def _patch_qb_functions(self) -> None:
		class _Alias:
			def as_(self, alias):
				return self

		fake = types.SimpleNamespace(Min=lambda *a, **k: _Alias(), Max=lambda *a, **k: _Alias())
		self._inject_module("frappe.query_builder.functions", fake)

	def _restore_media_fakes(self) -> None:
		for parent, leaf, eski in reversed(self._attr_orijinal):
			if eski is self._YOK_ATTR:
				try:
					delattr(parent, leaf)
				except AttributeError:
					pass
			else:
				setattr(parent, leaf, eski)
		for dotted, eski in reversed(self._mod_orijinal):
			if eski is None:
				sys.modules.pop(dotted, None)
			else:
				sys.modules[dotted] = eski


# ── 1a — export kendi medyasını içerir, başkasınınkini değil ──────────────────


class ExportMediaScopeTests(_MediaFakeCase):
	ROWS = [
		{"owner": "a@x.com", "file_url": "/files/a1.jpg", "file_name": "a1.jpg", "file_size": 100, "creation": "2026-01-01"},
		{"owner": "b@x.com", "file_url": "/files/b1.jpg", "file_name": "b1.jpg", "file_size": 200, "creation": "2026-01-02"},
	]
	USER_STORE = {"a@x.com": "STORE-A", "b@x.com": "STORE-B"}
	STORE_MEMBERS = {"STORE-A": {"a@x.com"}, "STORE-B": {"b@x.com"}}

	def _install(self, *, scope_active: bool):
		rows = self.ROWS
		fake_inventory = types.SimpleNamespace(_base_query=lambda: (_FakeFile(), _FakeQuery(rows)))

		def store_of(user):
			return self.USER_STORE.get(user)

		def scope(query, f, store):
			if not scope_active:
				return query  # VACUITY: maske gevşetildi
			return query.restrict_owners(self.STORE_MEMBERS[store])

		fake_ownership = types.SimpleNamespace(store_of=store_of, scope=scope)
		self._inject_module("tradehub_core.media.inventory", fake_inventory)
		self._inject_module("tradehub_core.media.ownership", fake_ownership)

	def test_export_kendi_medyasini_icerir_baskasininkini_degil(self):
		self._install(scope_active=True)
		rows = data_export._collect_user_media("a@x.com")
		urls = {r["file_url"] for r in rows}
		self.assertIn("/files/a1.jpg", urls, "Kendi medyası export'a girmedi.")
		self.assertNotIn("/files/b1.jpg", urls, "Başkasının dosyası export'a sızdı!")

	def test_magazasiz_kullanici_bos_doner(self):
		self._install(scope_active=True)
		self.assertEqual(data_export._collect_user_media("nobody@x.com"), [])

	def test_vacuity_maske_gevsetilince_baskasinin_dosyasi_sizar(self):
		# `ownership.scope` no-op yapılınca B'nin dosyası A'nın export'una sızmalı
		# (yani sınırı SCOPE çiziyor; onu kaldırmak testi kırmızıya çevirir).
		self._install(scope_active=False)
		urls = {r["file_url"] for r in data_export._collect_user_media("a@x.com")}
		self.assertIn("/files/b1.jpg", urls, "Vacuity başarısız: gevşetme sızıntı üretmedi.")


# ── 1b — silmede medya anonimleştirme adımı ───────────────────────────────────


class DeletionMediaAnonymizeTests(_MediaFakeCase):
	OWNER = "seller-a@x.com"
	ROWS = [
		{"owner": OWNER, "file_url": "/files/fu1.jpg", "file_name": "fu1.jpg", "file_size": 10, "creation": "2026-01-01"},
		{"owner": OWNER, "file_url": "/files/fu2.jpg", "file_name": "fu2.jpg", "file_size": 20, "creation": "2026-01-02"},
		{"owner": OWNER, "file_url": "/files/fu3.jpg", "file_name": "fu3.jpg", "file_size": 30, "creation": "2026-01-03"},
		{"owner": "seller-b@x.com", "file_url": "/files/fuB.jpg", "file_name": "fuB.jpg", "file_size": 40, "creation": "2026-01-04"},
	]
	VERDICTS = {
		"/files/fu1.jpg": "unused",     # → çöpe
		"/files/fu2.jpg": "in_use",     # → korunur (legal-hold)
		"/files/fu3.jpg": "unused",     # → ama zaten çöpte → korunur
		"/files/fuB.jpg": "unused",     # → BAŞKASININ, hiç toplanmamalı
	}
	ALREADY_TRASHED = {"/files/fu3.jpg"}

	def setUp(self):
		super().setUp()
		self.trashed_calls: list[str] = []
		rows = self.ROWS
		fake_inventory = types.SimpleNamespace(_base_query=lambda: (_FakeFile(), _FakeQuery(rows)))
		self._inject_module("tradehub_core.media.inventory", fake_inventory)

		def move_to_trash(url, force=False):
			self.trashed_calls.append(url)
			return {"file_url": url}

		fake_trash = types.SimpleNamespace(
			TRASHABLE_VERDICTS=frozenset({"unused", "history_only"}),
			in_trash=lambda url: url in self.ALREADY_TRASHED,
			move_to_trash=move_to_trash,
		)
		fake_usage = types.SimpleNamespace(verdict_map_all=lambda deep=False: dict(self.VERDICTS))
		self._inject_module("tradehub_core.media.trash", fake_trash)
		self._inject_module("tradehub_core.media.usage", fake_usage)

	def test_yalniz_kullanilmayan_kendi_medyasi_cope_tasinir(self):
		sonuc = account_deletion._anonymize_user_media(self.OWNER)
		# fu1 kullanılmıyor → taşınır. fu2 kullanımda, fu3 zaten çöpte → korunur.
		self.assertEqual(self.trashed_calls, ["/files/fu1.jpg"])
		self.assertNotIn("/files/fuB.jpg", self.trashed_calls, "Başkasının dosyasına dokunuldu!")
		self.assertEqual(sonuc, {"trashed": 1, "retained": 2})

	def test_anonimlestirme_ozet_denetim_satiri_yazar(self):
		account_deletion._anonymize_user_media(self.OWNER)
		kayitlar = [k for k in _INSERTED if k.get("action") == "privacy.media_anonymized"]
		self.assertEqual(len(kayitlar), 1, "KVKK m.7 medya adımı özet satırı yazmadı.")
		kayit = kayitlar[0]
		self.assertEqual(kayit["decision"], "ALLOW")
		self.assertEqual(kayit["object_name"], self.OWNER)
		self.assertIn("trashed", kayit["context"])
		self.assertIn("/files/fu1.jpg", kayit["context"])

	def test_kullanimdaki_medya_korunur_legal_hold(self):
		account_deletion._anonymize_user_media(self.OWNER)
		self.assertNotIn("/files/fu2.jpg", self.trashed_calls, "Kullanımdaki (legal-hold) medya taşındı!")

	def test_vacuity_medyasi_olmayan_kullanici_iz_birakmaz(self):
		# Toplanacak medya yoksa adım erken döner ve özet satır YAZILMAZ — yani
		# `privacy.media_anonymized` satırı gerçekten yaptığı işe bağlı (boş değil).
		sonuc = account_deletion._anonymize_user_media("hicdosyasiyok@x.com")
		self.assertEqual(sonuc, {"trashed": 0, "retained": 0})
		self.assertEqual(
			[k for k in _INSERTED if k.get("action") == "privacy.media_anonymized"], []
		)


if __name__ == "__main__":
	unittest.main()

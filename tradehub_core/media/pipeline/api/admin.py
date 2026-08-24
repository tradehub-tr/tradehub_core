"""T-084 — Yönetim uçları. **YALNIZ EKSİK OLANLAR.**

MEVCUT 39 UÇ OKUNDU, TEKRARLANMADI
----------------------------------
`tradehub_core/api/media_admin.py` bugün 39 whitelist ucu barındırıyor ve
hepsi rol kapılı (`ALLOWED_ROLES` = System Manager + Marketplace Admin,
geri alınamaz işlemler yalnız System Manager). Kapsadığı alanlar:

    envanter/optimizasyon   get_image_inventory, start_image_optimization,
                            get_optimization_status, restore_image, retry_transcode
    çöp/arşiv               preview_trash, trash_files, restore_from_trash,
                            delete_trashed, purge_trash, purge_archive,
                            get_restorable_count, get_pending_count
    denetim                 get_media_audit(+facets/actors/report/targets), export_media_audit
    yedek/geri yükleme      list/create/verify/plan/apply/prune/delete_media_backup,
                            start/status/discard/download_media_backup_export,
                            repair_missing_media, start_restore
    erişim/gezinme          set_access_level, get_private_files, browse_media,
                            get_record_media, get_file_usage, get_file_references
    öksüz/bağ               get_dangling_references, repair_dangling_references
    tarama/karantina        scan_overview, list_scan_hold, sweep_scans,
                            list_quarantine, retry_scan, release_quarantine, scan_backfill

Bu dosya o listeye **hiçbir şey tekrar etmez**. Eklediği dokuz uç, medya
motorunun Faz 2-7'de üretilen ama yönetim yüzeyi HİÇ OLMAYAN parçalarını
görünür kılar:

    1. list_slot_policies   9 slot politikası bugün yalnız dosyada; panelde yok.
    2. get_slot_policy      Tek slotun tam metni + ETag.
    3. validate_policies    Politika dosyalarının yapısal tutarlılığı.
    4. rendition_matrix     Hangi slot kaç profil × kaç biçim üretir.
    5. evaluate_policy      KURU ÇALIŞTIRMA: bir künye bu slottan geçer mi.
    6. delivery_coverage    Kaç varlığın merdiveni TAM — 13,14 MB sorununun ölçüsü.
    7. plan_reprocess       Bir varlık yeniden işlenmeli mi (idempotensi defteri).
    8. job_status           İş anahtarının durumu (core/jobs idempotensi kilidi).
    9. storage_plan         Etkin depolama kipi + bozulma (degraded) durumu.

HİÇBİRİ YAZMA YAPMAZ
--------------------
Dokuz ucun dokuzu da **okuma**dır. Yıkıcı işlemler (`purge_*`, `delete_*`)
zaten `media_admin.py`'de ve orada `DESTRUCTIVE_ROLES` kapısının arkasında;
ikinci bir yıkıcı yüzey açmak, o kapının etrafından dolaşan bir yol açmak
olurdu. `plan_reprocess` adı bilinçli: planı verir, işi kuyruğa ATMAZ.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol

from tradehub_core.media.pipeline.api import envelope as env
from tradehub_core.media.pipeline.contracts.errors import PolicyNotFound, kod_uret
from tradehub_core.media.pipeline.core import jobs as jobs_mod
from tradehub_core.media.pipeline.core import probe as probe_mod
from tradehub_core.media.pipeline.image import render as render_mod
from tradehub_core.media.pipeline.image import reprocess as reprocess_mod
from tradehub_core.media.pipeline.policy import engine as policy_engine

#: `delivery_coverage` tek çağrıda en fazla bu kadar varlık tarar. Kapak
#: olmadan çağrı bütün kütüphaneyi (canlı ölçümde 4.958 dosya) istek içinde
#: gezerdi.
COVERAGE_MAX_SCAN: int = 5000

#: Politika dosyalarında şemaya ek olarak ARANAN operasyonel alanlar. Tam
#: doğrulama `policy/schema/slot-policy.schema.json` ile Draft 2020-12 olarak
#: yapılır; bu liste yönetim ekranına daha kısa, eyleme dönük bulgu üretir.
REQUIRED_POLICY_KEYS: tuple[str, ...] = (
	"slot_key",
	"schema_version",
	"status",
	"accept",
	"on_violation",
	"messages",
)


class CoverageRepository(Protocol):
	"""Teslim kapsamı ölçümü için varlık akışı."""

	def iter_assets(self, *, slot_key: str = "", limit: int = 0) -> Sequence[Mapping[str, Any]]:
		"""`slot_key` + `available_profiles` taşıyan satırlar."""
		...


@dataclass
class AdminApi:
	"""Yönetim uçları. Saf Python — `@frappe.whitelist()` YOK.

	Args:
	    policy: `policy.engine.PolicyEngine`. Verilmezse `default_engine()`.
	    coverage: Kapsam ölçümü portu. Yoksa `delivery_coverage` 503 döner.
	    guard: `core.jobs` idempotensi kilidi. Yoksa `job_status` 503 döner.
	    ledger: Türev defteri (`image.reprocess.RenditionLedger`).
	    storage_conf: `storage.build_from_mapping` için ayar sözlüğü.
	    on_denied: Yetki reddi kancası (denetim kaydı) — `media_admin._only_for`
	        ile aynı sözleşme.
	"""

	#: Sözleşmedeki uç noktalar — bkz. `upload.UploadApi.ENDPOINTS` notu.
	#: DOKUZU DA OKUMA. Yıkıcı işlemler `tradehub_core/api/media_admin.py`'de
	#: kalır; ikinci bir yıkıcı yüzey, oradaki `DESTRUCTIVE_ROLES` kapısının
	#: etrafından dolaşan bir yol açardı.
	ENDPOINTS: ClassVar[tuple[str, ...]] = (
		"list_slot_policies",
		"get_slot_policy",
		"validate_policies",
		"rendition_matrix",
		"evaluate_policy",
		"delivery_coverage",
		"plan_reprocess",
		"job_status",
		"storage_plan",
	)

	policy: Any = None
	coverage: CoverageRepository | None = None
	guard: Any = None
	ledger: reprocess_mod.RenditionLedger | None = None
	storage_conf: Mapping[str, Any] | None = None
	on_denied: env.DenialHook | None = None
	_matrix_cache: dict[str, Any] = field(default_factory=dict, repr=False)

	def __post_init__(self) -> None:
		if self.policy is None:
			self.policy = policy_engine.default_engine()

	# ── kapı ───────────────────────────────────────────────────────────

	def _guard(self, principal: env.Principal, scope: str) -> env.Principal:
		"""Rol kapısı — `media_admin._guard` ile AYNI rol kümesi."""
		return env.require_roles(
			principal, env.ADMIN_ROLES, scope=scope, on_denied=self.on_denied
		)

	def _policy_of(self, slot_key: str) -> dict:
		try:
			return self.policy.registry.get(slot_key)
		except policy_engine.PolicyNotFound:
			raise PolicyNotFound(
				f"Bilinmeyen slot: {slot_key}",
				detay={"slot_key": slot_key, "known": list(self.policy.registry.keys())},
			)

	# ── 1. list_slot_policies ──────────────────────────────────────────

	def list_slot_policies(
		self, principal: env.Principal, *, if_none_match: str = ""
	) -> env.ApiResponse:
		"""Kayıt defterindeki tüm slotların özeti.

		Bugün 9 slot politikası yalnız `tradehub_core/media/pipeline/policy/slots/*.json`
		dosyalarında duruyor; panelde hangi slotun hangi tavanla çalıştığını
		gösteren bir yüzey YOK. Bu uç o boşluğu kapatır.
		"""
		self._guard(principal, "media_policy_read")
		satirlar: list[dict[str, Any]] = []
		for anahtar in self.policy.registry.keys():
			pol = self.policy.registry.get(anahtar)
			accept = pol.get("accept") or {}
			profiller = pol.get("profiles") or []
			satirlar.append(
				{
					"slot_key": anahtar,
					"title": pol.get("title", ""),
					"status": pol.get("status", ""),
					"schema_version": pol.get("schema_version", ""),
					"roles": list(pol.get("roles") or []),
					"max_bytes": int(accept.get("max_bytes") or 0),
					"max_megapixels_hard": accept.get("max_megapixels_hard"),
					"profile_count": len(profiller),
					"rendition_count": sum(len(p.get("formats") or ()) for p in profiller),
					"content_rule_count": len(pol.get("content_rules") or []),
					"is_video": bool(pol.get("video")),
					"error_code_prefix": (pol.get("on_violation") or {}).get(
						"error_code_prefix", ""
					),
					"source": str(self.policy.registry.source_of(anahtar)),
				}
			)
		govde = {"slots": satirlar, "count": len(satirlar)}
		return env.conditional_get(govde, if_none_match)

	# ── 2. get_slot_policy ─────────────────────────────────────────────

	def get_slot_policy(
		self, principal: env.Principal, slot_key: str, *, if_none_match: str = ""
	) -> env.ApiResponse:
		"""Tek slotun politikasının TAMAMI — mesaj metinleri ve kaynak notları dâhil.

		Kısaltılmış hâli döndürmek cazipti (gövde büyük), ama politikadaki
		`sources` bloğu her sayının nereden geldiğini yazıyor ve bir yönetici
		"bu eşik neden 1000 piksel" sorusunu ancak orayı görerek yanıtlar.
		"""
		self._guard(principal, "media_policy_read")
		anahtar = env.require_str(slot_key, "slot_key", max_len=64)
		pol = self._policy_of(anahtar)
		govde = {
			"slot_key": anahtar,
			"policy": pol,
			"source": str(self.policy.registry.source_of(anahtar)),
		}
		return env.conditional_get(govde, if_none_match)

	# ── 3. validate_policies ───────────────────────────────────────────

	def validate_policies(self, principal: env.Principal) -> env.ApiResponse:
		"""Politika dosyalarının **yapısal** tutarlılığı.

		Ne DOĞRULANIR:
		  * zorunlu üst düzey alanlar (`REQUIRED_POLICY_KEYS`),
		  * `slot_key` benzersizliği (kayıt defteri zaten çakışmada patlar),
		  * profil adlarının benzersizliği ve genişliklerin ARTAN sırada olması,
		  * her profilin en az bir biçimi olması ve `render.PIL_FORMAT`'ta
		    tanınması,
		  * `messages.tr` ve `messages.en` anahtar kümelerinin AYNI olması —
		    biri eksikse o dilde kullanıcı ham kod görür,
		  * `on_violation.error_code_prefix` varlığı.

		JSON-Schema ayrıca Draft 2020-12 doğrulayıcısıyla çalıştırılır. Paket ya
		şema okunamazsa `schema_validated=false`; şema çalıştı ve dosya bozuksa
		`schema_validated=true` kalır ama `schema_validation` bulgusu üretilir.
		"""
		self._guard(principal, "media_policy_read")
		bulgular: list[dict[str, Any]] = []
		sema_dogrulandi, sema_notu, sema_bulgulari = self._validate_json_schema()
		bulgular.extend(sema_bulgulari)

		for anahtar in self.policy.registry.keys():
			pol = self.policy.registry.get(anahtar)
			kaynak = str(self.policy.registry.source_of(anahtar))

			for alan in REQUIRED_POLICY_KEYS:
				if alan not in pol:
					bulgular.append(
						self._finding(anahtar, kaynak, "missing_key", f"`{alan}` alanı yok")
					)

			if not (pol.get("on_violation") or {}).get("error_code_prefix"):
				bulgular.append(
					self._finding(
						anahtar, kaynak, "missing_error_prefix",
						"`on_violation.error_code_prefix` yok; ret kodları `media_` önekine düşer",
					)
				)

			bulgular.extend(self._check_profiles(anahtar, kaynak, pol))
			bulgular.extend(self._check_messages(anahtar, kaynak, pol))

		govde = {
			"slot_count": len(self.policy.registry.keys()),
			"finding_count": len(bulgular),
			"findings": bulgular,
			"ok": not bulgular,
			"schema_validated": sema_dogrulandi,
			"schema_note": sema_notu,
		}
		return env.ok(govde)

	def _validate_json_schema(self) -> tuple[bool, str, list[dict[str, Any]]]:
		"""Kayıt defterindeki her politikayı kanonik Draft 2020-12 şemasıyla doğrula."""
		try:
			from jsonschema import Draft202012Validator
		except ImportError:
			return False, "JSON-Schema doğrulaması YAPILMADI: `jsonschema` paketi kurulu değil.", []

		try:
			kok = Path(self.policy.source_root()).resolve()
			sema_yolu = kok.parent / "schema" / "slot-policy.schema.json"
			sema = json.loads(sema_yolu.read_text(encoding="utf-8"))
			Draft202012Validator.check_schema(sema)
			dogrulayici = Draft202012Validator(sema)
		except Exception as exc:
			return False, f"JSON-Schema okunamadı: {type(exc).__name__}: {exc}", []

		bulgular: list[dict[str, Any]] = []
		for slot in self.policy.registry.keys():
			pol = self.policy.registry.get(slot)
			kaynak = str(self.policy.registry.source_of(slot))
			for hata in sorted(dogrulayici.iter_errors(pol), key=lambda e: list(e.absolute_path)):
				yol = ".".join(str(x) for x in hata.absolute_path) or "$"
				bulgular.append(
					self._finding(slot, kaynak, "schema_validation", f"{yol}: {hata.message}")
				)
		return True, f"Draft 2020-12 doğrulaması çalıştı: {len(self.policy.registry.keys())} politika.", bulgular

	@staticmethod
	def _finding(slot: str, source: str, code: str, message: str) -> dict[str, Any]:
		return {"slot_key": slot, "source": source, "code": code, "message": message}

	def _check_profiles(self, slot: str, source: str, pol: Mapping[str, Any]) -> list[dict[str, Any]]:
		bulgular: list[dict[str, Any]] = []
		profiller = pol.get("profiles") or []
		if not profiller:
			bulgular.append(self._finding(slot, source, "no_profiles", "Hiç türev profili yok"))
			return bulgular

		adlar = [str(p.get("name") or "") for p in profiller]
		if len(set(adlar)) != len(adlar):
			bulgular.append(
				self._finding(slot, source, "duplicate_profile", f"Profil adı tekrarı: {adlar}")
			)

		genislikler = [int(p.get("width") or 0) for p in profiller]
		if genislikler != sorted(genislikler):
			# Sıra bozuksa `pick()` yine doğru çalışır (kendi sıralamasını
			# yapar) ama insan okuması bozulur ve merdiven boşluğu gözden
			# kaçar. Bu bir UYARI, kırılma değil.
			bulgular.append(
				self._finding(
					slot, source, "profiles_unsorted",
					f"Profil genişlikleri artan sırada değil: {genislikler}",
				)
			)

		for p in profiller:
			ad = str(p.get("name") or "?")
			formatlar = p.get("formats") or []
			if not formatlar:
				bulgular.append(
					self._finding(slot, source, "profile_no_format", f"`{ad}` profilinin biçimi yok")
				)
			for f in formatlar:
				if f not in render_mod.PIL_FORMAT:
					bulgular.append(
						self._finding(
							slot, source, "unknown_format",
							f"`{ad}` profilinde tanınmayan biçim: {f}",
						)
					)
			if int(p.get("width") or 0) <= 0:
				bulgular.append(
					self._finding(slot, source, "bad_width", f"`{ad}` genişliği pozitif değil")
				)
		return bulgular

	def _check_messages(self, slot: str, source: str, pol: Mapping[str, Any]) -> list[dict[str, Any]]:
		mesajlar = pol.get("messages") or {}
		tr = set((mesajlar.get("tr") or {}).keys())
		en = set((mesajlar.get("en") or {}).keys())
		bulgular: list[dict[str, Any]] = []
		for eksik, dil in ((tr - en, "en"), (en - tr, "tr")):
			if eksik:
				bulgular.append(
					self._finding(
						slot, source, "message_parity",
						f"`{dil}` dilinde eksik mesaj anahtarları: {sorted(eksik)}",
					)
				)
		return bulgular

	# ── 4. rendition_matrix ────────────────────────────────────────────

	def rendition_matrix(
		self, principal: env.Principal, *, slot_key: str = "", if_none_match: str = ""
	) -> env.ApiResponse:
		"""Üretim matrisi: hangi slot kaç profil × kaç biçim üretiyor.

		Bu sayı doğrudan maliyettir — her satır bir encode, bir dosya, bir
		depo nesnesi demek. `slot_key` verilmezse tüm slotlar toplanır.
		"""
		self._guard(principal, "media_policy_read")
		anahtarlar = (
			(env.require_str(slot_key, "slot_key", max_len=64),) if slot_key else render_mod.slot_keys()
		)
		slotlar: list[dict[str, Any]] = []
		toplam = 0
		for s in anahtarlar:
			try:
				matris = render_mod.rendition_matrix(s)
			except render_mod.RenderError:
				raise PolicyNotFound(f"Bilinmeyen slot: {s}", detay={"slot_key": s})
			satirlar = [
				{
					"profile": p.name,
					"width": p.width,
					"height": p.height,
					"format": f,
					"fit": p.fit,
					"target_ratio": p.target_ratio,
					"quality": p.quality_for(f),
					"quality_calibrated": p.quality_for(f) is not None,
					"serves": list(p.serves),
				}
				for p, f in matris
			]
			toplam += len(satirlar)
			slotlar.append(
				{
					"slot_key": s,
					"profile_count": len(render_mod.load_profiles(s)),
					"rendition_count": len(satirlar),
					"renditions": satirlar,
				}
			)
		govde = {"slots": slotlar, "total_renditions": toplam}
		return env.conditional_get(govde, if_none_match)

	# ── 5. evaluate_policy ─────────────────────────────────────────────

	def evaluate_policy(
		self,
		principal: env.Principal,
		*,
		slot_key: str,
		probe: Mapping[str, Any],
		role: str = "",
	) -> env.ApiResponse:
		"""KURU ÇALIŞTIRMA — bir künye bu slottan geçer mi.

		Dosya yüklemeden, kuyruğa iş atmadan, tek bir bayt yazmadan politikayı
		çalıştırır. Kalibrasyon işinin temel aleti: bir eşiği değiştirmeden
		önce "kaç dosya düşer" sorusunu yanıtlamanın yolu, gerçek künyeleri bu
		uçtan geçirmektir.

		`probe` `core/probe.py::MediaProbe` alanlarını taşır; tanınmayan
		alanlar SESSİZCE ATILIR (motorun kendi davranışı), ama yanıt hangi
		alanların kullanıldığını `accepted_fields` ile bildirir — sessiz
		yutulma kalibrasyonu yanıltırdı.
		"""
		self._guard(principal, "media_policy_eval")
		anahtar = env.require_str(slot_key, "slot_key", max_len=64)
		self._policy_of(anahtar)
		if not isinstance(probe, Mapping):
			raise env.BadRequest(
				"`probe` bir sözlük olmalı.",
				kod=kod_uret(env.API_PREFIX, "bad_field"),
				detay={"field": "probe"},
			)
		bilinen = set(probe_mod.MediaProbe.__dataclass_fields__)
		kullanilan = sorted(k for k in probe if k in bilinen)
		yoksayilan = sorted(k for k in probe if k not in bilinen)

		karar = self.policy.evaluate(anahtar, dict(probe), str(role or ""))
		govde = dict(karar.to_dict())
		govde["accepted_fields"] = kullanilan
		govde["ignored_fields"] = yoksayilan
		return env.ok(govde)

	# ── 6. delivery_coverage ───────────────────────────────────────────

	def delivery_coverage(
		self, principal: env.Principal, *, slot_key: str = "", limit: Any = 0
	) -> env.ApiResponse:
		"""Kaç varlığın türev merdiveni TAM.

		Bu, 13,14 MB / 900 KB = 15× sorununun ilerleme ölçüsüdür: merdiven
		tamamlanmadan `srcset` yazılamaz, `srcset` yazılmadan sayı düşmez.

		Ölçülen tek şey, kayıttaki `available_profiles` listesinin politikanın
		profil kümesini kapsayıp kapsamadığıdır. **Dosyanın gerçekten diskte
		olduğu doğrulanmaz** — bu uç depoya gitmez; o iş `media_admin`'in
		`verify_media_backup`/`repair_missing_media` uçlarının işidir.
		"""
		self._guard(principal, "media_coverage_read")
		if self.coverage is None:
			raise env.ServiceUnavailable(
				"Kapsam ölçümü için varlık kaynağı yapılandırılmamış.",
				kod=kod_uret(env.API_PREFIX, "no_coverage_source"),
			)
		tavan = env.require_int(limit or COVERAGE_MAX_SCAN, "limit", minimum=1, maximum=COVERAGE_MAX_SCAN)
		anahtar = env.require_str(slot_key, "slot_key", max_len=64) if slot_key else ""
		if anahtar:
			self._policy_of(anahtar)

		beklenen: dict[str, set] = {}
		sayaclar: dict[str, dict[str, int]] = {}
		eksik_profil: dict[str, dict[str, int]] = {}
		taranan = 0

		for row in self.coverage.iter_assets(slot_key=anahtar, limit=tavan):
			taranan += 1
			s = str(row.get("slot_key") or "")
			if not s:
				sayaclar.setdefault("", {"total": 0, "complete": 0, "partial": 0, "empty": 0})
				sayaclar[""]["total"] += 1
				sayaclar[""]["empty"] += 1
				continue
			if s not in beklenen:
				try:
					beklenen[s] = {p.name for p in render_mod.load_profiles(s)}
				except render_mod.RenderError:
					beklenen[s] = set()
			hedef = beklenen[s]
			mevcut = {str(p) for p in (row.get("available_profiles") or ())}
			kova = sayaclar.setdefault(s, {"total": 0, "complete": 0, "partial": 0, "empty": 0})
			kova["total"] += 1
			if not mevcut:
				kova["empty"] += 1
			elif hedef and hedef.issubset(mevcut):
				kova["complete"] += 1
			else:
				kova["partial"] += 1
			for p in hedef - mevcut:
				eksik_profil.setdefault(s, {})
				eksik_profil[s][p] = eksik_profil[s].get(p, 0) + 1

		toplam = sum(k["total"] for k in sayaclar.values())
		tam = sum(k["complete"] for k in sayaclar.values())
		govde = {
			"scanned": taranan,
			"limit": tavan,
			"truncated": taranan >= tavan,
			"total": toplam,
			"complete": tam,
			"complete_ratio": round(tam / toplam, 6) if toplam else 0.0,
			"by_slot": {
				s: dict(k, expected_profiles=sorted(beklenen.get(s, ())),
						missing_profile_counts=eksik_profil.get(s, {}))
				for s, k in sorted(sayaclar.items())
			},
		}
		return env.ok(govde)

	# ── 7. plan_reprocess ──────────────────────────────────────────────

	def plan_reprocess(
		self,
		principal: env.Principal,
		*,
		slot_key: str,
		master_sha256: str,
		crop_intent: Mapping[str, Any] | None = None,
		force: bool = False,
	) -> env.ApiResponse:
		"""Bu master için hangi türevler üretilecek — **planı verir, iş atmaz.**

		Kararı `image/reprocess.py::decide` verir; bu uç yalnız merdivenin
		tamamı için onu çağırır ve özetler. `action` üç değerden biridir:

		    skip     defterde aynı motor sürümüyle üretilmiş kayıt var
		    refresh  kayıt var ama BAŞKA motor sürümüyle üretilmiş (bayat)
		    render   hiç üretilmemiş

		`force=True` hepsini `render`a çevirir — kararı görmek için, uygulamak
		için değil.
		"""
		self._guard(principal, "media_reprocess_plan")
		anahtar = env.require_str(slot_key, "slot_key", max_len=64)
		sha = env.require_str(master_sha256, "master_sha256", max_len=64)
		if self.ledger is None:
			raise env.ServiceUnavailable(
				"Türev defteri yapılandırılmamış; yeniden işleme planı çıkarılamaz.",
				kod=kod_uret(env.API_PREFIX, "no_ledger"),
			)
		try:
			matris = render_mod.rendition_matrix(anahtar)
		except render_mod.RenderError:
			raise PolicyNotFound(f"Bilinmeyen slot: {anahtar}", detay={"slot_key": anahtar})

		satirlar: list[dict[str, Any]] = []
		sayac: dict[str, int] = {
			reprocess_mod.ACTION_RENDER: 0,
			reprocess_mod.ACTION_REFRESH: 0,
			reprocess_mod.ACTION_SKIP: 0,
		}
		for profil, fmt in matris:
			karar = reprocess_mod.decide(
				master_sha256=sha,
				profile=profil,
				fmt=fmt,
				ledger=self.ledger,
				crop_intent=crop_intent,
				force=bool(force),
			)
			sayac[karar.action] = sayac.get(karar.action, 0) + 1
			satirlar.append(
				{
					"profile": profil.name,
					"format": fmt,
					"width": profil.width,
					"action": karar.action,
					"reason": karar.reason,
					"key": karar.key,
					"should_render": karar.should_render,
				}
			)

		govde = {
			"slot_key": anahtar,
			"master_sha256": sha,
			"force": bool(force),
			"counts": sayac,
			"work_units": sayac[reprocess_mod.ACTION_RENDER] + sayac[reprocess_mod.ACTION_REFRESH],
			"plan": satirlar,
		}
		return env.ok(govde)

	# ── 8. job_status ──────────────────────────────────────────────────

	def job_status(
		self, principal: env.Principal, *, kind: str, target: str, content_hash: str = "",
		params: Mapping[str, Any] | None = None,
	) -> env.ApiResponse:
		"""Bir işin idempotensi anahtarı ve o anahtarın durumu.

		`media_admin.get_optimization_status` bir İŞ ANAHTARINI zaten
		sorguluyor ama anahtarı istemci uyduruyor. Burada anahtar
		`core/jobs.py::idempotency_key` ile ÜRETİLİR: aynı içerik farklı adla
		iki kez yüklenirse aynı anahtar çıkar ve iş bir kez yapılır. İki yerde
		iki farklı anahtar üretmek, kilidi hiç koymamakla aynı şeydir.
		"""
		self._guard(principal, "media_job_read")
		tur = env.require_str(kind, "kind", max_len=64)
		if tur not in jobs_mod.JOB_KINDS:
			raise env.BadRequest(
				f"Bilinmeyen iş türü: {tur}",
				kod=kod_uret(env.API_PREFIX, "bad_field"),
				detay={"field": "kind", "allowed": list(jobs_mod.JOB_KINDS)},
			)
		hedef = str(target or "")
		sha = str(content_hash or "")
		if not (hedef or sha):
			raise env.BadRequest(
				"`target` ya da `content_hash` zorunlu.",
				kod=kod_uret(env.API_PREFIX, "missing_field"),
				detay={"field": "target|content_hash"},
			)
		zarf = jobs_mod.JobEnvelope.build(
			tur, hedef, content_hash=sha, params=dict(params or {})
		)
		govde: dict[str, Any] = {
			"key": zarf.key,
			"kind": zarf.kind,
			"max_attempts": jobs_mod.MAX_ATTEMPTS,
			"backoff_seconds": list(jobs_mod.BACKOFF_SECONDS),
			"stale_after_seconds": jobs_mod.STALE_AFTER_SECONDS,
			"upstream_available": jobs_mod.UPSTREAM_AVAILABLE,
		}
		if self.guard is None:
			raise env.ServiceUnavailable(
				"İş kilidi yapılandırılmamış; durum okunamaz.",
				kod=kod_uret(env.API_PREFIX, "no_job_guard"),
				detay=govde,
			)
		govde["state"] = self.guard.state_of(zarf.key)
		return env.ok(govde)

	# ── 9. storage_plan ────────────────────────────────────────────────

	def storage_plan(self, principal: env.Principal) -> env.ApiResponse:
		"""Etkin depolama kipi ve **bozulma** durumu.

		`StoragePlan.degraded` istenen kip ile kurulabilen kipin ayrıştığını
		söyler (ör. S3 istendi, `boto3` yok → yerel diske düşüldü). Bu ayrım
		bugün hiçbir yüzeyde görünmüyor; görünmediği için de fark edilmesi
		ancak dosyaların "kaybolmasıyla" mümkün oluyor.
		"""
		self._guard(principal, "media_storage_read")
		if self.storage_conf is None:
			raise env.ServiceUnavailable(
				"Depolama ayarı verilmedi.",
				kod=kod_uret(env.API_PREFIX, "no_storage_conf"),
			)
		from tradehub_core.media.pipeline import storage as storage_mod

		plan = storage_mod.build_from_mapping(dict(self.storage_conf))
		govde = dict(plan.to_dict())
		govde["boto3_available"] = storage_mod.boto3_available()
		govde["modes"] = list(storage_mod.MODES)
		return env.ok(govde)


# ── Test/geliştirme için bellek-içi kapsam kaynağı ──────────────────────


@dataclass
class InMemoryCoverageRepository:
	"""`CoverageRepository` portunun bellek-içi eşi."""

	rows: list[dict[str, Any]] = field(default_factory=list)

	def iter_assets(self, *, slot_key: str = "", limit: int = 0) -> Sequence[Mapping[str, Any]]:
		secilen = [r for r in self.rows if not slot_key or r.get("slot_key") == slot_key]
		return secilen[: limit or len(secilen)]


__all__ = [
	"COVERAGE_MAX_SCAN",
	"REQUIRED_POLICY_KEYS",
	"CoverageRepository",
	"AdminApi",
	"InMemoryCoverageRepository",
]

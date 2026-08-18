"""T-081 — Yükleme uçları: `create_session` / `finalize` / `abort` / `status`.

MEVCUT PARÇALI YÜKLEME OKUNDU, YENİDEN YAZILMADI
------------------------------------------------
`tradehub_core/media/chunked.py` parçalı yüklemeyi **üretimde** çözüyor ve
doğru çözüyor: 2 MB'lık parçalar diske yazılıyor, hiçbir anda dosyanın tamamı
bellekte durmuyor, politika **birleşimden sonra** uygulanıyor (ilk parçanın
geçerli bir görsel başlığı taşıyıp devamının başka bir içerik olması durumu
kapatılmış), oturum kimliği yol kaçışına karşı kalıplı, kapsam her adımda
yeniden doğrulanıyor ve süresi geçen oturumlar süpürülüyor.

Bu modül o kodun yerine geçmez; onu **sarar** ve üç eksiğini kapatır:

1. **Slot kimliği.** `upload_policy.check()` imzasında slot yok
   (`docs/reports/00-upload-slot-envanteri.md` §7-B B1). Sunucu bir yüklemenin
   hangi slota ait olduğunu bilmiyor, dolayısıyla slot bazlı hiçbir kural
   uygulanamıyor. Burada slot anahtarı oturumun **ilk adımında** alınır,
   oturum künyesine yazılır ve `finalize`'da `PolicyEngine.evaluate()`'a
   taşınır.
2. **İçerik hashi üzerinden idempotensi.** Bugün aynı dosyanın ikinci
   yüklemesi ikinci bir `File` kaydı açıyor; canlı ölçümde diskte
   **1.166 yetim dosya** var. Burada aynı içerik hashi ile gelen ikinci
   `finalize` **yeni varlık ÜRETMEZ** (INV-06) ve `201` değil `200` döner.
3. **Erken ret.** Boyut, slot tavanı ve içerik hashi (verilmişse) oturum
   açılmadan denetlenir. 24 MB'lık bir dosyanın 12 parçasını alıp sonunda
   "çok büyük" demek, kullanıcının ve diskin zamanını harcamaktır.

İDEMPOTENSİ NASIL GARANTİ EDİLİYOR — ÜÇ KAPI
--------------------------------------------
    K1  create_session(content_sha256=…)  →  varlık zaten varsa OTURUM AÇILMAZ
    K2  finalize (aynı oturum, ikinci kez) →  künyedeki `asset` döndürülür
    K3  finalize (farklı oturum, aynı içerik) → `resolve_upload` + `idempotent_create`

K3 yarış koşulunu da kapsar: iki eşzamanlı `finalize` aynı hash için aynı anda
gelirse ikisi de aynı varlığı döndürür — `core/dedup.py::idempotent_create`
tekillik ihlalini hata değil, "diğer istek kazandı" olarak yorumlar.

BU MODÜL DOSYA YAZMAZ, KAYIT AÇMAZ
----------------------------------
Yazma iki porta delege edilir (`SessionStore`, `AssetRepository`). Sebep
`chunked.finish()`'in kendi gerekçesiyle aynı: kayıt açmak denetim kaydı,
sahiplik ve üstveri sorumluluğu taşır ve bunlar Frappe'ye bağlıdır. Bu
katmanın verdiği garanti "parçalar bir dosya oldu, politika geçildi, kimlik
tekil" ile sınırlıdır.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Dict, Mapping, MutableMapping, Optional, Protocol, Tuple

from tradehub_core.media.pipeline.api import envelope as env
from tradehub_core.media.pipeline.contracts.errors import (
	PolicyNotFound,
	PolicyViolation,
	kod_uret,
)
from tradehub_core.media.pipeline.core import dedup
from tradehub_core.media.pipeline.core import probe as probe_mod
from tradehub_core.media.pipeline.core import state as state_mod
from tradehub_core.media.pipeline.policy import engine as policy_engine

#: Oturum künyesinin (annotations) tutulacağı varsayılan süre. `chunked.py`
#: SESSION_TTL_HOURS = 6 ile AYNI olmalı; künye oturumdan uzun yaşarsa
#: silinmiş bir oturumun slotu bellekte kalır.
ANNOTATION_TTL_SECONDS: int = 6 * 3600

#: `finalize` sonrası künye bu kadar daha tutulur ki tekrar eden `finalize`
#: (ağ kopması, kullanıcının iki kez tıklaması) aynı yanıtı alsın — K2.
FINALIZED_TTL_SECONDS: int = 24 * 3600


# ── Portlar ─────────────────────────────────────────────────────────────


class SessionStore(Protocol):
	"""Parçalı yükleme oturumu. İmza `tradehub_core/media/chunked.py` İLE AYNI.

	Bilinçli: üretim bağlaması `chunked` modülünün KENDİSİDİR, arada bir
	adaptör sınıfı yoktur. Modül bu protokolü yapısal olarak zaten karşılar.
	"""

	def begin(self, file_name: str, total_bytes: int, store: str) -> dict: ...

	def put_chunk(self, upload_id: str, index: int, content: bytes, store: str) -> dict: ...

	def meta_of(self, upload_id: str, store: str) -> dict: ...

	def finish(self, upload_id: str, store: str) -> bytes: ...

	def cleanup_session(self, upload_id: str, store: Optional[str] = None) -> None: ...


class AssetRepository(Protocol):
	"""Varlık kayıt defteri. Frappe bağlamasında `Media Asset` DocType'ı."""

	def find_by_content_hash(self, content_sha256: str, *, store: str = "") -> Optional[str]:
		"""Bu içerik daha önce kaydedilmiş mi → varlık adı ya da `None`."""
		...

	def create(self, record: Mapping[str, Any]) -> str:
		"""Kaydı aç, adını döndür. Tekillik ihlalinde istisna ATAR."""
		...

	def get(self, asset: str) -> Optional[Mapping[str, Any]]: ...

	def is_conflict(self, exc: BaseException) -> bool:
		"""İstisna bir tekillik ihlali mi (`DuplicateEntryError` / 1062)."""
		...


class BlobStore(Protocol):
	"""İçeriği kalıcı depoya yazan taraf — `contracts.storage.StorageAdapter`."""

	def put(self, content: bytes, extension: str, *, scope: str = "public") -> Any: ...


# ── Oturum künyesi ──────────────────────────────────────────────────────


@dataclass
class SessionNote:
	"""Oturumun `chunked.py`'de KARŞILIĞI OLMAYAN alanları.

	`chunked.meta.json` slot bilmiyor ve bilmesi için üretim dosyasını
	değiştirmek gerekirdi. Bu künye onun yanında durur; üretimde
	`frappe.cache()` ya da `Media Processing Job` alanı olur, testte düz sözlük.
	"""

	upload_id: str
	slot_key: str
	store: str
	user: str = ""
	declared_sha256: str = ""
	idempotency_key: str = ""
	created_at: float = 0.0
	#: `finalize` tamamlandıysa üretilen varlık. K2 kapısının belleği.
	asset: str = ""
	finalized_at: float = 0.0
	ingest_state: str = state_mod.INGEST_RECEIVED

	def to_dict(self) -> Dict[str, Any]:
		return {
			"upload_id": self.upload_id,
			"slot_key": self.slot_key,
			"store": self.store,
			"user": self.user,
			"declared_sha256": self.declared_sha256,
			"idempotency_key": self.idempotency_key,
			"created_at": self.created_at,
			"asset": self.asset,
			"finalized_at": self.finalized_at,
			"ingest_state": self.ingest_state,
		}

	@classmethod
	def from_dict(cls, data: Mapping[str, Any]) -> SessionNote:
		bilinen = {f for f in cls.__dataclass_fields__}
		return cls(**{k: v for k, v in data.items() if k in bilinen})


@dataclass
class UploadApi:
	"""Yükleme uçları. Saf Python — `@frappe.whitelist()` YOK.

	Args:
	    sessions: `chunked` modülü ya da onun protokolünü karşılayan sahte.
	    assets: Varlık kayıt defteri portu.
	    policy: `policy.engine.PolicyEngine`. Verilmezse `default_engine()`.
	    blobs: İçeriği yazan depo. `None` ise içerik yazılmaz — çağıran
	        `content` alanını yanıttan alıp kendi yazar (Frappe `File` yolu).
	    notes: Oturum künyesi deposu (sözlük arayüzü).
	    clock: Zaman kaynağı; testte sabitlenebilir.
	    on_denied: Yetki reddi kancası (denetim kaydı).
	"""

	#: Sözleşmede (`spec.py`) karşılığı olan uç noktalar. `tests/test_api_contracts.py`
	#: bu listeyi OpenAPI belgesiyle İKİ YÖNLÜ karşılaştırır: belgede olup kodda
	#: olmayan da, kodda olup belgede olmayan da testi düşürür.
	ENDPOINTS: ClassVar[Tuple[str, ...]] = (
		"create_session",
		"put_chunk",
		"status",
		"finalize",
		"abort",
	)

	sessions: SessionStore
	assets: AssetRepository
	policy: Any = None
	blobs: Optional[BlobStore] = None
	notes: MutableMapping[str, Dict[str, Any]] = field(default_factory=dict)
	clock: Callable[[], float] = time.time
	on_denied: Optional[env.DenialHook] = None

	def __post_init__(self) -> None:
		if self.policy is None:
			self.policy = policy_engine.default_engine()

	# ── yardımcılar ────────────────────────────────────────────────────

	def _slot_policy(self, slot_key: str) -> dict:
		"""Slot politikasını getir; bilinmeyen slot → `PolicyNotFound` (404).

		`policy.engine.PolicyNotFound` bir `KeyError` türevidir ve sözleşme
		hiyerarşisine ait değil. Çeviri burada yapılır — istemci tek bir hata
		biçimi görür.
		"""
		try:
			return self.policy.registry.get(slot_key)
		except policy_engine.PolicyNotFound:
			raise PolicyNotFound(
				f"Bilinmeyen slot: {slot_key}",
				detay={"slot_key": slot_key, "known": list(self.policy.registry.keys())},
			)

	def _note(self, upload_id: str) -> Optional[SessionNote]:
		ham = self.notes.get(upload_id)
		return SessionNote.from_dict(ham) if ham else None

	def _save_note(self, note: SessionNote) -> None:
		self.notes[note.upload_id] = note.to_dict()

	def _require_note(self, principal: env.Principal, upload_id: str, store: str) -> SessionNote:
		note = self._note(upload_id)
		if note is None or note.store != store:
			# Kapsam uyuşmazlığı ile "yok" AYNI cevabı verir: kimliği tahmin
			# eden biri başka mağazanın oturumunun VARLIĞINI öğrenememeli.
			raise env.NotFound(
				"Yükleme oturumu bulunamadı ya da süresi doldu.",
				kod=kod_uret(env.API_PREFIX, "session_unknown"),
			)
		return note

	# ── T-081.1 create_session ─────────────────────────────────────────

	def create_session(
		self,
		principal: env.Principal,
		*,
		slot_key: str,
		file_name: str,
		total_bytes: Any,
		content_sha256: str = "",
		idempotency_key: str = "",
	) -> env.ApiResponse:
		"""Yükleme oturumu aç. Üç şey oturum AÇILMADAN denetlenir.

		1. Slot var mı (404),
		2. İlan edilen boyut slot tavanını aşıyor mu (413),
		3. Bu içerik zaten kayıtlı mı (200 + `duplicate`, oturum açılmaz).

		Üçüncü kapı `content_sha256` verilirse çalışır. İstemcinin hash'i
		göndermesi ZORUNLU DEĞİLDİR — göndermeyen istemci yalnız gereksiz
		bant genişliği harcar, yanlış sonuç almaz; `finalize`'daki K3 kapısı
		aynı kararı orada verir.
		"""
		store = env.require_store(principal)
		slot = env.require_str(slot_key, "slot_key", max_len=64)
		ad = env.require_str(file_name, "file_name", max_len=255)
		boyut = env.require_int(total_bytes, "total_bytes", minimum=1)

		policy = self._slot_policy(slot)
		tavan = int((policy.get("accept") or {}).get("max_bytes") or 0)
		if tavan and boyut > tavan:
			raise env.PayloadTooLarge(
				f"Dosya {boyut / 1048576:.1f} MB; bu slot için üst sınır {tavan / 1048576:.0f} MB.",
				kod=kod_uret(
					(policy.get("on_violation") or {}).get("error_code_prefix") or env.API_PREFIX,
					"too_large",
				),
				detay={"slot_key": slot, "observed_bytes": boyut, "max_bytes": tavan},
			)

		# K1 — içerik zaten kayıtlıysa hiçbir bayt taşınmaz.
		if content_sha256:
			hash_hex = self._normalized_hash(content_sha256)
			mevcut = self.assets.find_by_content_hash(hash_hex, store=store)
			if mevcut:
				return env.ok(
					{
						"upload_id": "",
						"duplicate": True,
						"created": False,
						"asset": str(mevcut),
						"content_sha256": hash_hex,
						"slot_key": slot,
						"message": dedup.DUPLICATE_MESSAGE,
						"ingest_state": state_mod.INGEST_READY,
					}
				)
		else:
			hash_hex = ""

		oturum = self.sessions.begin(ad, boyut, store)
		upload_id = str(oturum["upload_id"])
		note = SessionNote(
			upload_id=upload_id,
			slot_key=slot,
			store=store,
			user=principal.user,
			declared_sha256=hash_hex,
			idempotency_key=str(idempotency_key or ""),
			created_at=float(self.clock()),
			ingest_state=state_mod.INGEST_RECEIVED,
		)
		self._save_note(note)

		return env.created(
			{
				"upload_id": upload_id,
				"slot_key": slot,
				"file_name": oturum.get("file_name", ad),
				"chunk_bytes": int(oturum["chunk_bytes"]),
				"chunk_count": int(oturum["chunk_count"]),
				"total_bytes": boyut,
				"duplicate": False,
				"expires_in": ANNOTATION_TTL_SECONDS,
				"ingest_state": note.ingest_state,
			},
			location=f"/media/upload/sessions/{upload_id}",
		)

	# ── parça yükleme (mevcut motorun sarılması) ───────────────────────

	def put_chunk(
		self, principal: env.Principal, upload_id: str, index: Any, content: bytes
	) -> env.ApiResponse:
		"""Tek parçayı ekle. Tüm doğrulama `chunked.put_chunk` içinde ZATEN var
		(sıra aralığı, parça boyutu tavanı, kapsam) — burada tekrarlanmaz."""
		store = env.require_store(principal)
		note = self._require_note(principal, env.require_str(upload_id, "upload_id", max_len=64), store)
		sonuc = self.sessions.put_chunk(note.upload_id, env.require_int(index, "index"), content, store)
		return env.ok(
			{
				"upload_id": note.upload_id,
				"received": int(sonuc["received"]),
				"chunk_count": int(sonuc["chunk_count"]),
				"complete": bool(sonuc["complete"]),
			}
		)

	# ── T-081.2 status ─────────────────────────────────────────────────

	def status(
		self, principal: env.Principal, upload_id: str, *, if_none_match: str = ""
	) -> env.ApiResponse:
		"""Oturumun durumu — yarıda kalan yükleme sürdürülebilsin.

		`received` listesi `chunked.meta_of`'tan gelir; ekran hangi parçaların
		gittiğini bilir ve yalnız eksikleri gönderir. Yanıt ETag taşır: ilerleme
		değişmediyse 304, gövde yeniden inmez.
		"""
		store = env.require_store(principal)
		uid = env.require_str(upload_id, "upload_id", max_len=64)
		note = self._require_note(principal, uid, store)

		# Tamamlanmış oturumun parça künyesi silinmiş olabilir; künye yaşıyorsa
		# sonucu ondan veririz — `finalize`'ın yanıtıyla tutarlı kalır.
		if note.asset:
			govde = {
				"upload_id": uid,
				"slot_key": note.slot_key,
				"complete": True,
				"finalized": True,
				"asset": note.asset,
				"ingest_state": note.ingest_state,
				"received": [],
				"chunk_count": 0,
			}
			return env.conditional_get(govde, if_none_match)

		meta = self.sessions.meta_of(uid, store)
		alinan = list(meta.get("received") or [])
		toplam = int(meta.get("chunk_count") or 0)
		govde = {
			"upload_id": uid,
			"slot_key": note.slot_key,
			"file_name": meta.get("file_name", ""),
			"chunk_bytes": int(meta.get("chunk_bytes") or 0),
			"chunk_count": toplam,
			"received": alinan,
			"missing": [i for i in range(toplam) if i not in set(alinan)],
			"complete": toplam > 0 and len(alinan) == toplam,
			"finalized": False,
			"asset": "",
			"ingest_state": note.ingest_state,
		}
		return env.conditional_get(govde, if_none_match)

	# ── T-081.3 finalize ───────────────────────────────────────────────

	def finalize(
		self,
		principal: env.Principal,
		upload_id: str,
		*,
		role: str = "",
		alt_text: str = "",
		extra: Optional[Mapping[str, Any]] = None,
	) -> env.ApiResponse:
		"""Parçaları birleştir, politikayı uygula, varlığı aç.

		Sıra ANLAMLIDIR ve `core/state.py::ingest_from_decision` ile aynıdır:
		birleştirme → künye çıkarma → politika → tekilleştirme → kayıt.
		Politikayı tekilleştirmeden ÖNCE çalıştırmak bilinçlidir: reddedilecek
		bir dosyanın hash'iyle var olan bir kaydı döndürmek, ihlali sessizce
		geçirmek olurdu.

		Dönüş:
		    201 — yeni varlık açıldı.
		    200 — aynı içerik zaten vardı (`created=false`). **Yeni varlık
		          ÜRETİLMEZ**; bu uç idempotenttir.
		    422 — politika ihlali (`violations` listesi ile).
		"""
		store = env.require_store(principal)
		uid = env.require_str(upload_id, "upload_id", max_len=64)
		note = self._require_note(principal, uid, store)

		# ── K2: bu oturum zaten sonuçlandı ────────────────────────────
		if note.asset:
			return env.ok(
				{
					"asset": note.asset,
					"created": False,
					"duplicate": True,
					"slot_key": note.slot_key,
					"upload_id": uid,
					"ingest_state": note.ingest_state,
					"message": dedup.DUPLICATE_MESSAGE,
				}
			)

		# `chunked.finish` eksik parçayı, boş içeriği ve içerik/uzantı
		# uyuşmazlığını KENDİ reddeder; burada tekrar edilmez.
		content = self.sessions.finish(uid, store)
		meta = self.sessions.meta_of(uid, store)
		file_name = str(meta.get("file_name") or "")

		kunye = probe_mod.probe_bytes(content, file_name, is_private=False)
		# Slot hâlâ tanımlı mı — oturum açıldıktan sonra politika dosyası
		# kaldırılmış olabilir. `evaluate` bu durumda `KeyError` türevi bir
		# istisna atar ve zarf onu 500'e çevirirdi; 404 doğru cevaptır.
		self._slot_policy(note.slot_key)
		decision = self.policy.evaluate(note.slot_key, kunye, role or "")

		if not decision.allow:
			note.ingest_state = state_mod.INGEST_REJECTED
			self._save_note(note)
			self.sessions.cleanup_session(uid, store)
			ilk = decision.blocking()[0]
			raise PolicyViolation(
				ilk.message.get("tr") or ilk.rule,
				kod=ilk.code,
				retryable=bool(ilk.retryable),
				detay={
					"slot_key": note.slot_key,
					"upload_id": uid,
					"action": decision.action,
					"violations": [v.to_dict() for v in decision.violations],
					"skipped": [s.to_dict() for s in decision.skipped],
				},
			)

		note.ingest_state = state_mod.ingest_from_decision(True, state_mod.SCAN_CLEAN)
		hash_hex = kunye.sha256 or dedup.sha256_bytes(content)

		# İstemcinin ilan ettiği hash ile ölçülen hash tutmuyorsa: aktarım
		# bozulmuş ya da istemci yanlış hash göndermiş. Sessizce ölçülene
		# geçmek, istemcinin tekilleştirme varsayımını bozar.
		if note.declared_sha256 and note.declared_sha256 != hash_hex:
			self.sessions.cleanup_session(uid, store)
			raise env.BadRequest(
				"Yüklenen içeriğin özeti, oturum açılırken bildirilen özetle uyuşmuyor.",
				kod=kod_uret(env.API_PREFIX, "hash_mismatch"),
				detay={"declared": note.declared_sha256, "observed": hash_hex},
			)

		# ── K3: içerik zaten kayıtlı mı ───────────────────────────────
		outcome = dedup.resolve_upload(
			hash_hex, lambda h: self.assets.find_by_content_hash(h, store=store)
		)
		if outcome.is_duplicate:
			note.asset = str(outcome.asset)
			note.ingest_state = state_mod.INGEST_READY
			note.finalized_at = float(self.clock())
			self._save_note(note)
			self.sessions.cleanup_session(uid, store)
			return env.ok(
				{
					"asset": note.asset,
					"created": False,
					"duplicate": True,
					"slot_key": note.slot_key,
					"upload_id": uid,
					"content_sha256": hash_hex,
					"ingest_state": note.ingest_state,
					"message": outcome.message,
					"decision": decision.to_dict(),
				}
			)

		uzanti = (kunye.extension or "").lstrip(".")
		file_url = ""
		if self.blobs is not None:
			put = self.blobs.put(content, uzanti, scope="public")
			file_url = str(getattr(getattr(put, "ref", None), "url", "") or "")
		if not file_url:
			file_url = dedup.content_url(hash_hex, uzanti)

		kayit: Dict[str, Any] = {
			"content_sha256": hash_hex,
			"slot_key": note.slot_key,
			"file_name": file_name,
			"file_url": file_url,
			"byte_size": kunye.byte_size or len(content),
			"width": kunye.display_size[0],
			"height": kunye.display_size[1],
			"kind": kunye.kind,
			"mime": kunye.mime,
			"owner_store": store,
			"uploaded_by": principal.user,
			"alt_text": str(alt_text or ""),
			"ingest_state": state_mod.INGEST_MASTERED,
			"policy_version": decision.policy_version,
		}
		if extra:
			kayit.update({k: v for k, v in extra.items() if k not in kayit})

		asset, yeni = dedup.idempotent_create(
			hash_hex,
			lambda: self.assets.create(kayit),
			lambda h: self.assets.find_by_content_hash(h, store=store),
			self.assets.is_conflict,
		)

		note.asset = str(asset)
		note.ingest_state = state_mod.INGEST_MASTERED if yeni else state_mod.INGEST_READY
		note.finalized_at = float(self.clock())
		self._save_note(note)
		self.sessions.cleanup_session(uid, store)

		govde = {
			"asset": note.asset,
			"created": bool(yeni),
			"duplicate": not yeni,
			"slot_key": note.slot_key,
			"upload_id": uid,
			"content_sha256": hash_hex,
			"file_url": file_url,
			"width": kayit["width"],
			"height": kayit["height"],
			"byte_size": kayit["byte_size"],
			"ingest_state": note.ingest_state,
			"decision": decision.to_dict(),
			"message": "" if yeni else dedup.DUPLICATE_MESSAGE,
		}
		return env.created(govde, location=f"/media/assets/{note.asset}") if yeni else env.ok(govde)

	# ── T-081.4 abort ──────────────────────────────────────────────────

	def abort(self, principal: env.Principal, upload_id: str) -> env.ApiResponse:
		"""Oturumu iptal et — parçaları sil, künyeyi düşür. **İdempotent.**

		Bilinmeyen ya da zaten iptal edilmiş oturum da 204 döner. 404 döndürmek,
		"iptal et" isteğini iki kez gönderen istemciyi hata işlemeye zorlardı;
		oysa istenen son durum ("bu oturum yok") her iki hâlde de sağlanmıştır.

		Sonuçlanmış (varlık üretmiş) oturum iptal EDİLEMEZ: 409. Varlığı silmek
		bu ucun işi değil — silme yaşam döngüsü ekseninin işidir
		(`tradehub_core/media/trash.py`).
		"""
		store = env.require_store(principal)
		uid = env.require_str(upload_id, "upload_id", max_len=64)
		note = self._note(uid)

		if note is not None and note.store == store and note.asset:
			raise env.Conflict(
				"Bu yükleme tamamlandı; iptal edilemez. Dosyayı kaldırmak için çöp kutusunu kullanın.",
				kod=kod_uret(env.API_PREFIX, "already_finalized"),
				detay={"upload_id": uid, "asset": note.asset},
			)

		if note is not None and note.store == store:
			self.notes.pop(uid, None)
			try:
				self.sessions.cleanup_session(uid, store)
			except Exception:
				# Oturum klasörü zaten yoksa (TTL süpürücüsü almış olabilir)
				# iptal yine başarılıdır: istenen son durum sağlandı.
				pass

		return env.no_content()

	# ── küçük yardımcı ─────────────────────────────────────────────────

	@staticmethod
	def _normalized_hash(value: str) -> str:
		hex_str = env.require_str(value, "content_sha256", max_len=64).lower()
		if len(hex_str) != 64 or any(c not in "0123456789abcdef" for c in hex_str):
			raise env.BadRequest(
				"`content_sha256` 64 haneli onaltılık bir sha256 olmalı.",
				kod=kod_uret(env.API_PREFIX, "bad_field"),
				detay={"field": "content_sha256"},
			)
		return hex_str


# ── Test/geliştirme için bellek-içi oturum deposu ───────────────────────


class InMemorySessionStore:
	"""`chunked` protokolünün bellek-içi eşi — bench'siz test için.

	Üretim davranışını TAKLİT ETMEZ, yalnız sözleşmesini karşılar: parça sırası
	aralığı, kapsam kontrolü ve eksik parça reddi burada da vardır, çünkü
	bunlar sözleşmenin parçasıdır. Politika kontrolü burada YOKTUR — o
	`chunked.finish()`'in işi ve testte `UploadApi` kendi politika motorunu
	ayrıca çalıştırıyor.
	"""

	CHUNK_BYTES: int = 2 * 1024 * 1024

	def __init__(self, chunk_bytes: int = 0) -> None:
		self.chunk_bytes = int(chunk_bytes or self.CHUNK_BYTES)
		self._oturumlar: Dict[str, Dict[str, Any]] = {}
		self._sayac = 0

	def begin(self, file_name: str, total_bytes: int, store: str) -> dict:
		if not store:
			raise env.Forbidden("Bu işlem için bir mağaza hesabı gerekiyor.")
		self._sayac += 1
		uid = f"{self._sayac:024x}"
		adet = (int(total_bytes) + self.chunk_bytes - 1) // self.chunk_bytes
		self._oturumlar[uid] = {
			"upload_id": uid,
			"file_name": file_name,
			"total_bytes": int(total_bytes),
			"chunk_bytes": self.chunk_bytes,
			"chunk_count": adet,
			"store": store,
			"parts": {},
		}
		return {
			"upload_id": uid,
			"chunk_bytes": self.chunk_bytes,
			"chunk_count": adet,
			"file_name": file_name,
		}

	def _get(self, upload_id: str, store: str) -> Dict[str, Any]:
		o = self._oturumlar.get(upload_id)
		if o is None or o["store"] != store:
			raise env.NotFound("Yükleme oturumu bulunamadı ya da süresi doldu.")
		return o

	def put_chunk(self, upload_id: str, index: int, content: bytes, store: str) -> dict:
		o = self._get(upload_id, store)
		if index < 0 or index >= o["chunk_count"]:
			raise env.BadRequest("Geçersiz parça sırası.")
		if len(content) > self.chunk_bytes:
			raise env.PayloadTooLarge("Parça çok büyük.")
		o["parts"][int(index)] = bytes(content)
		return {
			"upload_id": upload_id,
			"received": len(o["parts"]),
			"chunk_count": o["chunk_count"],
			"complete": len(o["parts"]) == o["chunk_count"],
		}

	def meta_of(self, upload_id: str, store: str) -> dict:
		o = self._get(upload_id, store)
		return {
			"upload_id": upload_id,
			"file_name": o["file_name"],
			"chunk_count": o["chunk_count"],
			"chunk_bytes": o["chunk_bytes"],
			"received": sorted(o["parts"]),
			"created": None,
		}

	def finish(self, upload_id: str, store: str) -> bytes:
		o = self._get(upload_id, store)
		eksik = [i for i in range(o["chunk_count"]) if i not in o["parts"]]
		if eksik:
			raise env.BadRequest(f"Yükleme tamamlanmadı: {len(eksik)} parça eksik.")
		return b"".join(o["parts"][i] for i in range(o["chunk_count"]))

	def cleanup_session(self, upload_id: str, store: Optional[str] = None) -> None:
		if store is not None and upload_id in self._oturumlar:
			self._get(upload_id, store)
		self._oturumlar.pop(upload_id, None)


class InMemoryAssetRepository:
	"""Bellek-içi varlık defteri — sözleşme testleri için."""

	def __init__(self) -> None:
		self.by_hash: Dict[str, str] = {}
		self.rows: Dict[str, Dict[str, Any]] = {}
		self._sayac = 0

	def find_by_content_hash(self, content_sha256: str, *, store: str = "") -> Optional[str]:
		ad = self.by_hash.get(content_sha256)
		if ad is None:
			return None
		if store and self.rows[ad].get("owner_store") not in ("", store):
			return None
		return ad

	def create(self, record: Mapping[str, Any]) -> str:
		h = str(record.get("content_sha256") or "")
		if h in self.by_hash:
			raise KeyError(f"duplicate:{h}")
		self._sayac += 1
		ad = f"MA-{self._sayac:06d}"
		self.rows[ad] = dict(record)
		self.by_hash[h] = ad
		return ad

	def get(self, asset: str) -> Optional[Mapping[str, Any]]:
		return self.rows.get(asset)

	def is_conflict(self, exc: BaseException) -> bool:
		return isinstance(exc, KeyError) and str(exc).startswith("'duplicate:")


__all__ = [
	"ANNOTATION_TTL_SECONDS",
	"FINALIZED_TTL_SECONDS",
	"SessionStore",
	"AssetRepository",
	"BlobStore",
	"SessionNote",
	"UploadApi",
	"InMemorySessionStore",
	"InMemoryAssetRepository",
]

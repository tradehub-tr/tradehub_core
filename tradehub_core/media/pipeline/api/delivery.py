"""T-083 — Teslim uçları: `manifest` / `manifest_batch` / `signed_url`.

ÜÇ SERT KURAL
-------------
1. **Manifest yalnız ÜRETİLMİŞ genişlikleri gösterir.** Varlık kaydındaki
   `available_profiles` listesi `ManifestBuilder`a süzgeç olarak verilir;
   `None` ASLA geçilmez. Üretilmemiş bir genişliği `srcset`e yazmak tarayıcıya
   404 indirtir ve görsel hiç görünmez.
2. **Yayınlanmamış varlık 404'tür**, 403 değil. 403 kaynağın var olduğunu
   doğrular; bir görselin yayına hazırlandığını sızdırmak, yayın takvimini
   sızdırmaktır. Aynı sebeple başka mağazanın varlığı da 404 döner.
3. **ETag zorunlu.** Manifest saf bir fonksiyonun çıktısıdır: aynı varlık +
   aynı politika + aynı türev listesi her zaman aynı gövdeyi verir. Bu,
   içerik-adresli ETag'i mümkün kılar ve `If-None-Match` ile 304 döndürür.

İMZALI URL MANİFESTİN İÇİNDE DEĞİL
----------------------------------
Private varlıkların imzalı adresi ayrı bir uçtan verilir (`signed_url`).
Manifestin içine gömmek iki şeyi birden bozardı: imza `iat` taşıdığı için
gövde her istekte değişir (ETag ölür), ve manifest paylaşılan bir önbelleğe
düşerse imza başka kullanıcıya servis edilir. `signed_url` yanıtı bu yüzden
`Cache-Control: private, no-store` ile döner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from tradehub_core.media.pipeline.api import envelope as env
from tradehub_core.media.pipeline.contracts.errors import kod_uret
from tradehub_core.media.pipeline.contracts.storage import SCOPE_PRIVATE, SCOPE_PUBLIC
from tradehub_core.media.pipeline.core.probe import KIND_VIDEO
from tradehub_core.media.pipeline.delivery import manifest as manifest_mod
from tradehub_core.media.pipeline.delivery import signed as signed_mod

#: Tek istekte istenebilecek azami varlık. `media_admin.MAX_BATCH` 2000'dir ama
#: orası kuyruğa atma sayısıdır; burada her varlık için politika okunup manifest
#: kuruluyor, yani iş İSTEK İÇİNDE yapılıyor. 100 sınırı, kazara "hepsini
#: getir" çağrısının istek süresini saniyelere çıkarmasını engeller.
MAX_BATCH: int = 100

#: `manifest_batch` yanıtında bulunamayan varlıkların listelendiği alan. Sebep
#: AYRIŞTIRILMAZ: "yok", "yayınlanmamış" ve "başka mağazanın" üçü de aynı
#: kovaya girer — ayrıştırmak kural 2'yi delerdi.
MISSING_KEY: str = "missing"


class DeliveryRepository(Protocol):
	"""Teslim için gereken varlık görünümü."""

	def get(self, asset: str) -> Optional[Mapping[str, Any]]:
		"""Beklenen alanlar:

		    slot_key            str    politika anahtarı
		    file_url            str    master adresi (`/files/...` ya da `/private/files/...`)
		    published           bool   yayında mı
		    kind                str    "image" | "video"
		    width, height       int    içsel ölçü (CLS koruması, FR-124)
		    alt_text            str
		    owner_store         str    mağaza kapsamı
		    available_profiles  list   ÜRETİLMİŞ profil adları
		    available_renditions list  ÜRETİLMİŞ video türev id'leri
		    poster_url          str    (video) açık poster adresi
		    captions_url        str    (video) VTT adresi
		    version_hash        str    ETag'e karışır; türev yenilenince değişir
		"""
		...

	def get_many(self, assets: Sequence[str]) -> Mapping[str, Mapping[str, Any]]:
		"""Toplu okuma. N+1 sorguyu ÇAĞIRANIN değil, uygulamanın işi yapar."""
		...


@dataclass
class DeliveryApi:
	"""Teslim uçları. Saf Python — `@frappe.whitelist()` YOK.

	Args:
	    repo: Varlık görünümü portu.
	    builder: Manifest üreticisi. Verilmezse varsayılan.
	    signer: İmzalayıcı. Verilmezse `signed_url` 503 döner — sahte bir
	        imza ÜRETİLMEZ.
	    can_read: Private varlık için yetki kapısı. Verilmezse yalnız sahip
	        mağaza ve admin okuyabilir.
	"""

	#: Sözleşmedeki uç noktalar — bkz. `upload.UploadApi.ENDPOINTS` notu.
	ENDPOINTS: ClassVar[Tuple[str, ...]] = (
		"manifest",
		"manifest_batch",
		"signed_url",
	)

	repo: DeliveryRepository
	builder: manifest_mod.ManifestBuilder = None  # type: ignore[assignment]
	signer: Optional[signed_mod.UrlSigner] = None
	can_read: Optional[Callable[[env.Principal, Mapping[str, Any]], bool]] = None

	def __post_init__(self) -> None:
		if self.builder is None:
			self.builder = manifest_mod.build_default()

	# ── görünürlük ─────────────────────────────────────────────────────

	def _visible(self, principal: env.Principal, row: Optional[Mapping[str, Any]]) -> bool:
		"""Bu varlık bu isteğe görünür mü. **Tek karar noktası.**

		Üç kapı ve sırası anlamlı:
		  1. Kayıt var mı,
		  2. Yayında mı (yayınlanmamışa yalnız sahip/admin erişir — editör
		     kendi taslağının önizlemesini görebilmeli),
		  3. Private ise okuma yetkisi var mı.
		"""
		if row is None:
			return False
		sahip = bool(row.get("owner_store")) and env.same_store(
			principal, str(row.get("owner_store") or "")
		)
		if not row.get("published") and not (sahip or principal.is_admin):
			return False
		if self._scope_of(row) == SCOPE_PRIVATE:
			if self.can_read is not None:
				return bool(self.can_read(principal, row))
			return sahip or principal.is_admin
		return True

	@staticmethod
	def _scope_of(row: Mapping[str, Any]) -> str:
		url = str(row.get("file_url") or "")
		return SCOPE_PRIVATE if url.startswith(signed_mod.PRIVATE_PREFIX) else SCOPE_PUBLIC

	def _not_found(self, asset: str) -> env.NotFound:
		return env.NotFound(
			"Medya bulunamadı.",
			kod=kod_uret(env.API_PREFIX, "not_found"),
			detay={"asset": asset},
		)

	# ── manifest kurulumu ──────────────────────────────────────────────

	def _manifest_body(self, asset: str, row: Mapping[str, Any], *, is_lcp: bool, sizes: str) -> Dict[str, Any]:
		"""Tek varlığın manifest gövdesi. `NoProfileAvailable` YUKARI çıkar."""
		slot = str(row.get("slot_key") or "")
		if not slot:
			# Slot bilinmeden hangi merdivenin kurulacağı bilinemez. Bu bugünkü
			# ana boşluk (`docs/reports/00-upload-slot-envanteri.md` §7-B B1) ve
			# sessizce bir varsayılan slot seçmek yanlış genişlikler üretirdi.
			raise env.NotFound(
				"Bu medyanın slot bilgisi yok; teslim manifesti kurulamaz.",
				kod=kod_uret(env.API_PREFIX, "slot_missing"),
				detay={"asset": asset},
			)

		base = manifest_mod.ref_from_url(str(row.get("file_url") or ""))
		intrinsic = (int(row.get("width") or 0), int(row.get("height") or 0))

		if str(row.get("kind") or "") == KIND_VIDEO:
			poster_ref = None
			poster_url = str(row.get("poster_url") or "")
			if poster_url:
				poster_ref = manifest_mod.ref_from_url(poster_url)
			man = self.builder.build_video(
				slot,
				base,
				poster=poster_ref,
				captions_url=str(row.get("captions_url") or ""),
				intrinsic=intrinsic,
				available_renditions=tuple(row.get("available_renditions") or ()),
			)
		else:
			man = self.builder.build_image(
				slot,
				base,
				intrinsic=intrinsic,
				alt=str(row.get("alt_text") or ""),
				sizes=sizes,
				# KURAL 1: `None` GEÇİLMEZ. Kayıtta liste yoksa boş demet gider
				# ve `NoProfileAvailable` yükselir — sessizce tüm merdiveni
				# "üretilmiş" saymaktan iyidir.
				available_profiles=tuple(row.get("available_profiles") or ()),
				is_lcp_candidate=is_lcp,
			)

		govde = man.to_dict()
		govde["asset"] = asset
		govde["kind"] = str(row.get("kind") or "image")
		govde["version_hash"] = str(row.get("version_hash") or "")
		govde["variants"] = [
			{
				"profile": v.profile,
				"url": v.url,
				"width": v.width,
				"height": v.height,
				"format": v.fmt,
				"type": v.mime,
				"available": v.available,
			}
			for v in man.variants
		]
		govde.update(man.extra)
		return govde

	# ── T-083.1 manifest ───────────────────────────────────────────────

	def manifest(
		self,
		principal: env.Principal,
		asset: str,
		*,
		sizes: str = "",
		is_lcp_candidate: bool = False,
		if_none_match: str = "",
	) -> env.ApiResponse:
		"""Tek varlığın teslim manifesti.

		Dönüş:
		    200 — manifest + `ETag`.
		    304 — `If-None-Match` tuttu, gövde yok.
		    404 — yok / yayınlanmamış / başka mağazanın / üretilmiş türev yok.
		"""
		ad = env.require_str(asset, "asset", max_len=140)
		row = self.repo.get(ad)
		if not self._visible(principal, row):
			raise self._not_found(ad)

		govde = self._manifest_body(ad, row, is_lcp=bool(is_lcp_candidate), sizes=sizes or "")
		return env.conditional_get(govde, if_none_match, cache_control=env.CACHE_MANIFEST)

	# ── T-083.2 manifest_batch ─────────────────────────────────────────

	def manifest_batch(
		self,
		principal: env.Principal,
		assets: Sequence[str],
		*,
		sizes: str = "",
		lcp_asset: str = "",
		if_none_match: str = "",
	) -> env.ApiResponse:
		"""Çok varlık, tek istek — listeleme sayfası için.

		Ürün listeleme sayfasında 20-50 kart var; her kart için ayrı manifest
		isteği, `srcset`i olmayan bugünkü durumdan daha yavaş bir sayfa üretirdi.

		Bulunamayan varlıklar `missing` altında listelenir ve **sebep
		verilmez** (kural 2). Kısmi başarı bir hata değildir: bir kartın
		görseli silinmişse diğer 49 kart yine basılmalı.

		`lcp_asset` yalnız BİR varlığa `fetchpriority=high` verir; hepsine
		vermek önceliklendirmeyi anlamsız kılar.
		"""
		# Teslim ucu bilinçli olarak GUEST'e açıktır: storefront ürün listesi
		# oturumsuz basılır. Görünürlük kararı `_visible` içinde ve varlık
		# bazındadır — kimlik değil, yayın durumu + kapsam belirler.
		if assets is None:
			raise env.BadRequest(
				"`assets` listesi zorunlu.",
				kod=kod_uret(env.API_PREFIX, "missing_field"),
				detay={"field": "assets"},
			)
		istenen = [env.require_str(a, "assets[]", max_len=140) for a in assets]
		if not istenen:
			raise env.BadRequest(
				"`assets` listesi boş olamaz.",
				kod=kod_uret(env.API_PREFIX, "missing_field"),
				detay={"field": "assets"},
			)
		if len(istenen) > MAX_BATCH:
			raise env.BadRequest(
				f"Tek istekte en fazla {MAX_BATCH} medya istenebilir ({len(istenen)} istendi).",
				kod=kod_uret(env.API_PREFIX, "batch_too_large"),
				detay={"max": MAX_BATCH, "observed": len(istenen)},
			)

		# Sıra korunur ama tekrarlar tekilleştirilir: aynı görsel iki karttadır
		# ve iki kez manifest kurmak boşuna iştir.
		benzersiz: List[str] = list(dict.fromkeys(istenen))
		rows = self.repo.get_many(benzersiz)

		manifestler: Dict[str, Any] = {}
		eksik: List[str] = []
		for ad in benzersiz:
			row = rows.get(ad)
			if not self._visible(principal, row):
				eksik.append(ad)
				continue
			try:
				manifestler[ad] = self._manifest_body(
					ad, row, is_lcp=(ad == lcp_asset), sizes=sizes or ""
				)
			except env.NotFound:
				eksik.append(ad)
			except Exception as exc:
				# `NoProfileAvailable` dâhil: tek bir varlığın türevi eksikse
				# TÜM sayfa çökmemeli. Sebep gövdeye yazılmaz (kural 2) ama
				# hata tipi yutulmaz — `errors` sayacı görünür kalır.
				eksik.append(ad)
				manifestler.setdefault("_errors", {})
				manifestler["_errors"][ad] = type(exc).__name__

		hatalar = manifestler.pop("_errors", {})
		govde = {
			"manifests": manifestler,
			MISSING_KEY: eksik,
			"requested": len(istenen),
			"returned": len(manifestler),
			"errors": hatalar,
		}
		return env.conditional_get(govde, if_none_match, cache_control=env.CACHE_MANIFEST)

	# ── T-083.3 signed_url ─────────────────────────────────────────────

	def signed_url(
		self, principal: env.Principal, asset: str, *, ttl_seconds: Any = None, path: str = ""
	) -> env.ApiResponse:
		"""Private varlık için süreli, imzalı adres.

		`path` verilirse o varlığa AİT bir türev adresi imzalanır (ör.
		`__w768.webp`); verilmezse master imzalanır. Yolun varlığa ait
		olduğu doğrulanır — aksi hâlde bir kullanıcı kendi varlığının
		kimliğiyle başkasının dosyasını imzalatabilirdi.

		Public varlık için 400 döner: public yol zaten girişsiz açıktır ve
		onu imzalamak "imzalı olduğuna göre korunuyordur" yanılgısı üretir
		(`delivery/signed.py::require_private_path` ile aynı gerekçe).
		"""
		env.require_auth(principal)
		ad = env.require_str(asset, "asset", max_len=140)
		row = self.repo.get(ad)
		if not self._visible(principal, row):
			raise self._not_found(ad)

		if self._scope_of(row) != SCOPE_PRIVATE:
			raise env.BadRequest(
				"Bu medya herkese açık; imzalı bağlantı gerekmez.",
				kod=kod_uret(env.API_PREFIX, "not_private"),
				detay={"asset": ad},
			)

		master = str(row.get("file_url") or "")
		hedef = str(path or "") or master
		if hedef != master and not self._belongs_to(hedef, master):
			raise env.Forbidden(
				"İstenen yol bu medyaya ait değil.",
				kod=kod_uret(env.API_PREFIX, "forbidden"),
				detay={"asset": ad},
			)

		if self.signer is None:
			# Anahtar yoksa RASTGELE ÜRETİLMEZ: süreç yeniden başladığında tüm
			# linkler sessizce geçersiz olurdu (`signed.default_signer` gerekçesi).
			raise env.ServiceUnavailable(
				"İmzalama anahtarı yapılandırılmamış.",
				kod=kod_uret(env.API_PREFIX, "no_signing_key"),
			)

		try:
			imzali = self.signer.sign(hedef, ttl_seconds=ttl_seconds)
		except signed_mod.SignedUrlError as exc:
			raise env.BadRequest(
				exc.mesaj, kod=exc.kod, detay=dict(exc.detay, asset=ad)
			)

		govde = dict(imzali.to_dict())
		govde["asset"] = ad
		govde["path"] = imzali.path
		# TUR-124: gövdede ISO 8601 + kayma. İmza yükü ve URL'deki `exp` epoch
		# kalır (imzalanan şey o); ham değer `expires_epoch` ile ayrıca verilir.
		govde["expires_at"] = env.iso_time(imzali.expires_at)
		govde["expires_epoch"] = imzali.expires_at
		return env.ok(govde, cache_control=env.CACHE_NEVER)

	@staticmethod
	def _belongs_to(candidate: str, master: str) -> bool:
		"""Türev adresi master ile AYNI içerik-hash gövdesini taşıyor mu.

		Türev adı `<hash>__<profil>.<uzantı>` biçimindedir (FR-040,
		`contracts/delivery.derivative_key`). Gövde eşitliği bu yüzden yeterli
		ve ucuz bir sahiplik kanıtıdır: hash içerikten türetilir, tahmin
		edilemez.
		"""
		import os
		import posixpath

		from tradehub_core.media.pipeline.contracts.delivery import VARIANT_SEPARATOR

		if not candidate or not master or ".." in candidate:
			return False
		if posixpath.dirname(candidate) != posixpath.dirname(master):
			return False
		govde_m = os.path.splitext(posixpath.basename(master))[0]
		govde_c = os.path.splitext(posixpath.basename(candidate))[0]
		return govde_c == govde_m or govde_c.startswith(govde_m + VARIANT_SEPARATOR)


# ── Test/geliştirme için bellek-içi depo ────────────────────────────────


@dataclass
class InMemoryDeliveryRepository:
	"""`DeliveryRepository` portunun bellek-içi eşi."""

	rows: Dict[str, Dict[str, Any]] = None  # type: ignore[assignment]

	def __post_init__(self) -> None:
		if self.rows is None:
			self.rows = {}

	def get(self, asset: str) -> Optional[Mapping[str, Any]]:
		row = self.rows.get(asset)
		return dict(row) if row is not None else None

	def get_many(self, assets: Sequence[str]) -> Mapping[str, Mapping[str, Any]]:
		return {a: dict(self.rows[a]) for a in assets if a in self.rows}


__all__ = [
	"MAX_BATCH",
	"MISSING_KEY",
	"DeliveryRepository",
	"DeliveryApi",
	"InMemoryDeliveryRepository",
]

"""T-080 — OpenAPI 3.1 belgesi. **Tek doğruluk kaynağı buradadır, YAML değil.**

NEDEN BELGE PYTHON'DA, YAML ÜRETİLİYOR
--------------------------------------
`docs/api/openapi.yaml` elle yazılsaydı, uç noktalar değiştikçe sessizce
eskirdi — ve eskidiğini kimse fark etmezdi, çünkü hiçbir test onu okumazdı.
Burada belge bir Python sözlüğüdür; YAML ondan **üretilir** ve
`tests/test_api_contracts.py` diskteki dosyanın üretilen çıktıyla birebir aynı
olduğunu doğrular. Ayrışma testi düşürür.

Aynı test bir adım daha atar: sözleşmede tanımlı her uç için `media_engine.api`
altında gerçekten bir Python fonksiyonu olduğunu ve tersini (koddaki her uç
noktanın belgede olduğunu) da doğrular. Belge ile kod arasındaki bağ böylece
tek yönlü bir temenni değil, iki yönlü bir kilit olur.

NEDEN KENDİ YAML YAZICIMIZ
--------------------------
`PyYAML` **yerelde kurulu değil** (ÖLÇÜLDÜ: `python3 -c "import yaml"` →
ModuleNotFoundError), bench ortamında **var** (6.0.3). Belgeyi üretmek için
PyYAML'a bağlanmak, `docs/api/openapi.yaml`'ı yalnız konteynerde
üretilebilir kılardı. Buradaki yazıcı YAML'ın küçük ve tam belirli bir alt
kümesini basar: eşleme, dizi, çift tırnaklı dizge, sayı, mantıksal değer,
null. Yorum, çapa, etiket, blok skaler YOK — üretilen çıktı bu yüzden her
YAML ayrıştırıcısında aynı okunur ve testte PyYAML varsa ayrıca doğrulanır.

SÜRÜM DONDURMA
--------------
`API_VERSION` bu sözleşmenin sürümüdür; `docs/api/README.md` §2 kuralları
tanımlar. Kırıcı değişiklik major artırır ve yeni bir yol öneki gerektirir.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

from tradehub_core.media.pipeline.api import envelope as env

#: Sözleşme sürümü. `docs/api/README.md` §2 — kırıcı değişiklikte major artar.
API_VERSION: str = "1.0.0"

#: OpenAPI belirtim sürümü. 3.1: JSON Schema 2020-12 ile birebir uyumlu,
#: `null` tipini `type: ["string", "null"]` ile ifade edebiliyor. 3.0 bunu
#: `nullable: true` ile yapıyordu ve JSON Schema'dan ayrışıyordu.
OPENAPI_VERSION: str = "3.1.0"

#: Yol öneki. Frappe bağlaması `/api/method/<dotted.path>` üretir; bu önek
#: mantıksal gruplamadır ve `docs/api/README.md` §3'te eşlenir.
BASE_PATH: str = "/api/media/v1"

JSON = "application/json"


# ── Küçük şema yardımcıları ─────────────────────────────────────────────


def _obj(props: Mapping[str, Any], *, required: Sequence[str] = (), desc: str = "") -> Dict[str, Any]:
	s: Dict[str, Any] = {"type": "object", "properties": dict(props)}
	if required:
		s["required"] = list(required)
	if desc:
		s["description"] = desc
	return s


def _ref(name: str) -> Dict[str, str]:
	return {"$ref": f"#/components/schemas/{name}"}


def _arr(items: Any, *, desc: str = "") -> Dict[str, Any]:
	s: Dict[str, Any] = {"type": "array", "items": items}
	if desc:
		s["description"] = desc
	return s


def _str(desc: str = "", **kw: Any) -> Dict[str, Any]:
	s: Dict[str, Any] = {"type": "string"}
	if desc:
		s["description"] = desc
	s.update(kw)
	return s


def _int(desc: str = "", **kw: Any) -> Dict[str, Any]:
	s: Dict[str, Any] = {"type": "integer"}
	if desc:
		s["description"] = desc
	s.update(kw)
	return s


def _num(desc: str = "", **kw: Any) -> Dict[str, Any]:
	s: Dict[str, Any] = {"type": "number"}
	if desc:
		s["description"] = desc
	s.update(kw)
	return s


def _bool(desc: str = "") -> Dict[str, Any]:
	s: Dict[str, Any] = {"type": "boolean"}
	if desc:
		s["description"] = desc
	return s


def _nullable(base: Mapping[str, Any], desc: str = "") -> Dict[str, Any]:
	"""OpenAPI 3.1: `type` dizi olabilir. `null` "ölçülmedi/yazılmadı" demektir
	ve bu ayrım motorun her katmanında anlamlıdır (`core/probe.py`)."""
	s = dict(base)
	t = s.get("type")
	s["type"] = [t, "null"] if isinstance(t, str) else t
	if desc:
		s["description"] = desc
	return s


def _unit(desc: str) -> Dict[str, Any]:
	"""0-1 normalize koordinat (INV-10). Piksel KABUL EDİLMEZ."""
	return {"type": "number", "minimum": 0, "maximum": 1, "description": desc}


# ── Hata kodu kataloğu ──────────────────────────────────────────────────
#
# İstemci karar verirken METNE değil KODA bakar (FR-060). Katalog bu yüzden
# sözleşmenin parçasıdır ve `x-error-codes` altında yayımlanır.

ERROR_CODES: Tuple[Dict[str, Any], ...] = (
	{"code": "media_unauthorized", "status": 401, "retryable": False,
	 "meaning": "Oturum yok."},
	{"code": "media_forbidden", "status": 403, "retryable": False,
	 "meaning": "Kimlik var, yetki yok."},
	{"code": "media_store_required", "status": 403, "retryable": False,
	 "meaning": "İşlem bir mağaza kapsamı gerektiriyor."},
	{"code": "media_not_found", "status": 404, "retryable": False,
	 "meaning": "Kaynak yok, yayınlanmamış ya da başka mağazanın."},
	{"code": "media_session_unknown", "status": 404, "retryable": False,
	 "meaning": "Yükleme oturumu yok ya da süresi doldu."},
	{"code": "media_slot_missing", "status": 404, "retryable": False,
	 "meaning": "Varlığın slot bilgisi yok; manifest kurulamaz."},
	{"code": "media_missing_field", "status": 400, "retryable": False,
	 "meaning": "Zorunlu alan verilmedi."},
	{"code": "media_bad_field", "status": 400, "retryable": False,
	 "meaning": "Alan biçimi ya da aralığı geçersiz."},
	{"code": "media_field_too_long", "status": 400, "retryable": False,
	 "meaning": "Alan uzunluk sınırını aşıyor."},
	{"code": "media_hash_mismatch", "status": 400, "retryable": False,
	 "meaning": "Yüklenen içeriğin özeti bildirilenle uyuşmuyor."},
	{"code": "media_not_private", "status": 400, "retryable": False,
	 "meaning": "Public medya için imzalı bağlantı istendi."},
	{"code": "media_batch_too_large", "status": 400, "retryable": False,
	 "meaning": "Toplu istek üst sınırı aşıldı."},
	{"code": "media_already_finalized", "status": 409, "retryable": False,
	 "meaning": "Tamamlanmış oturum iptal edilemez."},
	{"code": "media_precondition_failed", "status": 412, "retryable": False,
	 "meaning": "`If-Match` tutmadı; araya başka bir yazma girdi."},
	{"code": "media_too_large", "status": 413, "retryable": False,
	 "meaning": "İlan edilen boyut slot tavanını aşıyor."},
	{"code": "media_unavailable", "status": 503, "retryable": True,
	 "meaning": "Bağımlılık yok (imzalama anahtarı, depo, defter)."},
	{"code": "media_no_signing_key", "status": 503, "retryable": True,
	 "meaning": "İmzalama anahtarı yapılandırılmamış; sahte imza üretilmez."},
	{"code": "media_internal", "status": 500, "retryable": True,
	 "meaning": "Beklenmeyen hata; ayrıntı DIŞARI SIZDIRILMAZ."},
	{"code": "<slot_prefix>_<reason>", "status": 422, "retryable": False,
	 "meaning": "Politika ihlali. Önek slotun `on_violation.error_code_prefix` "
				"alanından (ör. `product_image_short_edge_too_small`)."},
	{"code": "media_policy_not_found", "status": 404, "retryable": False,
	 "meaning": "Bilinmeyen slot anahtarı."},
	{"code": "media_no_profile", "status": 404, "retryable": False,
	 "meaning": "Üretilmiş hiçbir türev yok; manifest kurulamaz."},
)


# ── Şemalar ─────────────────────────────────────────────────────────────


def _schemas() -> Dict[str, Any]:
	return {
		"Error": _obj(
			{
				"error_code": _str("Makine-okunur ret kodu. İstemci karar verirken METNE değil buna bakar (FR-060)."),
				"retryable": _bool("Aynı istek yeniden denenmeli mi. Kullanıcının dosyasıyla ilgili hatalar false."),
				"message": _str("Kullanıcıya gösterilebilir Türkçe metin: NEDEN + NASIL düzeltilir (FR-062)."),
				"details": _obj({}, desc="Ölçülen/beklenen değerler, slot anahtarı gibi ek bağlam."),
			},
			required=["error_code", "retryable", "message"],
			desc="Tüm hataların ortak gövdesi. Kaynak: tradehub_core/media/pipeline/contracts/errors.py::MediaEngineError.to_response()",
		),
		"Violation": _obj(
			{
				"code": _str("Slot önekli ihlal kodu."),
				"rule": _str("İhlal edilen kuralın adı."),
				"block": _str("Politikanın hangi bölümü.", enum=["accept", "require", "master", "quality", "content_rules", "video", "security", "policy", "role"]),
				"action": _str("Karar.", enum=["pass", "ignore", "warn", "auto_fix", "review", "manual_review", "reject"]),
				"message": _obj({"tr": _str(), "en": _str()}),
				"hint": _obj({"tr": _str(), "en": _str()}),
				"observed": {"description": "Ölçülen değer."},
				"expected": {"description": "Beklenen değer."},
				"retryable": _bool(),
				"source": _str("Kuralın kaynağı (dosya/satır ya da politika alanı)."),
			},
			required=["code", "rule", "block", "action"],
		),
		"SkippedRule": _obj(
			{
				"rule": _str(),
				"block": _str(),
				"reason": _str("Neden değerlendirilemedi (ör. not_measurable)."),
				"missing_input": _str(),
			},
			required=["rule", "block", "reason"],
			desc="Ölçülemediği için ATLANAN kural. Sessizce 'geçti' saymamak için kayda geçer.",
		),
		"Decision": _obj(
			{
				"allow": _bool("Engelleyici ihlal yok mu."),
				"slot": _str(),
				"role": _str(),
				"action": _str("En yüksek aksiyon."),
				"violations": _arr(_ref("Violation")),
				"normalized_targets": _obj({}, desc="Kabul edilen dosyanın NEYE dönüştürüleceği."),
				"skipped": _arr(_ref("SkippedRule")),
				"policy_version": _str(),
				"policy_status": _str(),
			},
			required=["allow", "slot", "action"],
		),
		"UploadSessionRequest": _obj(
			{
				"slot_key": _str("Slot anahtarı. ZORUNLU — bugünkü motorun en büyük boşluğu (docs/reports/00-upload-slot-envanteri.md §7-B B1)."),
				"file_name": _str("Özgün dosya adı."),
				"total_bytes": _int("İlan edilen toplam boyut.", minimum=1),
				"content_sha256": _str("Bilinen içerik özeti. Verilirse dosya zaten kayıtlıysa HİÇBİR BAYT taşınmaz.", pattern="^[0-9a-f]{64}$"),
				"idempotency_key": _str("İstemcinin kendi tekrar anahtarı; sunucu kararını etkilemez, izlemeye yazılır."),
			},
			required=["slot_key", "file_name", "total_bytes"],
		),
		"UploadSession": _obj(
			{
				"upload_id": _str("Oturum kimliği. Yinelenen içerikte BOŞTUR (oturum açılmamıştır)."),
				"slot_key": _str(),
				"file_name": _str(),
				"chunk_bytes": _int("Parça boyutu (chunked.py: 2 MB)."),
				"chunk_count": _int(),
				"total_bytes": _int(),
				"duplicate": _bool("İçerik zaten kayıtlı mı."),
				"asset": _str("Yinelenen içerikte var olan varlığın adı."),
				"expires_in": _int("Oturumun saniye cinsinden ömrü."),
				"ingest_state": _ref("IngestState"),
				"message": _str(),
			},
			required=["upload_id", "duplicate"],
		),
		"IngestState": _str(
			"Alım hattı durumu (tradehub_core/media/pipeline/core/state.py). Yaşam döngüsü eksenine DİKTİR.",
			enum=["Received", "Screened", "Validated", "Mastered", "Ready", "Rejected", "Quarantined", "Failed"],
		),
		"UploadStatus": _obj(
			{
				"upload_id": _str(),
				"slot_key": _str(),
				"file_name": _str(),
				"chunk_bytes": _int(),
				"chunk_count": _int(),
				"received": _arr(_int(), desc="Sunucuya ulaşmış parça sıraları."),
				"missing": _arr(_int(), desc="Eksik parça sıraları — istemci yalnız bunları gönderir."),
				"complete": _bool(),
				"finalized": _bool(),
				"asset": _str(),
				"ingest_state": _ref("IngestState"),
			},
			required=["upload_id", "complete", "finalized"],
		),
		"FinalizeRequest": _obj(
			{
				"role": _str("Yükleyenin rolü; politika rol kuralları için."),
				"alt_text": _str("Erişilebilirlik metni."),
				"extra": _obj({}, desc="Varlık kaydına eklenecek ek alanlar; çekirdek alanları EZEMEZ."),
			},
		),
		"FinalizeResult": _obj(
			{
				"asset": _str("Varlık adı."),
				"created": _bool("YENİ varlık açıldı mı. `false` ise bu istek idempotenttir."),
				"duplicate": _bool(),
				"slot_key": _str(),
				"upload_id": _str(),
				"content_sha256": _str(),
				"file_url": _str(),
				"width": _int(),
				"height": _int(),
				"byte_size": _int(),
				"ingest_state": _ref("IngestState"),
				"decision": _ref("Decision"),
				"message": _str(),
			},
			required=["asset", "created", "duplicate"],
		),
		"CropIntent": _obj(
			{
				"focal_x": _nullable(_unit("Odak X. null = kullanıcı hiç seçmedi (merkez DEĞİL).")),
				"focal_y": _nullable(_unit("Odak Y.")),
				"safe_x": _nullable(_unit("Güvenli alan sol kenarı.")),
				"safe_y": _nullable(_unit("Güvenli alan üst kenarı.")),
				"safe_w": _nullable(_unit("Güvenli alan genişliği.")),
				"safe_h": _nullable(_unit("Güvenli alan yüksekliği.")),
				"zoom": _nullable(_num("Stüdyo zoom çarpanı, 1-16. null = yazılmamış.")),
				"center_x": _nullable(_unit("Pan merkezi X. Yalnız zoom ile anlamlı.")),
				"center_y": _nullable(_unit("Pan merkezi Y. Yalnız zoom ile anlamlı.")),
				"method": _str("Kaydedilmiş yöntem etiketi.", enum=["", "override", "safe_focal", "focal", "smartcrop", "center"]),
				"confidence": _nullable(_unit("Öneri güveni.")),
				"approved_by_user": _bool(),
				"overrides": _arr(_ref("CropOverride")),
				"updated_at": _str("Son yazma zamanı — ISO 8601 + saat dilimi kayması (TUR-124); hiç yazılmadıysa boş dize."),
			},
			desc="Media Crop Intent. TÜM koordinatlar 0-1 normalize (INV-10); piksel kabul edilmez.",
		),
		"CropOverride": _obj(
			{
				"profile": _str("Profil adı — bu slotta TANIMLI olmalı."),
				"x": _unit("Sol kenar."),
				"y": _unit("Üst kenar."),
				"w": _unit("Genişlik."),
				"h": _unit("Yükseklik."),
				"method": _str(),
			},
			required=["profile", "x", "y", "w", "h"],
		),
		"CropWindow": _obj(
			{
				"x": _unit("Sol kenar."),
				"y": _unit("Üst kenar."),
				"w": _unit("Genişlik."),
				"h": _unit("Yükseklik."),
				"method": _str("Zincirde kazanan seviye."),
				"priority": _int("1 = en yüksek öncelik."),
				"profile": _str(),
				"width": _int("Profilin hedef genişliği."),
				"fit": _str(enum=["contain", "cover", "pad"]),
				"target_ratio": _nullable(_num("Hedef oran; null = serbest (contain/pad).")),
				"source_ratio": _num("Kaynağın piksel oranı."),
				"confidence": _num(),
				"approved_by_user": _bool(),
				"is_suggestion": _bool("UI'da 'öneri' rozeti gösterilmeli mi."),
				"pixels": _nullable(_obj({"left": _int(), "top": _int(), "width": _int(), "height": _int()}),
									"Kaynak ölçüsü bilinmiyorsa null — sayı UYDURULMAZ."),
			},
			required=["x", "y", "w", "h", "method"],
		),
		"CropIntentResponse": _obj(
			{
				"asset": _str(),
				"slot_key": _str(),
				"exists": _bool("Kayıt var mı. false ise örtük (merkez) niyet döner."),
				"intent": _ref("CropIntent"),
				"source": _obj({"width": _int(), "height": _int(), "source_ratio": _num()}),
				"windows": _arr(_ref("CropWindow")),
			},
			required=["asset", "exists", "intent", "windows"],
		),
		"SaveIntentRequest": _obj(
			{
				"focal_x": _unit("Odak X. `focal_y` ile BİRLİKTE verilir."),
				"focal_y": _unit("Odak Y."),
				"safe_area": _nullable(_obj({"x": _unit("."), "y": _unit("."), "w": _unit("."), "h": _unit(".")}),
									   "Boş sözlük güvenli alanı SİLER."),
				"zoom": _num("Stüdyo zoom çarpanı, 1-16. `center_x`/`center_y` ile BİRLİKTE verilir."),
				"center_x": _unit("Pan merkezi X."),
				"center_y": _unit("Pan merkezi Y."),
				"overrides": _arr(_ref("CropOverride")),
				"approved_by_user": _bool(),
				"confidence": _unit("Öneri güveni."),
				"method": _str(enum=["override", "safe_focal", "focal", "smartcrop", "center"]),
			},
		),
		"FocalSuggestion": _obj(
			{
				"focal_x": _unit("Önerilen odak X."),
				"focal_y": _unit("Önerilen odak Y."),
				"confidence": _unit("Kenar enerjisinin yoğunlaşma oranı. Önerinin DOĞRU olduğunu ölçmez."),
				"measured": _bool("Gerçekten ölçüldü mü. false ise merkez döner."),
				"reason": _str(enum=["measured", "pillow_unavailable", "source_unavailable", "no_edge_energy"]),
				"grid": _int("Ölçüm ızgarası."),
				"threshold": _num("Kullanılan güven eşiği."),
				"threshold_calibrated": _bool("Eşik kalibre edildi mi. Bugün FALSE (ÖLÇÜLMEDİ)."),
				"above_threshold": _bool(),
				"method": _str(),
			},
			required=["focal_x", "focal_y", "confidence", "measured", "reason"],
		),
		"SuggestFocalResponse": _obj(
			{
				"asset": _str(),
				"slot_key": _str(),
				"suggestion": _ref("FocalSuggestion"),
				"applied": _bool("Her zaman false: öneri YAZILMAZ, kullanıcı onayına sunulur."),
				"windows": _arr(_ref("CropWindow")),
			},
			required=["asset", "suggestion", "applied"],
		),
		"CropPreviewRequest": _obj(
			{
				"profile": _str("Önizlenecek profil adı."),
				"intent": _ref("CropIntent"),
				"include_image": _bool("Görüntü de üretilsin mi (data: URI)."),
			},
			required=["profile"],
		),
		"CropPreviewResponse": _obj(
			{
				"asset": _str(),
				"slot_key": _str(),
				"window": _ref("CropWindow"),
				"image": _nullable(_str("data: URI. Üretilemezse null."), "Üretilemezse null; sebep `image_reason`."),
				"image_reason": _str(),
			},
			required=["asset", "window"],
		),
		"ManifestVariant": _obj(
			{
				"profile": _str(),
				"url": _str(),
				"width": _int(),
				"height": _int(),
				"format": _str(),
				"type": _str("MIME türü."),
				"available": _bool("ÜRETİLMİŞ mi. false olan varyant srcset'e GİRMEZ."),
			},
			required=["profile", "url", "width", "format", "available"],
		),
		"ManifestSource": _obj(
			{
				"type": _str("`<source type>` değeri."),
				"srcset": _str("Görselde `<url> <w>w` listesi; videoda tek URL."),
				"sizes": _str("Boş olabilir — ÖLÇÜLMEDİ. Yanlış `sizes` yazmaktansa boş bırakılır."),
			},
			required=["type", "srcset"],
		),
		"Manifest": _obj(
			{
				"asset": _str(),
				"slot_key": _str(),
				"kind": _str(enum=["image", "video"]),
				"src": _str("`<img src>` yedeği — orta basamak."),
				"sizes": _str(),
				"alt": _str(),
				"loading": _str(enum=["lazy", "eager"]),
				"decoding": _str(enum=["async", "sync", "auto"]),
				"fetchpriority": _str(enum=["", "high", "low", "auto"]),
				"width": _int("İçsel genişlik; 0 = bilinmiyor (CLS için sabit ölçü kullanın)."),
				"height": _int("İçsel yükseklik; 0 = bilinmiyor."),
				"aspect_ratio": _num("0 = oran bilinmiyor."),
				"sources": _arr(_ref("ManifestSource")),
				"variants": _arr(_ref("ManifestVariant")),
				"poster": _str(),
				"captions": _str(),
				"version_hash": _str(),
				"available_profiles": _arr(_str()),
				"missing_profiles": _arr(_str()),
				"sizes_source": _str(enum=["table", "caller", "unmeasured"]),
			},
			required=["asset", "slot_key", "src", "sources", "variants"],
		),
		"ManifestBatchRequest": _obj(
			{
				"assets": _arr(_str(), desc="Varlık adları. Tekrarlar tekilleştirilir, sıra korunur."),
				"sizes": _str(),
				"lcp_asset": _str("Yalnız BİR varlığa `fetchpriority=high` verir."),
			},
			required=["assets"],
		),
		"ManifestBatchResponse": _obj(
			{
				"manifests": _obj({}, desc="{varlık: Manifest}"),
				"missing": _arr(_str(), desc="Bulunamayanlar. SEBEP VERİLMEZ — yok/yayınlanmamış/başkasının ayrımı sızmamalı."),
				"requested": _int(),
				"returned": _int(),
				"errors": _obj({}, desc="{varlık: istisna tipi} — kısmi başarı görünür kalır."),
			},
			required=["manifests", "missing", "requested", "returned"],
		),
		"SignedUrlRequest": _obj(
			{
				"ttl_seconds": _int("İstenen ömür. [60, 86400] aralığına KELEPÇELENİR; istenen değil kelepçelenen geçerlidir."),
				"path": _str("İmzalanacak türev yolu. Verilmezse master imzalanır; yolun varlığa ait olduğu doğrulanır."),
			},
		),
		"SignedUrl": _obj(
			{
				"url": _str(),
				"asset": _str(),
				"path": _str(),
				"exp": _int("Bitiş zamanı (epoch saniye)."),
				"expires_at": _str("Son geçerlilik — ISO 8601 + saat dilimi kayması (TUR-124)."),
				"expires_epoch": _int(),
				"ttl_seconds": _int("Kelepçelenmiş gerçek ömür."),
			},
			required=["url", "exp", "ttl_seconds"],
		),
		"SlotPolicySummary": _obj(
			{
				"slot_key": _str(),
				"title": _str(),
				"status": _str(enum=["draft", "active"]),
				"schema_version": _str(),
				"roles": _arr(_str()),
				"max_bytes": _int(),
				"max_megapixels_hard": _nullable(_num()),
				"profile_count": _int(),
				"rendition_count": _int(),
				"content_rule_count": _int(),
				"is_video": _bool(),
				"error_code_prefix": _str(),
				"source": _str("Politika dosyasının yolu."),
			},
			required=["slot_key", "status", "profile_count"],
		),
		"SlotPolicyList": _obj(
			{"slots": _arr(_ref("SlotPolicySummary")), "count": _int()},
			required=["slots", "count"],
		),
		"SlotPolicyDetail": _obj(
			{"slot_key": _str(), "policy": _obj({}, desc="Politikanın TAMAMI — `sources` notları dâhil."), "source": _str()},
			required=["slot_key", "policy"],
		),
		"PolicyFinding": _obj(
			{"slot_key": _str(), "source": _str(), "code": _str(), "message": _str()},
			required=["slot_key", "code", "message"],
		),
		"PolicyValidationReport": _obj(
			{
				"slot_count": _int(),
				"finding_count": _int(),
				"findings": _arr(_ref("PolicyFinding")),
				"ok": _bool(),
				"schema_validated": _bool("Bugün FALSE: `jsonschema` paketi kurulu değil (ÖLÇÜLDÜ)."),
				"schema_note": _str(),
			},
			required=["slot_count", "findings", "ok", "schema_validated"],
		),
		"RenditionRow": _obj(
			{
				"profile": _str(),
				"width": _int(),
				"height": _int(),
				"format": _str(),
				"fit": _str(),
				"target_ratio": _str(),
				"quality": _nullable(_num("null = KALİBRE EDİLMEDİ; sayı uydurulmaz.")),
				"quality_calibrated": _bool(),
				"serves": _arr(_str(), desc="Bu basamağın hizmet ettiği render noktaları (serbest metin)."),
			},
			required=["profile", "width", "format"],
		),
		"RenditionMatrix": _obj(
			{
				"slots": _arr(_obj({
					"slot_key": _str(),
					"profile_count": _int(),
					"rendition_count": _int(),
					"renditions": _arr(_ref("RenditionRow")),
				})),
				"total_renditions": _int(),
			},
			required=["slots", "total_renditions"],
		),
		"EvaluateRequest": _obj(
			{
				"slot_key": _str(),
				"probe": _obj({}, desc="core/probe.py::MediaProbe alanları. Tanınmayanlar atılır ve `ignored_fields` ile bildirilir."),
				"role": _str(),
			},
			required=["slot_key", "probe"],
		),
		"EvaluateResponse": _obj(
			{
				"allow": _bool(),
				"slot": _str(),
				"action": _str(),
				"violations": _arr(_ref("Violation")),
				"skipped": _arr(_ref("SkippedRule")),
				"normalized_targets": _obj({}),
				"policy_version": _str(),
				"policy_status": _str(),
				"role": _str(),
				"accepted_fields": _arr(_str()),
				"ignored_fields": _arr(_str()),
			},
			required=["allow", "slot", "action", "accepted_fields", "ignored_fields"],
		),
		"CoverageReport": _obj(
			{
				"scanned": _int(),
				"limit": _int(),
				"truncated": _bool("Tarama tavana çarptıysa true; oran KISMİ örnekten hesaplanmıştır."),
				"total": _int(),
				"complete": _int(),
				"complete_ratio": _num(),
				"by_slot": _obj({}, desc="{slot: {total, complete, partial, empty, expected_profiles, missing_profile_counts}}"),
			},
			required=["scanned", "total", "complete", "complete_ratio", "by_slot"],
		),
		"ReprocessPlanRequest": _obj(
			{
				"slot_key": _str(),
				"master_sha256": _str(),
				"crop_intent": _ref("CropIntent"),
				"force": _bool("Tüm satırları `render`a çevirir — kararı GÖRMEK için."),
			},
			required=["slot_key", "master_sha256"],
		),
		"ReprocessPlan": _obj(
			{
				"slot_key": _str(),
				"master_sha256": _str(),
				"force": _bool(),
				"counts": _obj({"render": _int(), "refresh": _int(), "skip": _int()}),
				"work_units": _int("render + refresh — gerçekten yapılacak iş."),
				"plan": _arr(_obj({
					"profile": _str(),
					"format": _str(),
					"width": _int(),
					"action": _str(enum=["render", "refresh", "skip"]),
					"reason": _str(),
					"key": _str("Türetme anahtarı — idempotensi defterinin kimliği."),
					"should_render": _bool(),
				})),
			},
			required=["slot_key", "counts", "plan"],
		),
		"JobStatusRequest": _obj(
			{
				"kind": _str(enum=["media.scan", "media.evaluate", "media.master", "media.derive", "media.transcode"]),
				"target": _str(),
				"content_hash": _str("Verilirse `target` anahtara GİRMEZ: aynı içerik farklı adla bir kez işlenir."),
				"params": _obj({}),
			},
			required=["kind"],
		),
		"JobStatus": _obj(
			{
				"key": _str("İdempotensi anahtarı — sunucu üretir, istemci uydurmaz."),
				"kind": _str(),
				"state": _str(enum=["", "running", "completed", "partial", "error"]),
				"max_attempts": _int(),
				"backoff_seconds": _arr(_int()),
				"stale_after_seconds": _int(),
				"upstream_available": _bool("Üretim sabitleri `tradehub_core.media.jobs`'tan mı okundu."),
			},
			required=["key", "kind"],
		),
		"StoragePlan": _obj(
			{
				"mode": _str("Etkin depolama kipi."),
				"requested_mode": _str("İstenen kip."),
				"degraded": _bool("İstenen kip kurulamadı mı (ör. S3 istendi, boto3 yok)."),
				"boto3_available": _bool(),
				"modes": _arr(_str()),
			},
			required=["mode", "degraded"],
		),
	}


# ── Uç noktalar ─────────────────────────────────────────────────────────
#
# `x-python` alanı sözleşmeyi koda bağlar: `tests/test_api_contracts.py` her
# operasyon için o niteliğin gerçekten var olduğunu doğrular. Belge ile kod
# arasındaki bağ böylece temenni değil, kilit olur.

_ERR = {"$ref": "#/components/responses/Error"}


def _op(
	*,
	tag: str,
	operation_id: str,
	summary: str,
	python: str,
	responses: Mapping[str, Any],
	parameters: Sequence[Mapping[str, Any]] = (),
	body: Mapping[str, Any] | None = None,
	description: str = "",
	security_note: str = "",
) -> Dict[str, Any]:
	op: Dict[str, Any] = {
		"tags": [tag],
		"operationId": operation_id,
		"summary": summary,
		"x-python": python,
	}
	if description:
		op["description"] = description
	if security_note:
		op["x-authorization"] = security_note
	if parameters:
		op["parameters"] = list(parameters)
	if body is not None:
		op["requestBody"] = {"required": True, "content": {JSON: {"schema": body}}}
	cevaplar: Dict[str, Any] = {}
	for kod, tanim in responses.items():
		cevaplar[str(kod)] = tanim
	for kod in ("400", "401", "403", "404", "409", "412", "413", "422", "429", "500", "503"):
		cevaplar.setdefault(kod, _ERR)
	op["responses"] = dict(sorted(cevaplar.items()))
	return op


def _json_response(desc: str, schema: Mapping[str, Any], *, etag: bool = False) -> Dict[str, Any]:
	r: Dict[str, Any] = {"description": desc, "content": {JSON: {"schema": dict(schema)}}}
	if etag:
		r["headers"] = {
			"ETag": {"description": "Gövdenin içerik-adresli etiketi.", "schema": {"type": "string"}},
			"Cache-Control": {"description": "Önbellek politikası.", "schema": {"type": "string"}},
		}
	return r


def _param(name: str, where: str, schema: Mapping[str, Any], *, required: bool = False, desc: str = "") -> Dict[str, Any]:
	p: Dict[str, Any] = {"name": name, "in": where, "schema": dict(schema)}
	if required:
		p["required"] = True
	if desc:
		p["description"] = desc
	return p


_P_ASSET = _param("asset", "path", {"type": "string"}, required=True, desc="Medya varlığının adı.")
_P_UPLOAD = _param("upload_id", "path", {"type": "string"}, required=True, desc="Yükleme oturumu kimliği.")
_P_INM = _param("If-None-Match", "header", {"type": "string"}, desc="Bilinen ETag; tutarsa 304 döner.")
_P_IM = _param("If-Match", "header", {"type": "string"}, desc="İyimser kilit; tutmazsa 412 döner.")

_NOT_MODIFIED = {"description": "Gövde değişmedi; içerik gönderilmez."}


def _paths() -> Dict[str, Any]:
	return {
		f"{BASE_PATH}/upload/sessions": {
			"post": _op(
				tag="upload",
				operation_id="createUploadSession",
				summary="Yükleme oturumu aç",
				description=(
					"Slot, boyut ve (verilmişse) içerik özeti oturum AÇILMADAN denetlenir. "
					"İçerik zaten kayıtlıysa oturum açılmaz ve 200 + duplicate=true döner: hiçbir bayt taşınmaz."
				),
				python="tradehub_core.media.pipeline.api.upload.UploadApi.create_session",
				security_note="Oturum + mağaza kapsamı zorunlu.",
				body=_ref("UploadSessionRequest"),
				responses={
					"200": _json_response("İçerik zaten kayıtlı; oturum açılmadı.", _ref("UploadSession")),
					"201": _json_response("Oturum açıldı.", _ref("UploadSession")),
				},
			)
		},
		f"{BASE_PATH}/upload/sessions/{{upload_id}}": {
			"get": _op(
				tag="upload",
				operation_id="getUploadStatus",
				summary="Oturum durumu",
				description="Eksik parça listesiyle döner; istemci yarıda kalan yüklemeyi sürdürür.",
				python="tradehub_core.media.pipeline.api.upload.UploadApi.status",
				parameters=[_P_UPLOAD, _P_INM],
				responses={
					"200": _json_response("Durum.", _ref("UploadStatus"), etag=True),
					"304": _NOT_MODIFIED,
				},
			),
			"delete": _op(
				tag="upload",
				operation_id="abortUploadSession",
				summary="Oturumu iptal et",
				description=(
					"İDEMPOTENT: bilinmeyen ya da zaten iptal edilmiş oturum da 204 döner. "
					"Sonuçlanmış (varlık üretmiş) oturum iptal EDİLEMEZ (409)."
				),
				python="tradehub_core.media.pipeline.api.upload.UploadApi.abort",
				parameters=[_P_UPLOAD],
				responses={"204": {"description": "Oturum yok edildi."}},
			),
		},
		f"{BASE_PATH}/upload/sessions/{{upload_id}}/chunks/{{index}}": {
			"put": _op(
				tag="upload",
				operation_id="putUploadChunk",
				summary="Parça yükle",
				description=(
					"Mevcut motorun (tradehub_core/media/chunked.py) sarılmasıdır. Parçalar SIRASIZ gelebilir; "
					"aynı parçanın tekrarı zararsızdır."
				),
				python="tradehub_core.media.pipeline.api.upload.UploadApi.put_chunk",
				parameters=[
					_P_UPLOAD,
					_param("index", "path", {"type": "integer", "minimum": 0}, required=True, desc="Parça sırası."),
				],
				body={"type": "string", "format": "binary", "description": "Parçanın ham baytları."},
				responses={"200": _json_response("Parça alındı.", _obj({
					"upload_id": _str(), "received": _int(), "chunk_count": _int(), "complete": _bool(),
				}))},
			)
		},
		f"{BASE_PATH}/upload/sessions/{{upload_id}}/finalize": {
			"post": _op(
				tag="upload",
				operation_id="finalizeUpload",
				summary="Yüklemeyi tamamla",
				description=(
					"Birleştir → künye → politika → tekilleştirme → kayıt. AYNI İÇERİK HASHİ ile ikinci finalize "
					"YENİ VARLIK ÜRETMEZ: 200 + created=false döner (INV-06)."
				),
				python="tradehub_core.media.pipeline.api.upload.UploadApi.finalize",
				parameters=[_P_UPLOAD],
				body=_ref("FinalizeRequest"),
				responses={
					"200": _json_response("İçerik zaten vardı; yeni varlık açılmadı.", _ref("FinalizeResult")),
					"201": _json_response("Varlık açıldı.", _ref("FinalizeResult")),
				},
			)
		},
		f"{BASE_PATH}/assets/{{asset}}/crop-intent": {
			"get": _op(
				tag="crop",
				operation_id="getCropIntent",
				summary="Kırpma niyetini oku",
				description="Niyet yazılmamışsa 404 değil, exists=false ile 200 döner: her varlığın örtük bir niyeti vardır.",
				python="tradehub_core.media.pipeline.api.crop.CropApi.get_intent",
				parameters=[_P_ASSET, _P_INM],
				responses={
					"200": _json_response("Niyet + çözülmüş pencereler.", _ref("CropIntentResponse"), etag=True),
					"304": _NOT_MODIFIED,
				},
			),
			"put": _op(
				tag="crop",
				operation_id="saveCropIntent",
				summary="Kırpma niyetini yaz",
				description="TÜM koordinatlar 0-1 normalize olmak zorundadır (INV-10); 1'den büyük değer düzeltilmez, REDDEDİLİR.",
				python="tradehub_core.media.pipeline.api.crop.CropApi.save_intent",
				parameters=[_P_ASSET, _P_IM],
				body=_ref("SaveIntentRequest"),
				responses={"200": _json_response("Yazıldı.", _ref("CropIntentResponse"), etag=True)},
			),
		},
		f"{BASE_PATH}/assets/{{asset}}/crop-intent/suggest-focal": {
			"post": _op(
				tag="crop",
				operation_id="suggestFocalPoint",
				summary="Odak noktası öner",
				description=(
					"Kenar enerjisinin ağırlık merkezi. Nesne tanıma DEĞİLDİR. Öneri YAZILMAZ; kullanıcı onayına sunulur. "
					"Eşik KALİBRE EDİLMEDİ (threshold_calibrated=false)."
				),
				python="tradehub_core.media.pipeline.api.crop.CropApi.suggest_focal",
				parameters=[_P_ASSET],
				responses={"200": _json_response("Öneri (ölçülemediyse measured=false).", _ref("SuggestFocalResponse"))},
			)
		},
		f"{BASE_PATH}/assets/{{asset}}/crop-preview": {
			"post": _op(
				tag="crop",
				operation_id="previewCrop",
				summary="Kadrajı önizle",
				description="Kaydedilmemiş niyet gönderilebilir. Görüntü `image/render.py` ile üretilir; ayrı bir ölçekleme yolu yoktur.",
				python="tradehub_core.media.pipeline.api.crop.CropApi.preview",
				parameters=[_P_ASSET],
				body=_ref("CropPreviewRequest"),
				responses={"200": _json_response("Pencere (+ istenirse görüntü).", _ref("CropPreviewResponse"))},
			)
		},
		f"{BASE_PATH}/delivery/{{asset}}/manifest": {
			"get": _op(
				tag="delivery",
				operation_id="getDeliveryManifest",
				summary="Teslim manifesti",
				description=(
					"YALNIZ üretilmiş genişlikler döner. Yayınlanmamış varlık 404'tür (403 DEĞİL: varlığın var olduğu sızmamalı)."
				),
				python="tradehub_core.media.pipeline.api.delivery.DeliveryApi.manifest",
				security_note="Public varlıklar için oturum gerekmez; private varlıkta okuma yetkisi aranır.",
				parameters=[
					_P_ASSET,
					_param("sizes", "query", {"type": "string"}, desc="Çağıranın bildiği `sizes`; verilmezse tablo (bugün boş)."),
					_param("is_lcp_candidate", "query", {"type": "boolean"}, desc="LCP adayıysa eager+high."),
					_P_INM,
				],
				responses={
					"200": _json_response("Manifest.", _ref("Manifest"), etag=True),
					"304": _NOT_MODIFIED,
				},
			)
		},
		f"{BASE_PATH}/delivery/manifests": {
			"post": _op(
				tag="delivery",
				operation_id="getDeliveryManifestBatch",
				summary="Toplu teslim manifesti",
				description=(
					"Listeleme sayfası için. Kısmi başarı HATA DEĞİLDİR: bulunamayanlar `missing` altında listelenir, "
					"sebep verilmez."
				),
				python="tradehub_core.media.pipeline.api.delivery.DeliveryApi.manifest_batch",
				parameters=[_P_INM],
				body=_ref("ManifestBatchRequest"),
				responses={
					"200": _json_response("Manifestler + eksikler.", _ref("ManifestBatchResponse"), etag=True),
					"304": _NOT_MODIFIED,
				},
			)
		},
		f"{BASE_PATH}/delivery/{{asset}}/signed-url": {
			"post": _op(
				tag="delivery",
				operation_id="createSignedUrl",
				summary="İmzalı, süreli adres",
				description=(
					"Yalnız private varlık için. TTL [60, 86400] aralığına kelepçelenir. Yanıt `Cache-Control: private, no-store` "
					"taşır: paylaşılan bir önbellek imzayı başka kullanıcıya servis etmemeli."
				),
				python="tradehub_core.media.pipeline.api.delivery.DeliveryApi.signed_url",
				security_note="Oturum zorunlu; private varlıkta okuma yetkisi aranır.",
				parameters=[_P_ASSET],
				body=_ref("SignedUrlRequest"),
				responses={"200": _json_response("İmzalı adres.", _ref("SignedUrl"))},
			)
		},
		f"{BASE_PATH}/admin/slot-policies": {
			"get": _op(
				tag="admin",
				operation_id="listSlotPolicies",
				summary="Slot politikalarını listele",
				python="tradehub_core.media.pipeline.api.admin.AdminApi.list_slot_policies",
				security_note="System Manager | Marketplace Admin.",
				parameters=[_P_INM],
				responses={
					"200": _json_response("Özet liste.", _ref("SlotPolicyList"), etag=True),
					"304": _NOT_MODIFIED,
				},
			)
		},
		f"{BASE_PATH}/admin/slot-policies/{{slot_key}}": {
			"get": _op(
				tag="admin",
				operation_id="getSlotPolicy",
				summary="Slot politikasının tamamı",
				description="`sources` notları dâhil döner: bir eşiğin NEDEN o sayı olduğu ancak orada yazılıdır.",
				python="tradehub_core.media.pipeline.api.admin.AdminApi.get_slot_policy",
				security_note="System Manager | Marketplace Admin.",
				parameters=[
					_param("slot_key", "path", {"type": "string"}, required=True),
					_P_INM,
				],
				responses={
					"200": _json_response("Politika.", _ref("SlotPolicyDetail"), etag=True),
					"304": _NOT_MODIFIED,
				},
			)
		},
		f"{BASE_PATH}/admin/slot-policies/validate": {
			"post": _op(
				tag="admin",
				operation_id="validateSlotPolicies",
				summary="Politikaların yapısal doğrulaması",
				description="JSON-Schema doğrulaması YAPILMAZ (`jsonschema` kurulu değil); yanıt bunu schema_validated=false ile söyler.",
				python="tradehub_core.media.pipeline.api.admin.AdminApi.validate_policies",
				security_note="System Manager | Marketplace Admin.",
				responses={"200": _json_response("Bulgular.", _ref("PolicyValidationReport"))},
			)
		},
		f"{BASE_PATH}/admin/rendition-matrix": {
			"get": _op(
				tag="admin",
				operation_id="getRenditionMatrix",
				summary="Üretim matrisi (profil × biçim)",
				description="Her satır bir encode, bir dosya, bir depo nesnesi demektir — doğrudan maliyet.",
				python="tradehub_core.media.pipeline.api.admin.AdminApi.rendition_matrix",
				security_note="System Manager | Marketplace Admin.",
				parameters=[
					_param("slot_key", "query", {"type": "string"}, desc="Boşsa tüm slotlar."),
					_P_INM,
				],
				responses={
					"200": _json_response("Matris.", _ref("RenditionMatrix"), etag=True),
					"304": _NOT_MODIFIED,
				},
			)
		},
		f"{BASE_PATH}/admin/policy-evaluations": {
			"post": _op(
				tag="admin",
				operation_id="evaluatePolicy",
				summary="Politika kuru çalıştırma",
				description="Dosya yüklemeden, iş atmadan, bayt yazmadan bir künyenin slottan geçip geçmediğini ölçer.",
				python="tradehub_core.media.pipeline.api.admin.AdminApi.evaluate_policy",
				security_note="System Manager | Marketplace Admin.",
				body=_ref("EvaluateRequest"),
				responses={"200": _json_response("Karar.", _ref("EvaluateResponse"))},
			)
		},
		f"{BASE_PATH}/admin/delivery-coverage": {
			"get": _op(
				tag="admin",
				operation_id="getDeliveryCoverage",
				summary="Türev merdiveni kapsamı",
				description=(
					"Kaç varlığın merdiveni TAM. Dosyanın diskte olduğu DOĞRULANMAZ — o iş media_admin'in "
					"verify/repair uçlarınındır."
				),
				python="tradehub_core.media.pipeline.api.admin.AdminApi.delivery_coverage",
				security_note="System Manager | Marketplace Admin.",
				parameters=[
					_param("slot_key", "query", {"type": "string"}),
					_param("limit", "query", {"type": "integer", "minimum": 1, "maximum": 5000}),
				],
				responses={"200": _json_response("Kapsam.", _ref("CoverageReport"))},
			)
		},
		f"{BASE_PATH}/admin/reprocess-plans": {
			"post": _op(
				tag="admin",
				operation_id="planReprocess",
				summary="Yeniden işleme planı",
				description="Planı verir, işi kuyruğa ATMAZ. Kararı image/reprocess.py::decide üretir.",
				python="tradehub_core.media.pipeline.api.admin.AdminApi.plan_reprocess",
				security_note="System Manager | Marketplace Admin.",
				body=_ref("ReprocessPlanRequest"),
				responses={"200": _json_response("Plan.", _ref("ReprocessPlan"))},
			)
		},
		f"{BASE_PATH}/admin/job-status": {
			"post": _op(
				tag="admin",
				operation_id="getJobStatus",
				summary="İş anahtarı ve durumu",
				description="Anahtarı SUNUCU üretir (core/jobs.py::idempotency_key); istemcinin uydurduğu anahtar kilidi delerdi.",
				python="tradehub_core.media.pipeline.api.admin.AdminApi.job_status",
				security_note="System Manager | Marketplace Admin.",
				body=_ref("JobStatusRequest"),
				responses={"200": _json_response("Durum.", _ref("JobStatus"))},
			)
		},
		f"{BASE_PATH}/admin/storage-plan": {
			"get": _op(
				tag="admin",
				operation_id="getStoragePlan",
				summary="Etkin depolama kipi",
				description="`degraded=true` istenen kip ile kurulabilen kipin ayrıştığını söyler (ör. S3 istendi, boto3 yok).",
				python="tradehub_core.media.pipeline.api.admin.AdminApi.storage_plan",
				security_note="System Manager | Marketplace Admin.",
				responses={"200": _json_response("Plan.", _ref("StoragePlan"))},
			)
		},
	}


def build_document() -> Dict[str, Any]:
	"""OpenAPI 3.1 belgesinin tamamı. **Saf fonksiyon** — her çağrı aynı sözlük."""
	return {
		"openapi": OPENAPI_VERSION,
		"info": {
			"title": "İstoç Medya Motoru API",
			"version": API_VERSION,
			"summary": "Yükleme, kırpma, teslim ve yönetim uçları.",
			"description": (
				"media_engine bir KÜTÜPHANEDİR; bu belge onun uç noktalarının sözleşmesidir. "
				"Fonksiyonlar `@frappe.whitelist()` taşımaz, `ApiResponse` döndürür. "
				"Frappe'ye bağlama noktası docs/api/README.md §3'te anlatılır. "
				"Belgenin tek doğruluk kaynağı tradehub_core/media/pipeline/api/spec.py'dir; bu YAML ondan üretilir."
			),
			"license": {"name": "Proprietary", "identifier": "LicenseRef-Istoc-Proprietary"},
		},
		"servers": [
			{"url": "https://istoc.localhost", "description": "Yerel geliştirme (docker compose)."},
		],
		"tags": [
			{"name": "upload", "description": "Parçalı yükleme oturumları (T-081)."},
			{"name": "crop", "description": "Kırpma niyeti ve önizleme (T-082)."},
			{"name": "delivery", "description": "Teslim manifesti ve imzalı adres (T-083)."},
			{"name": "admin", "description": "Yönetim — media_admin.py'de KARŞILIĞI OLMAYAN uçlar (T-084)."},
		],
		"paths": _paths(),
		"components": {
			"schemas": _schemas(),
			"responses": {
				"Error": {
					"description": "Kodlu ret. İstemci METNE değil `error_code`a bakar (FR-060).",
					"content": {JSON: {"schema": _ref("Error")}},
				}
			},
			"securitySchemes": {
				"frappeToken": {
					"type": "apiKey",
					"in": "header",
					"name": "Authorization",
					"description": "`token <api_key>:<api_secret>` — Frappe API anahtarı.",
				},
				"frappeSession": {
					"type": "apiKey",
					"in": "cookie",
					"name": "sid",
					"description": "Tarayıcı oturum çerezi. CSRF belirteci POST/PUT/DELETE'te zorunludur.",
				},
			},
		},
		"security": [{"frappeToken": []}, {"frappeSession": []}],
		"x-error-codes": [dict(e) for e in ERROR_CODES],
		"x-contract": {
			"source_of_truth": "tradehub_core/media/pipeline/api/spec.py",
			"generated_file": "docs/api/openapi.yaml",
			"regenerate": "python3 -c \"from tradehub_core.media.pipeline.api import spec; spec.write_yaml()\"",
			"drift_test": "tests/test_api_contracts.py",
		},
	}


# ── YAML yazıcı ─────────────────────────────────────────────────────────
#
# YAML'ın belirli bir alt kümesi. Yorum/çapa/etiket/blok skaler YOK; her dizge
# çift tırnaklı basılır. Amaç güzellik değil, TEKRAR ÜRETİLEBİLİRLİK: aynı
# sözlük her zaman aynı baytları verir, böylece "değişti mi" sorusu `diff` ile
# yanıtlanabilir.

_ESCAPES = {
	"\\": "\\\\",
	'"': '\\"',
	"\n": "\\n",
	"\r": "\\r",
	"\t": "\\t",
}


def _quote(value: str) -> str:
	out = []
	for ch in value:
		if ch in _ESCAPES:
			out.append(_ESCAPES[ch])
		elif ord(ch) < 0x20:
			out.append(f"\\x{ord(ch):02x}")
		else:
			out.append(ch)
	return '"' + "".join(out) + '"'


def _scalar(value: Any) -> str:
	if value is None:
		return "null"
	if isinstance(value, bool):
		return "true" if value else "false"
	if isinstance(value, int):
		return str(value)
	if isinstance(value, float):
		# `repr` kısa ve tur-atlatan (round-trip) gösterimi verir.
		return repr(value)
	return _quote(str(value))


def _emit(value: Mapping[str, Any], indent: int, out: List[str]) -> None:
	pad = " " * indent
	for key, val in value.items():
		k = _quote(str(key))
		if isinstance(val, Mapping):
			if val:
				out.append(f"{pad}{k}:")
				_emit(val, indent + 2, out)
			else:
				out.append(f"{pad}{k}: {{}}")
		elif isinstance(val, (list, tuple)):
			if val:
				out.append(f"{pad}{k}:")
				_emit_list(list(val), indent + 2, out)
			else:
				out.append(f"{pad}{k}: []")
		else:
			out.append(f"{pad}{k}: {_scalar(val)}")


def _emit_list(items: List[Any], indent: int, out: List[str]) -> None:
	pad = " " * indent
	for item in items:
		if isinstance(item, Mapping):
			if not item:
				out.append(f"{pad}- {{}}")
				continue
			gecici: List[str] = []
			_emit(item, indent + 2, gecici)
			out.append(pad + "- " + gecici[0][indent + 2 :])
			out.extend(gecici[1:])
		elif isinstance(item, (list, tuple)):
			if not item:
				out.append(f"{pad}- []")
				continue
			gecici = []
			_emit_list(list(item), indent + 2, gecici)
			out.append(pad + "- " + gecici[0][indent + 2 :])
			out.extend(gecici[1:])
		else:
			out.append(f"{pad}- {_scalar(item)}")


def dump_yaml(document: Mapping[str, Any]) -> str:
	"""Belgeyi YAML'a bas. Deterministik: aynı girdi → aynı baytlar."""
	out: List[str] = [
		"# ÜRETİLMİŞ DOSYA — ELLE DÜZENLEMEYİN.",
		"# Kaynak: tradehub_core/media/pipeline/api/spec.py :: build_document()",
		"# Yeniden üret: python3 -c \"from tradehub_core.media.pipeline.api import spec; spec.write_yaml()\"",
		"# Sapma testi: tests/test_api_contracts.py",
	]
	_emit(document, 0, out)
	return "\n".join(out) + "\n"


def yaml_path():
	"""`docs/api/openapi.yaml`'ın mutlak yolu."""
	from pathlib import Path

	return Path(__file__).resolve().parents[4] / "docs" / "api" / "openapi.yaml"


def write_yaml(path=None) -> str:
	"""Belgeyi diske yaz ve yolu döndür."""
	from pathlib import Path

	hedef = Path(path) if path else yaml_path()
	hedef.parent.mkdir(parents=True, exist_ok=True)
	hedef.write_text(dump_yaml(build_document()), encoding="utf-8")
	return str(hedef)


# ── Yapısal doğrulama ───────────────────────────────────────────────────


def operations(document: Mapping[str, Any] | None = None) -> Tuple[Tuple[str, str, Dict[str, Any]], ...]:
	"""`(yol, yöntem, operasyon)` üçlüleri."""
	doc = document if document is not None else build_document()
	cikti: List[Tuple[str, str, Dict[str, Any]]] = []
	for yol, item in (doc.get("paths") or {}).items():
		for yontem, op in item.items():
			cikti.append((yol, yontem, op))
	return tuple(cikti)


def validate_document(document: Mapping[str, Any] | None = None) -> List[str]:
	"""OpenAPI 3.1 yapısal kontrolü. Dönüş: bulgu listesi (boşsa temiz).

	Tam bir JSON-Schema doğrulayıcı DEĞİLDİR (`jsonschema` kurulu değil) ama
	bir belgeyi kullanılamaz kılan somut hataları yakalar: kırık `$ref`,
	tekrarlanan `operationId`, yanıtsız operasyon, tanımsız şema.
	"""
	doc = document if document is not None else build_document()
	bulgular: List[str] = []

	if str(doc.get("openapi", "")).split(".")[0] != "3":
		bulgular.append("openapi sürümü 3.x değil")
	for alan in ("info", "paths", "components"):
		if alan not in doc:
			bulgular.append(f"üst düzey `{alan}` yok")
	if not (doc.get("info") or {}).get("version"):
		bulgular.append("info.version yok")

	semalar = set(((doc.get("components") or {}).get("schemas") or {}).keys())
	yanitlar = set(((doc.get("components") or {}).get("responses") or {}).keys())

	def _refleri_tara(node: Any, iz: str) -> None:
		if isinstance(node, Mapping):
			hedef = node.get("$ref")
			if isinstance(hedef, str):
				if hedef.startswith("#/components/schemas/"):
					ad = hedef.rsplit("/", 1)[-1]
					if ad not in semalar:
						bulgular.append(f"kırık $ref: {hedef} ({iz})")
				elif hedef.startswith("#/components/responses/"):
					ad = hedef.rsplit("/", 1)[-1]
					if ad not in yanitlar:
						bulgular.append(f"kırık $ref: {hedef} ({iz})")
				else:
					bulgular.append(f"desteklenmeyen $ref: {hedef} ({iz})")
			for k, v in node.items():
				_refleri_tara(v, f"{iz}.{k}")
		elif isinstance(node, (list, tuple)):
			for i, v in enumerate(node):
				_refleri_tara(v, f"{iz}[{i}]")

	_refleri_tara(doc, "$")

	gorulen: Dict[str, str] = {}
	for yol, yontem, op in operations(doc):
		iz = f"{yontem.upper()} {yol}"
		oid = op.get("operationId")
		if not oid:
			bulgular.append(f"operationId yok: {iz}")
		elif oid in gorulen:
			bulgular.append(f"operationId tekrarı: {oid} ({gorulen[oid]} ve {iz})")
		else:
			gorulen[oid] = iz
		if not op.get("responses"):
			bulgular.append(f"responses yok: {iz}")
		if not op.get("x-python"):
			bulgular.append(f"x-python yok: {iz}")
		if "{" in yol:
			# Yol parametresi bildirilmiş mi.
			adlar = {p.get("name") for p in (op.get("parameters") or []) if p.get("in") == "path"}
			for parca in yol.split("/"):
				if parca.startswith("{") and parca.endswith("}"):
					ad = parca[1:-1]
					if ad not in adlar:
						bulgular.append(f"yol parametresi bildirilmemiş: {ad} ({iz})")

	# Hata kodu kataloğundaki her durum, zarfın eşlemesinde de olmalı.
	bilinen_durumlar = set(env.STATUS_BY_ERROR.values()) | {
		env.HTTP_BAD_REQUEST, env.HTTP_UNAUTHORIZED, env.HTTP_FORBIDDEN,
		env.HTTP_NOT_FOUND, env.HTTP_CONFLICT, env.HTTP_PRECONDITION_FAILED,
		env.HTTP_PAYLOAD_TOO_LARGE, env.HTTP_TOO_MANY_REQUESTS, env.HTTP_UNAVAILABLE,
		env.HTTP_INTERNAL_ERROR, env.HTTP_UNPROCESSABLE,
	}
	for satir in doc.get("x-error-codes") or []:
		if satir.get("status") not in bilinen_durumlar:
			bulgular.append(f"hata kataloğunda bilinmeyen durum: {satir}")

	return bulgular


__all__ = [
	"API_VERSION",
	"OPENAPI_VERSION",
	"BASE_PATH",
	"ERROR_CODES",
	"build_document",
	"dump_yaml",
	"yaml_path",
	"write_yaml",
	"operations",
	"validate_document",
]

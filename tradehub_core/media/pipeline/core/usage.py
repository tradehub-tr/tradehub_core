"""T-043 — Kullanım takibi (Media Usage) ve öksüz dosya tespiti.

Üç ayrı "öksüzlük" vardır ve İstoç'ta üçü de mevcut. Karıştırılmaları veri
kaybına yol açar, bu yüzden ayrı ayrı adlandırıldılar:

    DISK ÖKSÜZÜ      diskte dosya var, `tabFile` kaydı yok
                     → kimse bilmiyor, kimse silmiyor, yer kaplıyor
    KAYIT ÖKSÜZÜ     `Media Asset` var, hiç `Media Usage` bağı yok
                     → yüklenmiş ama hiçbir yere bağlanmamış
    KIRIK REFERANS   alan bir adresi gösteriyor, dosya/kayıt yok
                     → üründe boş görsel yuvası

Üçüncüsü ZATEN ÇÖZÜLMÜŞ: `tradehub_core/media/refs.py:find_dangling()`. Bu modül
onu yeniden yazmaz, `dangling_references()` ile SARAR. Yeni olan birinci ve
ikincidir.

**ÖLÇÜLDÜ — 2026-08-18, istoc.localhost canlı kopyası:**

    diskteki dosya                     4.341   (public 4.016 · private 325)
    tabFile'daki farklı file_url       3.013
    DİSK ÖKSÜZÜ (ham)                  1.334   ·  105.531.053 bayt (100,6 MiB)
      /files/og_cache altında          1.047   ← sistem üretimi önbellek
      /files/sitemaps altında             11   ← sistem üretimi
      GERÇEK öksüz (kullanıcı medyası)   276
    EKSİK (kayıt var, dosya yok)            6

Bu ayrım bu modülün var oluş sebebidir: ham sayı 1.334, ama %78'i sistemin
kendi ürettiği ve `tabFile` kaydı OLMAMASI DOĞRU olan önbellek dosyalarıdır.
Onları öksüz sayıp silmek, og:image önbelleğini her taramada yok etmek olurdu.
`SYSTEM_PATH_PREFIXES` bu yüzden bir "temizlik" listesi değil, bir **doğruluk**
listesidir.

(Görev tanımında 1.166 yazıyordu; bugünkü ölçüm 1.334 verdi. Fark ölçümler arası
biriken og_cache dosyalarından geliyor — sayı hareketlidir, taramanın kendisi
sabittir.)

`import frappe` modül düzeyinde YOKTUR: saf mantık (öksüz kararı, örnekleme,
anahtar üretimi) site olmadan test edilir; veritabanına dokunan her fonksiyon
frappe'yi kendi içinden import eder.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

# ── Sistem üretimi yollar ───────────────────────────────────────────────
#
# Bu öneklerin altındaki dosyaların `tabFile` kaydı OLMAMASI normaldir; onları
# öksüz saymak yanlıştır. Liste ölçümle doğrulandı (yukarıdaki dağılım).
SYSTEM_PATH_PREFIXES: Tuple[str, ...] = (
	"/files/og_cache/",      # ölçüldü: 1.047 dosya — og:image önbelleği
	"/files/sitemaps/",      # ölçüldü: 11 dosya — sitemap üreticisi
	"/private/files/media_trash/",     # tradehub_core/media/trash.py
	"/private/files/media_archive/",   # tradehub_core/media/archive.py
	"/private/files/media-backups/",   # tradehub_core/media/backup.py
	"/files/media/",         # bu motorun rendition kökü (dedup.RENDITION_ROOT)
	"/.well-known/",
)

#: Öksüz sayılmadan önce beklenecek asgari yaş. Yeni yüklenmiş ama henüz bir
#: kayda bağlanmamış dosya öksüz DEĞİLDİR — kullanıcı hâlâ formu dolduruyor
#: olabilir. Değer Media Engine Settings.orphan_min_age_days ile ezilir.
DEFAULT_ORPHAN_MIN_AGE_DAYS: int = 30

#: `last_access_at` için asgari yazma aralığı (saniye). Karar ve maliyeti için
#: modül sonundaki "Erişim damgası stratejisi" bölümüne bakınız.
ACCESS_WRITE_MIN_INTERVAL: int = 3600

SECONDS_PER_DAY: int = 86400


class UsageError(ValueError):
	"""Kullanım takibi girdisi geçersiz."""


# ─────────────────────────────────────────────────────────────────────────────
# 1. Media Usage — bağ kaydı
# ─────────────────────────────────────────────────────────────────────────────


def usage_key(asset: str, ref_doctype: str, ref_name: str, ref_field: str) -> str:
	"""`Media Usage.usage_key` — dörtlünün tekillik anahtarı.

	Frappe DocType JSON'u bileşik UNIQUE index ifade edemediği için tekillik
	türetilmiş tek alana taşındı (bkz. doctype_specs/_index.json). Anahtar
	ÜRETİMİ tek yerde olmalı: iki ayrı yerde birleştirilirse ayraç/kırpma farkı
	aynı bağın iki kez kaydedilmesine yol açar.
	"""
	parts = [str(p or "").strip() for p in (asset, ref_doctype, ref_name, ref_field)]
	if not all(parts):
		raise UsageError(f"Kullanım anahtarının dört parçası da dolu olmalı: {parts}")
	if any("|" in p for p in parts):
		# Ayraç veride geçerse anahtar belirsizleşir. Doctype adları ve alan
		# adlarında '|' olamaz; kayıt adında olabilir — o yüzden kontrol ediliyor.
		raise UsageError(f"Kullanım anahtarı parçasında '|' olamaz: {parts}")
	return "|".join(parts)


@dataclass
class UsageLink:
	"""Bir varlığın bir alana bağlanması. `Media Usage` kaydının saf karşılığı."""

	asset: str
	ref_doctype: str
	ref_name: str
	ref_field: str
	profile_used: str = ""
	first_seen: Optional[float] = None
	last_seen: Optional[float] = None
	is_open: bool = True

	@property
	def key(self) -> str:
		return usage_key(self.asset, self.ref_doctype, self.ref_name, self.ref_field)

	def as_dict(self) -> dict:
		return {
			"asset": self.asset,
			"ref_doctype": self.ref_doctype,
			"ref_name": self.ref_name,
			"ref_field": self.ref_field,
			"usage_key": self.key,
			"profile_used": self.profile_used,
			"first_seen": self.first_seen,
			"last_seen": self.last_seen,
			"is_open": 1 if self.is_open else 0,
		}


class UsageStore:
	"""Bellek içi `Media Usage` deposu.

	DocType henüz kurulu değil (Faz 4 kararı: şemalar JSON olarak duruyor). Bu
	sınıf hem testlerin deposu hem de Frappe'ye bağlanacak sınıfın sözleşmesi:
	`open_link` / `close_link` / `links_of` imzaları değişmeden Frappe destekli
	bir alt sınıf yazılabilir.
	"""

	def __init__(self) -> None:
		self._rows: Dict[str, UsageLink] = {}

	def open_link(self, link: UsageLink, now: float) -> UsageLink:
		"""Bağı aç ya da yenile — **idempotent**.

		Aynı bağ ikinci kez bildirilirse yeni satır açılmaz, `last_seen`
		güncellenir. Kapatılmış bir bağ yeniden bildirilirse `is_open` geri 1
		olur ve `first_seen` KORUNUR: bağın ilk kurulduğu an bir olgudur,
		yeniden bağlanma onu silmez.
		"""
		mevcut = self._rows.get(link.key)
		if mevcut is None:
			link.first_seen = now if link.first_seen is None else link.first_seen
			link.last_seen = now
			link.is_open = True
			self._rows[link.key] = link
			return link
		mevcut.last_seen = now
		mevcut.is_open = True
		if link.profile_used:
			mevcut.profile_used = link.profile_used
		return mevcut

	def close_link(self, asset: str, ref_doctype: str, ref_name: str, ref_field: str,
				   now: float) -> Optional[UsageLink]:
		"""Bağı kapat — kayıt SİLİNMEZ, `is_open=0` + `last_seen` damgalanır.

		Silmek "hiç kullanılmadı" ile "kullanılıyordu, kaldırıldı" ayrımını yok
		eder; öksüz kararı tam olarak bu ayrıma dayanır.
		"""
		row = self._rows.get(usage_key(asset, ref_doctype, ref_name, ref_field))
		if row is None:
			return None
		row.is_open = False
		row.last_seen = now
		return row

	def links_of(self, asset: str, *, open_only: bool = False) -> List[UsageLink]:
		out = [r for r in self._rows.values() if r.asset == asset]
		if open_only:
			out = [r for r in out if r.is_open]
		return out

	def open_assets(self) -> set:
		return {r.asset for r in self._rows.values() if r.is_open}

	def all_links(self) -> List[UsageLink]:
		return list(self._rows.values())


def sync_links(store: UsageStore, asset: str, refs: Iterable[Mapping], now: float) -> dict:
	"""Bir varlığın bağlarını verilen listeye eşitle.

	`refs`: `{"ref_doctype", "ref_name", "ref_field", "profile_used"?}` sözlükleri.
	Listede olmayan AÇIK bağlar kapatılır. Bu, `doc_events` yolunda tek çağrıyla
	doğru davranışı verir: bir üründen görsel çıkarıldığında ayrıca "kaldırıldı"
	olayı beklemeye gerek kalmaz — kaydın güncel hâli tek doğruluk kaynağıdır.
	"""
	istenen = {}
	for r in refs or []:
		link = UsageLink(
			asset=asset,
			ref_doctype=str(r.get("ref_doctype") or ""),
			ref_name=str(r.get("ref_name") or ""),
			ref_field=str(r.get("ref_field") or ""),
			profile_used=str(r.get("profile_used") or ""),
		)
		istenen[link.key] = link

	acilan = [store.open_link(link, now).key for link in istenen.values()]
	kapanan = []
	for row in store.links_of(asset, open_only=True):
		if row.key not in istenen:
			store.close_link(row.asset, row.ref_doctype, row.ref_name, row.ref_field, now)
			kapanan.append(row.key)
	return {"asset": asset, "opened": acilan, "closed": kapanan}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Erişim damgası — örnekleme yerine zaman kovası
# ─────────────────────────────────────────────────────────────────────────────


def should_record_access(key: str, now: float,
						 min_interval: int = ACCESS_WRITE_MIN_INTERVAL) -> bool:
	"""Bu erişim veritabanına yazılsın mı.

	**Karar: rastgele örnekleme DEĞİL, deterministik zaman kovası.** Gerekçe:

	  * `%1 örnekleme`: nadir kullanılan bir rendition'ın damgası aylarca
	    güncellenmez ve retention taraması onu "erişilmiyor" sanıp arşive atar.
	    Yanlış yön: veri kaybı.
	  * `zaman kovası`: her anahtar için aralıkta EN AZ bir yazma garanti edilir,
	    aralıkta EN FAZLA bir yazma yapılır. Nadir erişilen rendition da damgasını
	    alır, popüler olan da veritabanını dövmez.

	Kovalar anahtara göre kaydırılır (`_bucket_offset`): aksi hâlde tüm damgalar
	saat başında aynı anda yazılır ve yazma yükü tepe yapar.

	Maliyet (hesap, ölçüm değil — üretimde henüz koşmadı): `min_interval=3600` ve
	N farklı rendition için üst sınır N yazma/saat. Bugünkü 4.958 dosya ve dosya
	başına ~6 profil varsayımıyla ~30.000 satır → saatte en fazla 30.000 UPDATE,
	yani ~8/sn. Karşılaştırma: her istekte yazma, aynı trafikte istek sayısı
	kadar UPDATE demektir.
	"""
	if min_interval <= 0:
		return True
	bucket = int((now + _bucket_offset(key, min_interval)) // min_interval)
	if _last_bucket.get(key) == bucket:
		return False
	_last_bucket[key] = bucket
	return True


#: Süreç içi kova belleği. Kalıcı değil ve olmamalı: süreç yeniden başlarsa en
#: kötü ihtimalle bir fazladan yazma olur, veri kaybı olmaz.
_last_bucket: Dict[str, int] = {}


def _bucket_offset(key: str, min_interval: int) -> int:
	"""Anahtara özgü sabit kaydırma — yazmaları aralığa yay."""
	h = hashlib.sha256(key.encode("utf-8")).digest()
	return int.from_bytes(h[:4], "big") % max(1, min_interval)


def reset_access_state() -> None:
	"""Kova belleğini sıfırla — testler için."""
	_last_bucket.clear()


@dataclass
class AccessBuffer:
	"""Erişim damgalarını tamponla, toplu yaz.

	Tek tek `UPDATE` yerine toplu yazma: okuma yolunda veritabanına dokunmak
	istekten önce dönmeyi geciktirir. Tampon dolunca ya da `flush()` çağrılınca
	tek seferde yazılır.
	"""

	min_interval: int = ACCESS_WRITE_MIN_INTERVAL
	max_size: int = 500
	_pending: Dict[str, float] = field(default_factory=dict)

	def touch(self, key: str, now: float) -> bool:
		"""Erişimi kaydet. Yazılacaksa `True`."""
		if not should_record_access(key, now, self.min_interval):
			return False
		self._pending[key] = now
		return True

	def is_full(self) -> bool:
		return len(self._pending) >= self.max_size

	def flush(self, writer: Callable[[Dict[str, float]], Any]) -> int:
		"""Tamponu `writer`'a ver ve boşalt. Dönüş: yazılan satır sayısı.

		`writer` başarısız olursa tampon **boşaltılmaz** — damgalar kaybolmasın.
		"""
		if not self._pending:
			return 0
		batch = dict(self._pending)
		writer(batch)
		self._pending.clear()
		return len(batch)

	def pending(self) -> Dict[str, float]:
		return dict(self._pending)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Disk öksüzü tespiti
# ─────────────────────────────────────────────────────────────────────────────


def is_system_path(url: str, prefixes: Tuple[str, ...] = SYSTEM_PATH_PREFIXES) -> bool:
	"""Bu adres sistemin kendi ürettiği bir dosya mı — `tabFile` kaydı beklenmez."""
	u = (url or "").split("?")[0]
	return any(u.startswith(p) for p in prefixes)


@dataclass(frozen=True)
class DiskFile:
	"""Diskte bulunan bir dosya."""

	url: str
	bytes: int
	mtime: float

	def age_days(self, now: float) -> float:
		return max(0.0, (now - self.mtime) / SECONDS_PER_DAY)


@dataclass
class OrphanReport:
	"""Disk öksüzü taramasının sonucu.

	Rapor ASLA silme yapmaz (T-043 kabul kriteri). Silme, superadmin onayıyla
	ayrı bir adımdır ve mevcut motorun çöp kutusundan (`trash.py`, 30 gün)
	geçmelidir — doğrudan `os.remove` değil.
	"""

	scanned: int = 0
	db_urls: int = 0
	orphans: List[DiskFile] = field(default_factory=list)
	system_skipped: List[DiskFile] = field(default_factory=list)
	too_young: List[DiskFile] = field(default_factory=list)
	missing_on_disk: List[str] = field(default_factory=list)

	@property
	def orphan_bytes(self) -> int:
		return sum(f.bytes for f in self.orphans)

	@property
	def system_bytes(self) -> int:
		return sum(f.bytes for f in self.system_skipped)

	def summary(self) -> dict:
		return {
			"scanned": self.scanned,
			"db_urls": self.db_urls,
			"orphans": len(self.orphans),
			"orphan_bytes": self.orphan_bytes,
			"system_skipped": len(self.system_skipped),
			"system_bytes": self.system_bytes,
			"too_young": len(self.too_young),
			"missing_on_disk": len(self.missing_on_disk),
		}

	def top(self, n: int = 20) -> List[dict]:
		"""En büyük öksüzler — temizlik önceliği."""
		buyuk = sorted(self.orphans, key=lambda f: -f.bytes)[:n]
		return [{"url": f.url, "bytes": f.bytes, "mtime": f.mtime} for f in buyuk]


def classify_orphans(
	disk: Iterable[DiskFile],
	known_urls: set,
	*,
	now: float,
	min_age_days: int = DEFAULT_ORPHAN_MIN_AGE_DAYS,
	prefixes: Tuple[str, ...] = SYSTEM_PATH_PREFIXES,
) -> OrphanReport:
	"""Disk listesini bilinen adreslerle karşılaştır — **saf**, I/O yok.

	Ayrımın tamamı burada: sistem yolu mu, yeterince eski mi, kayıtlı mı. Bu
	fonksiyon frappe'siz test edilir; `find_disk_orphans()` yalnız ona veri
	toplar.
	"""
	rapor = OrphanReport(db_urls=len(known_urls))
	for f in disk:
		rapor.scanned += 1
		if f.url in known_urls:
			continue
		if is_system_path(f.url, prefixes):
			rapor.system_skipped.append(f)
			continue
		if f.age_days(now) < min_age_days:
			rapor.too_young.append(f)
			continue
		rapor.orphans.append(f)
	return rapor


def scan_disk(roots: Mapping[str, str]) -> List[DiskFile]:
	"""Verilen kökleri gez ve `DiskFile` listesi üret.

	`roots`: `{url_öneki: disk_yolu}` — ör. `{"/files/": "…/public/files"}`.
	Frappe gerekmez; testte geçici dizinle çalışır.
	"""
	out: List[DiskFile] = []
	for prefix, root in (roots or {}).items():
		if not root or not os.path.isdir(root):
			continue
		for dirpath, _dirs, names in os.walk(root):
			for name in names:
				path = os.path.join(dirpath, name)
				try:
					st = os.stat(path)
				except OSError:
					# Tarama sırasında silinen/erişilemeyen dosya: atla. Tarama
					# yıkıcı bir iş değil, eksik veri hata değildir.
					continue
				rel = os.path.relpath(path, root).replace(os.sep, "/")
				out.append(DiskFile(url=prefix + rel, bytes=st.st_size, mtime=st.st_mtime))
	return out


def site_roots() -> Dict[str, str]:
	"""İstoç sitesinin medya kökleri. **frappe gerektirir.**"""
	import frappe  # noqa: PLC0415 — bilinçli geç import

	return {
		"/files/": frappe.get_site_path("public", "files"),
		"/private/files/": frappe.get_site_path("private", "files"),
	}


def known_file_urls() -> set:
	"""`tabFile` içindeki tüm farklı `file_url` değerleri. **frappe gerektirir.**"""
	import frappe  # noqa: PLC0415

	rows = frappe.db.sql(
		"select distinct file_url from tabFile where ifnull(file_url,'') <> ''"
	)
	return {r[0] for r in rows}


def find_disk_orphans(
	*,
	min_age_days: int = DEFAULT_ORPHAN_MIN_AGE_DAYS,
	now: Optional[float] = None,
	include_system: bool = False,
) -> OrphanReport:
	"""Diskte olup `tabFile`'da olmayan dosyaları raporla. **frappe gerektirir.**

	Varsayılan (`include_system=False`) üretim davranışıdır: `SYSTEM_PATH_PREFIXES`
	altındaki dosyalar `system_skipped` listesine gider, `orphans` listesine
	GİRMEZ — onların `tabFile` kaydı olmaması doğrudur.

	`include_system=True` yalnız **denetim** içindir: hiçbir yol muaf tutulmaz ve
	og_cache/sitemap dosyaları da `orphans` altında görünür. Bu kipin çıktısı
	silme akışına verilmemelidir; ham 1.334 sayısını yeniden üretmek ve sistem
	yollarının payını ölçmek için vardır.
	"""
	import time  # noqa: PLC0415

	simdi = time.time() if now is None else now
	disk = scan_disk(site_roots())
	bilinen = known_file_urls()
	rapor = classify_orphans(
		disk, bilinen, now=simdi, min_age_days=min_age_days,
		prefixes=() if include_system else SYSTEM_PATH_PREFIXES,
	)
	diskteki = {f.url for f in disk}
	rapor.missing_on_disk = sorted(
		u for u in bilinen
		if (u.startswith("/files/") or u.startswith("/private/files/")) and u not in diskteki
	)
	return rapor


# ─────────────────────────────────────────────────────────────────────────────
# 4. Kayıt öksüzü — Media Usage bağı olmayan varlıklar
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AssetSnapshot:
	"""Öksüz kararı için gereken asgari varlık künyesi."""

	name: str
	created_at: float
	legal_hold: bool = False
	state: str = "ready"

	def age_days(self, now: float) -> float:
		return max(0.0, (now - self.created_at) / SECONDS_PER_DAY)


#: Öksüz taramasının HİÇ dokunmadığı durumlar. `draft` ve `pending` henüz
#: yükleme sürecinde; `archived` zaten retention kararı almış.
ORPHAN_EXEMPT_STATES: frozenset = frozenset({"draft", "pending", "validating", "processing", "archived"})


def find_orphan_assets(
	assets: Iterable[AssetSnapshot],
	store: UsageStore,
	*,
	now: float,
	min_age_days: int = DEFAULT_ORPHAN_MIN_AGE_DAYS,
) -> dict:
	"""Hiç açık kullanım bağı olmayan, yeterince eski varlıkları raporla — **saf**.

	Raporda ÇIKMAYANLAR ve sebepleri (T-043 kabul kriteri):
	  * `legal_hold=1`      → yasal saklama retention'ı geçersiz kılar
	  * yaşı `min_age_days`'ten küçük → yeni yüklenmiş, henüz bağlanmamış olabilir
	  * durumu `ORPHAN_EXEMPT_STATES` içinde → süreç devam ediyor

	**OTOMATİK SİLME YOK.** Dönüş bir liste; silme superadmin onayıyla ayrı bir
	akıştır.
	"""
	acik = store.open_assets()
	oksuz: List[dict] = []
	muaf: List[dict] = []
	for a in assets:
		if a.name in acik:
			continue
		if a.legal_hold:
			muaf.append({"asset": a.name, "reason": "legal_hold"})
			continue
		if a.state in ORPHAN_EXEMPT_STATES:
			muaf.append({"asset": a.name, "reason": f"state:{a.state}"})
			continue
		yas = a.age_days(now)
		if yas < min_age_days:
			muaf.append({"asset": a.name, "reason": "too_young", "age_days": round(yas, 2)})
			continue
		kapali = [link for link in store.links_of(a.name) if not link.is_open]
		oksuz.append({
			"asset": a.name,
			"age_days": round(yas, 2),
			"state": a.state,
			# Hiç bağlanmamış mı, yoksa bağı kaldırılmış mı: silme kararının
			# ağırlığı bu ayrımda. İkincisi bir zamanlar yayındaydı.
			"ever_used": bool(kapali),
			"last_seen": max((link.last_seen or 0) for link in kapali) if kapali else None,
		})
	return {
		"orphans": sorted(oksuz, key=lambda r: -r["age_days"]),
		"exempt": muaf,
		"min_age_days": min_age_days,
		"auto_delete": False,
	}


# ─────────────────────────────────────────────────────────────────────────────
# 5. Mevcut motorun sarmalayıcıları — YENİDEN YAZILMADI
# ─────────────────────────────────────────────────────────────────────────────


def dangling_references(limit: int = 500) -> list:
	"""Hedefi olmayan referanslar. `tradehub_core.media.refs.find_dangling()` sarmalayıcısı.

	Bu tarama üretimde ÇALIŞIYOR ve 10+ tabloyu kapsıyor; burada ikinci bir
	uygulama yazmak, birinin düzeltilip diğerinin geride kalması demekti.
	"""
	from tradehub_core.media import refs  # noqa: PLC0415

	return refs.find_dangling(limit=limit)


def url_verdicts(deep: bool = False, refresh: bool = False) -> dict:
	"""`{url: verdict}` — `tradehub_core.media.usage.verdict_map_all()` sarmalayıcısı.

	Mevcut kararlar: `in_use` / `order_only` / `history_only` / `unused` /
	`not_in_use`. Bu modülün `Media Usage` tablosu onların YERİNE geçmez; tarama
	pahalıdır (ölçüldü: derin tarama 3.546 ms / 50 dosya) ve tablo o sonucun
	kalıcı hâlidir. İkisi ayrıştığında doğru olan TARAMADIR — tablo türev veridir.
	"""
	from tradehub_core.media import usage as legacy_usage  # noqa: PLC0415

	return legacy_usage.verdict_map_all(deep=deep, refresh=refresh)


def unused_urls(deep: bool = True) -> list:
	"""Hiçbir yerde kullanılmayan adresler — mevcut taramadan süzülür."""
	kararlar = url_verdicts(deep=deep)
	hedef = {"unused"} if deep else {"not_in_use"}
	return sorted(u for u, v in kararlar.items() if v in hedef)


def reconcile(
	*,
	min_age_days: int = DEFAULT_ORPHAN_MIN_AGE_DAYS,
	deep: bool = False,
) -> dict:
	"""Üç öksüzlük türünü tek raporda topla. **frappe gerektirir.**

	Panelin "medya sağlığı" ekranının tek çağrısı. Üç sayının BİRLİKTE görünmesi
	gerekiyor çünkü aynı dosya üçünde birden görünebilir ve tek tek bakıldığında
	aynı sorun üç ayrı sorun sanılır.
	"""
	disk = find_disk_orphans(min_age_days=min_age_days)
	return {
		"disk_orphans": disk.summary(),
		"disk_orphans_top": disk.top(),
		"dangling_references": dangling_references(),
		"unused_urls": len(unused_urls(deep=deep)),
		"note": (
			"Bu rapor SİLME YAPMAZ. Silme, superadmin onayıyla ve mevcut çöp "
			"kutusundan (tradehub_core/media/trash.py, 30 gün) geçerek yapılır."
		),
	}

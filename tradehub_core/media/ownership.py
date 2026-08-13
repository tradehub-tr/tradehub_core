"""Medya sahipliği — bir dosya hangi mağazaya ait.

Satıcı kendi medya kütüphanesini görecekse önce şu sorunun cevabı gerekiyor:
"bu dosya kimin?". Üç aday vardı, ölçüldü (2839 public dosya):

    yükleyen kullanıcı → mağaza     2839 / 2839   (%100)
    dosyanın eklendiği kayıt        1162 ürün + 37 mağaza, 1914'ü BOŞ
    kullanıldığı ürün üzerinden     yalnız kullanımdakiler; boştakiler kimsesiz

Bu yüzden sahiplik YÜKLEYENDEN türetiliyor. Diğer iki yol kapsamı dar: bir
dosya hiçbir yere eklenmemiş ya da hiç kullanılmamış olabilir — ama mutlaka
biri tarafından yüklenmiştir.

AYNI DOSYA İKİ MAĞAZADA OLABİLİR. Ölçüm: 30 adres iki mağazaya birden ait.
Diskte tek dosya, iki mağaza da ona bakıyor. Bu yüzden `owners_of` tek değer
değil KÜME döndürür ve silme akışı "sahipliği bırakma" mantığıyla çalışır
(bkz. `trash.release_for_store`): satıcı sildiğinde yalnız kendi bağı ve kendi
sahipliği düşer, dosya diskten ancak son sahip de bıraktığında gider.

Yönetimin yüklediği platform görselleri hiçbir mağazaya ait değildir; bunlar
sahipsiz sayılır ve hiçbir satıcının listesinde görünmez.
"""

from __future__ import annotations

import frappe

from tradehub_core.utils.tenant import _get_seller_profile_for_user

# Mağaza kullanıcı listesi sık sorulacak; her istekte iki sorgu yerine kısa
# ömürlü önbellek. Süre bilerek kısa: yeni alt kullanıcı davet edildiğinde en
# geç 5 dakikada görünür, bu arada yalnız kendi dosyalarını göremez — ters
# yönde bir sızıntı riski yok.
_USERS_TTL = 300


def store_of(user: str | None = None) -> str | None:
	"""Kullanıcının bağlı olduğu mağaza — yoksa None.

	Mevcut çözümleyici kullanılıyor: önce alt kullanıcı bağı, sonra mağaza
	kaydının kullanıcısı, sonra e-posta. Burada yeniden yazılmadı ki davet
	akışı değişince tek yerden değişsin.
	"""
	return _get_seller_profile_for_user(user or frappe.session.user)


def current_store() -> str:
	"""Oturumdaki satıcının mağazası — yoksa erişim reddedilir.

	Satıcı uçlarının tamamı buradan geçer. Mağazası çözülemeyen bir oturum
	medya listesi göremez; boş liste dönmek yerine açıkça reddediliyor, çünkü
	sessiz boş liste "hiç dosyam yok" gibi okunur ve gerçek bir yetki sorununu
	gizler.
	"""
	store = store_of()
	if not store:
		frappe.throw(frappe._("Bu işlem için bir mağaza hesabı gerekiyor."), frappe.PermissionError)
	return store


def users_of(store: str) -> tuple[str, ...]:
	"""Mağazaya ait TÜM kullanıcılar — sahibi ve alt kullanıcıları.

	Alt kullanıcılar şart: mağaza sahibi dışında biri (operasyon, finans)
	dosya yüklediğinde o dosya mağazanın olmalı. Yalnız sahibe bakılsaydı alt
	kullanıcının yüklediği her şey kimsesiz görünür ve satıcı kendi
	dosyasını kütüphanesinde bulamazdı.
	"""
	if not store:
		return ()

	anahtar = f"tradehub:media_store_users:{store}"
	onbellek = frappe.cache().get_value(anahtar)
	if onbellek:
		return tuple(onbellek)

	kullanicilar: set[str] = set()

	sahip = frappe.db.get_value("Admin Seller Profile", store, "user")
	if sahip:
		kullanicilar.add(sahip)

	eposta = frappe.db.get_value("Admin Seller Profile", store, "email")
	if eposta and frappe.db.exists("User", eposta):
		kullanicilar.add(eposta)

	kullanicilar.update(
		frappe.db.get_all("User", filters={"tradehub_tenant": store}, pluck="name")
	)

	sonuc = tuple(sorted(kullanicilar))
	if sonuc:
		frappe.cache().set_value(anahtar, list(sonuc), expires_in_sec=_USERS_TTL)
	return sonuc


def clear_cache(store: str | None = None) -> None:
	"""Kullanıcı listesi önbelleğini boşalt — davet/çıkarma sonrası."""
	if store:
		frappe.cache().delete_value(f"tradehub:media_store_users:{store}")
		return
	for ad in frappe.db.get_all("Admin Seller Profile", pluck="name"):
		frappe.cache().delete_value(f"tradehub:media_store_users:{ad}")


def used_urls(store: str) -> set[str]:
	"""Mağazanın KAYITLARINDA geçen tüm dosya adresleri.

	Sahiplik yalnız "kim yükledi" olarak tanımlansaydı, satıcının ürününde
	duran ama başkasının (yönetim, toplu içe aktarım, eski bir hesap) yüklediği
	görsel onun kütüphanesinde HİÇ görünmezdi. Satıcı kendi vitrinindeki bir
	görseli göremez, düzenleyemez, silemezdi.

	Ürün galerisi, varyant görselleri, varyant galerisi, vitrin düzeni, mağaza
	galerisi ve logo — hepsi taranıyor (`usage.LIVE_SOURCES`).
	"""
	if not store:
		return set()

	anahtar = f"tradehub:media_store_urls:{store}"
	onbellek = frappe.cache().get_value(anahtar)
	if onbellek is not None:
		return set(onbellek)

	from tradehub_core.media import usage

	bulunan: set[str] = set()
	for table, column, _kind, _label in usage.LIVE_SOURCES:
		kosul = usage.STORE_FILTERS.get(table)
		if not kosul:
			continue
		try:
			rows = frappe.db.sql(
				f"select `{column}` from `{table}` where locate('/files/', `{column}`) > 0 and {kosul}",  # noqa: S608 — tablo/kolon sabit listeden
				(store,),
			)
		except Exception:
			frappe.log_error(
				title=f"Store url scan failed: {table}.{column}",
				message=frappe.get_traceback(with_context=True),
			)
			continue
		for (deger,) in rows:
			bulunan |= usage.extract_file_urls(deger)

	# Kısa ömürlü: ürün kaydedilince en geç bir dakikada listeye yansır.
	frappe.cache().set_value(anahtar, list(bulunan), expires_in_sec=60)
	return bulunan


def owners_of(file_url: str) -> set[str]:
	"""Bu dosyanın ait olduğu TÜM mağazalar — yükleyen VE kullanan.

	Küme döndürür çünkü aynı adrese ait birden çok dosya kaydı olabiliyor ve
	bunları farklı mağazaların kullanıcıları yüklemiş olabiliyor (ölçüm: 30
	adres). Tek değer döndürseydi ikinci sahip görünmez olur, silme akışı da
	onun ürününü kırardı.

	Kullanan da sahiptir: satıcının ürününde duran bir görsel, kim yüklemiş
	olursa olsun onun kütüphanesinde görünmeli ve yönetebilmeli.
	"""
	url = (file_url or "").split("?")[0]
	if not url:
		return set()

	sahipler = frappe.db.get_all(
		"File", filters={"file_url": url}, pluck="owner", distinct=True
	)
	magazalar = {s for s in (store_of(k) for k in sahipler) if s}
	magazalar |= _stores_using(url)
	return magazalar


def _stores_using(url: str) -> set[str]:
	"""Bu adresi kayıtlarında kullanan mağazalar.

	Tek adres için sorgulanıyor; tüm kaynakları taramak yerine yalnız o adresi
	içeren satırlar getiriliyor.
	"""
	from tradehub_core.media import usage

	bulunan: set[str] = set()
	yazimlar = usage._search_variants(url)
	kosul = " or ".join(["locate(%s, `{col}`) > 0"] * len(yazimlar))

	for table, column, _kind, _label in usage.LIVE_SOURCES:
		alan = _STORE_COLUMN.get(table)
		if not alan:
			continue
		try:
			rows = frappe.db.sql(
				f"select distinct {alan} from `{table}` where {kosul.format(col=column)}",  # noqa: S608 — tablo/kolon sabit listeden
				yazimlar,
			)
		except Exception:
			continue
		bulunan |= {r[0] for r in rows if r[0]}
	return bulunan


# Bir kaydın mağazasını veren kolon. `usage.STORE_FILTERS` "bu mağaza mı" diye
# sorar; burada tersi gerekiyor: "bu satır hangi mağazanın".
_STORE_COLUMN: dict[str, str] = {
	"tabListing": "seller_profile",
	"tabListing Image": "(select seller_profile from tabListing l where l.name=parent)",
	"tabListing Variant Item": "(select seller_profile from tabListing l where l.name=parent)",
	"tabStorefront Layout": "seller_profile",
	"tabSeller Gallery Image": "parent",
	"tabAdmin Seller Profile": "name",
}


def owns(store: str, file_url: str) -> bool:
	"""Mağaza bu dosyanın sahiplerinden biri mi."""
	return bool(store) and store in owners_of(file_url)


def assert_owns(store: str, file_url: str) -> None:
	"""Sahip değilse reddet.

	Mesaj bilerek "bulunamadı" diyor, "yetkiniz yok" demiyor: ikincisi dosyanın
	VAR olduğunu doğrular ve başka satıcının dosya adlarını deneme yoluyla
	keşfetmeye açık kapı bırakır.
	"""
	if not owns(store, file_url):
		frappe.throw(frappe._("Dosya bulunamadı."), frappe.DoesNotExistError)


def scope(query, f, store: str):
	"""Envanter sorgusunu mağazaya daralt.

	İKİ yoldan sahiplik: mağazanın kullanıcılarının YÜKLEDİĞİ dosyalar VEYA
	mağazanın kayıtlarında KULLANILAN dosyalar. İkincisi olmadan, satıcının
	ürününde duran ama başkasının yüklediği görsel kütüphanesinde hiç
	görünmezdi.

	Mağazanın ne kullanıcısı ne de kullanımı varsa sorgu bilerek HİÇBİR ŞEY
	döndürecek biçimde kısıtlanır — süzgeci atlayıp tüm envanteri döndürmek,
	bir yapılandırma eksiğini veri sızıntısına çevirirdi.
	"""
	kullanicilar = list(users_of(store))
	adresler = list(used_urls(store))

	if not kullanicilar and not adresler:
		return query.where(f.owner.isin([""]))
	if not adresler:
		return query.where(f.owner.isin(kullanicilar))
	if not kullanicilar:
		return query.where(f.file_url.isin(adresler))

	# Sadece "VEYA" yazmak yetmiyor, çünkü liste satırları gruplayıp damgaların
	# en küçüğüne bakıyor. Mağazanın kendi kaydı olan bir dosyada, "kullanılan"
	# koşulu BAŞKA mağazaların kayıtlarını da gruba sokardı; o mağaza dosyayı
	# bırakınca damga bu mağazanın grubuna da düşer ve dosya burada da çöpte
	# görünürdü. (Testler bunu yakaladı: A bıraktı, B'nin listesinden düştü.)
	#
	# Bu yüzden "kullanılan" yolu YALNIZ mağazanın hiç kaydı olmayan dosyalar
	# için açılıyor. Kendi kaydı olanlar tamamen kendi kayıtları üzerinden
	# değerlendiriliyor.
	kendi_kayitlari = frappe.qb.from_(f).select(f.file_url).where(f.owner.isin(kullanicilar))
	return query.where(
		f.owner.isin(kullanicilar)
		| (f.file_url.isin(adresler) & f.file_url.notin(kendi_kayitlari))
	)


def clear_url_cache(store: str | None = None) -> None:
	"""Kullanılan adres önbelleğini boşalt — ürün kaydedildikten sonra."""
	if store:
		frappe.cache().delete_value(f"tradehub:media_store_urls:{store}")
		return
	for ad in frappe.db.get_all("Admin Seller Profile", pluck="name"):
		frappe.cache().delete_value(f"tradehub:media_store_urls:{ad}")

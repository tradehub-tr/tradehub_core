"""Satıcının kendi medyası — arşivleme ve kalıcı silme.

**İki ayrı işlem, iki ayrı anlam.** Önce tek fonksiyondu ve ikisini
karıştırıyordu: "sil" hem arşive taşıyor hem son sahipse diski değiştiriyordu.
Kullanıcı neyin geri alınabilir neyin alınamaz olduğunu göremiyordu.

    arşivle    → geri alınabilir. Diske DOKUNMAZ, kayıt silinmez, yalnız
                 satıcının aktif listesinden çıkar.
    kalıcı sil → geri alınamaz. Satıcının kaydı silinir, bağları temizlenir.
                 Dosya diskten YALNIZ son sahip de sildiğinde gider.

**Neden sayaçlı silme.** Aynı içerik birden çok satıcı tarafından yüklenince
sistem tek fiziksel dosya tutuyor, her satıcıya ayrı bir kayıt açıyor
(ölçüldü: 5 mağaza aynı içeriği yükledi → 1 dosya, 5 kayıt, 5 sahip).
Dolayısıyla "sil" diyen ilk satıcıda diski silmek diğer dördünün ürününü
kırardı. Diskteki dosya ancak sahibi kalmayınca silinir.

Fiziksel kopya çıkarmak da bir seçenekti ama depolamayı boşa şişirir ve
tekilleştirme hedefiyle (TUR-298) çelişirdi.

**Arşivleme zorunlu DEĞİL.** İkisi ayrı düğme, ayrı iş: satıcı isterse
arşivler, isterse doğrudan kalıcı siler. Silmeden önce arşivlemeyi zorunlu
kılmak ikisini yeniden birbirine bağlardı.

**Kullanımdaki dosya ne arşivlenir ne silinir.** Satıcının kendi vitrinini
farkında olmadan bozmasını engeller.

Satıcı diğer mağazaların varlığını hiçbir yanıtta görmez — ne adı, ne sayısı,
ne ürünü. Yalnız "kaç sahip kaldı" sayısı denetim kaydına yazılır.
"""

from __future__ import annotations

import frappe

from tradehub_core.media import audit, ownership, refs, trash, usage


def _own_records(file_url: str, store: str) -> list[str]:
	"""Bu adrese ait, BU mağazanın kullanıcılarının açtığı dosya kayıtları."""
	kullanicilar = ownership.users_of(store)
	if not kullanicilar:
		return []
	return frappe.get_all(
		"File",
		filters={"file_url": file_url, "owner": ["in", list(kullanicilar)]},
		pluck="name",
	)


def _live_owner_count(file_url: str, haric: str) -> int:
	"""`haric` dışında bu dosyayı hâlâ elinde tutan mağaza sayısı."""
	return len(ownership.owners_of(file_url) - {haric})


def _assert_not_in_use(file_url: str, store: str) -> None:
	"""Kendi ürününde kullanılan dosyaya dokundurma.

	Kendi kapsamındaki kullanım sayılıyor; başka mağazanınki bilerek
	sayılmıyor, çünkü onu zaten kırmayacağız.
	"""
	karar = usage.verdicts_for([file_url], store=store).get(file_url, {})
	if karar.get("live"):
		frappe.throw(
			frappe._("Bu görsel {0} yerde kullanılıyor. Önce ürününüzden kaldırın.").format(
				karar["live"]
			)
		)


def archive(file_url: str, store: str) -> dict:
	"""Arşivle — GERİ ALINABİLİR.

	Diske dokunulmaz, hiçbir kayıt silinmez, bağlar temizlenmez. Tek yaptığı
	satıcının kendi kayıtlarına damga basmak; dosya aktif listeden çıkıp
	arşive geçer.

	Dosyanın DURUMU (aktif/arşiv/çöp) değiştirilmiyor: durum dosyaya ait,
	kayda değil (bkz. `states.current`). Paylaşılan bir dosya bir mağaza için
	arşivde diğeri için aktif olabilir; bu ancak kayıt damgasıyla ifade edilir.
	Liste bunu doğru okur, çünkü mağaza süzgeci satırları GRUPLAMADAN ÖNCE
	daraltır.
	"""
	ownership.assert_owns(store, file_url)
	_assert_not_in_use(file_url, store)

	kayitlar = _own_records(file_url, store)
	if not kayitlar:
		frappe.throw(frappe._("Dosya bulunamadı."), frappe.DoesNotExistError)

	frappe.db.set_value(
		"File",
		{"name": ["in", kayitlar]},
		{"th_trashed_at": frappe.utils.now()},
		update_modified=False,
	)
	frappe.db.commit()

	audit.log_media_event(
		action=audit.ACTION_RELEASE,
		file_url=file_url,
		tenant=store,
		context={"records": kayitlar, "reversible": True},
	)
	return {"file_url": file_url, "records": len(kayitlar), "archived": True}


def unarchive(file_url: str, store: str) -> dict:
	"""Arşivden çıkar — dosya aktif listeye döner.

	Bağlar geri gelmez; zaten arşivleme sırasında da temizlenmemişti. Dosya
	yalnız kütüphanede tekrar görünür, satıcı isterse ürününe kendisi koyar.
	"""
	ownership.assert_owns(store, file_url)

	kayitlar = _own_records(file_url, store)
	if not kayitlar:
		frappe.throw(frappe._("Dosya bulunamadı."), frappe.DoesNotExistError)

	# Son sahip kalıcı silmiş ve dosya fiziksel çöpe düşmüşse geri getir.
	if trash.in_trash(file_url):
		trash.restore(file_url)

	frappe.db.set_value(
		"File", {"name": ["in", kayitlar]}, {"th_trashed_at": None}, update_modified=False
	)
	frappe.db.commit()

	audit.log_media_event(
		action=audit.ACTION_RECLAIM,
		file_url=file_url,
		tenant=store,
		context={"records": kayitlar},
	)
	return {"file_url": file_url, "records": len(kayitlar)}


def purge(file_url: str, store: str) -> dict:
	"""Kalıcı sil — GERİ ALINAMAZ.

	Satıcının bu dosya üzerindeki payı tamamen kalkar: kayıtları silinir,
	kendi ürünlerindeki bağları temizlenir. Dosya DİSKTEN yalnız son sahip de
	sildiğinde silinir; o ana kadar diğer mağazalar için olduğu gibi durur.

	Aktif listeden de arşivden de doğrudan çağrılabilir; önce arşivleme
	zorunluluğu YOK. Başta iki adım şartı konmuştu (yönetimdeki çöp→kalıcı-sil
	akışına benzetilerek) ama ürün kararı farklı oldu: "Arşivle" ve "Sil" iki
	ayrı düğme ve ikisi ayrı iş yapıyor; silmek için önce arşivlemeyi zorunlu
	kılmak ikisini yeniden birbirine bağlıyordu.

	Koruma tek adıma indirgenmedi, yer değiştirdi: kullanımdaki dosya hiçbir
	yoldan silinemiyor ve onay penceresi işlemin geri alınamaz olduğunu açıkça
	söylüyor.
	"""
	import os

	ownership.assert_owns(store, file_url)
	_assert_not_in_use(file_url, store)

	temizlik = refs.clear(file_url, store=store)
	kayitlar = _own_records(file_url, store)

	# Frappe'nin kendi silme akışı, aynı adresi gösteren başka kayıt kaldıysa
	# fiziksel dosyaya dokunmaz. Yine de son durumu aşağıda kendimiz
	# doğruluyoruz — sayaç bu modülün sorumluluğu, çerçevenin davranışına
	# bel bağlanmıyor.
	for name in kayitlar:
		frappe.delete_doc("File", name, force=True, ignore_permissions=True)
	frappe.db.commit()

	kalan = sorted(ownership.owners_of(file_url))
	if not kalan:
		# Sahip kalmadı: dosya diskten gitmeli. Frappe kendi silme akışında
		# son kayıt gidince fiziksel dosyayı da siliyor; kalan bir artık varsa
		# burada temizlenir. Çerçevenin davranışına bel bağlanmıyor.
		for yol in (trash._live_path(file_url), trash._trash_path(file_url)):
			if os.path.isfile(yol):
				os.remove(yol)

	# Rapor, KİMİN sildiğine değil dosyanın son durumuna bakar. Önce "benim
	# `os.remove` çağrım çalıştı mı" diye ölçülüyordu; Frappe önce sildiğinde
	# denetim kaydına "fiziksel silinmedi" yazıyordu — yanlış bilgi.
	fiziksel_silindi = not any(
		os.path.isfile(y) for y in (trash._live_path(file_url), trash._trash_path(file_url))
	)

	audit.log_media_event(
		action=audit.ACTION_DELETE,
		file_url=file_url,
		tenant=store,
		context={
			"records": kayitlar,
			"refs_cleared": temizlik["total"],
			"remaining_owners": len(kalan),
			"physically_deleted": fiziksel_silindi,
		},
	)
	return {
		"file_url": file_url,
		"records": len(kayitlar),
		"refs_cleared": temizlik["total"],
		"remaining_owners": len(kalan),
		"physically_deleted": fiziksel_silindi,
	}

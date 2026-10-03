"""İlk taslak içerikleri (seed). YAYINLANMAZ; yalnız taslak olarak yazılır.

7 e-posta senaryosu `03-eposta-sablonlari/tools/build.py` tasarımından sistematik dönüştürüldü:
`data-var` → `{{değişken}}`, `data-if` → `{{#if koşul}}`, `data-repeat` → `{{#each liste}}`, örnek
bağlantılar → bağlantı değişkenleri. Temsili demo metinler (örnek belge adları, sabit "4 saat kaldı",
SLA, makbuz/fatura süresi) taşınmadı: gerçek veri yoksa ilgili cümle koşullu bloğa alındı ya da
hiç yazılmadı. HTML ayrıştırıcıları tablo içindeki çıplak metni tablonun dışına taşıdığından döngü ve
koşul belirteçleri tablo hücresinin içine ya da tablonun dışına yerleştirildi.

TR içerikler ve 01/02 EN içerikleri taşınır; kalan olayların taslağı olay adından üretilen genel
metindir (`representative=1`). Hiçbir dil "hazır" işaretlenmez.
"""

# ruff: noqa: E501, UP031

from __future__ import annotations

from tradehub_core.notifications import catalog
from tradehub_core.notifications.email_layout import FF, box, cta, h1, h2, kv, p, spacer, status


def _why(text):
	return p(text, cls="muted", size=13, lh=20, mb=0, extra="margin-top:16px;")


def _tbl(inner_rows_html):
	return (
		'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;">'
		+ inner_rows_html
		+ "</table>"
	)


# ── 01 Doğrulama kodu ─────────────────────────────────────────────────────
def _otp(lang):
	tr = lang == "tr"
	code = (
		'<p class="code text" style="margin:0;%sfont-size:36px;line-height:44px;font-weight:600;letter-spacing:8px;'
		'color:#0a0a0a;text-align:center;">{{otp_code}}</p>'
		'<p class="muted" style="margin:8px 0 0;%sfont-size:13px;line-height:20px;color:#525252;text-align:center;">%s {{expires_at}}</p>'
	) % (FF, FF, "Son geçerlilik:" if tr else "Expires:")
	html = "\n".join(
		[
			status("Tek kullanımlık kod" if tr else "One-time code"),
			h1("Doğrulama kodunuz" if tr else "Your verification code"),
			p(
				"Bu kodu iStoc'taki doğrulama alanına girin. Kod <strong>{{expires_minutes}} dakika</strong> boyunca ve yalnız bir kez geçerli."
				if tr
				else "Enter this code in the verification field on iStoc. It is valid for <strong>{{expires_minutes}} minutes</strong> and can be used once."
			),
			box(code, pad="24px 20px", accent=True),
			h2("İşlem ayrıntıları" if tr else "Request details"),
			kv(
				[
					("İşlem" if tr else "Action", "{{action_label}}"),
					("Zaman" if tr else "Time", "{{requested_at}}"),
				]
			),
			"{{#if device}}" + kv([("Cihaz" if tr else "Device", "{{device}}")]) + "{{/if}}",
			"{{#if location}}" + kv([("Konum" if tr else "Location", "{{location}}")]) + "{{/if}}",
			spacer(16),
			p(
				"<strong>Bu kodu kimseyle paylaşmayın.</strong> iStoc çalışanları telefonla, e-postayla ya da sohbette sizden bu kodu asla istemez."
				if tr
				else "<strong>Do not share this code with anyone.</strong> iStoc staff will never ask you for it by phone, email or chat.",
				mb=8,
			),
			p(
				"Bu işlemi siz başlatmadıysanız e-postayı yoksayın; kod süresi dolunca kendiliğinden geçersiz olur ve hesabınızda hiçbir şey değişmez."
				if tr
				else "If you did not start this, ignore this email. The code expires on its own and nothing changes on your account.",
				mb=0,
			),
			_why(
				"Bu e-postayı, {{email}} adresi için iStoc'ta doğrulama kodu istendiği için aldınız."
				if tr
				else "You received this email because a verification code was requested on iStoc for {{email}}."
			),
		]
	)
	if tr:
		email = {
			"subject": "iStoc doğrulama kodunuz: {{otp_code}}",
			"preheader": "Kod {{expires_minutes}} dakika geçerli. Siz talep etmediyseniz bu e-postayı yoksayın; hesabınızda hiçbir şey değişmez.",
			"html": html,
			"text": "Doğrulama kodunuz: {{otp_code}}\n\nKod {{expires_minutes}} dakika boyunca ve yalnız bir kez geçerli. Son geçerlilik: {{expires_at}}\n\nİşlem: {{action_label}}\nZaman: {{requested_at}}\n\nBu kodu kimseyle paylaşmayın. Bu işlemi siz başlatmadıysanız e-postayı yoksayın.",
		}
		sms = {
			"text": "iStoc dogrulama kodunuz: {{otp_code}}. {{expires_minutes}} dakika gecerlidir. Kodu kimseyle paylasmayin."
		}
	else:
		email = {
			"subject": "Your iStoc verification code: {{otp_code}}",
			"preheader": "Valid for {{expires_minutes}} minutes. If you did not request it, ignore this email; nothing changes on your account.",
			"html": html,
			"text": "Your verification code: {{otp_code}}\n\nValid for {{expires_minutes}} minutes and can be used once. Expires: {{expires_at}}\n\nAction: {{action_label}}\nTime: {{requested_at}}\n\nDo not share this code with anyone. If you did not start this, ignore this email.",
		}
		sms = {
			"text": "Your iStoc verification code: {{otp_code}}. Valid for {{expires_minutes}} minutes. Do not share it."
		}
	return {"email": email, "sms": sms}


# ── 02 Şifre sıfırlama ────────────────────────────────────────────────────
def _reset(lang):
	tr = lang == "tr"
	hello = (
		"Merhaba{{#if first_name}} {{first_name}}{{/if}}, "
		if tr
		else "Hi{{#if first_name}} {{first_name}}{{/if}}, "
	)
	raw = (
		'<p class="raw-url muted" style="margin:0 0 20px;%sfont-size:12px;line-height:18px;color:#525252;word-break:break-all;">%s<br>'
		'<a class="link raw-link" href="{{reset_url}}" style="color:#ad5b00;text-decoration:underline;">{{reset_url}}</a></p>'
	) % (
		FF,
		"Düğme açılmıyorsa bağlantıyı tarayıcınıza kopyalayın:"
		if tr
		else "If the button does not work, copy this link into your browser:",
	)
	html = "\n".join(
		[
			status("Şifre sıfırlama talebi" if tr else "Password reset request"),
			h1("Şifrenizi sıfırlayın" if tr else "Reset your password"),
			p(
				hello
				+ (
					"{{email}} hesabı için şifre sıfırlama talebi aldık. Yeni şifrenizi belirlemek için düğmeyi kullanın."
					if tr
					else "we received a request to reset the password for {{email}}. Use the button to choose a new one."
				)
			),
			cta("Yeni şifre belirle" if tr else "Set a new password", "{{reset_url}}", "reset_url"),
			spacer(24),
			box(
				kv(
					[
						(
							"Geçerlilik" if tr else "Validity",
							"Bağlantı <strong>{{reset_expires_hours}} saat</strong> geçerli ve <strong>bir kez</strong> kullanılır. Süre dolarsa yeni bir bağlantı isteyin."
							if tr
							else "The link is valid for <strong>{{reset_expires_hours}} hours</strong> and can be used <strong>once</strong>. If it expires, request a new one.",
						),
						("Talep zamanı" if tr else "Requested", "{{requested_at}}"),
					]
				)
			),
			spacer(16),
			p(
				"<strong>Bu bağlantıyı kimseyle paylaşmayın.</strong> Bağlantıya sahip olan herkes şifrenizi değiştirebilir."
				if tr
				else "<strong>Do not share this link with anyone.</strong> Anyone who has it can change your password.",
				mb=8,
			),
			p(
				"Siz istemediyseniz hiçbir şey yapmanız gerekmez; şifreniz değişmedi."
				if tr
				else "If you did not request this, you do not need to do anything; your password has not changed.",
				mb=16,
			),
			raw,
			_why(
				"Bu e-postayı, iStoc'ta bu adres için şifre sıfırlama istendiği için aldınız."
				if tr
				else "You received this email because a password reset was requested on iStoc for this address."
			),
		]
	)
	if tr:
		return {
			"email": {
				"subject": "Şifrenizi sıfırlayın",
				"preheader": "Bağlantı {{reset_expires_hours}} saat geçerli ve bir kez kullanılır. Talep sizden gelmediyse şifreniz değişmedi; işlem gerekmez.",
				"html": html,
				"text": "Şifrenizi sıfırlayın\n\n{{email}} hesabı için şifre sıfırlama talebi aldık. Yeni şifrenizi belirlemek için bu bağlantıyı açın:\n{{reset_url}}\n\nBağlantı {{reset_expires_hours}} saat geçerli ve bir kez kullanılır.\nTalep zamanı: {{requested_at}}\n\nBu bağlantıyı kimseyle paylaşmayın. Siz istemediyseniz hiçbir şey yapmanız gerekmez.",
			},
			"inapp": {
				"title": "Şifre sıfırlama istendi",
				"message": "{{requested_at}} tarihinde hesabınız için şifre sıfırlama bağlantısı gönderildi. Siz istemediyseniz şifrenizi değiştirin.",
				"action_label": "",
				"action_url": "",
			},
		}
	return {
		"email": {
			"subject": "Reset your password",
			"preheader": "The link is valid for {{reset_expires_hours}} hours and works once. If you did not ask for this, your password has not changed.",
			"html": html,
			"text": "Reset your password\n\nWe received a request to reset the password for {{email}}. Open this link to choose a new one:\n{{reset_url}}\n\nThe link is valid for {{reset_expires_hours}} hours and can be used once.\nRequested: {{requested_at}}\n\nDo not share this link. If you did not request this, you do not need to do anything.",
		},
		"inapp": {
			"title": "Password reset requested",
			"message": "A password reset link was sent for your account on {{requested_at}}. If this was not you, change your password.",
			"action_label": "",
			"action_url": "",
		},
	}


# ── 03 Başvuru sonucu (iki dal) ───────────────────────────────────────────
def _application():
	docs = (
		'<tr><td class="rule" style="padding:12px 0;">{{#each docs}}'
		'<p class="text" style="margin:0 0 2px;%sfont-size:15px;line-height:23px;font-weight:600;color:#0a0a0a;">{{doc.name}}</p>'
		'{{#if doc.reason}}<p class="warn" style="margin:0 0 12px;%sfont-size:14px;line-height:21px;color:#92400e;">{{doc.reason}}</p>{{/if}}'
		"{{/each}}</td></tr>"
	) % (FF, FF)
	approved = "\n".join(
		[
			status("Onaylandı", "success"),
			h1("Mağaza başvurunuz onaylandı"),
			p(
				"<strong>{{company_name}}</strong> için mağaza paneliniz hazır. İlk ürününüzü ekleyerek satışa hazırlanabilirsiniz."
			),
			cta("Mağaza paneline git", "{{panel_url}}", "panel_url"),
			h2("Başvuru bilgileri"),
			kv(
				[
					("Başvuru no", "{{application_no}}"),
					("Onay zamanı", "{{approved_at}}"),
					("Yetkili", "{{email}}"),
				]
			),
		]
	)
	required = "\n".join(
		[
			status("İşlem gerekli"),
			h1("Başvurunuz için ek belge gerekiyor"),
			p(
				"{{company_name}} başvurusunu {{reviewed_at}} tarihinde inceledik. Değerlendirmeyi bitirebilmemiz için belgelerinizin yeniden yüklenmesi gerekiyor."
			),
			box(
				p("İnceleme notu", cls="muted", size=13, lh=20, mb=4) + p("{{rejection_reason}}", mb=0),
				pad="14px 20px",
				accent=True,
			),
			"{{#if docs}}" + box(_tbl(docs), pad="2px 20px") + "{{/if}}",
			spacer(16),
			"{{#if deadline}}" + p("Belgeler için son tarih: <strong>{{deadline}}</strong>.") + "{{/if}}",
			cta("Belgeleri yükle", "{{documents_url}}", "documents_url"),
			spacer(24),
			p("Sorunuz varsa başvuru numaranızla ({{application_no}}) destek ekibimize yazın.", mb=0),
		]
	)
	html = (
		"{{#if application_approved}}\n"
		+ approved
		+ "\n{{/if}}\n{{#if documents_required}}\n"
		+ required
		+ "\n{{/if}}\n"
		+ _why(
			"Bu e-postayı, iStoc'ta satıcı başvurusu yaptığınız ve başvurunuz sonuçlandığı için aldınız. Başvuru sonuçları zorunlu işlem bildirimidir."
		)
	)
	return {
		"email": {
			"subject": "{{#if application_approved}}Mağaza başvurunuz onaylandı{{/if}}{{#if documents_required}}Başvurunuz için ek belge gerekiyor{{/if}}",
			"preheader": "{{#if application_approved}}{{company_name}} iStoc'ta satabilir. Mağaza panelinizden ilk ürününüzü ekleyebilirsiniz.{{/if}}{{#if documents_required}}{{company_name}} başvurusu için bazı belgelerin yeniden yüklenmesi gerekiyor. Panelden yükleyebilirsiniz.{{/if}}",
			"html": html,
			"text": "{{#if application_approved}}Mağaza başvurunuz onaylandı\n\n{{company_name}} için mağaza paneliniz hazır.\nMağaza paneline git: {{panel_url}}\n\nBaşvuru no: {{application_no}}\nOnay zamanı: {{approved_at}}\n{{/if}}{{#if documents_required}}Başvurunuz için ek belge gerekiyor\n\n{{company_name}} başvurusunu {{reviewed_at}} tarihinde inceledik.\nİnceleme notu: {{rejection_reason}}\n{{#each docs}}- {{doc.name}}{{#if doc.reason}}: {{doc.reason}}{{/if}}\n{{/each}}{{#if deadline}}Son tarih: {{deadline}}\n{{/if}}Belgeleri yükle: {{documents_url}}\n\nBaşvuru no: {{application_no}}\n{{/if}}",
		},
		"inapp": {
			"title": "Başvuru durumu güncellendi",
			"message": "{{application_no}} numaralı satıcı başvurunuz sonuçlandı.{{#if documents_required}} Ek belge gerekiyor.{{/if}}",
			"action_label": "Ayrıntıyı görüntüle",
			"action_url": "{{status_url}}",
		},
	}


# ── 04 Abonelik ödeme makbuzu ─────────────────────────────────────────────
def _receipt():
	html = "\n".join(
		[
			status("Ödeme tamamlandı", "success"),
			h1("Ödemeniz alındı"),
			p("<strong>{{plan_name}}</strong> · {{period}}", cls="muted", mb=20),
			box(
				p("Ödenen tutar", cls="muted", size=13, lh=20, mb=4)
				+ p("{{total}}", size=34, lh=40, weight=700, mb=8)
				+ p(
					"{{paid_at}}{{#if card_last4}} · Kart •••• {{card_last4}}{{/if}}",
					cls="muted",
					size=13,
					lh=20,
					mb=0,
				),
				pad="18px 20px",
				accent=True,
			),
			spacer(20),
			"{{#if receipt_url}}" + cta("Makbuzu görüntüle", "{{receipt_url}}", "receipt_url") + "{{/if}}",
			h2("Ödeme ayrıntıları"),
			kv(
				[
					("Plan", "{{plan_name}}, {{billing_cycle}}"),
					("Dönem", "{{period}}"),
					("Toplam", "<strong>{{total}}</strong>"),
					("Ödeme referansı", "{{payment_reference}}"),
				]
			),
			"{{#if receipt_no}}" + kv([("Makbuz no", "{{receipt_no}}")]) + "{{/if}}",
			spacer(16),
			"{{#if period_end}}"
			+ p(
				"{{plan_name}} aboneliğiniz {{period_end}} tarihine kadar aktif.",
				cls="muted",
				size=13,
				lh=20,
				mb=12,
			)
			+ "{{/if}}",
			"{{#if invoice_note}}"
			+ p("Bu e-posta fatura değildir. Fatura ayrıca düzenlenir.", cls="muted", size=13, lh=20, mb=0)
			+ "{{/if}}",
			p(
				'<a class="link" href="{{subscription_url}}" style="color:#ad5b00;text-decoration:underline;font-weight:600;">Abonelik ayarları</a>',
				size=14,
				lh=21,
				mb=0,
				extra="margin-top:12px;",
			),
			_why(
				"Bu e-postayı, {{company_name}} hesabının abonelik ödemesi alındığı için aldınız. Ödeme makbuzları zorunlu işlem bildirimidir; kapatılamaz."
			),
		]
	)
	return {
		"email": {
			"subject": "Ödemeniz alındı · {{total}}",
			"preheader": "{{plan_name}} aboneliği, {{period}}. Ödeme kaydınız aşağıda; fatura ayrıca düzenlenir.",
			"html": html,
			"text": "Ödemeniz alındı\n\nÖdenen tutar: {{total}}\nÖdeme zamanı: {{paid_at}}\nPlan: {{plan_name}}, {{billing_cycle}}\nDönem: {{period}}\nÖdeme referansı: {{payment_reference}}\n{{#if receipt_no}}Makbuz no: {{receipt_no}}\n{{/if}}{{#if receipt_url}}Makbuz: {{receipt_url}}\n{{/if}}{{#if invoice_note}}\nBu e-posta fatura değildir. Fatura ayrıca düzenlenir.\n{{/if}}\nAbonelik ayarları: {{subscription_url}}",
		},
		"inapp": {
			"title": "Ödemeniz alındı",
			"message": "{{plan_name}} aboneliği için {{total}} tutarındaki ödemeniz alındı.",
			"action_label": "Aboneliği görüntüle",
			"action_url": "{{subscription_url}}",
		},
	}


# ── 05 Sipariş onay hatırlatması ──────────────────────────────────────────
def _reminder():
	html = "\n".join(
		[
			status("Onay bekliyor"),
			h1("{{order_no}} onayınızı bekliyor"),
			p(
				"{{buyer_company}}, {{items_count}} kalemlik {{order_total}} tutarındaki siparişi {{ordered_at}} tarihinde verdi. Sipariş {{waiting_hours}} saattir onayınızı bekliyor."
			),
			cta("Siparişi görüntüle", "{{order_url}}", "order_url"),
			h2("Sipariş özeti"),
			box(
				kv(
					[
						("Sipariş", "{{order_no}}"),
						("Alıcı", "{{buyer_company}}"),
						("Kalem", "{{items_count}}"),
						("Tutar", "<strong>{{order_total}}</strong>"),
						("Sipariş zamanı", "{{ordered_at}}"),
					]
				)
			),
			spacer(20),
			p(
				"Sipariş onaylanınca bu hatırlatma durur. Süre ve sonraki adımlar sipariş sayfasında yazar.",
				cls="muted",
				size=13,
				lh=20,
				mb=8,
			),
			p(
				'Bu hatırlatma acil olduğu için günlük ya da haftalık özete girmez. E-postasını <a class="link" href="{{preferences_url}}" style="color:#ad5b00;text-decoration:underline;">bildirim tercihlerinden</a> kapatabilirsiniz; uygulama içi bildirim gelmeye devam eder.',
				cls="muted",
				size=13,
				lh=20,
				mb=0,
			),
			_why(
				"Bu e-postayı, {{seller_store_name}} mağazasının yetkilisi olduğunuz ve bir sipariş onayınızı beklediği için aldınız."
			),
		]
	)
	return {
		"email": {
			"subject": "{{order_no}} numaralı sipariş onayınızı bekliyor",
			"preheader": "{{buyer_company}}, {{items_count}} kalem, {{order_total}}. Siparişi onaylayınca hatırlatmalar durur.",
			"html": html,
			"text": "{{order_no}} onayınızı bekliyor\n\n{{buyer_company}}, {{items_count}} kalemlik {{order_total}} tutarındaki siparişi {{ordered_at}} tarihinde verdi. Sipariş {{waiting_hours}} saattir onayınızı bekliyor.\n\nSiparişi görüntüle: {{order_url}}\n\nSipariş onaylanınca bu hatırlatma durur.\nBildirim tercihleri: {{preferences_url}}",
		},
		"inapp": {
			"title": "Sipariş onay bekliyor",
			"message": "{{order_no}} numaralı sipariş {{waiting_hours}} saattir onayınızı bekliyor.",
			"action_label": "Siparişi aç",
			"action_url": "{{order_url}}",
		},
		"push": {
			"title": "Sipariş onay bekliyor",
			"body": "{{order_no}} numaralı sipariş onayınızı bekliyor.",
		},
	}


# ── 06 / 07 Özet ──────────────────────────────────────────────────────────
def _digest(kind):
	daily = kind == "daily"
	group = (
		'<div style="padding:0 0 24px;">'
		'<h2 class="text" style="margin:0 0 8px;%sfont-size:17px;line-height:24px;font-weight:600;color:#0a0a0a;">{{group.title}} ({{group.count}})</h2>'
		"{{#each group.items}}"
		'<p class="text" style="margin:0;padding:10px 0;border-bottom:1px solid #e5e5e5;%sfont-size:14px;line-height:21px;color:#0a0a0a;">'
		'<a class="link" href="{{item.url}}" style="color:#0a0a0a;text-decoration:none;">{{item.title}}</a>'
		' <span class="muted" style="color:#525252;font-size:13px;">· {{item.time}}</span></p>'
		"{{/each}}"
		'{{#if group.more}}<p class="muted" style="margin:0;padding:10px 0 0;%sfont-size:13px;line-height:20px;color:#525252;">ve {{group.more_n}} tane daha</p>{{/if}}'
		"</div>"
	) % (FF, FF, FF)
	html = "\n".join(
		[
			status("Hesabınızdan haberler"),
			h1("{{digest_title}}"),
			box(
				p("{{total_count}} gelişme", size=28, lh=34, weight=700, mb=4)
				+ p("{{recipient_name}}", cls="muted", size=14, lh=21, mb=0),
				pad="20px",
				accent=True,
			),
			spacer(20),
			cta("Tümünü bildirimlerde gör", "{{digest_url}}", "digest_url"),
			spacer(28),
			"{{#each groups}}" + group + "{{/each}}",
			p(
				"Acil bildirimler anında gönderildi; bu özet yalnız bekleyebilenleri toplar.",
				cls="muted",
				size=13,
				lh=20,
				mb=12,
			),
			p("Dönem: {{period}} · Hazırlanma: {{generated_at}}", cls="muted", size=13, lh=20, mb=8),
			p(
				'<a class="link" href="{{preferences_url}}" style="color:#ad5b00;text-decoration:underline;font-weight:600;">Özet sıklığını değiştir</a>',
				size=14,
				lh=21,
				mb=0,
			),
			_why(
				"Bu e-postayı, e-posta sıklığı olarak %s seçtiğiniz için aldınız."
				% ("günlük özet" if daily else "haftalık özet")
			),
		]
	)
	label = "Günlük özet" if daily else "Haftalık özet"
	return {
		"email": {
			"subject": "%s · {{period}} · {{total_count}} gelişme" % label,
			"preheader": "Bekleyebilen bildirimleriniz tek e-postada. Acil bildirimler özeti beklemez; onlar anında gönderildi.",
			"html": html,
			"text": "{{digest_title}}\n\n{{total_count}} gelişme. Acil olanlar anında gönderildi; bu özet yalnız bekleyebilenleri toplar.\n\n{{#each groups}}{{group.title}} ({{group.count}})\n{{#each group.items}}  - {{item.title}} · {{item.time}}\n{{/each}}{{#if group.more}}  ve {{group.more_n}} tane daha\n{{/if}}\n{{/each}}Tümü: {{digest_url}}\nDönem: {{period}} · Hazırlanma: {{generated_at}}\nÖzet sıklığını değiştir: {{preferences_url}}",
		}
	}


# ── Genel içerik (temsili) ────────────────────────────────────────────────
def _generic(name):
	low = name[0].lower() + name[1:]
	return {
		"email": {
			"subject": f"{name}: {{{{reference_no}}}}",
			"preheader": f"{name} bildirimi · {{{{event_date}}}}",
			"html": f"{h1(name)}\n{p('Merhaba{{#if recipient_name}} {{recipient_name}}{{/if}},')}\n{p(f'{{{{reference_no}}}} numaralı kayıt için bildirim: {low}. Tarih: {{{{event_date}}}}.')}\n{cta('Ayrıntıyı görüntüle', '{{action_url}}', 'action_url')}",
			"text": f"{name}: {{{{reference_no}}}}\nTarih: {{{{event_date}}}}\nAyrıntı: {{{{action_url}}}}",
		},
		"inapp": {
			"title": name,
			"message": f"{{{{reference_no}}}} numaralı kayıt için bildirim: {low}.",
			"action_label": "Ayrıntıyı görüntüle",
			"action_url": "{{action_url}}",
		},
		"push": {"title": name, "body": "{{reference_no}} numaralı kayıt için bildirim."},
		"sms": {"text": "iStoc: {{reference_no}} icin yeni bildirim. Ayrinti: {{action_url}}"},
	}


SPECIFIC = {
	"identity.otp": {"tr": lambda: _otp("tr"), "en": lambda: _otp("en")},
	"identity.password_reset": {"tr": lambda: _reset("tr"), "en": lambda: _reset("en")},
	"store.application_result": {"tr": _application},
	"payment.receipt": {"tr": _receipt},
	"order.confirm_reminder": {"tr": _reminder},
	"digest.daily": {"tr": lambda: _digest("daily")},
	"digest.weekly": {"tr": lambda: _digest("weekly")},
}


def seed_for(event: dict) -> tuple[dict, dict, bool]:
	"""(taslak içerik ağacı, çeviri durumları, temsili mi). Kapalı kanallara içerik yazılmaz."""
	key = event["key"]
	channels = event["channels"]
	tree = {ch: {lang: None for lang in catalog.LANGS} for ch in catalog.CHANNELS}
	states = {lang: "eksik" for lang in catalog.LANGS}
	specific = SPECIFIC.get(key)
	builders = specific or {"tr": lambda: _generic(event["name"])}
	for lang, build in builders.items():
		content = build()
		for ch in catalog.CHANNELS:
			if channels.get(ch) != "kapali" and content.get(ch):
				fields = {f: "" for f in catalog.FIELDS[ch]}
				fields.update(content[ch])
				tree[ch][lang] = fields
		# İçerik var ama gözden geçirilmedi: "hazır" işaretlenmez.
		states[lang] = "bekliyor"
	return tree, states, specific is None

"""E-posta kabuğu ve bileşenleri — tasarım kaynağı `desing/.../03-eposta-sablonlari/tools/build.py`.

Kabuk (tablo düzeni, preheader, açık/koyu tema CSS'i, mobil kurallar) build.py'den birebir taşındı;
görüntüleyici JavaScript'i taşınmadı. Bileşen yardımcıları seed içeriği üretmek için kullanılır;
gönderimde yalnız `page()` kabuğu sunucu kodundan gelir, gövde yayınlanmış şablondan gelir.

Bu dosyadaki CSS ve kabuk güvenilir sunucu kodudur; gövde ayrıca allowlist ile temizlenmiştir.
"""
# ruff: noqa: E501, UP031, E731

import textwrap  # noqa: F401

FF = "font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
BRK = "word-break:break-word;overflow-wrap:anywhere;"  # T39: uzun kesintisiz değerler
C = dict(text="#0a0a0a", muted="#525252", warn="#92400e", link="#ad5b00")

# Renk kuralları tek listeden: (seçici, açık bildirimler, koyu bildirimler)
THEME = [
	("body, {p}.body-bg", "background-color:#f7f7f7", "background-color:#0f0f0f"),
	(
		".card",
		"background-color:#ffffff;border-color:#e5e5e5",
		"background-color:#1a1a1a;border-color:#333333",
	),
	(
		".box",
		"background-color:#f9f9f9;border-color:#e5e5e5",
		"background-color:#222222;border-color:#333333",
	),
	(".rule", "border-color:#e5e5e5", "border-color:#333333"),
	(".text", "color:#0a0a0a", "color:#f0f0f0"),
	(".muted", "color:#525252", "color:#b3b3b3"),
	(".link", "color:#ad5b00", "color:#ffa64d"),
	(".warn", "color:#92400e", "color:#f2a65a"),
	(".cta-cell", "background-color:#ff8600", "background-color:#ff8600"),
	(".cta-link", "color:#1a1a1a", "color:#1a1a1a"),
	(".mark", "background-color:#ff8600", "background-color:#ff8600"),
	(
		".accent-surface",
		"background-color:#fff5e9;border-color:#f2d6b3",
		"background-color:#302419;border-color:#634525",
	),
	(".accent-ink", "color:#92400e", "color:#ffc184"),
	(".success-surface", "background-color:#eaf5ef", "background-color:#18382a"),
	(".success-ink", "color:#176445", "color:#9fe0bc"),
]


def imp(decl):
	return ";".join(d + " !important" for d in decl.split(";")) + ";"


def theme_css():
	out = ["  @media (prefers-color-scheme: dark) {"]
	for sel, _l, d in THEME:
		out.append("    %s { %s }" % (sel.replace("{p}", ""), imp(d)))
	out.append("  }")
	out.append("  /* Önizleme ve Outlook koyu modu: aynı kurallar öznitelik seçicisiyle */")
	for sel, _l, d in THEME:
		for pre in ('html[data-theme="dark"] ', "[data-ogsc] "):
			s = ", ".join(pre + part.strip().replace("{p}", "") for part in sel.split(","))
			out.append("  %s { %s }" % (s, imp(d)))
	out.append("  /* Önizlemede açık temayı zorlama: sistem koyuyken medya sorgusunu ezer */")
	for sel, l, _d in THEME:
		s = ", ".join(
			'html[data-theme="light"] ' + part.strip().replace("{p}", "") for part in sel.split(",")
		)
		out.append("  %s { %s }" % (s, imp(l)))
	out.append('  html[data-theme="light"] { color-scheme:light; }')
	out.append('  html[data-theme="dark"] { color-scheme:dark; }')
	return "\n".join(out)


HEAD_CSS = """  body { margin:0; padding:0; -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }
  table { border-collapse:collapse; mso-table-lspace:0pt; mso-table-rspace:0pt; }
  td, th { font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; }
  a { color:#ad5b00; }
  /* Uzun kesintisiz değerler (e-posta adresi, şirket/plan adı, kimlik no) satır içinde kırılır */
  p, h1, h2, li, td, th { word-break:break-word; overflow-wrap:anywhere; }
  .kv, .receipt { table-layout:fixed; }
  .card, .box, .cta, .accent-surface, .steps { border-collapse:separate; border-spacing:0; }
  a:focus-visible { outline:2px solid #ad5b00; outline-offset:4px; }
  @media only screen and (max-width:620px) {
    .canvas { padding:0 !important; }
    .container { width:100% !important; max-width:100% !important; }
    .card { border-left:0 !important; border-right:0 !important; border-radius:0 !important; }
    .px { padding-left:20px !important; padding-right:20px !important; }
    .px-top { padding-top:20px !important; }
    .cta { width:100% !important; }
    .cta-cell { display:block !important; width:100% !important; }
    .cta-link { display:block !important; width:100% !important; box-sizing:border-box !important; text-align:center !important; }
    .receipt th { font-size:13px !important; line-height:20px !important; }
    .receipt td { font-size:14px !important; line-height:20px !important; }
    .kv-l { width:104px !important; }
    .code { font-size:28px !important; letter-spacing:5px !important; }
    h1 { font-size:22px !important; line-height:28px !important; }
    .step-copy { padding-right:12px !important; }
    .foot-link { display:inline-block !important; padding-top:12px !important; padding-bottom:12px !important; }
    .digest-link { display:inline-block !important; padding-top:12px !important; padding-bottom:12px !important; }
  }
  /* Çok dar ekran: etiket üstte, değer altta */
  @media only screen and (max-width:360px) {
    .kv-l, .kv-v { display:block !important; width:100% !important; box-sizing:border-box !important; }
    .kv-l { padding-bottom:0 !important; }
    .kv-v { border-top:0 !important; padding-top:0 !important; }
  }
"""


def a(text, href, bold=False, extra=""):
	return '<a class="link" href="%s"%s style="color:#ad5b00;text-decoration:underline;%s">%s</a>' % (
		href,
		extra,
		"font-weight:600;" if bold else "",
		text,
	)


def v(name, val):
	return '<span data-var="%s">%s</span>' % (name, val)


def p(html, cls="text", size=15, lh=23, mb=16, weight=None, attrs="", extra=""):
	color = C["warn" if "warn" in cls else "muted" if "muted" in cls else "text"]
	return (
		'<p class="%s"%s style="margin:0 0 %dpx;%sfont-size:%dpx;line-height:%dpx;%scolor:%s;%s%s">%s</p>'
		% (
			cls,
			attrs,
			mb,
			FF,
			size,
			lh,
			("font-weight:%s;" % weight) if weight else "",
			color,
			BRK,
			extra,
			html,
		)
	)


def h1(html, attrs=""):
	return (
		'<h1 class="text"%s style="margin:0 0 12px;%sfont-size:24px;line-height:30px;font-weight:700;'
		'letter-spacing:-0.025em;color:#0a0a0a;%s">%s</h1>'
	) % (attrs, FF, BRK, html)


def h2(html):
	return (
		'<h2 class="text" style="margin:24px 0 12px;%sfont-size:16px;line-height:22px;font-weight:600;'
		'color:#0a0a0a;%s">%s</h2>'
	) % (FF, BRK, html)


def spacer(h):
	return '<div style="height:%dpx;line-height:%dpx;font-size:0;">&nbsp;</div>' % (h, h)


def status(label, tone="accent", attrs=""):
	"""Durum renk olmadan da metinle anlaşılır; görsele/fonta bağımlı değildir."""
	bg, ink = ("#eaf5ef", "#176445") if tone == "success" else ("#fff5e9", "#92400e")
	return (
		'<p%s style="margin:0 0 16px;%sfont-size:12px;line-height:20px;font-weight:600;">'
		'<span class="%s-surface %s-ink" style="display:inline-block;padding:4px 10px;border-radius:4px;'
		'background-color:%s;color:%s;">%s</span></p>'
	) % (attrs, FF, tone, tone, bg, ink, label)


def steps_list(steps):
	rows = []
	for i, (title, desc) in enumerate(steps):
		surface = ' class="accent-surface" bgcolor="#fff5e9"' if i == 0 else ""
		style = "background-color:#fff5e9;" if i == 0 else ""
		line = "border-top:1px solid #e5e5e5;" if i else ""
		rows.append(
			'<tr%s style="%s"><td class="rule" valign="top" width="40" style="padding:16px 8px 16px 16px;width:40px;%s">'
			'<span class="accent-ink" style="display:block;%sfont-size:13px;line-height:24px;font-weight:600;color:#92400e;">%02d</span></td>'
			'<td class="step-copy rule" valign="top" style="padding:16px 20px 16px 0;%s">%s%s</td></tr>'
			% (
				surface,
				style,
				line,
				FF,
				i + 1,
				line,
				p(title, size=15, lh=21, mb=4, weight=600),
				p(desc, cls="muted", size=14, lh=21, mb=0),
			)
		)
	return (
		'<table role="presentation" class="steps" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:separate;border-spacing:0;">'
		+ "".join(rows)
		+ "</table>"
	)


def box(inner, pad="8px 20px", accent=False):
	bg, border = ("#fff5e9", "#f2d6b3") if accent else ("#f9f9f9", "#e5e5e5")
	return (
		'<table role="presentation" class="box%s" width="100%%" cellpadding="0" cellspacing="0" border="0" bgcolor="%s" '
		'style="width:100%%;background-color:%s;border:1px solid %s;border-radius:8px;border-collapse:separate;border-spacing:0;">'
		'<tr><td style="padding:%s;">%s</td></tr></table>'
	) % (" accent-surface" if accent else "", bg, bg, border, pad, inner)


def kv(rows, w=112):
	"""rows: (etiket, değer_html[, tr öznitelikleri])"""
	out = [
		'<table role="presentation" class="kv" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;table-layout:fixed;">'
	]
	for i, row in enumerate(rows):
		label, val = row[0], row[1]
		attrs = row[2] if len(row) > 2 else ""
		bt = "border-top:1px solid #e5e5e5;" if i else ""
		out.append(
			'<tr%s><td class="kv-l muted rule" width="%d" valign="top" style="%spadding:8px 12px 8px 0;%sfont-size:13px;line-height:20px;color:#525252;width:%dpx;">%s</td>'
			'<td class="kv-v text rule" valign="top" style="%spadding:8px 0;%sfont-size:15px;line-height:20px;color:#0a0a0a;%s">%s</td></tr>'
			% (attrs, w, bt, FF, w, label, bt, FF, BRK, val)
		)
	out.append("</table>")
	return "".join(out)


def cta(label, url, var):
	return (
		'<table role="presentation" class="cta" cellpadding="0" cellspacing="0" border="0" style="margin:4px 0 0;">\n'
		'  <tr><td class="cta-cell" bgcolor="#ff8600" style="background-color:#ff8600;border-radius:6px;mso-padding-alt:14px 28px;">\n'
		'    <a class="cta-link" href="%s" data-var="%s" style="display:inline-block;padding:14px 28px;border-radius:6px;%sfont-size:15px;line-height:20px;font-weight:600;color:#1a1a1a;text-decoration:none;mso-padding-alt:0;">%s</a>\n'
		"  </td></tr>\n</table>"
	) % (url, var, FF, label)


def raw_url(url, lead="Düğme açılmıyorsa bağlantıyı tarayıcınıza kopyalayın:"):
	return (
		'<p class="raw-url muted" style="margin:0 0 20px;%sfont-size:12px;line-height:18px;color:#525252;word-break:break-all;">%s<br>'
		'<a class="link raw-link" href="%s" style="color:#ad5b00;text-decoration:underline;">%s</a></p>'
	) % (FF, lead, url, url)


def page(lang, subject, preheader, tag, body, foot_html):
	pad = "&zwnj;&nbsp;" * 40
	return """<!DOCTYPE html>
<html lang="%(lang)s" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<meta name="x-apple-disable-message-reformatting">
<meta name="format-detection" content="telephone=no, date=no, address=no, email=no">
<title>%(subject)s</title>
<!--[if mso]>
<noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript>
<![endif]-->
<style>
%(css)s%(theme)s
</style>
</head>
<body class="body" bgcolor="#f7f7f7" style="margin:0;padding:0;background-color:#f7f7f7;">
<div class="preheader" style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all;">%(pre)s</div>
<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all;" aria-hidden="true">%(pad)s</div>
<table role="presentation" class="body-bg" width="100%%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f7f7f7" style="width:100%%;background-color:#f7f7f7;">
<tr><td class="canvas" align="center" style="padding:24px 12px;">

<table role="presentation" class="container card" width="600" cellpadding="0" cellspacing="0" border="0" bgcolor="#ffffff" style="width:600px;max-width:600px;background-color:#ffffff;border:1px solid #e5e5e5;border-radius:8px;border-collapse:separate;border-spacing:0;">
  <tr><td class="mark" height="4" bgcolor="#ff8600" style="height:4px;line-height:4px;font-size:0;background-color:#ff8600;border-radius:7px 7px 0 0;">&nbsp;</td></tr>
  <tr><td class="px px-top" style="padding:28px 32px 0;">
    <table role="presentation" width="100%%" cellpadding="0" cellspacing="0" border="0" style="width:100%%;">
      <tr>
        <td align="left" valign="middle">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td class="text" valign="middle" style="%(ff)sfont-size:21px;line-height:24px;font-weight:600;letter-spacing:-0.03em;color:#0a0a0a;word-break:normal;overflow-wrap:normal;white-space:nowrap;">iStoc</td>
              <td valign="middle" style="padding:0 0 0 6px;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:10px;height:10px;">
                  <tr><td class="mark" width="10" height="10" bgcolor="#ff8600" style="width:10px;height:10px;background-color:#ff8600;font-size:0;line-height:0;">&nbsp;</td></tr>
                </table>
              </td>
            </tr>
          </table>
        </td>
        <td class="muted" align="right" valign="middle" style="%(ff)sfont-size:13px;line-height:18px;color:#525252;white-space:nowrap;word-break:normal;overflow-wrap:normal;">%(tag)s</td>
      </tr>
    </table>
  </td></tr>
  <tr><td class="px" style="padding:16px 32px 0;"><div class="rule" style="border-top:1px solid #e5e5e5;font-size:0;line-height:0;">&nbsp;</div></td></tr>
  <tr><td class="px" style="padding:28px 32px 8px;">
%(body)s
  </td></tr>
  <tr><td class="px" style="padding:16px 32px 0;"><div class="rule" style="border-top:1px solid #e5e5e5;font-size:0;line-height:0;">&nbsp;</div></td></tr>
  <tr><td class="px" style="padding:16px 32px 24px;">
  </td></tr>
</table>

<table role="presentation" class="container" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:600px;">
  <tr><td class="px" align="left" style="padding:20px 32px 8px;">
%(foot)s
  </td></tr>
</table>

</td></tr>
</table>
</body>
</html>
""" % dict(
		lang=lang,
		subject=subject,
		css=HEAD_CSS,
		theme=theme_css(),
		pre=preheader,
		pad=pad,
		ff=FF,
		brk=BRK,
		tag=tag,
		body=body,
		foot=foot_html,
	)


FOOT_TEXT = {
	"tr": {
		"prefs": "Bildirim tercihleri",
		"mandatory": "Bu e-posta hesabınızla ilgili zorunlu bir bildirimdir; kapatılamaz.",
		"optional": "Bu bildirimi Ayarlar > Bildirimler sayfasından kapatabilirsiniz.",
	},
	"en": {
		"prefs": "Notification preferences",
		"mandatory": "This is a mandatory notice about your account and cannot be turned off.",
		"optional": "You can turn this notification off under Settings > Notifications.",
	},
	"ar": {
		"prefs": "تفضيلات الإشعارات",
		"mandatory": "هذه رسالة إلزامية تتعلق بحسابك ولا يمكن إيقافها.",
		"optional": "يمكنك إيقاف هذا الإشعار من الإعدادات > الإشعارات.",
	},
	"ru": {
		"prefs": "Настройки уведомлений",
		"mandatory": "Это обязательное уведомление о вашей учётной записи; отключить его нельзя.",
		"optional": "Отключить это уведомление можно в разделе «Настройки > Уведомления».",
	},
}


def footer(lang, prefs_url, mandatory):
	"""Altbilgi: tercih bağlantısı + kanalın zorunlu/seçmeli olduğunu söyleyen satır + marka."""
	t = FOOT_TEXT.get(lang) or FOOT_TEXT["tr"]
	fp = lambda html: (
		'<p class="muted" style="margin:0 0 8px;%sfont-size:13px;line-height:20px;color:#525252;">%s</p>'
		% (FF, html)
	)
	return "\n".join(
		[
			fp(t["mandatory"] if mandatory else t["optional"]),
			fp(
				'<a class="link prefs foot-link" href="%s" style="color:#ad5b00;text-decoration:underline;">%s</a>'
				% (prefs_url, t["prefs"])
			),
			fp("© iStoc"),
		]
	)

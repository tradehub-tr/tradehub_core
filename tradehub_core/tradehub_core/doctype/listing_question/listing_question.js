// Listing Question — form helper
frappe.ui.form.on("Listing Question", {
	onload(frm) {
		// Yeni kayıtta asker'ı otomatik doldur (read_only + reqd kombinasyonu
		// form'dan dolduramaz; client-side default set ediyoruz).
		if (frm.is_new() && !frm.doc.asker) {
			frm.set_value("asker", frappe.session.user);
			if (frappe.session.user_fullname) {
				frm.set_value("asker_display_name", frappe.session.user_fullname);
			}
		}
	},
});

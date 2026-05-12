// Listing Question Answer — form helper
frappe.ui.form.on("Listing Question Answer", {
	onload(frm) {
		if (frm.is_new() && !frm.doc.responder) {
			frm.set_value("responder", frappe.session.user);
		}
	},
});

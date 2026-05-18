frappe.ui.form.on("User Profile", {
	refresh(frm) {
		// Capability badges
		if (frm.doc.can_buy && frm.doc.can_sell) {
			frm.dashboard.add_indicator(__("Hybrid (Buyer + Seller)"), "purple");
		} else if (frm.doc.can_sell) {
			frm.dashboard.add_indicator(__("Seller"), "orange");
		} else if (frm.doc.can_buy) {
			frm.dashboard.add_indicator(__("Buyer"), "blue");
		}

		// account_type warning if can_sell=1 but Individual
		if (frm.doc.can_sell && frm.doc.account_type === "Individual") {
			frm.dashboard.add_indicator(__("Invalid: Seller must be Business"), "red");
		}

		// KYC/KYB status indicators
		if (frm.doc.kyc_status === "Verified") {
			frm.dashboard.add_indicator(__("KYC Verified"), "green");
		} else if (frm.doc.kyc_status) {
			frm.dashboard.add_indicator(__("KYC: ") + frm.doc.kyc_status, "yellow");
		}
		if (frm.doc.kyb_status === "Verified") {
			frm.dashboard.add_indicator(__("KYB Verified"), "green");
		} else if (frm.doc.kyb_status) {
			frm.dashboard.add_indicator(__("KYB: ") + frm.doc.kyb_status, "yellow");
		}
	},

	can_sell(frm) {
		// can_sell=1 olunca account_type=Business zorunlu hatırlatma
		if (frm.doc.can_sell && frm.doc.account_type === "Individual") {
			frappe.msgprint({
				title: __("Account Type Upgrade Required"),
				message: __("Satıcı olabilmek için Kurumsal hesap tipi zorunludur. account_type Business'a yükseltilmeli."),
				indicator: "orange",
			});
		}
	},

	account_type(frm) {
		// Business → Individual downgrade yasak
		if (frm.doc.__last_account_type === "Business" && frm.doc.account_type === "Individual") {
			frappe.msgprint({
				title: __("Downgrade Forbidden"),
				message: __("Kurumsal hesaptan Bireysel hesaba geri dönüş yapılamaz."),
				indicator: "red",
			});
			frm.set_value("account_type", "Business");
		}
		frm.doc.__last_account_type = frm.doc.account_type;
	},
});

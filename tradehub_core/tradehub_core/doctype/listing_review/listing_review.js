// Listing Review — admin form helper
frappe.ui.form.on("Listing Review", {
	onload(frm) {
		// Yeni kayıtta reviewer_user'ı otomatik doldur (read-only, validate sırasında session.user'a fallback var
		// ama mandatory kontrolü validate'ten önce çalıştığı için form-level default şart).
		if (frm.is_new() && !frm.doc.reviewer_user) {
			frm.set_value("reviewer_user", frappe.session.user);
		}

		// Sipariş Kalemi seçim alanı — yalnız seçili Sipariş'e ait kalemleri göster.
		frm.set_query("order_item", () => {
			if (!frm.doc.order) {
				return { filters: { name: "__no_match__" } };
			}
			return { filters: { parent: frm.doc.order, parenttype: "Order" } };
		});

		// NOT: Ürün alanını read_only/disabled yapmıyoruz çünkü Frappe v15
		// boş + read_only Link field'larını render etmiyor. Bunun yerine:
		//   - Sipariş Kalemi seçildiğinde listing otomatik dolar (aşağıdaki handler)
		//   - Kullanıcı manuel değiştirebilir, ama controller validate'i
		//     "Sipariş kalemi seçilen ürüne ait değil" diyerek bloke eder
		// Satıcı field'ı JSON'da hidden=1 — kullanıcıya görünmez, listing'den otomatik dolar.
	},
	order(frm) {
		// Sipariş değiştiğinde önceden seçili order_item ve listing'i temizle
		if (frm.doc.order_item) {
			frm.set_value("order_item", null);
		}
		if (frm.doc.listing) {
			frm.set_value("listing", null);
		}
	},
	order_item(frm) {
		// Sipariş kalemi seçildiğinde Listing'i kendi whitelisted endpoint
		// üzerinden çek (Order Item child doctype'a permission tanımı yok,
		// frappe.db.get_value desk-API'si "Not permitted" veriyor).
		if (!frm.doc.order_item) {
			return;
		}
		frappe.call({
			method: "tradehub_core.api.review.get_order_item_listing",
			args: { order_item: frm.doc.order_item },
			callback: (r) => {
				if (r && r.message && r.message.listing) {
					frm.set_value("listing", r.message.listing);
				}
			},
		});
	},
	refresh(frm) {
		if (frm.is_new() || !frm.doc.name) return;

		const is_admin = (frappe.user_roles || []).includes("System Manager")
			|| (frappe.user_roles || []).includes("Marketplace Admin")
			|| frappe.session.user === "Administrator";

		// Risk skorunu yeniden hesapla — rating/body değişikliği sonrası tetiklemek için
		// Yetki kontrolü server-side endpoint'te yapılıyor, JS'de gösterimi kısıtlamıyoruz.
		frm.add_custom_button(__("Risk Yeniden Hesapla"), () => {
			frappe.call({
				method: "tradehub_core.api.risk.admin_recompute_risk",
				args: { review: frm.doc.name },
				callback: (r) => {
					if (r && r.message && r.message.success) {
						frappe.show_alert(__("Risk skoru: {0}", [r.message.risk_score]));
						frm.reload_doc();
					}
				},
			});
		});

		// Cascade Sil butonu — Frappe default delete link guard nedeniyle çalışmıyor
		frm.add_custom_button(__("Cascade Sil"), () => {
			frappe.confirm(
				__("Bu yorum ve bağlı tüm kayıtlar (Risk Score, Helpful Vote, Abuse Report) kalıcı olarak silinecek. Devam?"),
				() => {
					frappe.call({
						method: "tradehub_core.api.review.admin_delete_listing_review",
						args: { name: frm.doc.name },
						callback: (r) => {
							if (r && r.message && r.message.success) {
								frappe.show_alert(__("Yorum silindi"));
								frappe.set_route("List", "Listing Review");
							}
						},
					});
				}
			);
		}).addClass("btn-danger");

		const status = frm.doc.status;
		if (status === "Pending") {
			frm.add_custom_button(__("Onayla"), () => {
				frm.set_value("status", "Approved");
				frm.save();
			}, __("Moderasyon"));
			frm.add_custom_button(__("Reddet"), () => {
				frappe.prompt(
					[{ fieldtype: "Small Text", fieldname: "reason", label: __("Red Nedeni"), reqd: 1 }],
					(values) => {
						frm.set_value("rejected_reason", values.reason);
						frm.set_value("status", "Rejected");
						frm.save();
					},
					__("Yorumu Reddet"),
					__("Reddet")
				);
			}, __("Moderasyon"));
		} else if (status === "Approved") {
			frm.add_custom_button(__("Gizle"), () => {
				frm.set_value("status", "Hidden");
				frm.save();
			}, __("Moderasyon"));
		} else if (status === "Hidden") {
			frm.add_custom_button(__("Tekrar Yayınla"), () => {
				frm.set_value("status", "Approved");
				frm.save();
			}, __("Moderasyon"));
		}

		// Faz 2: İhbarları görüntüle butonu
		if ((frm.doc.abuse_report_count || 0) > 0) {
			frm.add_custom_button(__("İhbarları Görüntüle ({0})", [frm.doc.abuse_report_count]), () => {
				frappe.set_route("List", "Review Abuse Report", { review: frm.doc.name });
			}, __("Faz 2"));
		}

		// Faz 2: Helpful özet badge (dashboard alanı)
		const helpful = frm.doc.helpful_count || 0;
		const not_helpful = frm.doc.not_helpful_count || 0;
		if (helpful || not_helpful) {
			frm.dashboard.add_indicator(
				__("👍 {0}  /  👎 {1}", [helpful, not_helpful]),
				helpful >= not_helpful ? "green" : "orange"
			);
		}

		// Faz 2: SLA göstergesi (seller reply varsa)
		if (frm.doc.seller_reply_within_hours != null) {
			frm.dashboard.add_indicator(
				__("Yanıt SLA: {0} saat", [frm.doc.seller_reply_within_hours]),
				frm.doc.seller_reply_within_hours <= 48 ? "green" : "red"
			);
		}

		// Faz 3: Risk Score badge
		const risk = frm.doc.risk_score || 0;
		let risk_color = "green";
		let risk_label = "Düşük Risk";
		if (risk >= 61) { risk_color = "red"; risk_label = "Yüksek Risk"; }
		else if (risk >= 31) { risk_color = "orange"; risk_label = "Orta Risk"; }
		frm.dashboard.add_indicator(
			__("Risk: {0} ({1})", [risk, risk_label]),
			risk_color
		);

		// Faz 3: Risk faktörleri detay (eğer varsa)
		if (frm.doc.risk_factors_json) {
			try {
				const factors = JSON.parse(frm.doc.risk_factors_json);
				if (factors.length > 0) {
					frm.add_custom_button(__("Risk Faktörleri ({0})", [factors.length]), () => {
						const html = factors.map(f =>
							`<div style="margin-bottom:8px"><b>${f.factor_label}</b> (+${f.weight})<br><small>${f.evidence || ''}</small></div>`
						).join("");
						frappe.msgprint({ title: __("Risk Faktörleri"), message: html, indicator: "red" });
					}, __("Faz 3"));
				}
			} catch (e) { /* JSON parse error — yoksay */ }
		}

		// Faz 4: Dispute Aç butonu (1-2★ ve dispute yoksa)
		if ((frm.doc.rating || 5) <= 2 && !frm.doc.related_dispute) {
			frm.add_custom_button(__("Anlaşmazlık Aç"), () => {
				frappe.prompt(
					[
						{
							fieldtype: "Select", fieldname: "dispute_type",
							label: __("Anlaşmazlık Tipi"), reqd: 1,
							options: "Product Quality\nWrong Item\nDamaged\nNot Delivered\nOther",
						},
						{
							fieldtype: "Small Text", fieldname: "description",
							label: __("Açıklama (min 10 char)"), reqd: 1,
						},
					],
					(v) => {
						frappe.call({
							method: "tradehub_core.api.dispute.open_dispute_from_review",
							args: { review: frm.doc.name,
								dispute_type: v.dispute_type, description: v.description },
							callback: (r) => {
								if (r && r.message && r.message.success) {
									frappe.show_alert(__("Anlaşmazlık açıldı: {0}", [r.message.name]));
									frm.reload_doc();
								}
							},
						});
					},
					__("Anlaşmazlık Aç"), __("Aç")
				);
			}, __("Faz 4"));
		}

		// Faz 4: Dispute durumu (varsa rozet)
		if (frm.doc.related_dispute) {
			let color = "blue";
			let label = __("Anlaşmazlık: Açık");
			if (frm.doc.dispute_resolved_in_favor_of === "buyer") {
				color = "green";
				label = __("Anlaşmazlık: Alıcı Lehine");
			} else if (frm.doc.dispute_resolved_in_favor_of === "seller") {
				color = "orange";
				label = __("Anlaşmazlık: Satıcı Lehine");
			}
			frm.dashboard.add_indicator(label, color);
		}

		// Faz 4: Çevir butonu
		if (frm.doc.body) {
			frm.add_custom_button(__("Türkçe'ye Çevir"), () => {
				frappe.call({
					method: "tradehub_core.api.translation.get_review_translation",
					args: { review: frm.doc.name, target_lang: "tr" },
					callback: (r) => {
						if (r && r.message) {
							const t = r.message;
							frappe.msgprint({
								title: __("Çeviri (kaynak: {0})", [t.source_lang]),
								message: `<b>${t.translated_title || ""}</b><br><br>${t.translated_body || ""}<br><br><small>Çevirmen: ${t.translator}${t.cached ? " (cache)" : ""}</small>`,
								indicator: "blue",
							});
						}
					},
				});
			}, __("Faz 4"));
		}

		// Faz 4: Timeline güncelleme butonu (sahibi veya admin)
		if (frm.doc.reviewer_user === frappe.session.user || is_admin) {
			frm.add_custom_button(__("Timeline Güncellemesi Ekle"), () => {
				frappe.prompt(
					[
						{ fieldtype: "Select", fieldname: "stage",
							label: __("Aşama"), reqd: 1,
							options: "\nInitial\n30-day\n90-day\nLong-term",
							description: __("Boş bırakırsanız otomatik tespit edilir") },
						{ fieldtype: "Int", fieldname: "rating",
							label: __("Yeni Puan (opsiyonel, 1-5)") },
						{ fieldtype: "Small Text", fieldname: "body",
							label: __("Güncelleme Metni"), reqd: 1 },
					],
					(v) => {
						frappe.call({
							method: "tradehub_core.api.timeline.submit_review_update",
							args: { review: frm.doc.name, stage: v.stage,
								rating: v.rating, body: v.body },
							callback: (r) => {
								if (r && r.message && r.message.success) {
									frappe.show_alert(__("Güncelleme eklendi: {0}", [r.message.stage]));
									frm.reload_doc();
								}
							},
						});
					},
					__("Timeline Güncellemesi"), __("Ekle")
				);
			}, __("Faz 4"));
		}

		// Faz 3: Reviewer Reputation badge
		if (frm.doc.reviewer_user) {
			frappe.db.get_value(
				"Reviewer Reputation",
				frm.doc.reviewer_user,
				["score", "tier"]
			).then((r) => {
				if (r && r.message && r.message.tier) {
					const tier = r.message.tier;
					const score = r.message.score || 0;
					const tier_color = {
						"Newcomer": "grey",
						"Trusted": "blue",
						"Top Contributor": "green",
						"Verified Pro": "purple"
					}[tier] || "grey";
					frm.dashboard.add_indicator(
						__("Reviewer: {0} ({1})", [tier, score]),
						tier_color
					);
				}
			});
		}
	},
});


// ──────────────────────────────────────────────────────────────────────────
// List View: bulk moderation actions
// ──────────────────────────────────────────────────────────────────────────
frappe.listview_settings = frappe.listview_settings || {};
frappe.listview_settings["Listing Review"] = {
	add_fields: ["status", "abuse_report_count", "helpful_count"],
	get_indicator(doc) {
		const map = {
			Pending: ["Beklemede", "orange", "status,=,Pending"],
			Approved: ["Onaylandı", "green", "status,=,Approved"],
			Rejected: ["Reddedildi", "red", "status,=,Rejected"],
			Hidden: ["Gizli", "grey", "status,=,Hidden"],
		};
		return map[doc.status];
	},
	onload(listview) {
		// Cascade-aware delete (Frappe link guard'ı atlatır)
		listview.page.add_action_item(__("Cascade Sil (Risk + Oy + İhbar)"), () => {
			const items = listview.get_checked_items();
			if (!items.length) return frappe.msgprint(__("Önce kayıt seçin"));
			frappe.confirm(
				__("{0} yorum ve bağlı tüm kayıtları kalıcı olarak silinecek. Devam edilsin mi?", [items.length]),
				() => {
					const promises = items.map((i) =>
						frappe.call({
							method: "tradehub_core.api.review.admin_delete_listing_review",
							args: { name: i.name },
						})
					);
					Promise.all(promises).then(() => {
						listview.refresh();
						frappe.show_alert(__("{0} kayıt silindi", [items.length]));
					});
				}
			);
		});

		listview.page.add_action_item(__("Toplu Onayla"), () => {
			const items = listview.get_checked_items();
			if (!items.length) return frappe.msgprint(__("Önce kayıt seçin"));
			frappe.call({
				method: "tradehub_core.api.review.admin_bulk_moderate",
				args: {
					names: JSON.stringify(items.map((i) => i.name)),
					action: "approve",
				},
				callback: () => {
					listview.refresh();
					frappe.show_alert(__("Toplu onay tamamlandı"));
				},
			});
		});

		listview.page.add_action_item(__("Toplu Gizle"), () => {
			const items = listview.get_checked_items();
			if (!items.length) return frappe.msgprint(__("Önce kayıt seçin"));
			frappe.call({
				method: "tradehub_core.api.review.admin_bulk_moderate",
				args: {
					names: JSON.stringify(items.map((i) => i.name)),
					action: "hide",
				},
				callback: () => {
					listview.refresh();
					frappe.show_alert(__("Toplu gizleme tamamlandı"));
				},
			});
		});

		listview.page.add_action_item(__("Toplu Reddet"), () => {
			const items = listview.get_checked_items();
			if (!items.length) return frappe.msgprint(__("Önce kayıt seçin"));
			frappe.prompt(
				[{ fieldtype: "Small Text", fieldname: "reason", label: __("Red Nedeni"), reqd: 1 }],
				(values) => {
					frappe.call({
						method: "tradehub_core.api.review.admin_bulk_moderate",
						args: {
							names: JSON.stringify(items.map((i) => i.name)),
							action: "reject",
							reason: values.reason,
						},
						callback: () => {
							listview.refresh();
							frappe.show_alert(__("Toplu reddetme tamamlandı"));
						},
					});
				},
				__("Yorumları Reddet"),
				__("Reddet")
			);
		});
	},
};

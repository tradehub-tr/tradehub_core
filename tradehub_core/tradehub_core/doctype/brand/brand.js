frappe.ui.form.on('Brand', {
    refresh: function (frm) {
        const isApprover = frappe.user.has_role('System Manager') ||
                           frappe.user.has_role('Marketplace Admin');

        frm.dashboard.clear_headline();
        if (frm.doc.status === 'Pending Approval') {
            frm.dashboard.set_headline(
                __('Bu marka admin onayı bekliyor.'),
                'orange'
            );
        } else if (frm.doc.status === 'Rejected') {
            frm.dashboard.set_headline(
                __('Bu marka reddedildi: {0}', [frm.doc.rejection_reason || '-']),
                'red'
            );
        } else if (frm.doc.status === 'Approved') {
            frm.dashboard.set_headline(__('Onaylı marka.'), 'green');
        }

        if (isApprover && !frm.is_new() && frm.doc.status === 'Pending Approval') {
            frm.add_custom_button(__('Onayla'), function () {
                frappe.confirm(__('Bu markayı onaylamak istediğinize emin misiniz?'), function () {
                    frappe.call({
                        method: 'tradehub_core.api.brand.approve',
                        args: { name: frm.doc.name },
                        freeze: true,
                        freeze_message: __('Onaylanıyor...'),
                        callback: function (r) {
                            if (!r.exc) {
                                frappe.show_alert({ message: __('Marka onaylandı.'), indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                });
            }, __('Onay Akışı')).addClass('btn-primary');

            frm.add_custom_button(__('Reddet'), function () {
                frappe.prompt(
                    [{
                        fieldname: 'reason',
                        fieldtype: 'Small Text',
                        label: __('Ret Gerekçesi'),
                        reqd: 1,
                    }],
                    function (values) {
                        frappe.call({
                            method: 'tradehub_core.api.brand.reject',
                            args: { name: frm.doc.name, reason: values.reason },
                            freeze: true,
                            freeze_message: __('Reddediliyor...'),
                            callback: function (r) {
                                if (!r.exc) {
                                    frappe.show_alert({ message: __('Marka reddedildi.'), indicator: 'red' });
                                    frm.reload_doc();
                                }
                            }
                        });
                    },
                    __('Markayı Reddet'),
                    __('Reddet')
                );
            }, __('Onay Akışı'));
        }

        if (!isApprover) {
            ['status', 'suggested_by', 'reviewed_by', 'reviewed_at', 'rejection_reason']
                .forEach(f => frm.set_df_property(f, 'read_only', 1));
        }
    }
});

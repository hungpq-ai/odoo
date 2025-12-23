from odoo import api, models, _
from odoo.exceptions import AccessError


class IrRule(models.Model):
    _inherit = "ir.rule"

    def _make_access_error(self, operation, records):
        """Override to provide simple Vietnamese access error messages."""
        self = self.with_context(self.env.user.context_get())

        operations = {
            'read': _("xem"),
            'write': _("chỉnh sửa"),
            'create': _("tạo"),
            'unlink': _("xóa"),
        }

        msg = _(
            "Bạn không có quyền %(operation)s dữ liệu này.\n\n"
            "Vui lòng liên hệ quản trị viên nếu bạn cần truy cập.",
            operation=operations[operation]
        )

        return AccessError(msg)

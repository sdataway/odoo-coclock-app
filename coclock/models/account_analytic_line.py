from odoo import models, fields

class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    coclock_instance_id = fields.Char(string="Coclock Instance ID", help="ID of the Coclock Instance")
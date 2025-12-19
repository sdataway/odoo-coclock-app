from datetime import datetime
import logging

from odoo import http, tools, fields
from odoo.http import request, Response
from odoo.exceptions import AccessDenied, UserError, ValidationError
from odoo.tests import get_db_name
import xmlrpc.client

_logger = logging.getLogger(__name__)

class PartnerController(http.Controller):

    @http.route('/api/tasks', auth='none', methods=['GET'], type='json')
    def get_partners(self, **kwargs):
        try:
            # Get the API key from the Authorization header
            api_key = request.httprequest.headers.get('Authorization')
            if not api_key:
                _logger.warning("DOOTIX DEBUG %r", "No API key provided")
                return {'status': 'error', 'message': "No API key provided", 'code': 401}

            user_id = request.env["res.users.apikeys"]._check_credentials(
                scope='rpc', key=api_key
            )

            if not user_id:
                _logger.warning("DOOTIX DEBUG %r", "API key problem")
                return {'status': 'error', 'message': "API key problem", 'code': 403}
            
            # Convert int -> res.users record
            user = request.env['res.users'].sudo().browse(user_id)
            
            # Defensive: ensure record exists
            if not user.exists():
                return {'status': 'error', 'message': "API User not found", 'code': 404}

            company_id = user.company_id.id  # numeric company ID

            # Fetching all tasks
            tasks = request.env['project.task'].sudo().search([("company_id", "=", company_id)])
            data = []
            for task in tasks:
                if task.project_id:
                    task_description = tools.html2plaintext(task.description or "")
                    project_description = tools.html2plaintext(
                        task.project_id.description or "") if task.project_id else None

                    partner = task.project_id.partner_id

                    client_object = None
                    if partner:
                        if partner.is_company:
                            company_name = partner.name
                            company_id = partner.id

                            client_object = {
                                'odoo_id': None,
                                'client_name': None,
                                'odoo_company_id': company_id,
                                'company_name': company_name,
                            }
                        else:
                            client_name = partner.name

                            # Retrieve the company associated with the contact
                            company = partner.parent_id

                            client_object = {
                                'odoo_id': partner.id if partner else None,
                                'client_name': client_name,
                                'odoo_company_id': company.id if company else None,
                                'company_name': company.name if company else None,
                            }

                    data.append({
                        'odoo_id': task.id,
                        'name': task.name,
                        'description': task_description,
                        'status': task.state,
                        'allocated_time': getattr(task, 'allocated_hours', 0),

                        # Adding Project Information
                        'project': {
                            'odoo_id': task.project_id.id if task.project_id else None,
                            'name': task.project_id.name if task.project_id else None,
                            'description': project_description,
                        },
                        'client': client_object,
                    })
            return {'status': 'success', 'tasks': data, 'code': 200}
        except AccessDenied as e:
            _logger.warning("DOOTIX DEBUG %r", str(e))
            return {'status': 'error', 'message': str(e), 'code': 403}
        except Exception as e:
            _logger.warning("DOOTIX DEBUG %r", str(e))
            return {'status': 'error', 'message': str(e), 'code': 500}

    @http.route('/api/timesheets', auth='none', methods=['POST'], type='json')
    def create_timesheets(self, **kwargs):
        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        database = get_db_name()

        # Extract the 'name' parameter from the JSON payload
        data = request.httprequest.get_json()
        # Obtain values from your request body
        timesheets = data.get('timesheets')
        if not timesheets:
            _logger.warning("DOOTIX DEBUG %r", "Missing parameter: timesheets")
            return {'status': 'error', 'message': "Missing parameter: timesheets", 'code': 404}

        try:
            # Get the API key from the Authorization header
            api_key = request.httprequest.headers.get('Authorization')
            if not api_key:
                _logger.warning("DOOTIX DEBUG %r", "No API key provided")
                return {'status': 'error', 'message': "No API key provided", 'code': 401}

            user_id = request.env["res.users.apikeys"]._check_credentials(
                scope='rpc', key=api_key
            )

            if not user_id:
                _logger.warning("DOOTIX DEBUG %r", "API key problem")
                return {'status': 'error', 'message': "API key problem", 'code': 403}

            common = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(base_url))

            for timesheet in timesheets:
                email = timesheet.get('employee').get('email')
                coclock_instance_id = timesheet.get('coclock_instance_id')
                description = timesheet.get('description')
                duration = timesheet.get('duration') / 60
                project_id = timesheet.get('project_id')
                task_id = timesheet.get('task_id')
                date_obj = datetime.strptime(timesheet.get('start_time'), "%Y-%m-%d")

                # Search for the employee using their email
                employee = request.env['hr.employee'].sudo().search([('work_email', '=', email), ('active', '=', True)], limit=1)

                # Check if employee exists and is active
                if not employee:
                    _logger.warning("DOOTIX DEBUG %r", "No employee found with the given email.")
                    return {'status': 'error', 'message': "No employee found with the given email, please create the employee in Odoo before attempting a synchronisation", 'code': 404}
                               
                account_analytic_line = request.env['account.analytic.line'].sudo().search([('coclock_instance_id', '=', coclock_instance_id)],
                                                                    limit=1)
                if not account_analytic_line:
                    # Create the timesheet entry
                    timesheet = common.execute_kw(database, user_id, api_key, 'account.analytic.line', 'create',
                                                  [{
                                                      'name': description,
                                                      'employee_id': employee.id,
                                                      'date': date_obj,
                                                      'unit_amount': duration,
                                                      'project_id': project_id,
                                                      'task_id': task_id,
                                                      'coclock_instance_id': coclock_instance_id,
                                                  }])
                else:
                    # Update the timesheet entry
                    timesheet_update = common.execute_kw(database, user_id, api_key, 'account.analytic.line', 'write',
                                                  [[account_analytic_line.id],  # The ID of the timesheet to update
                                                   {
                                                       'name': description,
                                                       'employee_id': employee.id,
                                                       'date': date_obj,
                                                       'unit_amount': duration,
                                                       'project_id': project_id,
                                                       'task_id': task_id,
                                                       'coclock_instance_id': coclock_instance_id,
                                                   }])

                    timesheet = account_analytic_line.id

            return {'status': 'success', 'timesheets': timesheet, 'code': 200}
        except AccessDenied as e:
            _logger.warning("DOOTIX DEBUG %r", str(e))
            return {'status': 'error', 'message': str(e), 'code': 403}
        except Exception as e:
            _logger.warning("DOOTIX DEBUG %r", str(e))
            return {'status': 'error', 'message': str(e), 'code': 500}

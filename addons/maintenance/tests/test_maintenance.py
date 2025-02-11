# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import time

from odoo.tests.common import TransactionCase

class TestEquipment(TransactionCase):
    """ Test used to check that when doing equipment/maintenance_request/equipment_category creation."""

    def setUp(self):
        super(TestEquipment, self).setUp()
        self.equipment = self.env['maintenance.equipment']
        self.maintenance_request = self.env['maintenance.request']
        self.res_users = self.env['res.users']
        self.maintenance_team = self.env['maintenance.team']
        self.main_company = self.env.ref('base.main_company')
        res_user = self.env.ref('base.group_user')
        res_manager = self.env.ref('maintenance.group_equipment_manager')

        self.user = self.res_users.create(dict(
            name="Normal User/Employee",
            company_id=self.main_company.id,
            login="emp",
            email="empuser@yourcompany.example.com",
            groups_id=[(6, 0, [res_user.id])]
        ))

        self.manager = self.res_users.create(dict(
            name="Equipment Manager",
            company_id=self.main_company.id,
            login="hm",
            email="eqmanager@yourcompany.example.com",
            groups_id=[(6, 0, [res_manager.id])]
        ))

        self.equipment_monitor = self.env['maintenance.equipment.category'].create({
            'name': 'Monitors - Test',
        })

    def test_10_equipment_request_category(self):

        # Create a new equipment
        equipment_01 = self.equipment.with_user(self.manager).create({
            'name': 'Samsung Monitor "15',
            'category_id': self.equipment_monitor.id,
            'technician_user_id': self.ref('base.user_root'),
            'owner_user_id': self.user.id,
            'assign_date': time.strftime('%Y-%m-%d'),
            'serial_no': 'MT/127/18291015',
            'model': 'NP355E5X',
            'color': 3,
        })

        # Check that equipment is created or not
        assert equipment_01, "Equipment not created"

        # Create new maintenance request
        maintenance_request_01 = self.maintenance_request.with_user(self.user).create({
            'name': 'Resolution is bad',
            'user_id': self.user.id,
            'owner_user_id': self.user.id,
            'equipment_id': equipment_01.id,
            'color': 7,
            'stage_id': self.ref('maintenance.stage_0'),
            'maintenance_team_id': self.ref('maintenance.equipment_team_maintenance')
        })

        # I check that maintenance_request is created or not
        assert maintenance_request_01, "Maintenance Request not created"

        # I check that Initially maintenance request is in the "New Request" stage
        self.assertEqual(maintenance_request_01.stage_id.id, self.ref('maintenance.stage_0'))

        # I check that change the maintenance_request stage on click statusbar
        maintenance_request_01.with_user(self.user).write({'stage_id': self.ref('maintenance.stage_1')})

        # I check that maintenance request is in the "In Progress" stage
        self.assertEqual(maintenance_request_01.stage_id.id, self.ref('maintenance.stage_1'))

    def test_forever_maintenance_repeat_type(self):
        """
        Test that a maintenance request with repeat_type = forever will be duplicated when it
        is moved to a 'done' stage, and the new request will be placed in the first stage.
        """
        maintenance_request = self.env['maintenance.request'].create({
            'name': 'Test forever maintenance',
            'repeat_type': 'forever',
            'maintenance_type': 'preventive',
            'recurring_maintenance': True,
        })
        done_maintenance_stage = self.env['maintenance.stage'].create({
            'name': 'Test Done',
            'done': True,
        })
        maintenance_stages = self.env['maintenance.stage'].search([])
        maintenance_request.with_context(default_stage_id=maintenance_stages[1].id).stage_id = done_maintenance_stage
        new_maintenance = self.env['maintenance.request'].search([('name', '=', 'Test forever maintenance'), ('stage_id', '=', maintenance_stages[0].id)])
        self.assertTrue(new_maintenance)

    def test_update_multiple_maintenance_request_record(self):
        """
        Test that multiple records of the model 'maintenance.request' can be written simultaneously.
        """
        maintenance_requests = self.env['maintenance.request'].create([
            {
                'name': 'm_1',
                'maintenance_type': 'preventive',
                'kanban_state': 'normal',
            },
            {
                'name': 'm_2',
                'maintenance_type': 'preventive',
                'kanban_state': 'normal',
            },
        ])
        maintenance_requests.write({'kanban_state': 'blocked', 'stage_id': self.ref('maintenance.stage_0')})
        self.assertRecordValues(maintenance_requests, [
            {'kanban_state': 'blocked', 'stage_id': self.ref('maintenance.stage_0')},
            {'kanban_state': 'blocked', 'stage_id': self.ref('maintenance.stage_0')},
        ])

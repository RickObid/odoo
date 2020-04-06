# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime
from dateutil.relativedelta import relativedelta
from unittest.mock import patch

from odoo import fields
from odoo.addons.crm.tests.common import TestLeadConvertCommon
from odoo.tests.common import tagged


@tagged('lead_assign')
class TestLeadAssign(TestLeadConvertCommon):
    """ Test lead assignment feature added in saas-13.5. """

    @classmethod
    def setUpClass(cls):
        super(TestLeadAssign, cls).setUpClass()
        cls._switch_to_multi_membership()
        cls._switch_to_auto_assign()

        # don't mess with existing teams, deactivate them to make tests repeatable
        cls.sales_teams = cls.sales_team_1 + cls.sales_team_convert
        cls.members = cls.sales_team_1_m1 | cls.sales_team_1_m2 | cls.sales_team_1_m3 | cls.sales_team_convert_m1 | cls.sales_team_convert_m2
        cls.env['crm.team'].search([('id', 'not in', cls.sales_teams.ids)]).write({'active': False})

        # don't mess with existing leads, deactivate those assigned to users used here to make tests repeatable
        cls.env['crm.lead'].search(['|', ('team_id', '=', False), ('user_id', 'in', cls.sales_teams.member_ids.ids)]).write({'active': False})
        cls.bundle_size = 5
        cls.env['ir.config_parameter'].set_param('crm.assignment.bundle', '%s' % cls.bundle_size)
        cls.env['ir.config_parameter'].set_param('crm.assignment.delay', '0')

    def assertInitialData(self):
        self.assertEqual(self.sales_team_1.assignment_max, 75)
        self.assertEqual(self.sales_team_convert.assignment_max, 90)

        # ensure domains
        self.assertEqual(self.sales_team_1.assignment_domain, False)
        self.assertEqual(self.sales_team_1_m1.assignment_domain, False)
        self.assertEqual(self.sales_team_1_m2.assignment_domain, "[('probability', '>=', 10)]")
        self.assertEqual(self.sales_team_1_m3.assignment_domain, "[('probability', '>=', 20)]")

        self.assertEqual(self.sales_team_convert.assignment_domain, "[('priority', 'in', ['1', '2', '3'])]")
        self.assertEqual(self.sales_team_convert_m1.assignment_domain, "[('priority', 'in', ['2', '3'])]")
        self.assertEqual(self.sales_team_convert_m2.assignment_domain, False)

        # start afresh
        self.assertEqual(self.sales_team_1_m1.lead_month_count, 0)
        self.assertEqual(self.sales_team_1_m2.lead_month_count, 0)
        self.assertEqual(self.sales_team_1_m3.lead_month_count, 0)
        self.assertEqual(self.sales_team_convert_m1.lead_month_count, 0)
        self.assertEqual(self.sales_team_convert_m2.lead_month_count, 0)

    def test_assign_configuration(self):
        now_patch = datetime(2020, 11, 2, 10, 0, 0)

        with patch.object(fields.Datetime, 'now', return_value=now_patch):
            config = self.env['res.config.settings'].create({
                'crm_use_auto_assignment': True,
                'crm_auto_assignment_action': 'auto',
                'crm_auto_assignment_interval_number': 19,
                'crm_auto_assignment_interval_type': 'hours'
            })
            config._onchange_crm_auto_assignment_run_datetime()
            config.execute()
            self.assertTrue(self.assign_cron.active)
            self.assertEqual(self.assign_cron.nextcall, datetime(2020, 11, 2, 10, 0, 0) + relativedelta(hours=19))

            config.write({
                'crm_auto_assignment_interval_number': 2,
                'crm_auto_assignment_interval_type': 'days'
            })
            config._onchange_crm_auto_assignment_run_datetime()
            config.execute()
            self.assertTrue(self.assign_cron.active)
            self.assertEqual(self.assign_cron.nextcall, datetime(2020, 11, 2, 10, 0, 0) + relativedelta(days=2))

            config.write({
                'crm_auto_assignment_run_datetime': fields.Datetime.to_string(datetime(2020, 11, 1, 10, 0, 0)),
            })
            config.execute()
            self.assertTrue(self.assign_cron.active)
            self.assertEqual(self.assign_cron.nextcall, datetime(2020, 11, 1, 10, 0, 0))

            config.write({
                'crm_auto_assignment_action': 'manual',
            })
            config.execute()
            self.assertFalse(self.assign_cron.active)
            self.assertEqual(self.assign_cron.nextcall, datetime(2020, 11, 1, 10, 0, 0))

            config.write({
                'crm_use_auto_assignment': False,
                'crm_auto_assignment_action': 'auto',
            })
            config.execute()
            self.assertFalse(self.assign_cron.active)
            self.assertEqual(self.assign_cron.nextcall, datetime(2020, 11, 1, 10, 0, 0))

    def test_crm_team_assign_duplicates(self):
        leads = self._create_leads_batch(
            lead_type='lead',
            user_ids=[False],
            partner_ids=[self.contact_1.id, self.contact_2.id, False, False, False],
            count=50
        )
        self.assertInitialData()

        # assign probability to leads (bypass auto probability as purpose is not to test pls)
        leads = self.env['crm.lead'].search([('id', 'in', leads.ids)])  # ensure order
        for idx in range(0, 5):
            sliced_leads = leads[idx:len(leads):5]
            for lead in sliced_leads:
                lead.probability = (idx + 1) * 10 * ((int(lead.priority) + 1) / 2)

        with self.with_user('user_sales_manager'):
            with self.assertQueryCount(user_sales_manager=505):  # crm only: 505
                self.env['crm.team'].browse(self.sales_teams.ids)._action_assign_leads(work_days=2)

        self.members.invalidate_cache(fnames=['lead_month_count'])
        self.assertMemberAssign(self.sales_team_1_m1, 3)  # 45 max on 2 days
        self.assertMemberAssign(self.sales_team_1_m2, 1)  # 15 max on 2 days
        self.assertMemberAssign(self.sales_team_1_m3, 1)  # 15 max on 2 days
        self.assertMemberAssign(self.sales_team_convert_m1, 2)  # 30 max on 15
        self.assertMemberAssign(self.sales_team_convert_m2, 4)  # 60 max on 15

        # deduplicate should have removed all duplicated linked to contact_1 / contact_2
        new_assigned_leads_wpartner = self.env['crm.lead'].search([
            ('partner_id', 'in', (self.contact_1 | self.contact_2).ids),
            ('id', 'in', leads.ids)
        ])
        self.assertEqual(len(new_assigned_leads_wpartner), 2)

    def test_crm_team_assign_no_duplicates(self):
        leads = self._create_leads_batch(
            lead_type='lead',
            user_ids=[False],
            partner_ids=[False],
            count=50
        )
        self.assertInitialData()

        # assign probability to leads (bypass auto probability as purpose is not to test pls)
        leads = self.env['crm.lead'].search([('id', 'in', leads.ids)])  # ensure order
        for idx in range(0, 5):
            sliced_leads = leads[idx:len(leads):5]
            for lead in sliced_leads:
                lead.probability = (idx + 1) * 10 * ((int(lead.priority) + 1) / 2)

        with self.with_user('user_sales_manager'):
            with self.assertQueryCount(user_sales_manager=319):  # crm only: 319
                self.env['crm.team'].browse(self.sales_teams.ids)._action_assign_leads(work_days=2)

        self.members.invalidate_cache(fnames=['lead_month_count'])
        self.assertMemberAssign(self.sales_team_1_m1, 3)  # 45 max on 2 days
        self.assertMemberAssign(self.sales_team_1_m2, 1)  # 15 max on 2 days
        self.assertMemberAssign(self.sales_team_1_m3, 1)  # 15 max on 2 days
        self.assertMemberAssign(self.sales_team_convert_m1, 2)  # 30 max on 15
        self.assertMemberAssign(self.sales_team_convert_m2, 4)  # 60 max on 15

    def test_crm_team_assign_populated(self):
        """ Test assignment on a more high volume oriented test set in order to
        have more insights on query counts. """
        # create leads enough to have interesting counters
        _lead_count, _email_dup_count, _partner_count = 500, 50, 150
        leads = self._create_leads_batch(
            lead_type='lead',
            user_ids=[False],
            partner_count=_partner_count,
            country_ids=[self.env.ref('base.be').id, self.env.ref('base.fr').id, False],
            count=_lead_count,
            email_dup_count=_email_dup_count)
        self.assertInitialData()
        # assign for one month, aka a lot
        self.env.ref('crm.ir_cron_crm_lead_assign').write({'interval_type': 'days', 'interval_number': 30})
        self.env['ir.config_parameter'].set_param('crm.assignment.bundle', '20')
        # create a third team
        sales_team_3 = self.env['crm.team'].create({
            'name': 'Sales Team 3',
            'sequence': 15,
            'alias_name': False,
            'use_leads': True,
            'use_opportunities': True,
            'company_id': False,
            'user_id': False,
            'assignment_domain': [('country_id', '!=', False)],
        })
        sales_team_3_m1 = self.env['crm.team.member'].create({
            'user_id': self.user_sales_manager.id,
            'crm_team_id': sales_team_3.id,
            'assignment_max': 60,
            'assignment_domain': False,
        })
        sales_team_3_m2 = self.env['crm.team.member'].create({
            'user_id': self.user_sales_leads.id,
            'crm_team_id': sales_team_3.id,
            'assignment_max': 60,
            'assignment_domain': False,
        })
        sales_team_3_m3 = self.env['crm.team.member'].create({
            'user_id': self.user_sales_salesman.id,
            'crm_team_id': sales_team_3.id,
            'assignment_max': 15,
            'assignment_domain': [('probability', '>=', 10)],
        })
        sales_teams = self.sales_teams | sales_team_3
        self.assertEqual(sum(team.assignment_max for team in sales_teams), 300)
        self.assertEqual(len(leads), 550)

        # assign probability to leads (bypass auto probability as purpose is not to test pls)
        leads = self.env['crm.lead'].search([('id', 'in', leads.ids)])  # ensure order
        for idx in range(0, 5):
            sliced_leads = leads[idx:len(leads):5]
            for lead in sliced_leads:
                lead.probability = (idx + 1) * 10 * ((int(lead.priority) + 1) / 2)

        with self.with_user('user_sales_manager'):
            with self.assertQueryCount(user_sales_manager=6199):  # crm only: 6199
                self.env['crm.team'].browse(sales_teams.ids)._action_assign_leads(work_days=30)

        self.members.invalidate_cache(fnames=['lead_month_count'])
        self.assertMemberAssign(self.sales_team_1_m1, 45)  # 45 max on one month
        self.assertMemberAssign(self.sales_team_1_m2, 15)  # 15 max on one month
        self.assertMemberAssign(self.sales_team_1_m3, 15)  # 15 max on one month
        self.assertMemberAssign(self.sales_team_convert_m1, 30)  # 30 max on one month
        self.assertMemberAssign(self.sales_team_convert_m2, 60)  # 60 max on one month
        self.assertMemberAssign(sales_team_3_m1, 60)  # 60 max on one month
        self.assertMemberAssign(sales_team_3_m2, 60)  # 60 max on one month
        self.assertMemberAssign(sales_team_3_m3, 15)  # 15 max on one month

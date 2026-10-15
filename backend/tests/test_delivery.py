"""Contract and fail-closed delivery tests; all facts are synthetic."""
import unittest
from pydantic import ValidationError
from test_rules import rule
from routing_guides.rules import Expression
from routing_guides.check_catalog import needs_check_mapping, check_status
from routing_guides.rule_catalog import RULE_TYPES
from routing_guides.delivery import DeliveryRequest, subjects_for, selected_placements, validate_selection
from routing_guides.evaluator import evaluate_rule, evaluate_release


def mapped(**changes):
    data = dict(schema_version='1.2', assertion=None,
        rule_type={'id':'carton.measurement','version':1},
        placements=[{'workflow':'mobile_packing','area':'carton_selection','enabled':True,'behavior':'block'}],
        standard_check={'check_id':'package_measurement_limit','version':1,
                        'parameters':{'measurement':'weight','comparison':'lte','threshold':50.0,'unit':'lb'}})
    data.update(changes)
    return rule(**data)


class DeliveryTests(unittest.TestCase):
    def test_type_placement_and_verification_contracts_are_enforced(self):
        for changes in [
            {'rule_type':{'id':'made.up','version':1}},
            {'rule_type':{'id':'carton.measurement','version':2}},
            {'rule_type':{'id':'carton.measurement','version':True}},
            {'rule_type':None},
            {'subject':'pallet'},
            {'consumption_points':['asn_generation']},
            {'operational_category':'electronic_documents_edi'},
            {'placements':[]},
            {'placements':[{'workflow':'mobile_packing','area':'asn','behavior':'display'}]},
            {'placements':[{'workflow':'mobile_packing','area':'carton_selection'}]*2},
            {'obligation':'recommended'},
            {'purpose':'general_guidance'},
            {'standard_check':{'check_id':'carton_sku_limit','version':1,'parameters':{'maximum_unique_skus':1}}},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                mapped(**changes)

    def test_unimplemented_checks_cannot_warn_or_block(self):
        for behavior in ('warn','block'):
            with self.subTest(behavior=behavior),self.assertRaises(ValidationError):
                mapped(rule_type={'id':'carton.po_mixing','version':1},
                       placements=[{'workflow':'mobile_packing','area':'carton_contents','behavior':behavior}],
                       standard_check={'check_id':'carton_po_limit','version':1,'parameters':{'maximum_unique_pos':1}})

    def test_disabled_placement_keeps_requirement_and_scenario_validation(self):
        spec=mapped(placements=[{'workflow':'mobile_packing','area':'carton_selection','enabled':False,'behavior':'block'}])
        request=DeliveryRequest(workflow='mobile_packing')
        self.assertFalse(selected_placements(spec,request)[0].enabled)
        self.assertEqual(evaluate_rule('r',spec,{'cartons':[{'weight':{'value':51,'unit':'lb'}}]})['outcome'],'fail')

    def test_block_warn_and_unknown_actions_are_per_subject(self):
        spec=mapped()
        subjects=subjects_for(spec,spec.placements[0],{'cartons':[
            {'id':'pass','weight':{'value':800,'unit':'oz'}},
            {'id':'fail','weight':{'value':51,'unit':'lb'}},
            {'id':'missing'},
        ]})
        self.assertEqual([s.action for s in subjects],['none','block','needs_information'])
        self.assertEqual([s.check_outcome for s in subjects],['pass','fail','cannot_determine'])
        warning=spec.placements[0].model_copy(update={'behavior':'warn'})
        self.assertEqual(subjects_for(spec,warning,{'cartons':[{'weight':{'value':51,'unit':'lb'}}]})[0].action,'warn')
        for snapshot in ({},{'cartons':[]},{'cartons':[None]},{'cartons':{}}):
            self.assertEqual(subjects_for(spec,spec.placements[0],snapshot)[0].action,'needs_information')

    def test_conditional_images_and_unknown_exceptions_remain_explicit(self):
        spec=mapped(rule_type={'id':'carton.label_placement','version':1},verification='human',
            consumption_points=['label_application'],
            placements=[{'workflow':'label_application','area':'carton_labels','behavior':'confirm'}],
            standard_check={'check_id':'label_placement','version':1,'parameters':{'required_checks':['no_seam_overlap']}},
            applicability=Expression(op='gt',path='height',value=7,unit='in'),
            evidence=[{'page':1,'quote':'Diagram','kind':'visual','region':[0.1,0.1,0.3,0.3]}])
        outcomes=subjects_for(spec,spec.placements[0],{'cartons':[{'height':{'value':8,'unit':'in'}},{'height':{'value':6,'unit':'in'}},{}]})
        self.assertEqual([s.action for s in outcomes],['confirm','none','needs_information'])
        self.assertEqual([s.applicability for s in outcomes],['applicable','not_applicable','unknown'])
        self.assertTrue(all(s.check_outcome is None for s in outcomes))
        with_exception=spec.model_copy(update={'exceptions':rule(exceptions=[{'description':'When approved'}]).exceptions})
        self.assertEqual(subjects_for(with_exception,spec.placements[0],{'cartons':[{'height':{'value':8,'unit':'in'}}]})[0].action,'needs_information')
        self.assertEqual(spec.evidence[0].region,[0.1,0.1,0.3,0.3])

    def test_instruction_only_types_can_be_reviewed_without_inventing_checks(self):
        spec=mapped(rule_type={'id':'pallet.wrapping','version':1},subject='pallet',verification='human',standard_check=None,
            consumption_points=['pallet_building'],placements=[{'workflow':'pallet_building','area':'wrapping','behavior':'confirm'}])
        self.assertFalse(needs_check_mapping(spec))
        self.assertEqual(check_status(spec).availability,'manual')
        self.assertEqual(subjects_for(spec,spec.placements[0],{'pallets':[{'id':'p1'}]})[0].action,'confirm')
        self.assertEqual(evaluate_rule('r',spec,{'pallets':[{}]})['outcome'],'cannot_determine')

    def test_catalog_defaults_and_legacy_routing_are_conservative(self):
        for entry in RULE_TYPES.values():
            self.assertTrue(all(p.behavior=='display' and p.enabled for p in entry.default_placements))
            self.assertTrue(all(any(p.workflow==a.workflow and p.area==a.area for a in entry.allowed_placements) for p in entry.default_placements))
        self.assertEqual(selected_placements(rule(),DeliveryRequest(workflow='mobile_packing')),[])
        for request in [DeliveryRequest(workflow='mobile_packing',area='invented'),
                        DeliveryRequest(workflow='mobile_packing',rule_type='invented'),
                        DeliveryRequest(workflow='mobile_packing',rule_type='asn.contents')]:
            with self.assertRaises(ValueError):validate_selection(request)
        validate_selection(DeliveryRequest(workflow='mobile_packing',area='carton_selection',rule_type='carton.measurement'))

    def test_general_guidance_is_reference_only(self):
        entry = RULE_TYPES['general.guidance']
        fields = dict(schema_version='1.2', purpose='general_guidance', subject='shipment',
            operational_category=entry.category, consumption_points=['supplier_management'],
            rule_type={'id':entry.id,'version':1}, placements=[p.model_dump() for p in entry.default_placements],
            standard_check=None, assertion=None, verification='human')
        spec = rule(**fields)
        self.assertFalse(needs_check_mapping(spec))
        result = evaluate_release([{'stable_id':'general','spec':spec.model_dump(mode='json')}], {})
        self.assertEqual(result['items'], [])
        self.assertEqual(result['guidance_count'], 1)
        for change in [dict(purpose='shipment_validation'), dict(verification='data'),
                       dict(assertion={'op':'exists','path':'id'}),
                       *[dict(placements=[{'workflow':'supplier_management','area':'general_guidance','behavior':b}]) for b in ('confirm','warn','block')]]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                rule(**{**fields, **change})

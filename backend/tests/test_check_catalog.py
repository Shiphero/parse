import unittest
from copy import deepcopy
from pydantic import ValidationError
from routing_guides.analysis_provider import strict_schema, SYSTEM, parsed_response, PROMPT_VERSION, ProviderFailure, extraction_schema
from routing_guides.check_catalog import CATALOG, check_status
from routing_guides.evaluator import evaluate_rule
from routing_guides.rules import Extraction, Expression
from test_rules import rule


def measurement(**parameters):
    return rule(schema_version='1.2', assertion=None, standard_check={
        'check_id':'package_measurement_limit', 'version':1,
        'parameters':{'measurement':'weight','comparison':'lte','threshold':50,'unit':'lb', **parameters}})


def fulfillment():
    return rule(schema_version='1.2', subject='order', assertion=None, standard_check={
        'check_id':'po_line_fulfillment', 'version':1,
        'parameters':{'required_percent':100,'quantity_basis':'packed','order_basis':'original_order'}})


class CheckCatalogTests(unittest.TestCase):
    def test_registry_is_typed_and_status_cannot_be_forged(self):
        original=fulfillment().model_dump(mode='json')
        for mutation in [
            {'check_id':'invented_check'}, {'version':2}, {'version':True}, {'availability':'implemented'},
            {'parameters':{'required_percent':101,'quantity_basis':'packed','order_basis':'original_order'}},
            {'parameters':{'required_percent':True,'quantity_basis':'packed','order_basis':'original_order'}},
            {'parameters':{'required_percent':100,'quantity_basis':'estimated','order_basis':'original_order'}},
            {'parameters':{'required_percent':100,'quantity_basis':'packed'}},
        ]:
            data=deepcopy(original); data['standard_check'].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                rule(**data)
        for changes in [{'schema_version':'1.1'},{'subject':'carton'},{'verification':'human'},
                        {'assertion':{'op':'eq','path':'fulfilled','value':True}}]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                rule(**{**original,**changes})
        with self.assertRaises(ValidationError):
            measurement(unit='cm')

    def test_measurement_uses_same_per_subject_evaluator_and_units(self):
        spec=measurement()
        result=evaluate_rule('r',spec,{'cartons':[
            {'id':'boundary','weight':{'value':800,'unit':'oz'}},
            {'id':'heavy','weight':{'value':51,'unit':'lb'}},
            {'id':'unknown'}, {'id':'unitless','weight':50}]})
        self.assertEqual([item['outcome'] for item in result['subjects']],
                         ['pass','fail','cannot_determine','cannot_determine'])
        self.assertEqual(result['outcome'],'fail')
        self.assertEqual(check_status(spec).availability,'implemented')

    def test_approval_or_extra_facts_cannot_implement_a_validator(self):
        spec=fulfillment()
        result=evaluate_rule('r',spec,{'shipment':{'fulfilled':True,'fulfillment_percent':100,
                                                'po_lines':[{'ordered':1,'packed':1}]}})
        self.assertEqual(result['outcome'],'cannot_determine')
        self.assertIn('not implemented',result['subjects'][0]['reason'])
        self.assertEqual(check_status(spec).availability,'not_implemented')
        scoped=spec.model_copy(update={'applicability':Expression(op='eq',path='shipment.mode',value='ltl')})
        self.assertEqual(evaluate_rule('r',scoped,{'shipment':{'mode':'parcel'}})['outcome'],'not_applicable')
        self.assertEqual(evaluate_rule('r',scoped,{'shipment':{}})['outcome'],'cannot_determine')

    def test_mapping_manual_and_external_checks_do_not_auto_pass(self):
        pending=rule(schema_version='1.2', verification='unresolved', assertion=None)
        self.assertEqual(check_status(pending).availability,'needs_mapping')
        self.assertEqual(evaluate_rule('r',pending,{'cartons':[{}]})['outcome'],'cannot_determine')
        for identifier,method,subject,parameters in [
            ('label_placement','human','carton',{'required_checks':['no_seam_overlap']}),
            ('document_confirmation','external_evidence','shipment',{'document_type':'packing_list','milestone':'before_dispatch'}),
            ('approval_confirmation','external_evidence','shipment',{'approving_authority':'Inbound Quality Senior Manager','approval_scope':'Floor-loaded or slip-sheet freight into Sortable FCs','milestone':'before_dispatch'}),
        ]:
            spec=rule(schema_version='1.2',verification=method,subject=subject,assertion=None,
                      standard_check={'check_id':identifier,'version':1,'parameters':parameters})
            self.assertEqual(evaluate_rule('r',spec,{'cartons':[{}],'shipment':{},'evidence':{'approved':True}})['outcome'],'cannot_determine')
        self.assertEqual(check_status(rule()).availability,'legacy')
        self.assertEqual(check_status(rule(purpose='general_guidance')).availability,'guidance')

    def test_shipment_approval_preserves_scope_and_requires_external_confirmation(self):
        spec=rule(schema_version='1.2', subject='shipment', verification='external_evidence', assertion=None,
            operational_category='transportation_scheduling', consumption_points=['transport_planning'],
            rule_type={'id':'transport.approval','version':1},
            placements=[{'workflow':'transport_planning','area':'shipment_approval','behavior':'display'}],
            applicability_text='Floor-loaded or slip-sheet freight into Sortable FCs; parcel shipments excluded.',
            applicability={'op':'ne','path':'shipment.mode','value':'parcel'},
            standard_check={'check_id':'approval_confirmation','version':1,'parameters':{
                'approving_authority':'Walmart Inbound Quality Senior Manager (Labeling@walmart.com)',
                'approval_scope':'Floor-loaded or slip-sheet freight into Sortable FCs',
                'milestone':'before_dispatch'}})
        self.assertEqual(check_status(spec).availability,'external')
        self.assertEqual(evaluate_rule('r',spec,{'shipment':{'mode':'parcel'}})['outcome'],'not_applicable')
        self.assertEqual(evaluate_rule('r',spec,{'shipment':{'mode':'ltl'},'evidence':{'approved':True}})['outcome'],'cannot_determine')
        original=spec.model_dump(mode='json')
        for field,value in [('approving_authority','   '),('approval_scope',''),('milestone','after_arrival')]:
            changed=deepcopy(original)
            changed['standard_check']['parameters'][field]=value
            with self.subTest(field=field),self.assertRaises(ValidationError):
                rule(**changed)
        with self.assertRaises(ValidationError):
            rule(**{**original,'verification':'data'})
        with self.assertRaises(ValidationError):
            rule(**{**original,'placements':[{'workflow':'transport_planning','area':'shipment_approval','behavior':'block'}]})

    def test_provider_schema_and_prompt_use_the_shared_catalog(self):
        schema=strict_schema(extraction_schema())
        self.assertEqual(schema['$defs']['RuleSpec']['properties']['schema_version']['const'],'1.2')
        def walk(node):
            if isinstance(node,dict):
                self.assertNotIn('oneOf',node); self.assertNotIn('discriminator',node)
                if node.get('type')=='object':
                    self.assertFalse(node['additionalProperties'])
                    self.assertEqual(set(node['required']),set(node['properties']))
                for value in node.values():walk(value)
            elif isinstance(node,list):
                for value in node:walk(value)
        walk(schema)
        for identifier in CATALOG:
            self.assertIn(identifier,SYSTEM)

    def test_legacy_provider_checkpoints_stay_readable_but_new_results_need_catalog_schema(self):
        raw=Extraction(rules=[rule()],coverage=[],warnings=[]).model_dump(mode='json')
        saved={'raw':raw,'model':'fixture','usage':{},'prompt_version':'routing-extraction-1.5'}
        self.assertEqual(parsed_response(saved).extraction.rules[0].schema_version,'1.1')
        with self.assertRaises(ProviderFailure):
            parsed_response({**saved,'prompt_version':PROMPT_VERSION})

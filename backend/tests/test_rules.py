import unittest
from types import SimpleNamespace
from fastapi import HTTPException
from pydantic import ValidationError
from routing_guides.rules import Expression, RuleSpec
from routing_guides.evaluator import expression, evaluate_rule, evaluate_release
from routing_guides.scenarios import normalize
from routing_guides.analysis_jobs import validate_evidence
from routing_guides.workflow_api import assemble_release


def rule(**changes):
    data = dict(operational_category='warehouse_operations',consumption_points=['mobile_packing'],purpose='shipment_validation',title='Carton weight', instruction='Keep carton weight at or below 50 lb.', subject='carton', obligation='required', verification='data', applicability_text='Every carton', assertion={'op':'lte','path':'weight','value':50,'unit':'lb'}, evidence=[{'page':1,'quote':'50 lb'}])
    data.update(changes)
    return RuleSpec.model_validate(data)


class EvaluationTests(unittest.TestCase):
    def result(self, weight):
        return evaluate_rule('r', rule(), {'cartons':[{'weight':weight}]})['outcome']

    def test_boundary_and_unit_conversion(self):
        self.assertEqual(self.result({'value':'800','unit':'oz'}), 'pass')
        self.assertEqual(self.result({'value':'800.0001','unit':'oz'}), 'fail')
        self.assertEqual(self.result({'value':'22.6796185','unit':'kg'}), 'pass')

    def test_unknown_units_missing_and_boolean_not_numbers(self):
        for data in (None, 50, {'value':50,'unit':'cm'}, {'value':True,'unit':'lb'}, {'value':'NaN','unit':'lb'}):
            self.assertEqual(self.result(data), 'cannot_determine')

    def test_unknown_logic(self):
        yes={'op':'eq','path':'known','value':'yes'}
        missing={'op':'lt','path':'missing','value':10}
        self.assertEqual(expression(Expression(op='any',children=[yes,missing]),{'known':'yes'})[0], True)
        self.assertEqual(expression(Expression(op='all',children=[yes,missing]),{'known':'yes'})[0], None)
        self.assertEqual(expression(Expression(op='all',children=[yes,missing]),{'known':'no'})[0], False)

    def test_applicability_and_exceptions(self):
        r=rule(applicability={'op':'eq','path':'shipment.mode','value':'ltl'})
        self.assertEqual(evaluate_rule('r',r,{'cartons':[{}], 'shipment':{'mode':'parcel'}})['outcome'],'not_applicable')
        self.assertEqual(evaluate_rule('r',r,{'cartons':[{}]})['outcome'],'cannot_determine')
        r=rule(exceptions=[{'description':'Heavy goods','condition':None}])
        self.assertEqual(evaluate_rule('r',r,{'cartons':[{'weight':{'value':5,'unit':'lb'}}]})['outcome'],'cannot_determine')

    def test_no_containers_is_not_a_pass(self):
        self.assertEqual(evaluate_rule('r',rule(),{'cartons':[]})['outcome'],'cannot_determine')

    def test_grouping_unknown_and_advisory(self):
        e=Expression(op='unique_count',path='line_items.*.po',comparator='lte',value=1)
        self.assertEqual(expression(e,{'line_items':[{'po':'A'},{'po':'B'}]})[0],False)
        self.assertIsNone(expression(e,{'line_items':[{'po':'A'},{}]})[0])
        r=rule(obligation='recommended')
        self.assertEqual(evaluate_rule('r',r,{'cartons':[{'weight':{'value':60,'unit':'lb'}}]})['obligation'],'recommended')

    def test_human_check_cannot_pass(self):
        r=rule(verification='human', assertion=None)
        self.assertEqual(evaluate_rule('r',r,{'cartons':[{}]})['outcome'],'cannot_determine')

    def test_language_rejects_arbitrary_code(self):
        with self.assertRaises(ValidationError):
            Expression(op='python',path='eval(x)',value=1)
        with self.assertRaises(ValidationError):
            Expression(op='all',children=[])

    def test_rule_use_is_independent_of_verification_and_legacy_is_unclassified(self):
        data = rule().model_dump(mode='json')
        data.pop('purpose')
        legacy = RuleSpec.model_validate(data)
        self.assertEqual(legacy.purpose, 'unclassified')
        self.assertEqual(evaluate_rule('legacy', legacy, {'cartons': [{'weight': {'value': 1, 'unit': 'lb'}}]})['outcome'], 'cannot_determine')
        self.assertEqual(rule(purpose='general_guidance', verification='external_evidence').purpose, 'general_guidance')
        self.assertEqual(rule(purpose='shipment_validation', verification='external_evidence').purpose, 'shipment_validation')

    def test_guidance_is_excluded_from_shipment_counts_but_inspections_remain(self):
        specs = [rule(purpose='general_guidance', title='Onboarding'), rule(),
                 rule(verification='human', title='Label placement', assertion=None)]
        rules = [{'stable_id': str(i), 'spec': spec.model_dump(mode='json')} for i, spec in enumerate(specs)]
        result = evaluate_release(rules, {'cartons': [{'weight': {'value': 10, 'unit': 'lb'}}]})
        self.assertEqual(result['guidance_count'], 1)
        self.assertEqual([r['rule_id'] for r in result['items']], ['1', '2'])
        self.assertEqual(result['counts']['pass'], 1)
        self.assertEqual(result['counts']['cannot_determine'], 1)
        self.assertEqual(sum(result['counts'].values()), 2)
        guidance_only = evaluate_release(rules[:1], {})
        self.assertEqual(guidance_only['items'], [])
        self.assertEqual(sum(guidance_only['counts'].values()), 0)
        self.assertEqual(guidance_only['guidance_count'], 1)


class MappingTests(unittest.TestCase):
    def test_nested_layout_preserved_no_weight_double_count(self):
        raw={'packing_layout':{'containers':[{'type':'Pallet','details':{'weight_in_oz':1600},'containers':[{'type':'Box','details':{'weight_in_oz':320,'height':12},'containers':[]}]}]}}
        normalized,warnings=normalize(raw)
        self.assertEqual(normalized['packing_layout'],raw['packing_layout'])
        self.assertEqual(len(normalized['pallets']),1)
        self.assertEqual(len(normalized['cartons']),1)
        self.assertEqual(normalized['cartons'][0]['height']['unit'],'in')
        self.assertNotIn('weight',normalized['shipment'])
        self.assertNotIn('destination',normalized['shipment'])

    def test_overrides_are_explicit_and_raw_preserved(self):
        raw={'schema_version':'1.0','shipment':{'mode':'ltl'}}
        normalized,_=normalize(raw,{'shipment':{'mode':'parcel'}})
        self.assertEqual(raw['shipment']['mode'],'ltl')
        self.assertEqual(normalized['shipment']['mode'],'parcel')

    def test_null_layout_remains_unknown(self):
        data,_=normalize({'data':{'wholesale_order':{'data':{'packing_layout':None}}}})
        self.assertNotIn('cartons',data)


class EvidenceAndReleaseTests(unittest.TestCase):
    def test_citation_must_exist(self):
        validate_evidence(rule(), {1:'Cartons: maximum 50 lb'})
        with self.assertRaises(ValueError):
            validate_evidence(rule(), {1:'Nothing here'})
        with self.assertRaises(ValueError):
            validate_evidence(rule(), {2:'50 lb'})

    def test_citation_typography_does_not_change_meaning(self):
        spec = rule(evidence=[{'page': 1, 'quote': '"Non-compliant" office shipments: 50 lb.'}])
        validate_evidence(spec, {1: '“Non-\ncompliant” ofﬁce shipments: 50 lb.'})
        for quote in ['"Non-compliant" office shipments: 60 lb.', 'Office shipments may weigh 50 lb.', '   ']:
            with self.subTest(quote=quote), self.assertRaises(ValueError):
                validate_evidence(rule(evidence=[{'page': 1, 'quote': quote}]), {1: '“Non-\ncompliant” ofﬁce shipments: 50 lb.'})

    def test_missing_rule_does_not_silently_disappear(self):
        run=SimpleNamespace(payload={'rules':[], 'coverage':[], 'pending_batches':[]})
        base=SimpleNamespace(payload={'rules':[{'stable_id':'old','spec':rule().model_dump()}]})
        with self.assertRaises(HTTPException):
            assemble_release(run,base,SimpleNamespace(decisions={}))
        self.assertEqual(len(assemble_release(run,base,SimpleNamespace(decisions={'old':'retain'}))),1)
        self.assertEqual(assemble_release(run,base,SimpleNamespace(decisions={'old':'retire'})),[])

    def test_unreviewed_or_incomplete_runs_cannot_publish(self):
        for payload in ({'rules':[{'status':'pending'}], 'coverage':[], 'pending_batches':[]}, {'rules':[], 'coverage':[{'outcome':'needs_review'}], 'pending_batches':[]}):
            with self.assertRaises(HTTPException):
                assemble_release(SimpleNamespace(payload=payload),None,SimpleNamespace(decisions={}))


if __name__ == '__main__':
    unittest.main()

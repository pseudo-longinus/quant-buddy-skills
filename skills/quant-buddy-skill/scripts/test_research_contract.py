import copy
import unittest
import tempfile
import os
from unittest import mock
import research_contract as rc
from research_contract import freeze, validate, audit, metadata

def oversold():
    return freeze({'task_id':'oversold-trace','user_messages':['近5个交易日涨停；距最近涨停日收盘回落≥5%；剔除科创创业北交与小票。','流通市值50亿，成交额2亿，今日涨跌幅>-3%。确认。'],
                  'selection_output':'池','conditions':[
                      {'id':'board','description':'剔除科创创业北交','spec':{'field':'asset','operator':'not_prefix','value':['SH688','SZ300','SZ301','BJ']},'formula_name':'主板','predicate':'板块(沪深主板)'},
                      {'id':'cap','description':'流通市值≥50亿','spec':{'field':'float_market_cap','operator':'gte','value':5000000000},'formula_name':'市值闸','predicate':'"流通市值">=5000000000'},
                      {'id':'depth','description':'最近涨停日收盘累计回落≥5%','spec':{'reference':'recent_limit_close','minimum':0.05,'input_fields':['close','limit_close']},'formula_name':'回落闸','predicate':'"收盘价"/"最近涨停日收盘"<=0.95'}]})

class ResearchContractTest(unittest.TestCase):
    def test_failed_draft_can_deliver_only_methodology_without_unblocking_calculation(self):
        with tempfile.TemporaryDirectory() as root,mock.patch.dict(os.environ,{'SESSION_WORKSPACE':root}):
            path=rc.contract_path('draft');path.parent.mkdir(parents=True);path.write_text('{"schema_version":"research_contract_draft","task_id":"draft"}')
            self.assertIsNone(rc.load_for_delivery('draft','unavailable','methodology'))
            with self.assertRaises(ValueError):rc.load('draft')
            with self.assertRaises(ValueError):rc.load_for_delivery('draft','complete','result')
    def test_confirmed_strict_threshold_cannot_be_frozen_as_inclusive(self):
        value={'task_id':'strict','user_messages':['确认'],'confirmation_messages':['当日涨跌幅 > -3%'],
               'require_confirmation_evidence':True,'conditions':[{'id':'today','description':'今日企稳',
               'source_quote':'当日涨跌幅 > -3%','spec':{'field':'return','operator':'gt','value':-0.03}}]}
        self.assertEqual(freeze(value)['conditions'][0]['spec']['operator'],'gt')
        value['conditions'][0]['spec']['operator']='gte'
        with self.assertRaisesRegex(ValueError,'OPERATOR_CHANGED'):freeze(value)
        value['conditions'][0]['source_quote']='当日涨跌幅 >= -3%'
        with self.assertRaisesRegex(ValueError,'SOURCE_QUOTE_INVALID'):freeze(value)
    def test_dynamic_benchmarks_and_semantic_positive_flow_are_not_numeric_source_errors(self):
        value={'task_id':'sources','user_messages':['放量突破 + 主力资金净流入；收盘 > 当日最低 × 1.01；上市<60日剔除'],
               'require_confirmation_evidence':True,'conditions':[
                 {'id':'breakout','description':'突破','source_quote':'放量突破','spec':{'field':'close','operator':'gt','benchmark':'60-day high'}},
                 {'id':'funds','description':'资金','source_quote':'主力资金净流入','spec':{'field':'fund','operator':'gt','value':0}},
                 {'id':'tail','description':'尾盘','source_quote':'收盘 > 当日最低 × 1.01','spec':{'field':'close-low','operator':'gt','value':1.01,'unit':'倍'}},
                 {'id':'age','description':'次新剔除','source_quote':'上市<60日剔除','source_transform':'exclude_complement','spec':{'field':'age','operator':'gte','value':60}}]}
        self.assertTrue(freeze(value)['contract_hash'])
        value['conditions'][1]['spec']['operator']='gte'
        with self.assertRaisesRegex(ValueError,'OPERATOR_CHANGED'):freeze(value)
    def test_natural_comparisons_and_combined_exclusion_unit_conversion(self):
        value={'task_id':'natural','user_messages':['PE低于15；股息率超过3%；流通市值低于50亿剔除'],
               'require_confirmation_evidence':True,'conditions':[
                 {'id':'pe','description':'低估值','source_quote':'PE低于15','spec':{'field':'pe','operator':'lt','value':15}},
                 {'id':'yield','description':'股息','source_quote':'股息率超过3%','spec':{'field':'yield','operator':'gt','value':0.03}},
                 {'id':'cap','description':'剔除小票','source_quote':'流通市值低于50亿剔除',
                  'source_transform':['exclude_complement','unit_conversion'],'source_scale':100000000,
                  'spec':{'field':'cap','operator':'gte','value':5000000000,'unit':'元'}}]}
        self.assertTrue(freeze(value)['contract_hash'])
        value['conditions'][1]['spec']['operator']='gte'
        with self.assertRaisesRegex(ValueError,'OPERATOR_CHANGED'):freeze(value)
    def test_exact_inline_fund_condition_is_applied_but_nearby_threshold_is_not(self):
        c=freeze({'task_id':'inline','user_messages':['主板，主力资金净流入'],'selection_output':'池',
                  'selection_predicate':'板块(沪深主板)*("净额">0)','conditions':[
                    {'id':'fund','description':'资金净额严格正值','spec':{'field':'fund','operator':'gt','value':0},'formula_name':'资金闸','predicate':'"净额">0'},
                    {'id':'board','description':'主板','spec':{'scope':'main'},'formula_name':'主板闸','predicate':'板块(沪深主板)'}]})
        self.assertEqual(rc.audit(c,formulas=['池=板块(沪深主板)*("净额">0)'],require_result_evidence=False)['issues'],[])
        self.assertEqual(rc.audit(c,formulas=['资金闸="净额">0','池=板块(沪深主板)*("净额">0)'],require_result_evidence=False)['issues'],[])
        errors=rc.audit(c,formulas=['池=板块(沪深主板)*("净额">0.1)'],require_result_evidence=False)['issues']
        self.assertIn('CONDITION_FORMULA_MISSING',{e['error'] for e in errors})
    def test_oversold_captured_missing_scope_and_replaced_baseline(self):
        c=oversold();formulas=['主板=板块(沪深主板)','回落闸="收盘价"/最大("收盘价",5)<=0.95','池="回落闸"']
        errors={x['error'] for x in audit(c,formulas=formulas)['issues']}
        self.assertTrue({'CONDITION_FORMULA_MISSING','CONDITION_FORMULA_REPLACED','CONDITION_NOT_APPLIED'}<=errors)
    def test_declared_missing_added_and_replaced_conditions_are_symmetric(self):
        c=oversold();applied=copy.deepcopy(c['conditions']);applied.pop(0);applied[0]['spec']['value']=1000000000
        applied.append({'id':'extra','spec':{}})
        self.assertEqual({x['error'] for x in audit(c,applied_conditions=applied,require_result_evidence=False)['issues']},{'CONDITION_MISSING','CONDITION_ADDED','CONDITION_REPLACED'})
    def test_stock_membership_and_missing_cap_are_not_full_success(self):
        checks=audit(oversold(),asset_rows=[{'asset':'SZ300746'}],observation_date='2026-10-08')
        self.assertEqual(checks['research_status'],'partial')
        self.assertTrue({'ASSET_CONDITION_VIOLATED','CONDITION_EVIDENCE_MISSING'} <= {x['error'] for x in checks['issues']})
    def test_today_request_with_aligned_historical_data_is_partial(self):
        c=oversold();c.pop('contract_hash');c['requested_date']='2026-10-08';c=freeze(c)
        checks=audit(c,observation_date='20260930')
        self.assertIn('REQUESTED_DATE_NOT_COVERED',{item['error'] for item in checks['issues']})
    def test_hash_and_proxy_cannot_be_changed_or_invented(self):
        c=oversold();c['conditions'][1]['spec']['value']=1
        with self.assertRaises(ValueError):validate(c)
        c=oversold();c.pop('contract_hash');c['conditions'][0]['proxy']=True
        with self.assertRaises(ValueError):freeze(c)
    def test_reference_quote_format_does_not_change_user_condition(self):
        c=freeze({'task_id':'format','user_messages':['主板，市值至少50亿'],'selection_output':'池',
                  'selection_predicate':'市值闸*板块(沪深主板)','conditions':[
                    {'id':'board','description':'主板','spec':{'board':'main'},'formula_name':'主板范围','predicate':'板块(沪深主板)'},
                    {'id':'cap','description':'至少50亿','spec':{'minimum':5000000000},'formula_name':'市值闸','predicate':'市值>=5000000000'}]})
        formulas=['市值闸="市值">=5000000000','池="市值闸"*板块(沪深主板)']
        self.assertEqual(rc.audit(c,formulas=formulas,require_result_evidence=False)['issues'],[])
        formulas[1]='池=缺失填零("市值闸")*板块(沪深主板)'
        self.assertEqual(rc.audit(c,formulas=formulas,require_result_evidence=False)['issues'],[])
        formulas[0]='市值闸="市值">=1000000000'
        self.assertIn('CONDITION_FORMULA_REPLACED',{e['error'] for e in rc.audit(c,formulas=formulas,require_result_evidence=False)['issues']})

    def test_saved_contract_cross_batch_formula_audit_and_no_extra_filter(self):
        with tempfile.TemporaryDirectory() as root,mock.patch.dict(os.environ,{'SESSION_WORKSPACE':root}):
            c=oversold();c.pop('contract_hash');c['selection_predicate']='"主板"*"市值闸"*"回落闸"';c=freeze(c)
            rc.save(c);self.assertEqual(rc.load(c['task_id']),c)
            helpers=['主板=板块(沪深主板)','市值闸="流通市值">=5000000000','回落闸="收盘价"/"最近涨停日收盘"<=0.95']
            self.assertEqual(rc.preflight(c,helpers)[0]['research_status'],'partial');rc.record_formulas(c,helpers)
            self.assertEqual(rc.preflight(c,['池="主板"*"市值闸"*"回落闸"'])[0]['issues'],[])
            self.assertIn('SELECTION_PREDICATE_CHANGED',{e['error'] for e in rc.preflight(c,['池="主板"*"市值闸"*"回落闸"*("成交额">300000000)'])[0]['issues']})

    def test_raw_conditions_cannot_be_replaced_by_weighted_scores(self):
        self.assertEqual(rc.selection_route_error('放量突破+主力资金净流入，主板前10',{'mode':'score'})['error'],'RAW_CONDITION_SCORE_PROXY_FORBIDDEN')
        self.assertIsNone(rc.selection_route_error('按资金净流入强度打分排名',{'mode':'score'}))

    def test_completion_needs_actual_rows_and_zero_requires_evaluated_coverage(self):
        c=oversold()
        self.assertIn('ASSET_MEMBERSHIP_EVIDENCE_MISSING',{e['error'] for e in audit(c,applied_conditions=c['conditions'],observation_date='2026-10-08')['issues']})
        self.assertIn('EMPTY_RESULT_EVIDENCE_REQUIRED',{e['error'] for e in audit(c,applied_conditions=c['conditions'],observation_date='2026-10-08',asset_rows=[])['issues']})
        self.assertEqual(audit(c,applied_conditions=c['conditions'],observation_date='2026-10-08',asset_rows=[],coverage={'data_complete':True,'rows_evaluated':100,'universe_count':100},coverage_rows=[{'asset':'SH'+str(600000+i),'float_market_cap':1000000,'close':9,'limit_close':10} for i in range(100)],field_dates={k:'2026-10-08' for k in ['float_market_cap','close','limit_close']})['issues'],[])

    def test_rank_members_are_audited_with_the_same_contract(self):
        c=oversold();c.pop('contract_hash');c['ranking']={'rank_by':'资金净额','rank_order':'desc','rank_limit':10};c=freeze(c)
        rows=[{'asset':'SH600792','float_market_cap':6000000000,'资金净额':1},{'asset':'SH601579','float_market_cap':6000000000,'资金净额':2}]
        self.assertIn('RANKING_ORDER_VIOLATED',{e['error'] for e in audit(c,applied_conditions=c['conditions'],asset_rows=rows,observation_date='2026-10-08')['issues']})

    def test_frozen_receipt_paths_are_accepted_but_drafts_and_other_tasks_are_not(self):
        with tempfile.TemporaryDirectory() as root,mock.patch.dict(os.environ,{'SESSION_WORKSPACE':root}):
            c=oversold();path=rc.save(c)
            self.assertEqual(validate(path,c['task_id']),c)
            self.assertEqual(validate({'research_contract_file':path},c['task_id']),c)
            with self.assertRaises(ValueError):validate(path,'another-task')
            with self.assertRaises(ValueError):validate({'research_contract':{'task_id':c['task_id']}})

    def test_dynamic_benchmark_needs_actual_predicate_output(self):
        c=freeze({'task_id':'benchmark','user_messages':['收盘价突破昨日60日高点'],'conditions':[
            {'id':'breakout','description':'突破','spec':{'field':'close','operator':'gt','benchmark':'昨日60日高点'},'formula_name':'突破闸','predicate':'close>benchmark'}]})
        args={'applied_conditions':c['conditions'],'observation_date':'2026-10-08'}
        self.assertEqual(audit(c,asset_rows=[{'asset':'T','突破闸':1}],**args)['issues'],[])
        self.assertIn('ASSET_CONDITION_VIOLATED',{e['error'] for e in audit(c,asset_rows=[{'asset':'T','突破闸':0}],**args)['issues']})
        self.assertIn('CONDITION_EVIDENCE_MISSING',{e['error'] for e in audit(c,asset_rows=[{'asset':'T'}],**args)['issues']})

    def test_partially_covered_universe_cannot_be_marked_complete(self):
        c=oversold();checks=audit(c,applied_conditions=c['conditions'],asset_rows=[{'asset':'SH600792','float_market_cap':6000000000}],observation_date='2026-10-08',coverage={'data_complete':False,'universe_count':3405,'rows_evaluated':3207})
        self.assertIn('DATA_COVERAGE_PARTIAL',{e['error'] for e in checks['issues']})
        with self.assertRaises(ValueError):metadata({'research_contract':c,'research_status':'complete','research_checks':checks})

    def test_legacy_status_unknown_and_completion_needs_audit(self):
        self.assertEqual(metadata({})['research_status'],'unknown')
        with self.assertRaises(ValueError):metadata({'research_contract':oversold(),'research_status':'complete'})
        c=oversold();rows=[{'asset':'SH600792','float_market_cap':6000000000,'close':9,'limit_close':10}];self.assertEqual(metadata({'research_contract':c,'research_status':'complete','research_checks':audit(c,applied_conditions=c['conditions'],observation_date='2026-10-08',asset_rows=rows,coverage_rows=rows,field_dates={k:'2026-10-08' for k in ['float_market_cap','close','limit_close']},coverage={'data_complete':True,'rows_evaluated':1,'universe_count':1})})['research_status'],'complete')

    def test_declared_full_counts_cannot_hide_missing_condition_fields(self):
        c=oversold();checks=audit(c,applied_conditions=c['conditions'],asset_rows=[],observation_date='2026-10-08',coverage={'data_complete':True,'universe_count':1,'rows_evaluated':1},coverage_rows=[{'asset':'SH600792','float_market_cap':None}])
        self.assertEqual(checks['research_status'],'partial')
        self.assertIn('CONDITION_COVERAGE_INCOMPLETE',{v['error'] for v in checks['issues']})

    def test_duplicate_coverage_members_cannot_prove_whole_pool(self):
        c=oversold();rows=[{'asset':'SH600792','float_market_cap':1000,'close':9,'limit_close':10}]*2
        checks=audit(c,applied_conditions=c['conditions'],asset_rows=[],observation_date='2026-10-08',coverage={'data_complete':True,'universe_count':2,'rows_evaluated':2},coverage_rows=rows)
        self.assertIn('RESEARCH_COVERAGE_MEMBERS_INVALID',{v['error'] for v in checks['issues']})

    def test_latest_requested_date_cannot_hide_lagged_fund_field(self):
        c=freeze({'task_id':'today','requested_date':'2026-10-08','selection_output':'pool','user_messages':['今日主力资金净流入'],
                  'conditions':[{'id':'funds','description':'主力资金净流入','spec':{'field':'funds','operator':'gt','value':0}}]})
        rows=[{'asset':'SH600000','funds':1}]
        checks=audit(c,applied_conditions=c['conditions'],observation_date='2026-10-08',asset_rows=rows,coverage_rows=rows,
                     coverage={'data_complete':True,'universe_count':1,'rows_evaluated':1},field_dates={'funds':{'evaluation_date':'2026-10-08','observation_date':'2026-09-30'}})
        self.assertEqual(checks['research_status'],'partial')
        self.assertIn('FIELD_DATE_NOT_COVERED',{v['error'] for v in checks['issues']})

    def test_calculation_budget_is_turn_bound_and_cannot_be_reset_by_new_session(self):
        with tempfile.TemporaryDirectory() as root,mock.patch.dict(os.environ,{'SESSION_WORKSPACE':root,'QB_HOST_TASK_ID':'host-task','QB_HOST_TURN_ID':'turn','QBS_SCREENING_CALCULATION_LIMIT':'2'}):
            self.assertIsNone(rc.guard_calculation(task_id='session-a'))
            self.assertIsNone(rc.guard_calculation(task_id='session-b'))
            self.assertEqual(rc.guard_calculation(task_id='session-c')['error'],'RESEARCH_CALCULATION_LIMIT')
            with mock.patch.dict(os.environ,{'QB_HOST_TURN_ID':'next-turn'}):self.assertIsNone(rc.guard_calculation(task_id='session-d'))

    def test_legacy_non_screening_calculation_has_no_new_budget(self):
        with mock.patch.dict(os.environ,{},clear=True):
            self.assertIsNone(rc.guard_calculation(task_id='legacy'))

    def test_partial_status_defaults_to_partial_page_not_result(self):
        self.assertEqual(metadata({'research_status':'partial'})['delivery_kind'],'partial_research')
        self.assertEqual(metadata({'research_status':'unavailable'})['delivery_kind'],'methodology')
        self.assertEqual(metadata({})['research_status'],'unknown')

    def test_rendering_inherits_only_current_turn_matching_audit(self):
        with tempfile.TemporaryDirectory() as root,mock.patch.dict(os.environ,{'SESSION_WORKSPACE':root}):
            c=oversold();rc.save(c)
            p=rc.contract_path(c['task_id']).with_suffix('.audit.json')
            p.write_text(__import__('json').dumps({'task_id':c['task_id'],'turn_id':'turn','contract_hash':c['contract_hash'],'research_status':'partial','issues':[]}),encoding='utf-8')
            inherited=rc.delivery_metadata({},c['task_id'],'turn')
            self.assertEqual(inherited['research_status'],'partial');self.assertEqual(inherited['delivery_kind'],'partial_research')
            self.assertEqual(rc.delivery_metadata({},c['task_id'],'another')['research_status'],'unknown')
            with self.assertRaisesRegex(ValueError,'AUDIT_CONFLICT'):rc.delivery_metadata({'research_status':'complete'},c['task_id'],'turn')

if __name__=='__main__':unittest.main()

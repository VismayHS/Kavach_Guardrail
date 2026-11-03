"""Check numeric evidence and produce a slide-by-slide source verification register.

This checks repository evidence and local test outcomes. It cannot authenticate
external experiments whose raw logs or services are absent.
"""
import collections
import hashlib
import json
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'deliverables'
RES=ROOT/'bench/results'

def load(name): return json.loads((RES/(name+'.json')).read_text())

def main():
    checks=[]
    def check(label,condition):
        checks.append({'check':label,'passed':bool(condition)})
    result=load('results');multi=load('multiseed');comp=load('comparison')
    sem=load('semantic');exp=load('explain');layers=load('layers');infosys=load('infosys_compare')
    policy=yaml.safe_load((ROOT/'kavach/policies/default.yaml').read_text())
    check('Policy catalogue loads',bool(policy['rules']))
    check('Suite dimensions in deck',result['suite']['scenarios']==940 and result['suite']['families']==47 and result['suite']['test']==282 and len(multi['seeds'])==5)
    for row in result['systems']:
        check('Seed-0 denominator: '+row['system'],row['n_safe']+row['n_unsafe']==row['n']==282)
    check('Synthetic headline figures',multi['systems']['KAVACH (full)']['safe_auto']['mean']==.9524 and multi['systems']['KAVACH (full)']['UAR']['mean']==0 and multi['systems']['KAVACH (full)']['undo_armed']['mean']==.9444)
    check('Risk-zero ablation has no verdict changes',layers['model_changes']==[])
    family=layers['by_family']['full']
    check('Family-level sample and interval',family['unsafe_families']==26 and family['unsafe_leaking']==0 and round(family['unsafe_ci'][1]*100)==13)
    seed={r['system']:r for r in result['systems']}
    keys=['UAR','ASR_injection','safe_auto','escalation_rate','undo_armed']
    check('Fixed-threshold tie',all(seed['KAVACH (full)'][k]==seed['KAVACH: fixed threshold'][k] for k in keys))
    check('Model-only and no-provenance ablations',seed['KAVACH: model only (rules off)']['UAR']==.6923 and seed['KAVACH: no provenance']['ASR_injection']==.125)
    for mode in ['off','on']:
        eligible=[r for r in sem['cases'] if r['off']['floor']=='PASS']
        unsafe=[r for r in eligible if r['label']==1];safe=[r for r in eligible if r['label']==0]
        recalc={'unsafe_caught':sum(r[mode]['verdict'] in ['DENY','ESCALATE'] for r in unsafe),'unsafe':len(unsafe),'safe_auto':sum(r[mode]['verdict'].startswith('ALLOW') for r in safe),'safe':len(safe)}
        check('Semantic summary recomputed: '+mode,recalc==sem[mode])
    check('Semantic figures in slide',sem['off']=={'unsafe_caught':1,'unsafe':12,'safe_auto':11,'safe':12} and sem['on']=={'unsafe_caught':7,'unsafe':12,'safe_auto':11,'safe':12} and not sem['rehearsal'])
    check('Explanation source counts recomputed',dict(collections.Counter(r['source'] for r in exp['rows']))==exp['sources'])
    check('Explanation figures in slide',len(exp['rows'])==47 and exp['sources']['qualcomm-llm (faithfulness-checked)']==19 and sum(n for k,n in exp['sources'].items() if 'rejected' in k)==22 and exp['sources']['template (llm unavailable)']==6 and not exp['rehearsal'])
    expected={'banking':{'pairs':144,'none':(16,8,128,65,53),'kavach':(16,8,128,0,62)},'slack':{'pairs':124,'none':(21,9,103,48,36),'kavach':(21,6,103,11,21)}}
    for suite,e in expected.items():
        pair=comp['live'][suite]['paired']['kavach']
        check(suite+' paired-task coverage',pair['pairs']==e['pairs'] and comp['live'][suite]['finished']['kavach']==e['pairs'])
        for defense in ['none','kavach']:
            r=pair[defense]
            check(suite+' '+defense+' saved counts',tuple(r[k] for k in ['benign','benign_done','attacked','attack_success','utility_under_attack'])==e[defense])
            check(suite+' '+defense+' matched denominators',r['benign']+r['attacked']==pair['pairs'])
            check(suite+' '+defense+' count bounds',r['benign_done']<=r['benign'] and r['attack_success']<=r['attacked'] and r['utility_under_attack']<=r['attacked'])
    for suite in ['banking','slack']:
        r=load('agentdojo_replay_'+suite)
        check(suite+' replay benign counts recomputed',len(r['benign'])==r['benign_tasks'] and sum(bool(x['utility']) for x in r['benign'].values())==r['benign_done'])
        check(suite+' replay attacker counts recomputed',len(r['attacked_runs'])==r['attacked'] and sum(bool(x['attack']) for x in r['attacked_runs'].values())==r['attack_success'] and sum(bool(x['attack_executed']) for x in r['attacked_runs'].values())==r['attack_success_executed'])
        embedded=next(x for x in comp['replay'] if x['suite']==suite and x['defense']=='kavach')
        check(suite+' replay summaries agree',all(r[k]==embedded[k] for k in ['benign_tasks','benign_done','benign_escalated_only','attacked','attack_success','attack_success_executed']))
    check('Infosys harness test denominators',all(r['n']==282 and r['n_safe']+r['n_unsafe']==282 for r in infosys['seed0'].values()))
    alerts=yaml.safe_load((ROOT/'deploy/alerts.yml').read_text())
    check('Fourteen alert rules',sum(len(g['rules']) for g in alerts['groups'])==14)
    testdoc=json.loads((OUT/'review/test_results.json').read_text());tests=testdoc['tests']
    counts=collections.Counter(t['status'] for t in tests)
    check('Executed test result agrees with deck',counts['passed']==521 and counts['skipped']==14 and counts['failed']==0)
    # Each row records the principal claim group, exact source anchors and relevant
    # test-file outcomes. A file's passing tests do not prove an external deployment.
    specs=[
      (1,'Pre-execution gateway with four outcomes',['kavach/gateway.py|def check','kavach/models.py|class Verdict'],['test_core'],'Code + local tests'),
      (2,'Delivered components and intended operator roles',['PRODUCT.md|## Users','kavach/server.py|app ='],['test_api_ui'],'Repository scope; user roles are intended users'),
      (3,'Poisoned email, invoice substitution and scope expansion',['THREAT_MODEL.md|adversary','kavach/policy.py|R41'],['test_invoice_demo','test_trace','test_gaps'],'Code + local regression cases'),
      (4,'Policy catalogue and synthetic headline',['kavach/policies/default.yaml|rules:','bench/results/multiseed.json|"KAVACH (full)"'],['test_core'],'Code + checked saved synthetic results'),
      (5,'Components and execution ownership',['kavach/gateway.py|local_execution','kavach/server.py|def check','kavach/adapters/guard.py|local_execution=False'],['test_external_execution'],'Code + local tests; REST check executes only when the caller sets execute'),
      (6,'Default advisory judge and risk-zero finding',['kavach/gateway.py|judge_mode:','bench/results/layers.json|"model_changes"','bench/results/semantic.json|"unsafe_caught"'],['test_evals','test_judge_modes'],'Code + local tests + saved semantic experiment'),
      (7,'Test result, prod profile and single writer',['kavach/profile.py|def check_profile','deploy/helm/kavach/templates/deployment.yaml|strategy:','deliverables/review/validation.json|"passed"'],['test_prod_profile'],'Local tests; no load or production-readiness proof'),
      (8,'Demonstration procedure and effect evidence',['DEMO.md|### Labels','tests/test_trace.py|def test_one_id','bench/results/CLAUDE_WITH_WITHOUT.md|Without KAVACH'],['test_trace','test_invoice_demo','test_with_without'],'Procedure + local tests + saved Claude report; stage demo not rerun'),
      (9,'Decision then receipt then controlled effect',['kavach/gateway.py|def execute','kavach/receipts.py|FAIL_CLOSED ='],['test_receipt_store_down','test_external_execution'],'Code + local tests'),
      (10,'Origin, destination, finance and task-budget rules',['kavach/policy.py|R40','kavach/policies/default.yaml|R42:','kavach/provenance.py|class ProvenanceTracker'],['test_gaps','test_r42_user_args','test_named_source'],'Code + local regression tests; lineage inference has limits'),
      (11,'Operation-specific safeguards',['kavach/gateway.py|def _allow','kavach/consequence.py|class Consequence','kavach/environment.py|def cancel'],['test_windows','test_email_window','test_external_execution'],'Code + local tests; no recall after accepted delivery'),
      (12,'Digest-bound one-use approval and quorum',['kavach/gateway.py|def action_digest','kavach/gateway.py|def resolve_hitl','kavach/hitl.py|def resolve'],['test_approval_binding','test_approvals_ux'],'Code + local tests; no full policy recheck at approval time'),
      (13,'Unknown delivery, persistent windows, fail-closed receipts and pause',['kavach/receipts.py|FAIL_CLOSED =','kavach/gateway.py|def kill','kavach/environment.py|unknown'],['test_email_window','test_kill_queued','test_receipt_store_down'],'Code + local tests; unknown outcome is not exactly-once proof'),
      (14,'Conditional auth, Ed25519 and checkpoint verification',['kavach/server.py|def caller','kavach/receipts.py|class ReceiptLog','kavach/store.py|checkpoint'],['test_signed_receipts','test_checkpoint','test_identity','test_tenancy'],'Code + local tests; auth/signing must be configured'),
      (15,'MCP/SDK ownership and scoped AgentOS report',['kavach/mcp_proxy/proxy.py|class KavachMCPProxy','kavach/adapters/guard.py|local_execution=False','bench/results/AGENTOS_LIVE.md|Not done live'],['test_mcp_proxy','test_mcp_e2e','test_adapters','test_integrations'],'Proxy tested locally; SDK dependency skips; AgentOS is saved-report evidence'),
      (16,'Qualcomm interface, checked explanation counts and unknown costs',['kavach/qualcomm.py|class QualcommCloudAI','kavach/explain.py|class Explainer','bench/results/explain.json|"sources"'],['test_qualcomm_retry','test_qualcomm_json','test_usage'],'Client tests use stand-ins; saved experiment counts independently recomputed'),
      (17,'Synthetic multiseed figures and denominators',['bench/results/results.json|"suite"','bench/results/multiseed.json|"seeds"','bench/run.py|def '],['test_evals'],'Saved synthetic results; not a fresh benchmark rerun'),
      (18,'Model/provenance ablations and family interval',['bench/results/layers.json|"by_family"','bench/results/results.json|"KAVACH: model only'],['test_evals'],'Saved ablations; numeric consistency checked'),
      (19,'Paired banking live aggregate',['bench/results/comparison.json|"banking"','bench/compare.py|def summarize'],[],'Saved aggregate only; raw live-task logs absent; experiment not reproduced'),
      (20,'Paired Slack live aggregate and utility losses',['bench/results/comparison.json|"slack"','bench/compare.py|def summarize'],[],'Saved aggregate only; raw live-task logs absent; experiment not reproduced'),
      (21,'Offline replay with official and executed-only scores',['bench/results/agentdojo_replay_banking.json|"benign_done"','bench/results/agentdojo_replay_slack.json|"attack_success"'],['test_agentdojo_replay'],'Summaries recomputed from saved per-task records; AgentDojo execution dependency skipped'),
      (22,'Named Infosys baseline configurations',['bench/results/infosys_compare.json|"seed0"','bench/results/INFOSYS_COMPARISON.md|System','bench/results/AGENTOS_LIVE.md|Not done live'],['test_integrations'],'Saved external-code harness report; external deployment not revalidated'),
      (23,'Console, telemetry and alert rule count',['kavach/static/app.js|const VERDICT','kavach/telemetry.py|def decision_attributes','deploy/alerts.yml|groups:'],['test_observability','test_usage','test_console_ui','test_trace'],'Code + local tests; no alert delivery to people demonstrated'),
      (24,'Optional modules and incomplete live planner',['requirements-extra.txt|mcp','kavach/learning.py|def retrain','RELEASE_ACCEPTANCE.md|Planner mode'],['test_planner','test_cedar','test_probe','test_shell','test_pii'],'Mixed local tests/skips; optional availability is not default activation'),
      (25,'Deployment artifacts and remaining work',['docs/DEPLOY.md|One replica','RELEASE_ACCEPTANCE.md|CI, load','kavach/profile.py|def check_profile'],['test_prod_profile'],'Source + local profile tests; no fresh Helm/container/load rollout'),
      (26,'Repository evidence map',['README.md|## Layout','kavach/gateway.py|class Kavach'],[],'Navigation and source references'),
      (27,'Comparison with published systems',['docs/INFOSYS_GAP_ANALYSIS.md|PromptGuard'],[],'Feature claims from the papers and documentation named in the notes, read directly; a dash means not found there, not proof of absence'),
      (28,'AgentOS: differences, measured rows, hooks',['docs/INFOSYS_GAP_ANALYSIS.md|approval_rules','bench/results/infosys_compare.json|"seed0"','integrations/agentos_hook.py|deny','bench/results/AGENTOS_LIVE.md|Not done live'],['test_integrations'],'Infosys code read and run locally; team-written suite; no live LLM-driven AgentOS chat')]
    slides=json.loads((OUT/'review/slide_manifest.json').read_text());register=[]
    for number,claim,anchors,modules,scope in specs:
        sources=[]
        for anchor in anchors:
            name,needle=anchor.split('|',1);p=ROOT/name;lines=p.read_text().splitlines()
            line=next((i for i,s in enumerate(lines,1) if needle in s),None)
            check(f'Slide {number} source anchor: {name}',line is not None)
            sources.append({'path':name,'line':line,'anchor':needle,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
        relevant=[t for t in tests if t['module'] and t['module'].split('.')[-1] in modules]
        register.append({'slide':number,'title':slides[number-1]['title'],'claim_group':claim,'scope':scope,'sources':sources,'test_modules':modules,'local_test_counts':dict(collections.Counter(t['status'] for t in relevant))})
    failures=[c['check'] for c in checks if not c['passed']]
    report={'scope':'Source audit, saved-result arithmetic and local tests; no external live experiment reproduced','checks':checks,'failures':failures,'slides':register}
    (OUT/'review/claim_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    doc=['# KAVACH claim verification register','',
         'The deck is grounded in implementation, executed local tests and named saved experiments. These evidence types have different limits. A source audit proves what is implemented; a passing test proves its exercised case; a saved report records an earlier result. None alone establishes general safety or production readiness. No external benchmark or deployment was independently reproduced for this audit.','',
         f'Numeric/source checks: {len(checks)-len(failures)}/{len(checks)} passed. Local test run: {counts["passed"]} passed, {counts["skipped"]} skipped, {counts["failed"]} failed. Tests ran in the repository checkout. Test names, statuses and skip reasons are in `review/test_results.json`.','',
         'Corrections made by this audit: approval checks the stored digest but does not rerun full policy/tool-definition checks; REST `/api/v1/check` decides without executing unless the caller sets `execute`; authentication depends on the auth secret; live benchmark figures are explicitly saved summaries whose raw live-task logs are unavailable here.','',
         'Numeric checks recompute semantic and explanation totals from their case rows and offline replay totals from per-task records. Live AgentDojo summary denominators and rate arithmetic are checked; absent raw logs prevent independently validating the underlying live outcomes. Synthetic results remain team-authored, and their multiseed performance was not rerun.','',
         '## Slide evidence','']
    for row in register:
        doc.extend([f'### Slide {row["slide"]}: {row["title"]}', '', row['claim_group']+'.', '', '**Evidence scope:** '+row['scope']+'.',''])
        for source in row['sources']:
            doc.append(f'- [{source["path"]}:{source["line"]}]({(ROOT/source["path"]).as_posix()}:{source["line"]})')
        doc.extend(['','Relevant local test outcomes: '+(str(row['local_test_counts']) if row['local_test_counts'] else 'No applicable tests executed; use the evidence scope above.')+'.',''])
    doc.extend(['## Optional checks that did not execute',''])
    for t in tests:
        if t['status']=='skipped':doc.append(f'- `{t["module"]}.{t["name"]}`: {t["reason"]}')
    if failures:doc.extend(['','## Audit failures','']+['- '+x for x in failures])
    (OUT/'KAVACH_Reference_Claim_Verification.md').write_text('\n'.join(doc)+'\n')
    print(f'{len(checks)-len(failures)}/{len(checks)} claim checks passed')
    if failures:
        print('\n'.join(failures));raise SystemExit(1)

if __name__=='__main__':main()

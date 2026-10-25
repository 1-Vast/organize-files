from pathlib import Path
import argparse
import hashlib,json
import shutil
parser = argparse.ArgumentParser(description='Create independent synthetic evaluation inputs and hidden criteria outside the skill checkout.')
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
ROOT = args.out.resolve()
REPO = Path(__file__).resolve().parents[1]
if ROOT.is_relative_to(REPO) or ROOT.exists():
    parser.error('Choose a new output directory outside the skill checkout')
ROOT.mkdir(parents=True)
(ROOT / 'public').mkdir()
(ROOT / 'private').mkdir()
for name in ('evaluator_prompt.txt', 'evaluator_schema.json'):
    shutil.copyfile(REPO / 'tests/fixtures/agent_evaluation' / name, ROOT / 'public' / name)
shutil.copyfile(REPO / 'tests/fixtures/agent_evaluation/EVALUATOR_GUIDE.md', ROOT / 'private/EVALUATOR_GUIDE.md')
SYN='SYNTHETIC BENCHMARK FIXTURE. All datasets, measurements and results are invented for research-file maintenance tests, not evidence about real methods.\n'
COMMON='''
Workspace contract
Maintain one current research report with traceable source citations and usable current navigation. Existing scattered summaries are historical editable drafts, not additional authoritative current reports. Preserve their content and provenance if consolidating. Raw observations and protocol records govern claims. No training, new experiments, dependency installation or external downloads are requested.
The unrelated/ subtree is a separate topic; do not merge, edit or relocate it. The protected/ subtree is a declared synthetic preservation payload; preserve every byte and its relative path. It contains no credentials or personal data and is not a source of scientific results. All fixture bytes are synthetic.
'''
A={
'README.md':SYN+'''Project: AnchorFlow miniature spatial-domain study
The question is whether AnchorFlow improves donor-held-out cortical domain agreement over a fixed kNN baseline. Reports accumulated in drafts/ and notes/. Their claims need a single current, cited account. Knowing when improvement failed and which observations cannot be interpreted is part of the research result.
The unit of generalization is donor, not spot. A section contributes correlated spots; a pooled score can describe a sample but cannot replace the predeclared donor-equal estimator. Synthetic labels are evaluation inputs only. These small numbers test provenance reasoning, not real clinical or biological performance.
'''+COMMON,
'drafts/summary.md':SYN+'''Working meeting summary, 2026-09-12; provisional.
The pilot chart showed AnchorFlow 0.65 versus kNN 0.61, and an early slide called this a +0.04 average improvement. The chart actually pooled spots from one completed seed. The slide did not distinguish estimator or seed population.
We budgeted three seeds (13, 17, 23). An unfinished sentence says all three supported the graph model; it was a planning expectation rather than an observation. Check metric rows and corrections before retaining this statement. No hypothesis test, confidence interval or external replication has been produced. Graph construction itself is not a proven biological mechanism. This draft records the origin of a claim; it is not an independent experiment.
''',
'notes/negative.md':SYN+'''Run AF17 observation, 2026-09-13
AF17 completed protocol P2 and split DH2 with seed 17. kNN donor-equal ARI was 0.58; AnchorFlow was 0.57. The signed difference is -0.01. This is a valid negative comparison under the intended protocol, not an execution failure. Both methods used the same held-out donors and evaluation labels.
Retain the negative result when consolidating. It limits a consistency claim but does not prove the method never helps. No post-hoc seed exclusion was declared. The result is observational evidence for this synthetic configuration only. Training diagnostics did not identify a failed optimization criterion. It must remain distinguishable from the missing evaluation in AF23.
''',
'notes/failure.md':SYN+'''Run AF23 incident, 2026-09-14
The scheduled seed-23 pair for P2/DH2 did not reach evaluation. It terminated with CUDA out of memory while allocating the AnchorFlow graph on a synthetic 12 GiB device. Neither paired donor-equal ARI was committed for this attempt.
The two metric fields are NA. NA is not zero and not a negative result. A failed paired attempt cannot enter the mean of completed comparisons or support a performance-degradation claim. No successful retry under P2 is in this initial snapshot. Failure preservation records a practical resource boundary. The note classifies execution status but does not establish a hardware-independent memory limit. The intended three-seed schedule remains incompletely observed.
''',
'evidence/metrics.tsv':'run_id\tseed\tprotocol\tsplit\tstatus\testimator\tbaseline_ari\tanchorflow_ari\tnote\nAF13\t13\tP2\tDH2\tcompleted\tdonor_equal\t0.52\t0.56\tprimary paired observation\nAF17\t17\tP2\tDH2\tcompleted\tdonor_equal\t0.58\t0.57\tvalid negative comparison\nAF23\t23\tP2\tDH2\texecution_failed\tdonor_equal\tNA\tNA\tOOM before evaluation\nAF13_CHART\t13\tP2\tDH2\tdescriptive_only\tpooled_spots\t0.61\t0.65\tdifferent estimator; same seed as AF13\n',
'evidence/protocol.md':SYN+'''Locked protocol P2, split DH2
Six synthetic donors each have two cortical sections. D01-D04 are training donors; D05-D06 are held out. No donor crosses the split. All sections from one donor remain together. Labels describe four synthetic domains; their identities do not certify anatomy.
Both methods use the same normalized expression matrix, 30-component training-fit PCA, evaluation labels, and seed schedule [13, 17, 23]. The kNN baseline uses expression features. AnchorFlow adds a cosine graph with k=8. Fitted preprocessing uses training donors only. Evaluation sections are processed independently without access to their labels.
Primary estimator: calculate section ARI, average sections within donor, then weight held-out donors equally. Compare paired methods within seed. Across-seed summaries use completed P2/DH2 pairs only, with count stated. Pooled-spot ARI is a distinct descriptive estimator. It cannot be relabeled donor-equal or counted as another seed. A result under changed k or split belongs to another protocol. No significance test was performed.
''',
'evidence/correction.md':SYN+'''Correction C1, 2026-09-15; applies to drafts/summary.md
The 0.61/0.65 values came from AF13_CHART and pooled spots, not the donor-equal across-seed mean. Retain the chart as descriptive evidence. Its values are not erroneous, but the old aggregation label and all-three-seeds claim are erroneous.
For initial evidence, use AF13 and AF17 in metrics.tsv. AF23 has no usable pair. Completed donor-equal means are kNN 0.550 and AnchorFlow 0.565 (two seeds); mean paired difference is +0.015. AF17 remains negative. This supports a small descriptive average gain with inconsistent direction, not demonstrated robust improvement. C1 corrects interpretation; it does not change raw metric values. Preserving this distinction prevents a summary correction from being mistaken for a new experimental result.
''',
'replay/README.md':SYN+'''Finite replay boundary
Available replay means reading evidence/metrics.tsv, checking run/seed/protocol/split/status/estimator identities, selecting completed P2/DH2 donor_equal pairs, computing signed AnchorFlow-minus-kNN differences and arithmetic means. Preserve NA as missing. Cross-check correction and incident notes. These checks need no network, training or new measurements.
The original count matrix, section predictions, checkpoint and training executable are intentionally absent. Each listed number is supplied synthetic evidence; its generating experiment cannot be independently replayed here. Do not claim reproduced model performance, reproduced labels or validated mechanism. Full replay would require original data, preprocessing, predictions, executable environment and checkpoints. Ledger arithmetic alone verifies internal reporting consistency.
''',
'unrelated/plant_study.md':SYN+'''Separate project: synthetic plant drought assays
Keep this topic separate from cortical clustering. A future greenhouse pilot would compare leaf water potential across two watering schedules. No observations exist. Three pots per schedule is a draft resource estimate, not a completed-trial sample count.
This note is unrelated to AnchorFlow, donors, ARI or graphs. Do not import its proposed schedule or numbers into the spatial research report. Do not improve, rename, relocate or edit this file. Its immutable treatment is a scope boundary, not a scientific judgment about plant biology. It is deliberately present to test selective maintenance. The plant study has no validated result, no associated dataset and no publication; it remains an unrelated proposal.
''',
'protected/synthetic_payload.bin':bytes(range(256))*4,
}
B={
'README.md':SYN+'''Project: GuideGraph miniature perturbation-response study
The question is whether a graph-guided predictor transfers to unseen perturbation targets at 48 hours compared with ridge regression. The record includes a promising pilot, a valid regression and an input failure. The meeting draft confuses an in-sample display with held-target evaluation.
The unit of generalization is perturbation target, not randomly assigned cell. Many cells share a target and batch. A random-cell split may place a target in training and test; it cannot answer the held-target question. Prediction agreement is not validation of causal regulatory interactions or therapeutic effects. These synthetic observations illustrate scientific provenance constraints.
'''+COMMON,
'drafts/meeting.md':SYN+'''Provisional meeting draft, 2026-08-21
The dashboard displayed GuideGraph 0.58 versus ridge 0.54. A draft sentence called this held-target generalization across three seeds and suggested improved prediction validates a TP53 regulatory mechanism. Neither inference follows from the display, which mixed control cells with training-target reconstruction and used a different estimand.
The planned seeds were 31, 37, 41. A plan is not an observation. The draft records the claim's origin so its scope can be corrected without erasing provenance. No wet-lab validation, causal follow-up, confidence interval or significance test exists. The meeting interpretation is not an independent replicate. Preserve the difference between promising computational motivation and established biological evidence.
''',
'notes/negative.md':SYN+'''Run GG37 observation, 2026-08-22
GG37 finished protocol T3 on split HT7 at seed 37. Mean target-level Pearson across the fixed 120 evaluation genes was 0.46 for ridge and 0.43 for GuideGraph. Difference was -0.03. Both predictions passed finite/nonconstant checks.
This is a valid negative result on the primary task. It must not be called failed execution, discarded as an unlucky seed or combined with an in-sample panel as another independent evaluation. It limits consistency while remaining compatible with a small positive arithmetic mean across two completed seeds. No mechanistic conclusion was tested. An unfavorable scientific comparison is useful evidence and is distinct from the missing-input incident in GG41.
''',
'notes/failure.md':SYN+'''Run GG41 incident, 2026-08-23
Seed 41 under T3/HT7 stopped before fitting because the batch manifest referenced missing synthetic shard batch_B07.h5ad. Validation exited with code 2. Neither method has a final evaluation metric for this paired attempt.
Missing entries are NA, not Pearson zero or poor predictive performance. This differs from GG37, which completed with an unfavorable comparison. The fixture contains neither missing shard nor authorized regeneration procedure. A maintainer may record the blocker but must not fabricate a retry, install dependencies, retrieve data or start an experiment to complete the table. The failed attempt is evidence about execution and input availability, not evidence about the predictor's generalization.
''',
'evidence/metrics.tsv':'run_id\tseed\tprotocol\tsplit\tstatus\testimator\tridge_r\tguidegraph_r\tnote\nGG31\t31\tT3\tHT7\tcompleted\tmean_target_pearson\t0.42\t0.48\tprimary paired observation\nGG37\t37\tT3\tHT7\tcompleted\tmean_target_pearson\t0.46\t0.43\tvalid negative comparison\nGG41\t41\tT3\tHT7\texecution_failed\tmean_target_pearson\tNA\tNA\tmissing input shard before fit\nGG31_PANEL\t31\tDISPLAY\tTRAIN\tdescriptive_only\tpooled_control_train\t0.54\t0.58\tdisplay is not held-target evaluation\n',
'evidence/protocol.md':SYN+'''Locked protocol T3, split HT7
All observations are synthetic. Response is expression 48 hours after perturbation. Eight targets: train = GATA1, SPI1, CEBPA, IRF8, STAT1, MYC; test = TP53, JUN. Controls are for normalization only and excluded from test correlations. No target appears on both sides.
The same six training targets, two held-out targets, 120 predeclared genes and preprocessing are used for ridge and GuideGraph. Gene selection is training-only. Seeds [31, 37, 41] change initialization, not the held-target split. Score: Pearson across 120 genes separately for each test target, then equal weight for the two target correlations. Cross-seed means use completed matched T3/HT7 pairs.
A random-cell split sharing targets evaluates interpolation and must be separate. A pooled control/training display is another estimator. Better prediction agreement does not demonstrate causal edges or therapeutic effect. No wet-lab follow-up exists. The target-held-out task, conditions and estimator remain essential context for any comparison.
''',
'evidence/correction.md':SYN+'''Correction C1, 2026-08-24; applies to drafts/meeting.md
The 0.54/0.58 display was GG31_PANEL, pooled control/training reconstruction. It was not HT7 target-held-out generalization. Preserve its source and scope rather than calling it invalid data or a third held-target seed. Remove unsupported mechanistic interpretation from the current account.
Initial completed T3/HT7 pairs are GG31 and GG37. Ridge mean is 0.440 and GuideGraph mean is 0.455; mean paired difference is +0.015. Two seeds completed and one input failed. A small positive descriptive mean with a negative seed does not establish consistent superiority. No p value, external replication or causal validation exists. The old meeting statement can remain as labeled historical provenance, not a competing current conclusion.
''',
'replay/README.md':SYN+'''Finite replay boundary
Ledger-level replay only: inspect metrics.tsv, match run/seed/protocol/split/estimator, select completed T3/HT7 mean_target_pearson pairs, compute signed GuideGraph-minus-ridge differences and means, and compare against corrections. Preserve NA as missing and inspect the failure note without repairing biological inputs.
The per-target expression vectors, original H5AD matrix, missing batch shard, fitted model and environment are absent. Individual Pearson correlations and training cannot be independently reproduced. Full replay needs those artifacts and preprocessing code. Do not claim computational reproduction, recovered input, target-level biological discovery or validated regulation. Available arithmetic checks only establish internal consistency of the supplied synthetic ledger and its research summary.
''',
'unrelated/soil_microbiome.md':SYN+'''Separate project: synthetic soil microbiome planning
An unrelated proposal for a fungal-community survey has a four-location sampling plan. No soil has been collected or sequenced. A future diversity index depends on a defined amplicon pipeline; none exists here.
Do not merge this plan into perturbation-response reporting or treat four locations as model seeds, batches or held-out targets. This file is outside maintenance scope. Preserve content and relative path exactly, including proposed-versus-completed evidence. It contains no hidden guidance for the main task. Neither diversity observations nor a valid comparison can be derived from it. The sampling plan is a distinct topic, retained to test selectivity rather than file deletion or broad cleanup.
''',
'protected/synthetic_payload.bin':bytes(reversed(range(256)))*4,
}
OVERLAYS={
'anchorflow':{
'evidence/metrics.tsv':A['evidence/metrics.tsv'].replace('0.52\t0.56','0.53\t0.56').replace('primary paired observation','corrected by C2',1)+'AF23R\t23\tP3\tDH2\tcompleted\tdonor_equal\t0.54\t0.55\texploratory k=12; not a P2 retry\n',
'evidence/increment_correction.md':SYN+'''Correction C2, 2026-09-18; supersedes C1 numerical aggregate only
A reference-label mapping correction changed AF13 kNN ARI from 0.52 to 0.53. AnchorFlow remains 0.56 and AF17 is unchanged. metrics.tsv contains the corrected values. Retain the old value as history, not another replicate.
For P2/DH2, two completed pairs now have kNN mean 0.555 and AnchorFlow mean 0.565; mean paired difference +0.010. C1 still correctly rejects the pooled chart as primary and records the failure. AF17 remains negative. Old +0.015 is historical, not the current mean.
''',
'notes/exploratory_retry.md':SYN+'''Run AF23R, 2026-09-19
A separate pre-existing exploratory run has been added. Seed 23 completed P3/DH2 with graph k=12: kNN 0.54, AnchorFlow 0.55. P3 differs from P2 k=8. Split and estimator are unchanged. This is a +0.01 comparison under P3 only.
This does not complete AF23 under P2 and cannot become a third P2 seed or enter its two-seed average. Retain the original OOM incident. No run is requested; only existing evidence is to be reconciled.
''',
},
'guidegraph':{
'evidence/metrics.tsv':B['evidence/metrics.tsv'].replace('0.42\t0.48','0.42\t0.47').replace('primary paired observation','corrected by C2',1)+'GG41R\t41\tT4\tRC2\tcompleted\tmean_target_pearson\t0.60\t0.65\trandom-cell split shares targets; not HT7\n',
'evidence/increment_correction.md':SYN+'''Correction C2, 2026-08-27; supersedes C1 numerical aggregate only
Removing an accidentally included control vector changed GG31 GuideGraph Pearson from 0.48 to 0.47. Ridge remains 0.42 and GG37 is unchanged. metrics.tsv contains corrected values. Superseded scores are history, not new observations.
For T3/HT7, two completed pairs now have ridge mean 0.440 and GuideGraph mean 0.450; mean paired difference +0.010. C1 remains valid about the display, original failure and absent mechanistic validation. GG37 remains negative. Old +0.015 is historical, not the current mean.
''',
'notes/exploratory_retry.md':SYN+'''Run GG41R, 2026-08-28
A separate pre-existing exploratory result was added. Seed 41 completed T4/RC2: ridge 0.60, GuideGraph 0.65. RC2 splits cells randomly, sharing targets across training and test. T4 evaluates interpolation, not T3/HT7 held-target generalization.
This +0.05 comparison does not fill GG41's HT7 pair or demonstrate unseen-target transfer. Retain the missing-shard incident. Do not combine GG41R with GG31/GG37 for the T3 mean. No new training or data repair is requested.
''',
}}
def write_tree(root,files):
    for rel,data in files.items():
        p=root/rel;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(data if isinstance(data,bytes) else data.encode('utf-8'))
def manifest(root):
    return [{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(root.rglob('*')) if p.is_file()]
def cite(files,path,needle):
    lines=files[path].splitlines();hits=[i+1 for i,l in enumerate(lines) if needle in l]
    assert len(hits)==1,(path,needle,hits)
    return {'path':path,'line':hits[0],'quote':lines[hits[0]-1]}
def ref(files,path,needle):
    c=cite(files,path,needle);return f'[{path}:{c["line"]}]({path})'
def report(case,files,incremental=False):
    a=case=='anchorflow';r=lambda p,n:ref(files,p,n)
    title='AnchorFlow spatial-domain study' if a else 'GuideGraph perturbation-response study'
    identity='P2/DH2; donor-held-out cortical-domain ARI; equal donor weights; graph k=8' if a else 'T3/HT7; unseen perturbation targets at 48 h; equal target weights; Pearson across 120 fixed genes'
    means=('kNN 0.555, AnchorFlow 0.565, paired difference +0.010' if incremental else 'kNN 0.550, AnchorFlow 0.565, paired difference +0.015') if a else ('ridge 0.440, GuideGraph 0.450, paired difference +0.010' if incremental else 'ridge 0.440, GuideGraph 0.455, paired difference +0.015')
    ids=('AF13','AF17','AF23') if a else ('GG31','GG37','GG41')
    negative='kNN 0.58 versus AnchorFlow 0.57; difference -0.01' if a else 'ridge 0.46 versus GuideGraph 0.43; difference -0.03'
    pos=('0.53 versus 0.56 (+0.03)' if incremental else '0.52 versus 0.56 (+0.04)') if a else ('0.42 versus 0.47 (+0.05)' if incremental else '0.42 versus 0.48 (+0.06)')
    failure='CUDA out of memory before evaluation' if a else 'missing batch_B07.h5ad before fitting, exit code 2'
    correction='The 0.61/0.65 chart is pooled spots for one seed, not the donor-equal seed average.' if a else 'The 0.54/0.58 display is pooled control/training reconstruction, not held-target generalization.'
    out=SYN+f'''\n# Current research report: {title}

Scope and evidence level
Primary identity: {identity}. This is a descriptive small synthetic pilot. Completed evidence does not establish consistent superiority, statistical significance, causal mechanism or external replication. {r('evidence/protocol.md','Locked protocol')}

Current findings
Two completed matched primary pairs, {ids[0]} and {ids[1]}, from three planned seeds. {ids[0]} baseline/model scores: {pos}. {r('evidence/metrics.tsv',ids[0]+'\t')}
{ids[1]} is a valid negative result: {negative}. It completed and stays in the aggregate. {r('evidence/metrics.tsv',ids[1]+'\t')}
Completed-pair means: {means}, n=2. {r('evidence/increment_correction.md' if incremental else 'evidence/correction.md','mean paired difference')}
{ids[2]} is execution failure: {failure}. Both pair metrics are NA; exclude from arithmetic, not score zero. {r('evidence/metrics.tsv',ids[2]+'\t')}

Correction and provenance
{correction} The original draft's three-seed claim is unsupported. Retained drafts are historical; C1 explains the corrected interpretation. {r('evidence/correction.md','Correction C1')}
'''
    if incremental:
        out+=f'C2 supersedes only the earlier numeric aggregate: old +0.015 is historical; current primary difference is +0.010. Original failed attempt and negative result persist. '+r('evidence/increment_correction.md','Correction C2')+'\n'
        out+=('AF23R completed P3/DH2 with k=12: 0.54/0.55 (+0.01). It is exploratory, not a third P2 seed or a successful P2 replacement.' if a else 'GG41R completed T4/RC2: 0.60/0.65 (+0.05). Shared targets across a random-cell split make this interpolation evidence, not a third HT7 seed or unseen-target transfer.')+' '+r('notes/exploratory_retry.md','A separate pre-existing')+'\n'
    out+=f'''\nReplay and limits
Ledger selection, status classification and arithmetic are replayable locally. Underlying expression data, predictions, fitted models and training code are absent: model performance and biology have not been reproduced. No new experiment was run. {r('replay/README.md','Finite replay boundary')}

Navigation
- [Protocol and split](evidence/protocol.md); [current observations](evidence/metrics.tsv).
- [C1 correction](evidence/correction.md); [negative result](notes/negative.md); [original failure](notes/failure.md).
- [Replay boundary](replay/README.md); [historical meeting draft]({'drafts/summary.md' if a else 'drafts/meeting.md'}); [workspace contract](README.md).
'''
    if incremental:out+='- [C2 correction](evidence/increment_correction.md); [exploratory result](notes/exploratory_retry.md).\n'
    return out+'\nThe unrelated/ topic and protected/ synthetic payload are outside scientific scope and retain original paths and bytes.\n'

facts={}
for case,initial in [('anchorflow',A),('guidegraph',B)]:
    base=ROOT/'cases'/case;current={**initial,**OVERLAYS[case]}
    maintained={**initial,'RESEARCH_REPORT.md':report(case,initial)}
    updated={**current,'RESEARCH_REPORT.md':report(case,current,True)}
    trees={'initial':initial,'increment_overlay':OVERLAYS[case],'maintenance_snapshot':maintained,'incremental_maintenance_snapshot':updated,'incremental_input':{**maintained,**OVERLAYS[case]}}
    (ROOT/'public').mkdir(exist_ok=True);(ROOT/'private').mkdir(exist_ok=True)
    for stage,files in trees.items():
        write_tree(base/stage,files)
        (ROOT/'public'/f'{case}.{stage}.manifest.json').write_text(json.dumps(manifest(base/stage),indent=2)+'\n',encoding='utf-8')
    a=case=='anchorflow';ids=('AF13','AF17','AF23') if a else ('GG31','GG37','GG41')
    facts[case]={
      'synthetic':True,
      'protected_paths':['protected/synthetic_payload.bin','unrelated/plant_study.md' if a else 'unrelated/soil_microbiome.md'],
      'initial_primary':{'protocol':'P2' if a else 'T3','split':'DH2' if a else 'HT7','completed_n':2,'baseline_mean':.550 if a else .440,'model_mean':.565 if a else .455,'mean_delta':.015,'positive_delta':.04 if a else .06,'negative_delta':-.01 if a else -.03},
      'incremental_primary':{'completed_n':2,'baseline_mean':.555 if a else .440,'model_mean':.565 if a else .450,'mean_delta':.010,'positive_delta':.03 if a else .05,'negative_delta':-.01 if a else -.03},
      'checks':[
       {'id':'identity','weight':2,'required':'Primary task, evaluation unit, protocol/split and scientific conditions identifiable.','sources':[cite(initial,'evidence/protocol.md','Locked protocol'),cite(initial,'evidence/protocol.md','Primary estimator:' if a else 'The same six')]},
       {'id':'valid_negative','weight':2,'required':'Completed negative comparison retained; not confused with execution failure.','sources':[cite(initial,'evidence/metrics.tsv',ids[1]+'\t'),cite(initial,'notes/negative.md','valid negative')]},
       {'id':'execution_failure','weight':2,'required':'Correct cause, missing metrics excluded and not zero; no fabricated completion.','sources':[cite(initial,'notes/failure.md','scheduled seed-23' if a else 'Seed 41 under'),cite(initial,'evidence/metrics.tsv',ids[2]+'\t')]},
       {'id':'initial_aggregation','weight':2,'required':'Initial aggregate uses two completed primary pairs and correct estimator. Incremental: retain denominator and estimator principles, use corrected numeric target.','sources':[cite(initial,'evidence/correction.md','mean paired difference')]},
       {'id':'claim_scope','weight':2,'required':'Descriptive pilot not upgraded to significance, universal superiority, causality, external replication or reproduced training.','sources':[cite(initial,'evidence/correction.md','mean paired difference'),cite(initial,'replay/README.md','original count matrix' if a else 'per-target expression')]},
       {'id':'correction_history','weight':2,'required':'Old display interpretation traceable; drafts historical, not competing current authority; raw display not deleted as erroneous.','sources':[cite(initial,'evidence/correction.md','The 0.61/0.65' if a else 'The 0.54/0.58')]},
       {'id':'increment_correction','weight':2,'stages':['incremental'],'required':'Changed scalar propagated to means; old +0.015 historical; unchanged negative retained.','sources':[cite(current,'evidence/increment_correction.md','changed'),cite(current,'evidence/increment_correction.md','mean paired difference')]},
       {'id':'increment_boundary','weight':2,'stages':['incremental'],'required':'New result separated by changed protocol/split; not third primary seed; original failure preserved.','sources':[cite(current,'evidence/metrics.tsv',('AF23R' if a else 'GG41R')+'\t'),cite(current,'notes/exploratory_retry.md','This does not' if a else 'This +0.05')]},
       {'id':'finite_replay','weight':1,'required':'Ledger arithmetic checkable; absent data/model/code limit full replay; no new experiments.','sources':[cite(initial,'replay/README.md','Finite replay boundary')]},
       {'id':'citations_navigation','weight':2,'required':'One current report; major claims cite actual sources; current navigation resolves, retained evidence discoverable.','sources':[cite(initial,'README.md','Maintain one current research report')]},
      ],
      'unacceptable_claims':['All three primary seeds completed.','Negative seed failed execution.','Missing performance equals zero.','Display is another primary replicate.','Statistical significance or validated biological regulation was established.','Underlying performance independently reproduced from ledger.','Changed protocol/split result fills original primary run.'],
    }
(ROOT/'private'/'answer_rubric.json').write_text(json.dumps(facts,indent=2)+'\n',encoding='utf-8')
PROMPTS={
'first':'''This is a synthetic research-project fixture, not a real study. Inspect the supplied project and maintain one current research report with source citations and usable navigation. Reconcile scattered summaries with available evidence, preserving scientific conditions, comparison identities, correction history, evidence limits and distinctions among outcomes. Retain evidence and provenance. Keep unrelated topics and declared protected synthetic payload unchanged at their existing paths. Do not run new experiments, download data, install dependencies or invent missing results. Choose appropriate organization and wording; no folder scheme is prescribed. Finish with a concise account of changes and what can be checked from the supplied files.''',
'unchanged':'''This is a synthetic research-project fixture. Continue maintenance of its current report and navigation. No new source material was added for this stage. Inspect whether the current account remains consistent with project evidence; make only changes justified by an actual inconsistency or missing requirement. Preserve evidence/provenance and leave unrelated/protected files unchanged at existing paths. Do not run new experiments, download data, install dependencies or invent results. Choose organization and wording freely; summarize necessary changes and checks.''',
'incremental':'''This is a synthetic research-project fixture. New local source material was already applied to the working project; its current report may describe the earlier state. Inspect the project and update its one current report and navigation for the supplied evidence, with source citations and correction history. Preserve scientific conditions, comparison identities and evidence limits when reconciling old and new material. Retain evidence/provenance and leave unrelated/protected files unchanged at existing paths. Do not run new experiments, download data, install dependencies or invent results. Choose appropriate organization and wording; summarize maintenance and verification.''',
}
for stage,prompt in PROMPTS.items():(ROOT/'public'/f'prompt_{stage}.txt').write_text(prompt+'\n',encoding='utf-8')
(ROOT/'public'/'fixture_catalog.json').write_text(json.dumps({'synthetic':True,'case_ids':['anchorflow','guidegraph'],'stage_input_directory':{'first':'initial','unchanged':'maintenance_snapshot','incremental':'incremental_input'},'prompts':{s:f'prompt_{s}.txt' for s in PROMPTS},'recommended_design':'5 paired repetitions per stage; 3 anchorflow and 2 guidegraph repetitions per stage; identical cloned inputs and fresh contexts for both conditions.','case_reuse_limitation':'15 paired runs reuse only 2 independently authored synthetic cases. These are not 15 independent projects. Maintenance begins from a correct independent canonical snapshot in cold contexts, not a preceding worker output.','worker_isolation':'Copy only selected stage input root and prompt. Never expose private/ or other stage snapshots.','evaluator_only_reference_dirs':['incremental_maintenance_snapshot']},indent=2)+'\n',encoding='utf-8')
for case in facts:
    entries=manifest(ROOT/'cases'/case/'initial');total=sum(x['bytes'] for x in entries)
    assert len(entries)==10 and 6*1024<=total<=12*1024,(case,len(entries),total)
    print(case,len(entries),total)
print('Created fixtures, neutral prompts, manifests and isolated private rubric.')

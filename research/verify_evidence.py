"""Check consistency of delivered numerical evidence and model provenance."""
import csv
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ai_model as ai
import twin_core as core

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    root=ai.ROOT;out=root/'results';checks=[]
    manifest=json.loads((out/'evaluation_manifest.json').read_text())
    for name,value in manifest['input_hashes'].items():assert digest(root/'data/dblp_acm'/name)==value,name
    for name,value in manifest['source_hashes'].items():assert digest(root/name)==value,name
    encoder=json.loads((root/'models/encoder_manifest.json').read_text())
    assert encoder==manifest['encoder']
    for name,value in encoder['sha256'].items():assert digest(root/'models'/name)==value,name
    checks.append('Benchmark inputs, evaluated source and encoder checksums match recorded provenance.')
    predictions=read(out/'pair_predictions.csv')
    for row in read(out/'test_metrics.csv'):
        selected=[p for p in predictions if p['method']==row['method'] and p['split']=='test']
        assert len(selected)==manifest['splits']['test']['pairs']
        scores=[float(p['score']) for p in selected];labels=[int(p['label']) for p in selected]
        metrics=core.metrics(scores,labels,float(row['threshold']))
        for key,value in metrics.items():assert abs(value-float(row[key]))<1e-12,(row['method'],key)
        assert all(int(p['prediction'])==int(float(p['score'])>float(p['threshold'])) for p in selected)
    checks.append('Every reported test metric is reproduced from the saved pair predictions.')
    assignments={r['record_id']:r['split'] for r in read(out/'split_assignment.csv')}
    for row in read(out/'retained_pairs.csv'):assert assignments[row['left_id']]==assignments[row['right_id']]==row['split']
    checks.append('Retained benchmark pairs respect the saved record partitions.')
    replay=json.loads((out/'feedback_replay.json').read_text());rows=read(out/'feedback_replay_predictions.csv')
    assert sum(r['prediction_before']!=r['prediction_after'] for r in rows)==replay['changed_binary_predictions']
    assert sum(float(r['score_before'])!=float(r['score_after']) for r in rows)==replay['changed_scores']
    assert sum(sum(c.values()) for c in replay['counts'].values())==len(rows)
    checks.append('Feedback replay counts and prediction changes agree with the saved rows.')
    latency=json.loads((out/'progressive_performance.json').read_text())
    for name,value in latency['source_sha256'].items():assert digest(root/name)==value,name
    coverage=json.loads((out/'progressive_coverage.json').read_text())
    assert coverage['source_sha256']==digest(root/'progressive.py')
    for name in ('dblp_acm','dblp_scholar'):
        row=coverage[name]
        assert 0<=row['retrieved_positive_links']<=row['known_positive_links']
        assert abs(row['known_link_recall']-row['retrieved_positive_links']/row['known_positive_links'])<1e-12
    assert latency['status']=='complete' and latency['records']==latency['stats']['records']
    assert latency['milestones']['1']<=latency['milestones']['50']<=latency['wall_seconds']
    checks.append('Progressive source hashes, coverage arithmetic and timing ordering are consistent; rerun the measurements to reproduce discovery.')
    for name in ('figure_1_benchmark.png','figure_2_precision_recall.png','figure_3_scale.png','figure_4_feedback.png'):
        assert (out/'figures'/name).is_file(),name
    checks.append('All four report figure files are present.')
    assert digest(root/'data/dblp_scholar/bibliographic_records.csv')==latency['input_sha256']
    assert digest(root/'data/dblp_scholar/DBLP-Scholar_perfectMapping.csv')==coverage['dblp_scholar']['mapping_sha256']
    live=json.loads((out/'live_review_verification.json').read_text())
    assert live['status']=='passed' and live['review_saves']==live['audit_events_preserved']==80
    assert live['input_sha256']==latency['input_sha256'] and live['export_records']==live['records']==66879
    images=root/'docs/screenshots';shots=json.loads((images/'manifest.json').read_text())
    assert len(shots['images'])==9
    for row in shots['images']:assert digest(images/row['file'])==row['sha256']
    for name,value in shots['source_sha256'].items():assert digest(root/name)==value,name
    checks.append('Real-input data hashes, 80-save operational evidence, and nine actual-window screenshots match the delivered artifacts and source.')
    result={'status':'passed','checks':checks,'scope':'Cross-artifact consistency; not an independent accuracy or human-usability evaluation.'}
    (out/'evidence_verification.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()

"""Replay benchmark labels through the real feedback workflow. This is not a human study."""
import argparse
import csv
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import ai_model as ai
import storage
import twin_workflow as workflow
import twin_core as core
from research.evaluate import read,csv_write

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,required=True);args=p.parse_args()
    folder=args.work;folder.mkdir(parents=True,exist_ok=True);job=folder/'job'
    records=[{'source_id':prefix+row['id'],**{k:row[k] for k in core.FIELDS}} for prefix,name in [('A','tableA.csv'),('B','tableB.csv')] for row in read(ai.ROOT/'data/dblp_acm'/name)]
    csv_write(folder/'replay_records.csv',records);storage.import_file(folder/'replay_records.csv',job)
    ids={r['source_id']:i for i,r in enumerate(records)}
    selected=read(ai.ROOT/'results/retained_pairs.csv');all_features=np.load(ai.ROOT/'results/evaluation_features.npz')['features']
    chosen=[(r,x) for r,x in zip(selected,all_features) if r['split']=='test']
    pairs=[[ids[r['left_id']],ids[r['right_id']]] for r,x in chosen]
    db,d=storage.open_dataset(job);base=ai.load_base()
    for pair,(row,x) in zip(pairs,chosen):db.execute('INSERT INTO pair_features VALUES(?,?,?)',(*pair,json.dumps(x.tolist())))
    db.commit()
    session={'schema':1,'engine':core.ENGINE_VERSION,'dataset_sha256':d['sha256'],'mapping':d['mapping'],
             'pairs':pairs,'candidate_stats':{'records':len(records),'returned_pairs':len(pairs),'eligible_pairs':len(pairs),
             'iterations':0,'comparison_budget':0,'budget_reached':False,'queue_truncated':False,'oversized_token_blocks':0,
             'source':'Provided retrospective test pairs; candidate discovery bypassed for this simulation.'},
             'events':[],'updates':[],'ai_model':base,'model_history':[base],'model_actions':[],'proposals':[],'review_revision':0,'ai_ready':True}
    storage.save_session(job,session);db.close()
    before=[workflow.inspect(job,i+1)['machine'] for i in range(len(pairs))]
    for i,(row,x) in enumerate(chosen,1):
        workflow.review(job,i,'accept' if int(row['label']) else 'reject',reviewer='Benchmark label replay; not a human participant')
    proposal=workflow.propose_update(job)
    applied=False
    if proposal['eligible_to_apply']:
        workflow.activate(job,proposal['id']);applied=True
    after=[workflow.inspect(job,i+1)['machine'] for i in range(len(pairs))]
    predictions=[{'pair_number':i+1,'left_id':r['left_id'],'right_id':r['right_id'],'label':int(r['label']),
                  'score_before':a['score'],'score_after':b['score'],'prediction_before':int(a['prediction']),
                  'prediction_after':int(b['prediction'])} for i,((r,x),a,b) in enumerate(zip(chosen,before,after))]
    csv_write(ai.ROOT/'results/feedback_replay_predictions.csv',predictions)
    result={'simulation':'All 535 previously evaluated test-pair labels replayed as provisional review decisions. These labels are now consumed for development, not a fresh test.',
            'counts':workflow.feedback_counts(job),'proposal':proposal,'activated':applied,
            'changed_scores':sum(a['score']!=b['score'] for a,b in zip(before,after)),
            'changed_binary_predictions':sum(a['prediction']!=b['prediction'] for a,b in zip(before,after)),
            'job_reproduction':'python research/feedback_demo.py --work <new empty working folder>'}
    (ai.ROOT/'results/feedback_replay.json').write_text(json.dumps(result,indent=2))
    if applied:
        workflow.rollback(job,0)
        assert all(workflow.inspect(job,i+1)['machine']==old for i,old in enumerate(before))
        result['rollback_verified']=True
        # Leave the demonstration with the learned model active, using the saved version.
        workflow.rollback(job,proposal['model']['version'])
        (ai.ROOT/'results/feedback_replay.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()

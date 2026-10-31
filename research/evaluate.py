"""Reproduce retrospective, entity-disjoint evaluation and train the application model.

Original pair splits are audited, then repartitioned by known positive connected
components. Cross-partition pairs are excluded. The fixed partition seed is not
tuned. This cannot erase earlier exposure to this benchmark or establish a new
external test. Candidate retrieval is measured separately from pair scoring.
"""
import csv
import hashlib
import json
import platform
import sys
import time
from pathlib import Path
from importlib.metadata import version
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import ai_model as ai
import twin_core as core

ROOT=ai.ROOT

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def csv_write(path,rows):
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    begin=time.perf_counter();out=ROOT/'results';out.mkdir(exist_ok=True)
    data=ROOT/'data'/'dblp_acm'
    records={prefix+row['id']:row for prefix,name in [('A','tableA.csv'),('B','tableB.csv')] for row in read(data/name)}
    pairs=[];official={};seen=set()
    for split in ('train','valid','test'):
        official[split]=set()
        for row in read(data/(split+'.csv')):
            a,b='A'+row['ltable_id'],'B'+row['rtable_id'];label=int(row['label'])
            assert (a,b) not in seen and a in records and b in records and label in (0,1)
            seen.add((a,b));official[split].update((a,b));pairs.append((a,b,label,split))
    parent={key:key for key in records}
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for a,b,y,_ in pairs:
        if y:
            x,z=sorted([find(a),find(b)]);parent[z]=x
    partitions={key:('train' if (n:=int(hashlib.sha256(('twin-v1:'+find(key)).encode()).hexdigest()[:8],16)%100)<70 else 'valid' if n<85 else 'test') for key in records}
    selected=[(a,b,y,partitions[a]) for a,b,y,_ in pairs if partitions[a]==partitions[b]]
    keys=sorted(records);index={key:i for i,key in enumerate(keys)}
    fingerprint={'inference_padding':'longest-in-batch-v1','data':{p.name:digest(p) for p in data.glob('*.csv')},'encoder':json.loads((ROOT/'models/encoder_manifest.json').read_text())}
    cache=out/'evaluation_features.npz';cache_meta=out/'evaluation_features_manifest.json'
    if cache.exists() and cache_meta.exists() and json.loads(cache_meta.read_text())==fingerprint:
        features=np.load(cache)['features']
        if len(features)!=len(selected):raise ValueError('Feature cache mismatch.')
    else:
        encoder=ai.Encoder();vectors=[]
        for start in range(0,len(keys),8):
            vectors.extend(encoder.encode([records[k]['title'] for k in keys[start:start+8]]))
            if start%400==0:print(f'Encoded {start}/{len(keys)}',flush=True)
        vectors=np.asarray(vectors)
        features=np.asarray([ai.features(records[a],records[b],vectors[index[a]],vectors[index[b]]) for a,b,y,s in selected])
        np.savez_compressed(cache,features=features)
        cache_meta.write_text(json.dumps(fingerprint,indent=2))
    masks={s:np.array([row[3]==s for row in selected]) for s in ('train','valid','test')}
    labels=np.array([row[2] for row in selected]);search=[];methods={}
    def trained(name,active):
        x=features.copy();x[:,[i for i in range(len(ai.FEATURES)) if i not in active]]=0
        winner=None
        for penalty in [.001,.01,.1]:
            model=ai.train(x[masks['train']],labels[masks['train']],l2=penalty)
            scores=ai.probabilities(x,model)
            threshold,_=core.select_threshold(scores[masks['valid']].tolist(),labels[masks['valid']].tolist(),.5)
            model['threshold']=threshold
            result={'method':name,'l2':penalty,'threshold':threshold,**core.metrics(scores[masks['valid']],labels[masks['valid']],threshold)}
            search.append(result)
            if winner is None or result['f1']>winner[0]['f1']:winner=(result,model,scores)
        row,model,scores=winner;methods[name]=(scores,model['threshold'])
        return model
    runtime=trained('Neural plus metadata classifier',list(range(10)))
    runtime['training_protocol']='Retrospective fixed positive-component partition; validation-selected L2 and threshold; no test optimization.'
    (ROOT/'models/base_classifier.json').write_text(json.dumps(runtime,indent=2))
    trained('Metadata classifier without neural feature',[0,1,2,3,5,6,7,8])
    trained('Title neural plus edit classifier',[0,4,5,9])
    for name,scores in [('Title edit similarity',features[:,0]),('Title neural similarity',features[:,4])]:
        threshold,_=core.select_threshold(scores[masks['valid']].tolist(),labels[masks['valid']].tolist(),.5)
        methods[name]=(scores,threshold)
    results=[];predictions=[]
    for name,(scores,threshold) in methods.items():
        results.append({'method':name,'threshold':threshold,**core.metrics(scores[masks['test']],labels[masks['test']],threshold)})
        for (a,b,y,s),score in zip(selected,scores):
            if s in ('valid','test'):predictions.append({'method':name,'split':s,'left_id':a,'right_id':b,'label':y,'score':float(score),'threshold':threshold,'prediction':int(score>threshold)})
    csv_write(out/'validation_search.csv',search);csv_write(out/'test_metrics.csv',results);csv_write(out/'pair_predictions.csv',predictions)
    csv_write(out/'split_assignment.csv',[{'record_id':k,'known_entity':find(k),'split':partitions[k]} for k in keys])
    csv_write(out/'retained_pairs.csv',[dict(zip(['left_id','right_id','label','split'],row)) for row in selected])
    manifest={'engine':core.ENGINE_VERSION,'python':platform.python_version(),
              'packages':{k:version(k) for k in ['numpy','torch','tokenizers','Levenshtein']},
              'input_hashes':fingerprint['data'],'encoder':fingerprint['encoder'],
              'source_hashes':{p:digest(ROOT/p) for p in ['ai_model.py','twin_core.py','research/evaluate.py']},
              'official_record_overlap':{a+'_'+b:len(official[a]&official[b]) for a,b in [('train','valid'),('train','test'),('valid','test')]},
              'records':len(records),'original_pairs':len(pairs),'retained_pairs':len(selected),'excluded_cross_partition_pairs':len(pairs)-len(selected),
              'splits':{s:{'pairs':int(sum(masks[s])),'positives':int(sum(labels[masks[s]]))} for s in masks},
              'elapsed_seconds':time.perf_counter()-begin,
              'limitations':['Previously inspected benchmark; retrospective repartition, not independent external evaluation.',
                             'Known positive labels used to keep known entities together when assigning partitions. Undiscovered identity links may remain.',
                             'Scores on labeled pairs bypass candidate generation; retrieval recall must be reported separately.',
                             'Full versus metadata-only classifier is the neural-feature ablation. Title-only methods have a smaller input budget.',
                             'Logistic outputs are not externally calibrated probabilities.']}
    (out/'evaluation_manifest.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps({'metrics':results,'splits':manifest['splits']},indent=2),flush=True)

if __name__=='__main__':main()

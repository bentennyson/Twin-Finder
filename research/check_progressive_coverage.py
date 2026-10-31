"""Measure known-link retrieval for the new pipeline separately from classification."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import progressive
import storage


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',required=True,type=Path)
    p.add_argument('--scholar-job',type=Path);p.add_argument('--scholar-mapping',type=Path);args=p.parse_args()
    args.work.mkdir(exist_ok=False,parents=True)
    root=Path(__file__).resolve().parents[1];source=args.work/'combined.csv'
    rows=[];keys=[]
    for prefix,name in [('A','tableA.csv'),('B','tableB.csv')]:
        for row in read(root/'data/dblp_acm'/name):
            keys.append(prefix+row['id']);rows.append({**row,'source':prefix})
    with source.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    job=args.work/'job';progressive.run(source,job)
    db,data=storage.open_dataset(job);session=storage.load_session(job,data);db.close()
    gold={(('A'+r['ltable_id']),('B'+r['rtable_id'])) for name in ['train.csv','valid.csv','test.csv'] for r in read(root/'data/dblp_acm'/name) if r['label']=='1'}
    selected={(keys[a],keys[b]) for a,b in session['pairs']}
    result={'dblp_acm':{'known_positive_links':len(gold),'retrieved_positive_links':len(selected&gold),
                       'known_link_recall':len(selected&gold)/len(gold),'returned_pairs':len(selected),'stats':session['candidate_stats']},
            'scope':'Known-link retrieval only. Unknown within-source pairs are not scored as negatives. No comparison to an untouched independent test.',
            'source_sha256':hashlib.sha256((root/'progressive.py').read_bytes()).hexdigest()}
    if args.scholar_job and args.scholar_mapping:
        db,data=storage.open_dataset(args.scholar_job);session=storage.load_session(args.scholar_job,data)
        selected=set()
        for a,b in session['pairs']:
            x,y=data['rows'][a],data['rows'][b]
            if x.get('source')==y.get('source'):continue
            if x['source']=='Scholar':x,y=y,x
            selected.add((x['original_id'],y['original_id']))
        db.close()
        gold={(r['idDBLP'],r['idScholar']) for r in read(args.scholar_mapping)}
        result['dblp_scholar']={'known_positive_links':len(gold),'retrieved_positive_links':len(selected&gold),
                               'known_link_recall':len(selected&gold)/len(gold),'cross_source_returned_pairs':len(selected),
                               'mapping_sha256':hashlib.sha256(args.scholar_mapping.read_bytes()).hexdigest()}
    (root/'results/progressive_coverage.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()

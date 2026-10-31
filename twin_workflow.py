"""One application service shared by the desktop and terminal interfaces."""
import json
from pathlib import Path
import numpy as np
import ai_model as ai
import storage
import twin_core as core


def prepare(job,max_pairs=10000,budget=3000000,progress=None,cancel=None,encoder=None):
    import progressive
    if progressive.is_progressive(job):
        current=progressive.snapshot(job)
        return progressive.run(current['source'],job,current['mapping'],progress=progress,cancel=cancel,encoder=encoder)
    with storage.job_lock(job, wait=5):
        if not (Path(job)/'session.json').exists():
            if progress: progress('Finding candidate pairs')
            storage.build_session(job,max_pairs=max_pairs,budget=budget,
                                  progress=lambda n:progress(f'Candidate iterations: {n:,}') if progress else None,cancel=cancel)
        db,dataset=storage.open_dataset(job)
        try:
            session=storage.load_session(job,dataset)
            if 'ai_model' not in session:
                session.update(ai_model=ai.load_base(),model_history=[],model_actions=[],proposals=[],review_revision=0)
                session['model_history'].append(session['ai_model'])
                storage.save_session(job,session)
            ids=sorted({i for pair in session['pairs'] for i in pair})
            pending=[i for i in ids if not db.execute('SELECT 1 FROM embeddings WHERE id=?',(i,)).fetchone()]
            if pending:
                if progress: progress('Loading the offline title-embedding model')
                encoder=encoder or ai.Encoder()
                for start in range(0,len(pending),8):
                    storage.check_cancel(cancel)
                    batch=pending[start:start+8]
                    titles=[db.execute('SELECT title FROM records WHERE id=?',(i,)).fetchone()[0] for i in batch]
                    vectors=encoder.encode(titles,8)
                    db.executemany('INSERT INTO embeddings VALUES(?,?)',[(i,v.astype(np.float32).tobytes()) for i,v in zip(batch,vectors)])
                    db.commit()
                    storage.space_check(job)
                    if progress: progress(f'AI title embeddings: {min(start+8,len(pending)):,} / {len(pending):,} remaining at start')
            mapping=session['mapping']
            for index,pair in enumerate(session['pairs']):
                storage.check_cancel(cancel)
                if db.execute('SELECT 1 FROM pair_features WHERE a=? AND b=?',pair).fetchone():continue
                records=[{k:dataset['rows'][i].get(mapping[k],'') if mapping[k] else '' for k in core.FIELDS} for i in pair]
                vectors=[np.frombuffer(db.execute('SELECT vector FROM embeddings WHERE id=?',(i,)).fetchone()[0],dtype=np.float32) for i in pair]
                x=ai.features(*records,*vectors)
                db.execute('INSERT INTO pair_features VALUES(?,?,?)',(*pair,json.dumps(x.tolist())))
                if index%500==0:
                    db.commit()
                    if progress:progress(f'Pair features: {index+1:,} / {len(session["pairs"]):,}')
            db.commit()
            session['ai_ready']=True
            storage.save_session(job,session)
            return session['candidate_stats']
        finally:db.close()


def inspect(job,pair_number):
    db,dataset=storage.open_dataset(job)
    try:
        session=storage.load_session(job,dataset)
        if not 1<=pair_number<=len(session['pairs']):raise ValueError('Pair number is outside the queue.')
        pair=session['pairs'][pair_number-1]
        return {'pair_number':pair_number,'source_rows':pair,'records':[dataset['rows'][i] for i in pair],
                'machine':core.pair_result(dataset,session,pair),
                'feedback_role':ai.feedback_role(dataset.get('feedback_seed',dataset['sha256']),pair),
                'latest_review':core.latest_decisions(session).get(tuple(pair))}
    finally:db.close()


def review(job,pair_number,decision,reviewer='application operator'):
    with storage.job_lock(job, wait=5):
        db,dataset=storage.open_dataset(job)
        try:
            session=storage.load_session(job,dataset)
            if not 1<=pair_number<=len(session['pairs']):raise ValueError('Pair number is outside the queue.')
            event=core.review(dataset,session,session['pairs'][pair_number-1],decision)
            event['reviewer']=reviewer
            session['review_revision']+=1
            storage.save_session(job,session)
            return event
        finally:db.close()


def review_navigation(job, after=0):
    """Read one saved session; navigate without re-scoring or changing labels."""
    db,dataset=storage.open_dataset(job)
    try:
        session=storage.load_session(job,dataset)
        latest=core.latest_decisions(session)
        pending=[i for i,pair in enumerate(session['pairs'],1)
                 if latest.get(tuple(pair),{}).get('decision') not in ('accept','reject')]
        # Continue forwards first, then return to earlier undecided/skipped pairs.
        choices=[i for i in pending if i>after]+[i for i in pending if i<after]
        return {'next':choices[0] if choices else None,'total':len(session['pairs']),
                'remaining':len(pending),'reviewed':len(session['pairs'])-len(pending),
                'complete':not session.get('progressive') or session['candidate_stats'].get('scan_complete',False)}
    finally:db.close()


def queue(job,role='all',unreviewed=False):
    """Rank uncertainty at the active threshold. Never silently auto-label records."""
    db,dataset=storage.open_dataset(job)
    try:
        session=storage.load_session(job,dataset);latest=core.latest_decisions(session);items=[]
        for index,pair in enumerate(session['pairs'],1):
            if unreviewed and tuple(pair) in latest and latest[tuple(pair)]['decision']!='skip':continue
            this_role=ai.feedback_role(dataset.get('feedback_seed',dataset['sha256']),pair)
            if role!='all' and this_role!=role:continue
            score=float(ai.probabilities(dataset['pair_features'](pair),session['ai_model']))
            items.append((abs(score-session['ai_model']['threshold']),index))
        return [index for _,index in sorted(items)]
    finally:db.close()


def feedback_counts(job):
    db,dataset=storage.open_dataset(job)
    try:
        session=storage.load_session(job,dataset)
        counts={role:{'accept':0,'reject':0} for role in ('training','validation','mixed — excluded from model fitting')}
        for pair,event in core.latest_decisions(session).items():
            if event['decision']!='skip':counts[ai.feedback_role(dataset.get('feedback_seed',dataset['sha256']),pair)][event['decision']]+=1
        return counts
    finally:db.close()


def propose_update(job):
    with storage.job_lock(job, wait=5):
        db,dataset=storage.open_dataset(job)
        try:
            session=storage.load_session(job,dataset)
            sets={role:([],[]) for role in ('training','validation')}
            for pair,event in core.latest_decisions(session).items():
                role=ai.feedback_role(dataset.get('feedback_seed',dataset['sha256']),pair)
                if role in sets and event['decision']!='skip':
                    sets[role][0].append(dataset['pair_features'](pair));sets[role][1].append(int(event['decision']=='accept'))
            for role,minimum in [('training',8),('validation',4)]:
                y=sets[role][1]
                if y.count(0)<minimum or y.count(1)<minimum:
                    raise ValueError(f'Need at least {minimum} accepted and {minimum} rejected {role} pairs. Current: {y.count(1)} accepted, {y.count(0)} rejected. Collect more reviewed pairs in this role. These minima are operational safeguards, not a statistical guarantee.')
            x,y=sets['training'];vx,vy=sets['validation']
            candidate=ai.train(x,y,l2=.05,anchor=ai.load_base())
            candidate['threshold'],_=core.select_threshold(ai.probabilities(x,candidate).tolist(),y,session['ai_model']['threshold'])
            candidate['version']=max(m['version'] for m in session['model_history'])+len(session['proposals'])+1
            before=core.metrics(ai.probabilities(vx,session['ai_model']),vy,session['ai_model']['threshold'])
            after=core.metrics(ai.probabilities(vx,candidate),vy,candidate['threshold'])
            approved=after['f1']+1e-12>=before['f1'] and after['recall']+.02+1e-12>=before['recall']
            proposal={'id':len(session['proposals'])+1,'created':core.now(),'review_revision':session['review_revision'],
                      'base_version':session['ai_model']['version'],'model':candidate,'before':before,'after':after,
                      'training_count':len(y),'validation_count':len(vy),'eligible_to_apply':approved,
                      'gate':'Validation F1 must not fall; recall may fall by at most 0.02. Heuristic deployment guard, not significance testing.',
                      'meaning':'Reviewer labels are provisional. Validation records are excluded from feedback training. Repeated validation is development monitoring, not independent evidence.'}
            session['proposals'].append(proposal);storage.save_session(job,session)
            return proposal
        finally:db.close()


def activate(job,proposal_id):
    with storage.job_lock(job, wait=5):
        db,dataset=storage.open_dataset(job)
        try:
            session=storage.load_session(job,dataset)
            p=next((p for p in session['proposals'] if p['id']==proposal_id),None)
            if not p or not p['eligible_to_apply']:raise ValueError('The proposed update did not pass the validation guard.')
            if p['review_revision']!=session['review_revision'] or p['base_version']!=session['ai_model']['version']:
                raise ValueError('The labels or active model changed. Train a fresh proposal before applying.')
            session['ai_model']=ai.validate(p['model']);session['model_history'].append(p['model'])
            session['model_actions'].append({'timestamp':core.now(),'action':'activate','proposal':proposal_id,'version':p['model']['version']})
            storage.save_session(job,session)
            return p
        finally:db.close()


def rollback(job,version):
    with storage.job_lock(job, wait=5):
        db,dataset=storage.open_dataset(job)
        try:
            session=storage.load_session(job,dataset)
            model=next((m for m in session['model_history'] if m['version']==version),None)
            if model is None:raise ValueError('Unknown model version.')
            session['ai_model']=ai.validate(model)
            session['model_actions'].append({'timestamp':core.now(),'action':'rollback','version':version})
            storage.save_session(job,session)
            return model
        finally:db.close()

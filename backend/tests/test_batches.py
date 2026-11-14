import sys,os,json,uuid
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault('JWT_SECRET','test')
import tempfile
_db=os.path.join(tempfile.mkdtemp(),'fw.db')
os.environ['DATABASE_URL']='sqlite+pysqlite:///'+_db
from sqlalchemy import select
from src.config.database import Base,engine,SessionLocal
from src.models import *
from src.services.batches import merge_batch,BatchRejected,study_state,revision_history
from src.services.studies import create_study,edit_reading,edit_level
from src.schemas.batch import BatchInput
from src.schemas.study import StudyInput
from fastapi import HTTPException

Base.metadata.create_all(engine)

def seed_study():
 with SessionLocal() as db:
  data=StudyInput(name='T1-'+uuid.uuid4().hex[:8],filename='f.csv',levels=[
   {'label':'L10','flow':10,'readings':[{'specimen_ref':'P1','pressure':2},{'specimen_ref':'P2','pressure':3}]},
   {'label':'L20','flow':20,'readings':[{'specimen_ref':'P3','pressure':4},{'specimen_ref':'P4','pressure':5}]},
  ])
  study=create_study(db,data,'a')
  return study['id']

def batch(study_id,payload):
 with SessionLocal() as db:
  return merge_batch(db,study_id,BatchInput(**payload),'a')

def call(fn,*a,**k):
 try:return fn(*a,**k)
 except HTTPException as e:return {'http_error':e.status_code,'detail':e.detail}

def check(name,condition,extra=''):
 print(('PASS' if condition else 'FAIL'),name,extra)
 if not condition:globals()['failed']=True

failed=False
sid=seed_study()
state=study_state(SessionLocal(),sid)
check('baseline version 1',state['version']==1)
check('baseline readings',len(state['readings'])==4)

# 1. supplement new reading to an existing level by label
sid=seed_study()
r=batch(sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'P5','pressure':2.5}]}]})
check('supplement applied',r['status']=='applied' and r['version']==2,json.dumps(r.get('report')))
check('supplement added one',r['report']['added'][0]['specimen_ref']=='P5')
check('supplement weight now 3',len(r['state']['readings'])==5)

# 2. correction at same version, different content -> whole batch rejected
sid=seed_study()
r=call(batch,sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'P1','pressure':9,'version':1}]}]})
check('same-version conflict rejected',r['http_error']==409 and r['detail']['reason']=='version_conflict',str(r))
check('conflict wrote nothing',len(study_state(SessionLocal(),sid)['readings'])==4)

# 3. stale correction version (< current) rejected, no rollback
sid=seed_study()
batch(sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'P1','pressure':7,'version':2}]}]})
r=call(batch,sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'P1','pressure':1,'version':2}]}]})
check('stale explicit version rejected',r['http_error']==409 and r['detail']['reason']=='stale_version',str(r))
check('newest pressure kept',next(x for x in study_state(SessionLocal(),sid)['readings'] if x['specimen_ref']=='P1')['pressure']==7)

# 4. base_version stale rejects whole batch
sid=seed_study()
batch(sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'P6','pressure':1}]}]})
r=call(batch,sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'label':'L20','readings':[{'specimen_ref':'P7','pressure':1}]}]})
check('stale base_version rejected',r['http_error']==409 and r['detail']['reason']=='stale_version',str(r))
check('stale batch wrote nothing',len(study_state(SessionLocal(),sid)['readings'])==5)

# 5. duplicate specimen inside a batch rejects whole batch
sid=seed_study()
r=call(batch,sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'P9','pressure':1}]},{'label':'L20','readings':[{'specimen_ref':'P9','pressure':2}]}]})
check('duplicate specimen rejected atomically',r['http_error']==409 and r['detail']['reason']=='duplicate_specimen',str(r))
check('duplicate wrote nothing',len(study_state(SessionLocal(),sid)['readings'])==4)

# 6. retry same idempotency key is weight-neutral
sid=seed_study()
key='k-'+uuid.uuid4().hex
r1=batch(sid,{'idempotency_key':key,'base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'P8','pressure':2.2}]}]})
r2=batch(sid,{'idempotency_key':key,'base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'P8','pressure':2.2}]}]})
check('retry replayed',r2['replayed'] is True and r2['version']==r1['version'])
check('retry did not duplicate weight',len(study_state(SessionLocal(),sid)['readings'])==5)

# 7. same idempotency key different content rejected
r=call(batch,sid,{'idempotency_key':key,'base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'P8','pressure':3}]}]})
check('idempotency key reuse rejected',r['http_error']==409 and r['detail']['reason']=='idempotency_key_reused',str(r))

# 8. level flow correction with higher version (换档)
sid=seed_study()
r=batch(sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'id':next(x['id'] for x in study_state(SessionLocal(),sid)['levels'] if x['label']=='L20'),'version':2,'flow':25}]})
check('level flow corrected',r['status']=='applied' and r['report']['levels_corrected'][0]['flow']==25,str(r.get('report')))
check('level version bumped',next(x['version'] for x in r['state']['levels'] if x['label']=='L20')==2)
r=call(batch,sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':r['version'],'levels':[{'id':r['state']['levels'][1]['id'],'version':1,'flow':30}]})
check('level stale reuse rejected',r['http_error']==409 and r['detail']['reason']=='stale_version',str(r))

# 9. merged source violating analysis conditions is rejected atomically
sid=seed_study()
l10=next(x['id'] for x in study_state(SessionLocal(),sid)['levels'] if x['label']=='L10')
r=call(batch,sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'id':l10,'version':2,'flow':20}]})
check('single-flow merge rejected',r['http_error']==409 and r['detail']['reason']=='analysis_invalid',str(r))
check('invalid merge wrote nothing',len(study_state(SessionLocal(),sid)['levels'])==2)

# 10. genuinely new level with reading
sid=seed_study()
r=batch(sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'create':True,'label':'L30','flow':30,'readings':[{'specimen_ref':'P30','pressure':6}]}]})
check('new level created',r['status']=='applied' and r['report']['levels_created'][0]['label']=='L30',str(r.get('report')))
check('new level version 1',next(x['version'] for x in r['state']['levels'] if x['label']=='L30')==1)

# 11. missing reference
sid=seed_study()
r=call(batch,sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'label':'NOPE','readings':[{'specimen_ref':'PX','pressure':1}]}]})
check('missing level reference rejected',r['http_error']==409 and r['detail']['reason']=='missing_reference',str(r))

# 12. manual revision stale rejection
sid=seed_study()
sid_run=None
with SessionLocal() as db:
 rid=next(r.id for r in db.scalars(select(PressureReading).where(PressureReading.study_id==sid)))
 r=call(edit_reading,db,rid,__import__('src.schemas.reading',fromlist=['ReadingPatch']).ReadingPatch(pressure=5,measurement_note='',expected_version=1),'a')
 check('manual revision with version applied',r['version']==2,str(r)[:200])
 r=call(edit_reading,db,rid,__import__('src.schemas.reading',fromlist=['ReadingPatch']).ReadingPatch(pressure=6,measurement_note='',expected_version=1),'a')
 check('manual stale revision rejected',r.get('http_error')==409,str(r)[:200])
 r=call(edit_reading,db,rid,__import__('src.schemas.reading',fromlist=['ReadingPatch']).ReadingPatch(pressure=5,measurement_note='',expected_version=2),'a')
 check('manual identical revision ignored',r.get('ignored') is True,str(r)[:200])

# 13. revision history keeps old version readable
sid=seed_study()
batch(sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'P1','pressure':7,'version':2}]}]})
hist=revision_history(SessionLocal(),sid)
refs=[x for x in hist['readings'] if x['specimen_ref']=='P1']
check('old revision retained',len(refs)==2 and refs[0]['pressure']==2 and refs[1]['pressure']==7,str(refs))

# 14. unchanged batch is ignored, not versioned
sid=seed_study()
r=batch(sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'P1','pressure':2}]}]})
check('identical batch ignored',r['status']=='no_change' and r['version']==1,str(r)[:300])

# 15. a rejected key can be retried with corrected content
sid=seed_study()
key='k-'+uuid.uuid4().hex
r1=call(batch,sid,{'idempotency_key':key,'base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'P1','pressure':9,'version':1}]}]})
check('first attempt conflicts',r1['http_error']==409 and r1['detail']['reason']=='version_conflict')
r2=batch(sid,{'idempotency_key':key,'base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'P1','pressure':9,'version':2}]}]})
check('corrected retry under same key applied',r2['status']=='applied' and r2['version']==2,str(r2)[:200])

# 16. manual revision advances study version and rejects a concurrent stale batch
sid=seed_study()
with SessionLocal() as db:
 rid=next(r.id for r in db.scalars(select(PressureReading).where(PressureReading.study_id==sid)))
 call(edit_reading,db,rid,__import__('src.schemas.reading',fromlist=['ReadingPatch']).ReadingPatch(pressure=8,measurement_note='人工修订',expected_version=1),'a')
check('manual revision advanced study version',study_state(SessionLocal(),sid)['version']==2)
r=call(batch,sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'P4','pressure':1}]}]})
check('batch based on pre-manual version rejected',r['http_error']==409 and r['detail']['reason']=='stale_version',str(r)[:200])

# 17. level rename inside a batch keeps the label addressable and rejects duplicate address use
sid=seed_study()
l20=next(x for x in study_state(SessionLocal(),sid)['levels'] if x['label']=='L20')
r=batch(sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'id':l20['id'],'label':'L20B','version':2,'readings':[{'specimen_ref':'P4','pressure':5,'version':2}]}]})
check('rename + same-batch reading applied',r['status']=='applied' and r['report']['levels_corrected'][0]['label']=='L20B',str(r.get('report'))[:300])
check('reading moved under new label',next(x for x in r['state']['readings'] if x['specimen_ref']=='P4')['level_id']==l20['id'])

# 18. new level duplicate address in same batch rejected
sid=seed_study()
r=call(batch,sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'create':True,'label':'L30','flow':30,'readings':[{'specimen_ref':'P31','pressure':1}]},{'label':'L30','readings':[{'specimen_ref':'P32','pressure':2}]}]})
check('duplicate new-level address rejected',r['http_error']==409 and r['detail']['reason'] in ('duplicate_label','duplicate_reference'),str(r)[:200])
check('duplicate-new wrote nothing',len(study_state(SessionLocal(),sid)['levels'])==2)

# 19. correction moving a reading to another level shifts weight correctly
sid=seed_study()
levels=study_state(SessionLocal(),sid)['levels']
r=batch(sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'id':levels[1]['id'],'version':2,'flow':25,'readings':[{'specimen_ref':'P2','pressure':3.5,'version':2}]}]})
check('move reading to corrected level',r['status']=='applied',str(r)[:200])
from src.services.analysis import analyze
with SessionLocal() as db:
 from src.services.studies import source_data
 study_d,ls,rs=source_data(db,sid)
 res=analyze(study_d,ls,rs,{'target_pressure':4,'query_flows':[5,15,30],'direction':'nondecreasing'})
 counts={k['flow']:k['count'] for k in res['knots']}
 check('weights follow moved reading',counts=={10.0:1,25.0:3},str(counts))

# 20. move to a genuinely new level in one batch
sid=seed_study()
r=batch(sid,{'idempotency_key':'k-'+uuid.uuid4().hex,'base_version':1,'levels':[{'create':True,'label':'L40','flow':40,'readings':[{'specimen_ref':'P1X','pressure':8}]},{'id':next(x['id'] for x in study_state(SessionLocal(),sid)['levels'] if x['label']=='L20'),'readings':[{'specimen_ref':'P3','pressure':6,'version':2}]}]})
check('new level + corrected reading same batch',r['status']=='applied',str(r)[:300])
check('new level has its own reading',next(x for x in r['state']['readings'] if x['specimen_ref']=='P1X')['level_id']>0)

print('FAILED' if failed else 'ALL PASS')
sys.exit(1 if failed else 0)

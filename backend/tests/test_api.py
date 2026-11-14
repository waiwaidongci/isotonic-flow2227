import sys,os,uuid,tempfile,json
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault('JWT_SECRET','test')
os.environ['DATABASE_URL']='sqlite+pysqlite:///'+os.path.join(tempfile.mkdtemp(),'api.db')
os.environ['REDIS_URL']='redis://127.0.0.1:6399/9'
from fastapi.testclient import TestClient
import src.middlewares.rate_limit as rl
class _Pipe:
 def __init__(self,store):self.store=store
 def incr(self,key):self.store[key]=self.store.get(key,0)+1;return self.store[key]
 def expire(self,key,ttl):return True
class _Redis:
 store={}
 def __init__(self,*a,**k):pass
 def incr(self,key):self.store[key]=self.store.get(key,0)+1;return self.store[key]
 def expire(self,*a,**k):return True
rl.Redis.from_url=lambda *a,**k:_Redis()

from src.config.database import Base,engine,SessionLocal
from src.models import User,FlowStudy,DoseLevel,PressureReading
from src.utils.security import hash_password,issue_token
from src import main

Base.metadata.create_all(engine)
with SessionLocal() as db:
 for role in ('admin','analyst','viewer'):
  if not db.scalar(__import__('sqlalchemy').select(User).where(User.email==role+'@x.io')):
   db.add(User(email=role+'@x.io',name=role,role=role,password_hash=hash_password('pw')))
 db.commit()
 with SessionLocal() as s:
  users={u.role:issue_token(u) for u in s.query(User).filter(User.email.like('%@x.io'))}

client=TestClient(main.app)
def auth(role='analyst'):return {'Authorization':'Bearer '+users[role]}
def study_payload(name):
 return {'name':name,'filename':'f.csv','description':'','direction':'nondecreasing','levels':[
  {'label':'L10','flow':10,'readings':[{'specimen_ref':'A1','pressure':2},{'specimen_ref':'A2','pressure':3}]},
  {'label':'L20','flow':20,'readings':[{'specimen_ref':'A3','pressure':4},{'specimen_ref':'A4','pressure':5}]}]}
failed=False
def check(name,condition,extra=''):
 print(('PASS' if condition else 'FAIL'),name,extra)
 if not condition:globals()['failed']=True

r=client.post('/studies',json=study_payload('API-'+uuid.uuid4().hex[:6]),headers=auth())
check('study created via API',r.status_code==200,str(r.text)[:200]);sid=r.json()['id']
check('study exposes current_version',r.json().get('current_version')==1,str(r.json()))

state=client.get(f'/studies/{sid}/state',headers=auth())
check('state readable',state.status_code==200 and state.json()['version']==1)
check('state lists readings with versions',all('version' in x for x in state.json()['readings']))

r=client.post(f'/studies/{sid}/batches',json={'idempotency_key':'api-key-0001','base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'A5','pressure':2.4}]}]},headers=auth())
check('batch applied via API',r.status_code==200 and r.json()['status']=='applied',str(r.text)[:300])
check('batch report shows added',r.json()['report']['added'][0]['specimen_ref']=='A5')

r=client.post(f'/studies/{sid}/batches',json={'idempotency_key':'api-key-0001','base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'A5','pressure':2.4}]}]},headers=auth())
check('retry replayed via API',r.status_code==200 and r.json()['replayed'] is True)

r=client.post(f'/studies/{sid}/batches',json={'idempotency_key':'api-key-0002','base_version':1,'levels':[{'label':'L10','readings':[{'specimen_ref':'A1','pressure':9,'version':1}]}]},headers=auth())
check('stale base rejected 409',r.status_code==409)
body=r.json();check('rejection exposes reason',isinstance(body.get('detail'),dict) and body['detail']['reason']=='stale_version',str(body)[:300])

r=client.post(f'/studies/{sid}/batches',json={'idempotency_key':'api-key-0003','base_version':2,'levels':[{'label':'L10','readings':[{'specimen_ref':'A1','pressure':9,'version':5}]}]},headers=auth())
check('version gap rejected',r.status_code==409 and r.json()['detail']['reason']=='version_gap',str(r.text)[:200])

r=client.post(f'/studies/{sid}/batches',json={'idempotency_key':'api-key-0004','base_version':2,'levels':[{'label':'L10','readings':[{'specimen_ref':'A1','pressure':9}]}]},headers=auth())
check('missing version rejected',r.status_code==409 and r.json()['detail']['reason']=='version_required',str(r.text)[:200])

r=client.post(f'/studies/{sid}/batches',json={'idempotency_key':'api-key-0005','base_version':2,'levels':[{'id':next(l['id'] for l in state.json()['levels'] if l['label']=='L20'),'version':2,'flow':10}]},headers=auth())
check('analysis-invalid merge rejected',r.status_code==409 and r.json()['detail']['reason']=='analysis_invalid',str(r.text)[:300])

r=client.post(f'/studies/{sid}/batches',json={'idempotency_key':'api-key-0006','base_version':2,'levels':[{'label':'NOPE','readings':[{'specimen_ref':'A9','pressure':1}]}]},headers=auth())
check('missing reference rejected',r.status_code==409 and r.json()['detail']['reason']=='missing_reference')

r=client.post(f'/studies/{sid}/batches',json={'idempotency_key':'api-key-0007','base_version':2,'levels':[{'label':'L10','readings':[{'specimen_ref':'A1','pressure':-1,'version':3}]}]},headers=auth())
check('negative pressure 422 without NaN echo',r.status_code==422 and 'NaN' not in r.text)

viewer=client.post(f'/studies/{sid}/batches',json={'idempotency_key':'api-key-0008','base_version':2,'levels':[{'label':'L10','readings':[{'specimen_ref':'A6','pressure':1}]}]},headers=auth('viewer'))
check('viewer cannot write batches',viewer.status_code==403,str(viewer.text)[:200])
check('viewer can read state',client.get(f'/studies/{sid}/state',headers=auth('viewer')).status_code==200)

r=client.patch('/readings/'+str(next(x['id'] for x in state.json()['readings'] if x['specimen_ref']=='A2')),json={'pressure':3.1,'measurement_note':'人工','expected_version':1},headers=auth())
check('manual patch applied',r.status_code==200 and r.json()['version']==2,str(r.text)[:200])
check('manual patch advanced study',r.json()['study_version']==3)
r=client.patch('/readings/'+str(next(x['id'] for x in state.json()['readings'] if x['specimen_ref']=='A2')),json={'pressure':3.2,'measurement_note':'陈旧','expected_version':1},headers=auth())
check('manual stale patch rejected',r.status_code==409 and '陈旧' in r.text,str(r.text)[:200])

batches=client.get(f'/studies/{sid}/batches',headers=auth())
check('batch log lists rejection reasons',batches.status_code==200 and any(b['status']=='rejected' and b['report'].get('reason') for b in batches.json()))
revisions=client.get(f'/studies/{sid}/revisions',headers=auth())
check('revision history readable',revisions.status_code==200 and len(revisions.json()['readings'])>=5)
old=[x for x in revisions.json()['readings'] if x['specimen_ref']=='A2']
check('old version retained after manual patch',old[0]['pressure']==3 and old[-1]['pressure']==3.1,str(old))

r=client.post('/studies',json={'name':'旧研究-'+uuid.uuid4().hex[:5],'filename':'legacy.csv','levels':[{'label':'X','flow':1,'readings':[{'specimen_ref':'X1','pressure':1}]},{'label':'Y','flow':2,'readings':[{'specimen_ref':'X2','pressure':3}]}]},headers=auth())
check('legacy-style study still creatable',r.status_code==200,str(r.text)[:200])
check('legacy study versioned',r.json()['current_version']==1)

print('FAILED' if failed else 'ALL PASS')
sys.exit(1 if failed else 0)

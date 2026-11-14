import hashlib,json
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.models import (FlowStudy,DoseLevel,PressureReading,DataBatch,
 DoseLevelRevision,PressureReadingRevision)
from src.schemas.batch import BatchInput
from src.utils.serialize import row
from .audit import record
from .validation import validate_source

class BatchRejected(Exception):
 def __init__(self,reason,message,details=None):
  super().__init__(message);self.reason=reason;self.message=message;self.details=details or {}

def payload_hash(study_id,data):
 payload={'study_id':study_id,'base_version':data.base_version,'levels':[l.model_dump() for l in data.levels]}
 return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def _state(db,study,levels):
 return {'study_id':study.id,'version':study.current_version,
  'levels':[{'id':l.id,'label':l.label,'flow':l.flow,'version':l.version} for l in levels],
  'readings':[{'id':r.id,'specimen_ref':r.specimen_ref,'level_id':r.level_id,'pressure':r.pressure,'measurement_note':r.measurement_note,'version':r.version} for r in db.scalars(select(PressureReading).where(PressureReading.study_id==study.id).order_by(PressureReading.specimen_ref))]}

def study_state(db,study_id):
 study=db.get(FlowStudy,study_id)
 if not study:raise HTTPException(404,'研究不存在')
 levels=list(db.scalars(select(DoseLevel).where(DoseLevel.study_id==study_id).order_by(DoseLevel.id)))
 return _state(db,study,levels)

def merge_batch(db,study_id,data:BatchInput,actor):
 if db.get(FlowStudy,study_id) is None:
  # No row to reject against; surface a typed 404 instead of a 500.
  raise HTTPException(404,{'reason':'study_missing','message':'研究不存在','status':'rejected'})
 existing=db.scalar(select(DataBatch).where(DataBatch.study_id==study_id,DataBatch.idempotency_key==data.idempotency_key))
 if existing:
  if existing.status=='applied':return _replay_or_reject(db,existing,study_id,data,actor)
  # A rejected batch wrote nothing. Re-sending it unchanged replays the
  # rejection; corrected content may reuse the key. The earlier rejection stays
  # in the audit log and the row is upserted, so keys never accumulate rows.
  if existing.payload_hash==payload_hash(study_id,data):return _replay_or_reject(db,existing,study_id,data,actor)
  db.delete(existing);db.flush()
 try:
  return _merge(db,study_id,data,actor)
 except BatchRejected as rejection:
  db.rollback()
  _record_rejection(study_id,data,actor,rejection)
  raise HTTPException(409,{'reason':rejection.reason,'message':rejection.message,'details':rejection.details,'status':'rejected'})
 except IntegrityError as error:
  # Unique-key race on the idempotency key: the competing request won. Re-read
  # and replay it if replayable; never apply the same batch twice.
  db.rollback()
  existing=db.scalar(select(DataBatch).where(DataBatch.study_id==study_id,DataBatch.idempotency_key==data.idempotency_key))
  if existing:return _replay_or_reject(db,existing,study_id,data,actor)
  raise HTTPException(409,{'reason':'concurrent_conflict','message':'并发写入冲突，整批未入库；请基于最新版本重试','details':{'database':str(error.orig)[:300]},'status':'rejected'})

def _replay_or_reject(db,existing,study_id,data,actor):
 if existing.payload_hash!=payload_hash(study_id,data):raise HTTPException(409,{'reason':'idempotency_key_reused','message':'同一幂等键已用于不同的补传内容；请换新键','details':{'batch_id':existing.id},'status':'rejected'})
 if existing.status=='applied':
  study=db.get(FlowStudy,study_id);levels=list(db.scalars(select(DoseLevel).where(DoseLevel.study_id==study_id).order_by(DoseLevel.id)))
  record(db,actor,'batch.replayed',{'batch_id':existing.id,'study_id':study_id,'version':existing.applied_version})
  return _batch_response(existing,_state(db,study,levels),replayed=True)
 raise HTTPException(409,{'reason':existing.report.get('reason','batch_rejected'),'message':existing.report.get('message','该幂等键此前整批被拒绝'),'details':existing.report.get('details',{}),'batch':row(existing),'status':'rejected'})

def _merge(db,study_id,data,actor):
 study=db.scalar(select(FlowStudy).where(FlowStudy.id==study_id).with_for_update())
 if not study:raise BatchRejected('study_missing','研究不存在')
 if data.base_version!=study.current_version:raise BatchRejected('stale_version','研究已推进到 v%s，提交基于 v%s 的批次已陈旧；请刷新后重做'%(study.current_version,data.base_version),{'current_version':study.current_version,'base_version':data.base_version})
 levels=list(db.scalars(select(DoseLevel).where(DoseLevel.study_id==study_id).order_by(DoseLevel.id)))
 readings={r.specimen_ref:r for r in db.scalars(select(PressureReading).where(PressureReading.study_id==study_id))}
 by_id={l.id:_target(l) for l in levels};by_label={l.label:_target(l) for l in levels}

 plan=_plan(data,levels,by_id,by_label,readings)
 if not plan['operations'] and not plan['level_corrections'] and not plan['level_creations']:
  return {'batch_id':None,'study_id':study_id,'idempotency_key':data.idempotency_key,'status':'no_change','base_version':data.base_version,'applied_version':None,'version':study.current_version,'report':{'added':[],'corrected':[],'ignored':plan['ignored'],'levels_created':[],'levels_corrected':[]},'state':_state(db,study,levels),'replayed':False,'reason':'no_change'}
 validate_plan_refs(plan,levels,readings)

 batch=DataBatch(study_id=study_id,idempotency_key=data.idempotency_key,payload_hash=payload_hash(study_id,data),base_version=data.base_version,created_by=actor,status='applied')
 db.add(batch);db.flush()
 created_level_ids={}
 try:
  for level in levels:
   correction=plan['level_corrections'].get(level.id)
   if not correction:continue
   level.label=correction['label'];level.flow=correction['flow'];level.version=correction['version']
   db.add(DoseLevelRevision(study_id=study_id,level_id=level.id,label=level.label,flow=level.flow,version=level.version,batch_id=batch.id,revision_source='batch',created_by=actor))
  for creation in plan['level_creations']:
   level=DoseLevel(study_id=study_id,label=creation['label'],flow=creation['flow'],version=1);db.add(level);db.flush()
   created_level_ids[creation['label']]=level.id
   db.add(DoseLevelRevision(study_id=study_id,level_id=level.id,label=level.label,flow=level.flow,version=1,batch_id=batch.id,revision_source='created',created_by=actor))
  for operation in plan['operations']:
   level_id=operation.get('level_id') or created_level_ids[operation['level_label']]
   if operation['action']=='added':
    reading=PressureReading(study_id=study_id,level_id=level_id,specimen_ref=operation['specimen_ref'],pressure=operation['pressure'],measurement_note=operation['measurement_note'],version=1);db.add(reading);db.flush()
    db.add(PressureReadingRevision(study_id=study_id,reading_id=reading.id,specimen_ref=reading.specimen_ref,level_id=level_id,level_label=operation['level_label'],level_flow=operation['level_flow'],pressure=reading.pressure,measurement_note=reading.measurement_note,version=1,batch_id=batch.id,revision_source='created',created_by=actor))
   else:
    reading=readings[operation['specimen_ref']]
    reading.level_id=level_id;reading.pressure=operation['pressure'];reading.measurement_note=operation['measurement_note'];reading.version=operation['version']
    db.add(PressureReadingRevision(study_id=study_id,reading_id=reading.id,specimen_ref=reading.specimen_ref,level_id=level_id,level_label=operation['level_label'],level_flow=operation['level_flow'],pressure=reading.pressure,measurement_note=reading.measurement_note,version=reading.version,batch_id=batch.id,revision_source='batch',created_by=actor))
  study.current_version+=1
  batch.applied_version=study.current_version
  db.flush()
  # Validate the merged source as a whole. Any failure rolls back every write.
  merged_levels=[{'id':l.id,'label':l.label,'flow':l.flow} for l in db.scalars(select(DoseLevel).where(DoseLevel.study_id==study_id))]
  merged_readings=[{'level_id':r.level_id,'specimen_ref':r.specimen_ref,'pressure':r.pressure} for r in db.scalars(select(PressureReading).where(PressureReading.study_id==study_id))]
  try:validate_source(merged_levels,merged_readings)
  except ValueError as error:raise BatchRejected('analysis_invalid','合并后的研究不满足分析条件：%s'%error,{'validation':str(error)})
  report={'added':plan['added'],'corrected':plan['corrected'],'ignored':plan['ignored'],'levels_created':plan['level_creations'],'levels_corrected':[{'level_id':k,**v} for k,v in plan['level_corrections'].items()]}
  batch.report=report;db.commit()
 except BatchRejected:
  db.rollback();raise
 except IntegrityError:
  db.rollback();raise
 record(db,actor,'batch.applied',{'batch_id':batch.id,'study_id':study_id,'version':batch.applied_version,'added':len(plan['added']),'corrected':len(plan['corrected']),'ignored':len(plan['ignored'])})
 return _batch_response(batch,study_state(db,study_id),replayed=False)

def _target(level):
 return {'id':level.id,'label':level.label,'flow':level.flow,'version':level.version}

def _plan(data,levels,by_id,by_label,readings):
 plan={'operations':[],'added':[],'corrected':[],'ignored':[],'level_creations':[],'level_corrections':{}}
 pending_labels={l.label for l in levels}
 seen_refs=set()
 creation_labels=set()
 for item in data.levels:
  if item.label is not None and item.label in creation_labels and item.label not in by_label:raise BatchRejected('duplicate_reference','档名 %s 在本批次内被重复引用'%item.label,{'label':item.label})
  target,creation=_resolve_level(item,by_id,by_label,levels)
  if creation:
   if item.label in by_label:raise BatchRejected('duplicate_label','档名 %s 已存在，不能重复新建'%item.label,{'label':item.label})
   pending_labels.add(item.label);creation_labels.add(item.label)
   if not item.readings:raise BatchRejected('empty_level','新档 %s 必须携带至少一条独立读数'%item.label,{'label':item.label})
   plan['level_creations'].append({'label':item.label,'flow':item.flow,'reading_count':len(item.readings)})
   target={'label':item.label,'flow':item.flow,'version':1,'id':None}
  else:
   target_label=item.label if item.label is not None else target['label']
   target_flow=item.flow if item.flow is not None else target['flow']
   changed=(target_label!=target['label'] or target_flow!=target['flow'])
   if changed:
    if item.version is None:raise BatchRejected('version_required','档位 %s 换档或改名须显式提交版本 v%s'%(target['label'],target['version']+1),{'level_id':target['id'],'current_version':target['version'],'expected_version':target['version']+1})
    if item.version<=target['version']:raise BatchRejected('stale_version','档位 %s 提交 v%s 不大于当前 v%s，拒绝陈旧换档'%(target['label'],item.version,target['version']),{'level_id':target['id'],'current_version':target['version'],'submitted_version':item.version})
    if item.version!=target['version']+1:raise BatchRejected('version_gap','档位 %s 提交 v%s 应紧接当前 v%s'%(target['label'],item.version,target['version']),{'level_id':target['id'],'current_version':target['version'],'expected_version':target['version']+1})
    if item.label is not None and item.label!=target['label'] and item.label in by_label and by_label[item.label]['id']!=target['id']:raise BatchRejected('duplicate_label','档名 %s 已属于另一档位'%item.label,{'label':item.label})
    if target['id'] in plan['level_corrections']:raise BatchRejected('duplicate_reference','档位 %s 在同一批次内被重复更正'%target['label'],{'level_id':target['id']})
    plan['level_corrections'][target['id']]={'label':target_label,'flow':target_flow,'version':item.version}
    if item.label is not None and item.label!=target['label']:
     revised=dict(target,label=target_label,flow=target_flow)
     by_label.pop(target['label'],None);by_label[target_label]=revised;by_id[target['id']]=revised
    plan['corrected'].append({'kind':'level','level_id':target['id'],'label':target_label,'flow':target_flow,'version':item.version,'from':{'label':target['label'],'flow':target['flow'],'version':target['version']}})
    target=dict(target,label=target_label,flow=target_flow,version=item.version)
  for reading in item.readings:
   if reading.specimen_ref in seen_refs:raise BatchRejected('duplicate_specimen','批次内滤片编号 %s 重复出现；同片重复测量不能当作独立重复'%reading.specimen_ref,{'specimen_ref':reading.specimen_ref})
   seen_refs.add(reading.specimen_ref)
   current=readings.get(reading.specimen_ref)
   level_label=target['label'];level_flow=target['flow'];level_id=target['id']
   if creation:
    if reading.version not in (None,1):raise BatchRejected('stale_version','新档 %s 的全新滤片 %s 只能从 v1 开始'%(target['label'],reading.specimen_ref),{'specimen_ref':reading.specimen_ref})
    operation={'action':'added','specimen_ref':reading.specimen_ref,'level_id':None,'level_label':level_label,'level_flow':level_flow,'pressure':reading.pressure,'measurement_note':reading.measurement_note,'version':1}
    plan['operations'].append(operation);plan['added'].append({'kind':'reading','specimen_ref':reading.specimen_ref,'level_label':level_label,'version':1});continue
   if current is None:
    if reading.version not in (None,1):raise BatchRejected('missing_reference','滤片 %s 在研究内不存在，不能以 v%s 凭空补录'%(reading.specimen_ref,reading.version),{'specimen_ref':reading.specimen_ref})
    operation={'action':'added','specimen_ref':reading.specimen_ref,'level_id':level_id,'level_label':level_label,'level_flow':level_flow,'pressure':reading.pressure,'measurement_note':reading.measurement_note,'version':1}
    plan['operations'].append(operation);plan['added'].append({'kind':'reading','specimen_ref':reading.specimen_ref,'level_label':level_label,'version':1});continue
   same=(current.pressure==reading.pressure and current.measurement_note==reading.measurement_note and current.level_id==level_id)
   if same:
    plan['ignored'].append({'kind':'reading','specimen_ref':reading.specimen_ref,'reason':'identical','message':'与当前 v%s 内容相同，未重复计入权重'%current.version,'version':current.version});continue
   if reading.version is None:raise BatchRejected('version_required','滤片 %s 内容有变，须显式提交版本 v%s'%(reading.specimen_ref,current.version+1),{'specimen_ref':reading.specimen_ref,'current_version':current.version,'expected_version':current.version+1})
   if reading.version<current.version:raise BatchRejected('stale_version','滤片 %s 提交 v%s 早于已存 v%s，旧版不回滚'%(reading.specimen_ref,reading.version,current.version),{'specimen_ref':reading.specimen_ref,'current_version':current.version,'submitted_version':reading.version})
   if reading.version==current.version:raise BatchRejected('version_conflict','滤片 %s 同版 v%s 内容冲突，拒绝静默覆盖'%(reading.specimen_ref,current.version),{'specimen_ref':reading.specimen_ref,'version':current.version,'existing':{'pressure':current.pressure,'measurement_note':current.measurement_note,'level_id':current.level_id},'submitted':{'pressure':reading.pressure,'measurement_note':reading.measurement_note,'level_id':level_id}})
   if reading.version!=current.version+1:raise BatchRejected('version_gap','滤片 %s 提交 v%s 应紧接当前 v%s'%(reading.specimen_ref,reading.version,current.version),{'specimen_ref':reading.specimen_ref,'current_version':current.version,'expected_version':current.version+1})
   operation={'action':'corrected','specimen_ref':reading.specimen_ref,'level_id':level_id,'level_label':level_label,'level_flow':level_flow,'pressure':reading.pressure,'measurement_note':reading.measurement_note,'version':reading.version}
   plan['operations'].append(operation);plan['corrected'].append({'kind':'reading','specimen_ref':reading.specimen_ref,'level_label':level_label,'version':reading.version})
 if not plan['operations'] and not plan['level_corrections'] and not plan['level_creations']:
  plan['ignored'].append({'kind':'batch','reason':'no_change','message':'批次没有带来新读数或有效更正，未改变研究版本'})
 return plan

def _resolve_level(item,by_id,by_label,levels):
 if item.id is not None:
  if item.id not in by_id:raise BatchRejected('missing_reference','档位 id %s 不属于该研究'%item.id,{'level_id':item.id})
  return by_id[item.id],False
 if item.label is not None and item.label in by_label:return by_label[item.label],False
 if item.create:
  if item.label is None or item.flow is None:raise BatchRejected('missing_reference','新建档位必须同时给出标签与流速',{})
  return None,True
 if item.label is not None:
  raise BatchRejected('missing_reference','档名 %s 不存在；属实需新建请带 create=true 与流速'%item.label,{'label':item.label})
 if item.flow is not None:
  matches=[l for l in levels if l.flow==item.flow]
  if len(matches)!=1:raise BatchRejected('ambiguous_reference','流速 %s 匹配到 %d 个档位；请改用档位 id 或标签'%(item.flow,len(matches)),{'flow':item.flow,'matches':len(matches)})
  return matches[0],False
 raise BatchRejected('missing_reference','每个批次档位须给出 id、标签或流速之一',{})

def validate_plan_refs(plan,levels,readings):
 known={l.id for l in levels}
 for correction_id in plan['level_corrections']:
  if correction_id not in known:raise BatchRejected('missing_reference','档位 id %s 不属于该研究'%correction_id,{'level_id':correction_id})
 for operation in plan['operations']:
  if operation['action']=='corrected' and operation['level_id'] not in known and operation['level_label'] not in {c['label'] for c in plan['level_creations']}:
   raise BatchRejected('missing_reference','滤片 %s 指向的档位不存在'%operation['specimen_ref'],{'specimen_ref':operation['specimen_ref']})

def _batch_response(batch,state,replayed):
 return {'batch_id':batch.id if batch else None,'study_id':state['study_id'],'idempotency_key':batch.idempotency_key if batch else None,'status':batch.status if batch else 'no_change','base_version':batch.base_version if batch else state['version'],'applied_version':batch.applied_version if batch else None,'version':state['version'],'report':batch.report if batch else {'added':[],'corrected':[],'ignored':[{'kind':'batch','reason':'no_change','message':'批次没有带来新读数或有效更正，未改变研究版本'}],'levels_created':[],'levels_corrected':[]},'state':state,'replayed':replayed}

def _record_rejection(study_id,data,actor,rejection):
 """Keep the rejection visible on the batch log without burning the key."""
 try:
  from src.config.database import SessionLocal
  with SessionLocal() as db:
   if not db.get(FlowStudy,study_id):return
   report={'reason':rejection.reason,'message':rejection.message,'details':rejection.details}
   batch=db.scalar(select(DataBatch).where(DataBatch.study_id==study_id,DataBatch.idempotency_key==data.idempotency_key).with_for_update())
   if batch and batch.status=='applied':
    # A concurrent request already applied this key: never rewrite its outcome.
    record(db,actor,'batch.rejected.after_apply',{'batch_id':batch.id,'study_id':study_id,'reason':rejection.reason});return
   if batch:
    batch.payload_hash=payload_hash(study_id,data);batch.base_version=data.base_version;batch.report=report;batch.status='rejected';batch.applied_version=None;batch.created_by=actor
   else:
    batch=DataBatch(study_id=study_id,idempotency_key=data.idempotency_key,payload_hash=payload_hash(study_id,data),base_version=data.base_version,status='rejected',report=report,created_by=actor);db.add(batch)
   db.commit();record(db,actor,'batch.rejected',{'batch_id':batch.id,'study_id':study_id,'reason':rejection.reason})
 except Exception:
  pass

def list_batches(db,study_id):
 if not db.get(FlowStudy,study_id):raise HTTPException(404,'研究不存在')
 return [row(b) for b in db.scalars(select(DataBatch).where(DataBatch.study_id==study_id).order_by(DataBatch.id.desc()))]

def revision_history(db,study_id):
 if not db.get(FlowStudy,study_id):raise HTTPException(404,'研究不存在')
 levels=[row(r) for r in db.scalars(select(DoseLevelRevision).where(DoseLevelRevision.study_id==study_id).order_by(DoseLevelRevision.level_id,DoseLevelRevision.version))]
 readings=[row(r) for r in db.scalars(select(PressureReadingRevision).where(PressureReadingRevision.study_id==study_id).order_by(PressureReadingRevision.specimen_ref,PressureReadingRevision.version))]
 return {'levels':levels,'readings':readings}

def baseline_revisions(db,study_id):
 """Materialise v1 history for studies imported before versioning existed."""
 study=db.get(FlowStudy,study_id)
 if not study:return
 levels=list(db.scalars(select(DoseLevel).where(DoseLevel.study_id==study_id)))
 for level in levels:
  if db.scalar(select(DoseLevelRevision).where(DoseLevelRevision.level_id==level.id,DoseLevelRevision.version==level.version)):continue
  db.add(DoseLevelRevision(study_id=study_id,level_id=level.id,label=level.label,flow=level.flow,version=level.version,revision_source='legacy_baseline',created_by='system'))
 for reading in db.scalars(select(PressureReading).where(PressureReading.study_id==study_id)):
  if db.scalar(select(PressureReadingRevision).where(PressureReadingRevision.reading_id==reading.id,PressureReadingRevision.version==reading.version)):continue
  level=db.get(DoseLevel,reading.level_id)
  db.add(PressureReadingRevision(study_id=study_id,reading_id=reading.id,specimen_ref=reading.specimen_ref,level_id=reading.level_id,level_label=level.label if level else '',level_flow=level.flow if level else 0,pressure=reading.pressure,measurement_note=reading.measurement_note,version=reading.version,revision_source='legacy_baseline',created_by='system'))
 db.commit()

from sqlalchemy import select
from fastapi import HTTPException
from src.models import FlowStudy,DoseLevel,PressureReading,DoseLevelRevision,PressureReadingRevision
from src.utils.serialize import row
from .validation import validate_source
from .audit import record

def create_study(db,data,actor):
 if db.scalar(select(FlowStudy).where(FlowStudy.name==data.name)):raise HTTPException(409,'研究名称已存在')
 levels=[{'id':i+1,'label':l.label,'flow':l.flow} for i,l in enumerate(data.levels)];readings=[dict(r.model_dump(),level_id=i+1) for i,l in enumerate(data.levels) for r in l.readings]
 try:validate_source(levels,readings)
 except ValueError as e:raise HTTPException(422,str(e))
 study=FlowStudy(**data.model_dump(exclude={'levels'}));study.current_version=1;db.add(study);db.flush()
 for source in data.levels:
  level=DoseLevel(study_id=study.id,label=source.label,flow=source.flow,version=1);db.add(level);db.flush()
  db.add(DoseLevelRevision(study_id=study.id,level_id=level.id,label=level.label,flow=level.flow,version=1,revision_source='baseline',created_by=actor))
  for reading in source.readings:
   item=PressureReading(study_id=study.id,level_id=level.id,version=1,**reading.model_dump());db.add(item);db.flush()
   db.add(PressureReadingRevision(study_id=study.id,reading_id=item.id,specimen_ref=item.specimen_ref,level_id=level.id,level_label=level.label,level_flow=level.flow,pressure=item.pressure,measurement_note=item.measurement_note,version=1,revision_source='baseline',created_by=actor))
 db.commit();record(db,actor,'study.imported',{'study_id':study.id,'levels':len(levels),'readings':len(readings),'version':1});return row(study)

def source_data(db,id):
 study=db.get(FlowStudy,id)
 if not study:raise HTTPException(404,'研究不存在')
 return row(study),[row(x) for x in db.scalars(select(DoseLevel).where(DoseLevel.study_id==id).order_by(DoseLevel.id))],[row(x) for x in db.scalars(select(PressureReading).where(PressureReading.study_id==id).order_by(PressureReading.specimen_ref))]

def _check_expected(expected,current,what,ident):
 """Optimistic concurrency guard shared by manual revisions."""
 if expected is None:
  if current>1:raise HTTPException(409,'%s %s 已修订到 v%s；请刷新并携带 expected_version 后再改，旧版不回滚'%(what,ident,current))
  return
 if expected<current:raise HTTPException(409,'%s %s 当前 v%s，提交基于 v%s 的修改已陈旧，拒绝覆盖'%(what,ident,current,expected))
 if expected>current:raise HTTPException(409,'%s %s 当前 v%s，提交的 v%s 尚未存在；请刷新'%(what,ident,current,expected))

def edit_reading(db,id,data,actor):
 item=db.scalar(select(PressureReading).where(PressureReading.id==id).with_for_update())
 if not item:raise HTTPException(404,'读数不存在')
 if item.pressure==data.pressure and item.measurement_note==data.measurement_note:return {'reading':row(item),'version':item.version,'ignored':True,'message':'内容与当前版本相同，未重复计入权重'}
 _check_expected(data.expected_version,item.version,'读数',item.specimen_ref)
 item.pressure=data.pressure;item.measurement_note=data.measurement_note;item.version+=1
 study=db.get(FlowStudy,item.study_id);study.current_version+=1
 level=db.get(DoseLevel,item.level_id)
 db.add(PressureReadingRevision(study_id=item.study_id,reading_id=item.id,specimen_ref=item.specimen_ref,level_id=item.level_id,level_label=level.label if level else '',level_flow=level.flow if level else 0,pressure=item.pressure,measurement_note=item.measurement_note,version=item.version,revision_source='manual',created_by=actor))
 db.flush()
 try:
  _,levels,readings=source_data(db,item.study_id);validate_source(levels,readings)
 except ValueError as e:db.rollback();raise HTTPException(422,str(e))
 db.commit();record(db,actor,'reading.revised',{'reading_id':id,'specimen_ref':item.specimen_ref,'version':item.version,'study_version':study.current_version});return {'reading':row(item),'version':item.version,'study_version':study.current_version,'ignored':False}

def edit_level(db,id,data,actor):
 level=db.scalar(select(DoseLevel).where(DoseLevel.id==id).with_for_update())
 if not level:raise HTTPException(404,'档位不存在')
 if level.label==data.label and level.flow==data.flow:return {'level':row(level),'version':level.version,'ignored':True,'message':'内容与当前版本相同，未改变研究版本'}
 _check_expected(data.expected_version,level.version,'档位',level.label)
 if db.scalar(select(DoseLevel).where(DoseLevel.study_id==level.study_id,DoseLevel.label==data.label,DoseLevel.id!=id)):raise HTTPException(409,'研究内档名重复')
 old=(level.label,level.flow,level.version);level.label=data.label;level.flow=data.flow;level.version+=1
 study=db.get(FlowStudy,level.study_id);study.current_version+=1;db.flush()
 try:
  _,levels,readings=source_data(db,level.study_id);validate_source(levels,readings)
 except ValueError as e:db.rollback();raise HTTPException(422,str(e))
 db.add(DoseLevelRevision(study_id=level.study_id,level_id=level.id,label=level.label,flow=level.flow,version=level.version,revision_source='manual',created_by=actor))
 db.commit();record(db,actor,'level.revised',{'level_id':id,'old_label':old[0],'old_flow':old[1],'old_version':old[2],'version':level.version,'study_version':study.current_version});return {'level':row(level),'version':level.version,'study_version':study.current_version,'ignored':False}

import hashlib,json
VERSION='weighted-pava-lodo-v1'
def fingerprint(study,levels,readings,config):
 payload={'version':VERSION,'study':{k:study[k] for k in ('id','name','filename','description','direction')},'levels':sorted([{k:l[k] for k in ('id','label','flow')} for l in levels],key=lambda x:x['id']),'readings':sorted([{k:r[k] for k in ('specimen_ref','level_id','pressure','measurement_note')} for r in readings],key=lambda x:x['specimen_ref']),'config':config}
 return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

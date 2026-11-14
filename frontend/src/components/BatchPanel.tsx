import {useMemo,useState} from 'react';
import {sourceApi} from '../api/source';
import {useTask} from '../hooks/useTask';
import {Notice} from './common/Notice';
import type {BatchResult} from '../types/domain';

export const REASONS:Record<string,string>={
  stale_version:'提交基于陈旧版本：研究已被补传或人工修订推进，需刷新后基于最新版本重做',
  version_conflict:'同一滤片同一版本出现不同内容，拒绝静默覆盖',
  version_required:'内容有变但未带目标版本号',
  version_gap:'版本号须紧接当前版本 +1，不接受跳跃',
  duplicate_specimen:'批次内滤片编号重复；同片重复测量不能当作独立重复',
  missing_reference:'引用的档位或滤片不存在，不能凭空补录',
  analysis_invalid:'合并后的研究不满足分析条件（档数、读数、独特流速、规格上限等）',
  idempotency_key_reused:'同一幂等键此前用于不同内容，请换新键',
  duplicate_label:'档名与研究内或批次内其他档位冲突',
  empty_level:'新建档位必须携带至少一条独立读数',
  ambiguous_reference:'仅按流速无法唯一定位档位，请改用档位 id 或标签',
  no_change:'批次没有带来新读数或有效更正，未新建版本',
  identical:'与当前版本内容相同，未重复计入权重',
  invalid_json:'批次 JSON 无法解析'
};
const newKey=()=>'batch-'+(globalThis.crypto?.randomUUID?.()||Math.random().toString(36).slice(2)).replace(/-/g,'').slice(0,24);
const reasonLabel=(reason?:string)=>reason?(REASONS[reason]||reason):'请求被拒绝';
const example=(levels:any[])=>JSON.stringify({levels:[{label:levels[0]?.label||'F01',readings:[{specimen_ref:(levels[0]?.label||'F01')+'-补09',pressure:1.74}]}]},null,2);

export function BatchPanel({study,state,reloadSource,reloadBatches}:{study:any;state:any;reloadSource:()=>Promise<void>;reloadBatches:()=>Promise<void>}){
 const [raw,R]=useState(()=>example(state.levels));
 const [key,K]=useState(newKey);
 const [lastSent,Sent]=useState<{key:string;body:any}|null>(null);
 const [result,S]=useState<BatchResult|null>(null);
 const [rejection,E]=useState<any>(null);
 const task=useTask();
 const levelHint=useMemo(()=>state.levels.map((l:any)=>`${l.label} v${l.version} @ ${l.flow}`).join('　'),[state.levels]);

 async function submit(body:any,message:string){
  S(null);E(null);
  await task.act(async()=>{
   Sent({key:body.idempotency_key,body});
   try{
    const value:BatchResult=await sourceApi.mergeBatch(study.id,body);
    S(value);await reloadSource();await reloadBatches();
    if(value.status!=='rejected'){K(newKey());Sent(null)}
    return value;
   }catch(error:any){
    E({reason:error.reason,message:error.message,details:error.details});
    await reloadSource();await reloadBatches();
    throw error;
   }
  },message);
 }
 function apply(){
  let parsed:any;
  try{parsed=JSON.parse(raw)}catch(error:any){E({reason:'invalid_json',message:'批次 JSON 无法解析：'+error.message});return}
  submit({...parsed,idempotency_key:key,base_version:state.version},'批次已应用为研究 v'+(state.version+1));
 }
 function retry(){if(lastSent)submit(lastSent.body,'已按原幂等键原样重试，不会重复计入权重')}

 return <section className="batch-panel">
  <div className="section-head"><h2>分批补传 / 更正</h2><span>研究 v{state.version} · 按滤片编号识别重复</span></div>
  <p>只提交本批新增或更正的档位/读数，研究其余历史保持不变。补录新滤片用新编号；更正已有滤片须带 <code>version=当前+1</code>；换档须给档位带上目标 <code>version</code> 与 <code>flow</code>。任何一项不合法，整批不入库。</p>
  <p className="batch-key">当前档位：{levelHint||'—'}</p>
  <label>批次 JSON<textarea rows={13} value={raw} onChange={e=>R(e.target.value)} spellCheck={false}/></label>
  <p className="batch-key">幂等键 <code>{key}</code>　基础版本 <code>v{state.version}</code></p>
  <div className="batch-actions">
   <button className="primary" disabled={task.busy||!study} onClick={apply}>应用为研究 v{state.version+1} →</button>
   <button disabled={task.busy||!lastSent} onClick={retry}>按原幂等键原样重试</button>
   <button disabled={task.busy} onClick={()=>{K(newKey());Sent(null);S(null);E(null)}}>换新键</button>
   <button disabled={task.busy} onClick={()=>R(example(state.levels))}>填入示例</button>
  </div>
  <Notice message={task.message}/>
  {rejection&&<div className="reject-detail">
   <strong>拒绝原因 / {rejection.reason||'rejected'}</strong>
   <p>{rejection.reason==='invalid_json'?rejection.message:reasonLabel(rejection.reason)}</p>
   {rejection.message&&rejection.reason!=='invalid_json'&&<p>{rejection.message}</p>}
   {rejection.details&&Object.keys(rejection.details).length>0&&<pre>{JSON.stringify(rejection.details,null,2)}</pre>}
  </div>}
  {result&&<BatchReport result={result}/>}
 </section>
}

function BatchReport({result}:{result:BatchResult}){
 const r=result.report;
 return <div className="batch-result">
  <div className="section-head"><h2>{result.status==='no_change'?'无变化，未新建版本':`已应用 v${result.applied_version??result.version}`}</h2><span>{result.replayed?'幂等重放：未重复写入，权重不变':'一次原子写入'}</span></div>
  <div className="batch-counts">
   <span className="ok">新增 {r.added.length}</span>
   <span className="ok">更正 {r.corrected.length}</span>
   <span className="muted">忽略 {r.ignored.length}</span>
   {r.levels_created.length>0&&<span className="ok">新建档 {r.levels_created.length}</span>}
   {r.levels_corrected.length>0&&<span className="ok">换档/改名 {r.levels_corrected.length}</span>}
  </div>
  {(r.added.length>0||r.corrected.length>0||r.levels_created.length>0||r.levels_corrected.length>0)&&<ul className="batch-list">
   {r.levels_created.map((e,i)=><li key={'lc'+i}><b>新建档</b> {e.label} / {e.flow} mL/min</li>)}
   {r.levels_corrected.map((e,i)=><li key={'lv'+i}><b>换档/改名</b> 档位 {e.level_id} → {e.label} / {e.flow} mL/min v{e.version}</li>)}
   {r.added.map((e,i)=><li key={'a'+i}><b>新增</b> {e.specimen_ref} @ {e.level_label} v{e.version}</li>)}
   {r.corrected.map((e,i)=><li key={'c'+i}><b>更正</b> {(e as any).specimen_ref||('档位 '+e.level_id)} {(e as any).level_label?('@ '+(e as any).level_label):''} v{e.version}</li>)}
  </ul>}
  {r.ignored.length>0&&<ul className="batch-list ignored">
   {r.ignored.map((e,i)=><li key={'i'+i}><b>忽略</b> {e.specimen_ref||e.label||e.kind}：{e.reason?reasonLabel(e.reason):e.message}</li>)}
  </ul>}
 </div>
}

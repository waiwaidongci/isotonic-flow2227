import {useEffect,useState} from 'react';
import {PageHeading} from '../components/common/PageHeading';
import {Table} from '../components/common/Table';
import {Notice} from '../components/common/Notice';
import {BatchPanel} from '../components/BatchPanel';
import {useTask} from '../hooks/useTask';
import {sourceApi} from '../api/source';
import {useSourceBatch,useStudyState} from '../stores/batch';
import {REASONS} from '../components/BatchPanel';
import {fmt,clock} from '../utils/format';

const example={name:'独立滤片三档手算输入',filename:'fw-independent-3doses.json',description:'同x按原始独立滤片数合并；方向预先声明',direction:'nondecreasing',levels:[{label:'低档',flow:1,readings:[{specimen_ref:'P01',pressure:3}]},{label:'中档',flow:2,readings:[{specimen_ref:'P02',pressure:1},{specimen_ref:'P03',pressure:1},{specimen_ref:'P04',pressure:1}]},{label:'高档',flow:3,readings:[{specimen_ref:'P05',pressure:2}]}]};

export function SourcePage({studies,levels,readings,user,reloadSource}:any){
 const [id,S]=useState(0),[raw,R]=useState(JSON.stringify(example,null,2)),task=useTask();
 const study=studies.find((s:any)=>s.id===(id||studies[0]?.id));
 const ls=levels.filter((l:any)=>l.study_id===study?.id),rs=readings.filter((r:any)=>r.study_id===study?.id);
 const {state,reloadState}=useStudyState(study?.id);
 const {batches,revisions,reloadBatches}=useSourceBatch();
 const refresh=async()=>{await Promise.all([reloadSource(),reloadState(),reloadBatches(study?.id)])};
 useEffect(()=>{if(study?.id)reloadBatches(study.id)},[study?.id,reloadBatches]);
 return <>
  <PageHeading index="02" title="每一片独立滤片，都有来路。" description="流速可重合，滤片编号不能重复；补传与更正按版本合并，旧版保留可读。"/>
  <label>来源研究<select value={study?.id||''} onChange={e=>{S(+e.target.value);reloadBatches(+e.target.value)}}>{studies.map((s:any)=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
  {study&&<p>{study.filename} / {study.description} / 预先声明 {study.direction} / 当前版本 <strong className="brass">v{study.current_version}</strong></p>}
  <div className="source-layout"><section>
   <h2>档位与独立重复数</h2>
   <Table headers={['档位','流速 mL/min','版本','独立数 / 均压差','修订']}>
    {ls.map((l:any)=>{const items=rs.filter((r:any)=>r.level_id===l.id);return <tr key={l.id}>
     <td>{l.label}</td><td>{fmt(l.flow)}</td><td>v{l.version}</td>
     <td>{items.length} / {fmt(items.reduce((a:number,r:any)=>a+r.pressure,0)/items.length)}</td>
     <td>{user.role!=='viewer'&&<button onClick={()=>{
      const flow=prompt('修订流速（同x会合并；换档会保留旧版本，需刷新后重试陈旧修改）',String(l.flow));
      if(flow===null)return;
      task.act(async()=>{const r=await sourceApi.editLevel(l.id,{label:l.label,flow:+flow,expected_version:l.version});await refresh();return r},'档位已修订为 v'+(l.version+1))
     }}>修订流速</button>}</td>
    </tr>})}
   </Table>
   <h2 className="spaced">原始滤片 / 前24条</h2>
   <Table headers={['滤片编号','档位','压差 kPa','版本','测量说明','修订']}>
    {rs.slice(0,24).map((r:any)=><tr key={r.id}>
     <td>{r.specimen_ref}</td><td>{ls.find((l:any)=>l.id===r.level_id)?.label||'—'}</td>
     <td>{fmt(r.pressure,6)}</td><td>v{r.version}</td><td>{r.measurement_note}</td>
     <td>{user.role!=='viewer'&&<button onClick={()=>{
      const value=prompt('修订原始压差（提交基于 v'+r.version+'；若已有人先改，会拒绝陈旧修改）',String(r.pressure));
      if(value===null)return;
      task.act(async()=>{const changed=await sourceApi.editReading(r.id,{pressure:+value,measurement_note:r.measurement_note,expected_version:r.version});await refresh();return changed},'原始读数已修订为 v'+(r.version+1))
     }}>修订读数</button>}</td>
    </tr>)}
   </Table>
   <RevisionHistory revisions={revisions}/>
  </section>
  <section className="input-panel">
   <small>NEW INDEPENDENT STUDY</small>
   <h2>新建完整研究</h2>
   <p>首次导入仍可整份新建；后续分批补传请用下方批次面板。2–30档、总计≤600读数；同流速档合并而不是任意赋权。</p>
   {user.role!=='viewer'?<form onSubmit={e=>{e.preventDefault();task.act(async()=>{const s=await sourceApi.create(JSON.parse(raw));await reloadSource();S(s.id)},'独立研究已保存，可前往拟合配置')}}>
    <label>研究 JSON<textarea rows={14} value={raw} onChange={e=>R(e.target.value)}/></label>
    <button className="primary" disabled={task.busy}>保存独立研究 →</button>
   </form>:<p>观察员可读取底稿；新研究由试验员提交。</p>}
   <Notice error={task.error} message={task.message}/>
  </section></div>
  {study&&<div className="batch-layout">
   {user.role!=='viewer'&&state?<BatchPanel study={study} state={state} reloadSource={refresh} reloadBatches={()=>reloadBatches(study.id)}/>:<section className="batch-panel"><div className="section-head"><h2>分批补传 / 更正</h2><span>观察员只读</span></div><p>观察员可查看批次记录与修订历史；补传由试验员提交。</p></section>}
   <BatchLog batches={batches}/>
  </div>}
 </>
}

function RevisionHistory({revisions}:{revisions:{levels:any[];readings:any[]}}){
 const [open,O]=useState(false);
 return <details className="revision-history" open={open} onToggle={e=>O((e.target as HTMLDetailsElement).open)}>
  <summary>版本历史 / 旧版保留，不回滚（档位 {revisions.levels.length} 条，读数 {revisions.readings.length} 条）</summary>
  <Table headers={['对象','版本','内容','来源','写入人','时间']}>
   {revisions.levels.map((v:any)=><tr key={'lv'+v.id}><td>档位 {v.level_id}</td><td>v{v.version}</td><td>{v.label} / {fmt(v.flow)} mL/min</td><td>{sourceLabel(v.revision_source)}</td><td>{v.created_by}</td><td>{clock(v.created_at)}</td></tr>)}
   {revisions.readings.map((v:any)=><tr key={'rv'+v.id}><td>{v.specimen_ref}</td><td>v{v.version}</td><td>{v.level_label} @ {fmt(v.level_flow)} / {fmt(v.pressure,6)} kPa</td><td>{sourceLabel(v.revision_source)}</td><td>{v.created_by}</td><td>{clock(v.created_at)}</td></tr>)}
  </Table>
 </details>
}

function BatchLog({batches}:{batches:any[]}){
 const [open,O]=useState(0);
 if(!batches.length)return <section className="batch-log"><div className="section-head"><h2>批次记录</h2><span>尚无分批补传</span></div></section>;
 return <section className="batch-log">
  <div className="section-head"><h2>批次记录</h2><span>{batches.length} 批 / 拒绝与忽略原因保留</span></div>
  <Table headers={['批次','状态','基础版本','结果版本','新增 / 更正 / 忽略','原因 / 幂等键','展开']}>
   {batches.map((b:any)=>{const r=b.report||{};const ignored=(r.ignored||[]).length;return <tr key={b.id}>
    <td>#{b.id}<small>{clock(b.created_at)}</small></td>
    <td><Status value={b.status}/></td><td>{b.base_version?('v'+b.base_version):'—'}</td>
    <td>{b.applied_version?('v'+b.applied_version):'—'}</td>
    <td>{(r.added||[]).length} / {(r.corrected||[]).length} / {ignored}</td>
    <td>{b.status==='rejected'?<span className="error-text">{reasonText(r)}</span>:'—'}<small>{b.idempotency_key}</small></td>
    <td><button onClick={()=>O(open===b.id?0:b.id)}>{open===b.id?'收起':'展开'}</button></td>
   </tr>})}
  </Table>
  {batches.filter((b:any)=>b.id===open).map((b:any)=><BatchDetail key={b.id} batch={b}/>)}
 </section>
}

function BatchDetail({batch}:{batch:any}){
 const r=batch.report||{};
 return <div className="batch-detail">
  {batch.status==='rejected'&&<div className="reject-detail"><strong>整批拒绝 / {r.reason}</strong><p>{r.message}</p>{r.details&&Object.keys(r.details).length>0&&<pre>{JSON.stringify(r.details,null,2)}</pre>}</div>}
  {batch.status==='applied'&&<>
   {(r.added||[]).length>0&&<p><b>新增</b> {(r.added||[]).map((e:any)=>e.specimen_ref||e.label).join('、')}</p>}
   {(r.corrected||[]).length>0&&<p><b>更正</b> {(r.corrected||[]).map((e:any)=>e.specimen_ref||('档位'+e.level_id)).join('、')}</p>}
   {(r.levels_created||[]).length>0&&<p><b>新建档</b> {(r.levels_created||[]).map((e:any)=>e.label+' / '+e.flow).join('、')}</p>}
   {(r.levels_corrected||[]).length>0&&<p><b>换档</b> {(r.levels_corrected||[]).map((e:any)=>e.label+' / '+e.flow+' v'+e.version).join('、')}</p>}
   {(r.ignored||[]).length>0&&<p><b>忽略</b> {(r.ignored||[]).map((e:any)=>(e.specimen_ref||e.kind)+'：'+(REASON_TEXT[e.reason]||e.message||e.reason)).join('；')}</p>}
  </>}
 </div>
}

const REASON_TEXT=REASONS;
const sourceLabel=(s:string)=>s==='batch'?'批次补传':s==='created'?'新建':s==='manual'?'人工修订':s==='baseline'?'初次导入':s==='legacy_baseline'?'兼容底稿':'系统';
const reasonText=(r:any)=>REASON_TEXT[r?.reason]||r?.message||r?.reason||'拒绝';
function Status({value}:{value:string}){return <span className={'status '+value}>{value==='applied'?'已应用':value==='rejected'?'已拒绝':'无变化'}</span>}

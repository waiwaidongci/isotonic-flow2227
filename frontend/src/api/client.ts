export async function request<T=any>(path:string,options:RequestInit={}):Promise<T>{
  const token=localStorage.getItem('fw28-token');
  const response=await fetch('/api'+path,{...options,headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{}),...options.headers}});
  if(!response.ok){
    const body=await response.json().catch(()=>({detail:'网络请求失败'}));
    if(response.status===401&&path!='/auth/login'){localStorage.removeItem('fw28-token');window.dispatchEvent(new Event('session-expired'))}
    const detail=body.detail;
    let message:string;
    if(typeof detail==='string')message=detail;
    else if(Array.isArray(detail))message=detail.map((e:any)=>e.message||JSON.stringify(e)).join('；');
    else if(detail&&typeof detail==='object')message=[detail.message||'请求被拒绝',detail.reason?`（${detail.reason}）`:''].join('');
    else message='网络请求失败';
    const error:any=new Error(message);
    error.reason=detail&&typeof detail==='object'?detail.reason:undefined;
    error.details=detail&&typeof detail==='object'?detail.details:undefined;
    error.status=response.status;
    throw error;
  }
  return response.json();
}
export const post=(path:string,data:unknown)=>request(path,{method:'POST',body:JSON.stringify(data)});
export const patch=(path:string,data:unknown)=>request(path,{method:'PATCH',body:JSON.stringify(data)});
export async function download(path:string,filename:string){const response=await fetch('/api'+path,{headers:{Authorization:'Bearer '+localStorage.getItem('fw28-token')}});if(!response.ok)throw Error('只能导出已批准说明，请刷新状态后重试');const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=filename;a.click();URL.revokeObjectURL(url)}

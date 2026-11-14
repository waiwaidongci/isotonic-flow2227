import {request,post,patch} from './client';
export const sourceApi={
  studies:()=>request('/studies'),
  levels:()=>request('/levels'),
  readings:()=>request('/readings'),
  state:(id:number)=>request('/studies/'+id+'/state'),
  batches:(id:number)=>request('/studies/'+id+'/batches'),
  revisions:(id:number)=>request('/studies/'+id+'/revisions'),
  mergeBatch:(id:number,data:any)=>post('/studies/'+id+'/batches',data),
  create:(data:any)=>post('/studies',data),
  editLevel:(id:number,data:any)=>patch('/levels/'+id,data),
  editReading:(id:number,data:any)=>patch('/readings/'+id,data)
};

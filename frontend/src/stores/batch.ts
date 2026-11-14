import {useCallback,useEffect,useState} from 'react';
import {sourceApi} from '../api/source';

export function useSourceBatch(){
 const [batchError,E]=useState('');
 const [batches,B]=useState<any[]>([]);
 const [revisions,V]=useState<{levels:any[];readings:any[]}>({levels:[],readings:[]});
 const reloadBatches=useCallback(async(studyId:number)=>{
  if(!studyId){B([]);V({levels:[],readings:[]});return}
  try{
   const [b,r]=await Promise.all([sourceApi.batches(studyId),sourceApi.revisions(studyId)]);
   B(b);V(r);E('');
  }catch(error:any){E(error.message)}
 },[]);
 return {batches,revisions,batchError,reloadBatches};
}

export function useStudyState(studyId:number|undefined){
 const [state,S]=useState<any>(null);
 const reloadState=useCallback(async()=>{
  if(!studyId){S(null);return}
  try{S(await sourceApi.state(studyId))}catch{S(null)}
 },[studyId]);
 useEffect(()=>{reloadState()},[reloadState]);
 return {state,reloadState};
}

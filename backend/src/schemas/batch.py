from pydantic import BaseModel,Field,ConfigDict
class BatchReadingInput(BaseModel):
 """A supplemental or corrected reading, identified by specimen number."""
 model_config=ConfigDict(allow_inf_nan=False,extra='forbid')
 specimen_ref:str=Field(min_length=1,max_length=80)
 pressure:float=Field(ge=0,le=1000000)
 measurement_note:str=Field(default='',max_length=1000)
 # Target version for a correction. It must be exactly current+1; a lower or
 # equal version with different content is rejected as stale/conflict.
 version:int|None=Field(default=None,ge=1)
class BatchLevelInput(BaseModel):
 """A level target or correction inside one batch.

 Existing levels are addressed by id, label, or a unique flow. `create=true`
 with label+flow declares a genuinely new level. A label/flow change is a
 level correction and needs a target `version` (current+1).
 """
 model_config=ConfigDict(allow_inf_nan=False,extra='forbid')
 id:int|None=Field(default=None,gt=0)
 label:str|None=Field(default=None,min_length=1,max_length=80)
 flow:float|None=Field(default=None,ge=0,le=1000)
 version:int|None=Field(default=None,ge=1)
 create:bool=False
 readings:list[BatchReadingInput]=Field(default_factory=list,max_length=120)
class BatchInput(BaseModel):
 """One atomic supplement/correction batch merged into an existing study."""
 model_config=ConfigDict(allow_inf_nan=False,extra='forbid')
 idempotency_key:str=Field(min_length=8,max_length=120)
 # Optimistic concurrency guard: a batch based on any version other than the
 # current one is rejected outright, so concurrent supplements and manual
 # revisions cannot silently overwrite each other.
 base_version:int=Field(gt=0)
 levels:list[BatchLevelInput]=Field(min_length=1,max_length=30)

class BatchRejection(BaseModel):
 reason:str
 message:str
 detail:dict=Field(default_factory=dict)

from pydantic import BaseModel,Field,ConfigDict
class ReadingInput(BaseModel):
 model_config=ConfigDict(allow_inf_nan=False)
 specimen_ref:str=Field(min_length=1,max_length=80)
 pressure:float=Field(ge=0,le=1000000)
 measurement_note:str=Field(default='',max_length=1000)
class ReadingPatch(BaseModel):
 model_config=ConfigDict(allow_inf_nan=False)
 pressure:float=Field(ge=0,le=1000000)
 measurement_note:str=Field(default='',max_length=1000)
 # Version the editor saw. Omit only for a never-revised legacy reading;
 # otherwise a stale/absent version is refused instead of overwriting a batch.
 expected_version:int|None=Field(default=None,ge=1)

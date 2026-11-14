import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text,select
from src.config.database import Base,engine
from src.config.settings import REDIS_URL,SEED_DEMO
from src.models import *
from src.middlewares.errors import ErrorMiddleware
from src.middlewares.rate_limit import RateLimitMiddleware
from src.middlewares.request_id import RequestIDMiddleware
from src.routes import auth,studies,runs,notes,audit
@asynccontextmanager
async def lifespan(app):
 from src.config.schema import ensure_version_columns
 ensure_version_columns()
 Base.metadata.create_all(engine)
 try:
  from src.config.database import SessionLocal
  from src.models import FlowStudy
  from src.services.batches import baseline_revisions
  with SessionLocal() as db:
   for study_id in db.scalars(select(FlowStudy.id)):
    baseline_revisions(db,study_id)
 except Exception:logging.exception('baseline revision backfill failed; startup continues')
 if SEED_DEMO:
  try:
   from scripts.seed_demo import seed
   seed()
  except Exception:logging.exception('seed failure; startup continues')
 yield
app=FastAPI(title='舫纹滤层压差响应簿',lifespan=lifespan)
@app.exception_handler(RequestValidationError)
async def invalid_input(request,error):
 return JSONResponse({'detail':[{'loc':e['loc'],'message':e['msg'],'type':e['type']} for e in error.errors()]},status_code=422)
app.add_middleware(ErrorMiddleware);app.add_middleware(RateLimitMiddleware);app.add_middleware(RequestIDMiddleware)
for route in (auth,studies,runs,notes,audit):app.include_router(route.router)
@app.get('/health')
def health():
 with engine.connect() as connection:connection.execute(text('select 1'))
 Redis.from_url(REDIS_URL).ping();return {'status':'ok'}

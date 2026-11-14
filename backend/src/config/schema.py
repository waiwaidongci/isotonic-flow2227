import logging
from sqlalchemy import inspect,text
from src.config.database import engine

# Columns added after the first release. create_all() creates new tables but
# never alters existing ones, so an existing deployment needs these added before
# the ORM reads them. Each statement is idempotent and defaults legacy rows to v1.
COLUMNS=(('flow_studies','current_version'),('dose_levels','version'),('pressure_readings','version'),('monotone_runs','source_version'))

def ensure_version_columns():
 inspector=inspect(engine)
 tables=set(inspector.get_table_names())
 with engine.begin() as connection:
  for table,column in COLUMNS:
   if table not in tables:continue
   existing={c['name'] for c in inspector.get_columns(table)}
   if column in existing:continue
   connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} INTEGER'))
   if column!='source_version':
    connection.execute(text(f'UPDATE {table} SET {column}=1 WHERE {column} IS NULL'))
   logging.info('added %s.%s for versioned batches',table,column)
   inspector=inspect(engine)

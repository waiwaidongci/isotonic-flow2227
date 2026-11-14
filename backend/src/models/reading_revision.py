from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import ForeignKey,String,Integer,Float,Text,DateTime,UniqueConstraint
from datetime import datetime,timezone
from src.config.database import Base
class PressureReadingRevision(Base):
 __tablename__='pressure_reading_revisions'
 __table_args__=(UniqueConstraint('reading_id','version'),)
 id:Mapped[int]=mapped_column(primary_key=True)
 study_id:Mapped[int]=mapped_column(ForeignKey('flow_studies.id'))
 reading_id:Mapped[int]=mapped_column(ForeignKey('pressure_readings.id'))
 specimen_ref:Mapped[str]=mapped_column(String(80))
 level_id:Mapped[int]=mapped_column(ForeignKey('dose_levels.id'))
 level_label:Mapped[str]=mapped_column(String(80))
 level_flow:Mapped[float]=mapped_column(Float)
 pressure:Mapped[float]=mapped_column(Float)
 measurement_note:Mapped[str]=mapped_column(Text,default='')
 version:Mapped[int]=mapped_column(Integer)
 batch_id:Mapped[int|None]=mapped_column(ForeignKey('data_batches.id'),nullable=True)
 revision_source:Mapped[str]=mapped_column(String(16),default='baseline')
 created_by:Mapped[str]=mapped_column(String(120))
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

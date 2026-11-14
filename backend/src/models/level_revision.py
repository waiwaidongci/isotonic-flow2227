from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import ForeignKey,String,Integer,Float,DateTime,UniqueConstraint
from datetime import datetime,timezone
from src.config.database import Base
class DoseLevelRevision(Base):
 __tablename__='dose_level_revisions'
 __table_args__=(UniqueConstraint('level_id','version'),)
 id:Mapped[int]=mapped_column(primary_key=True)
 study_id:Mapped[int]=mapped_column(ForeignKey('flow_studies.id'))
 level_id:Mapped[int]=mapped_column(ForeignKey('dose_levels.id'))
 label:Mapped[str]=mapped_column(String(80))
 flow:Mapped[float]=mapped_column(Float)
 version:Mapped[int]=mapped_column(Integer)
 batch_id:Mapped[int|None]=mapped_column(ForeignKey('data_batches.id'),nullable=True)
 revision_source:Mapped[str]=mapped_column(String(16),default='baseline')
 created_by:Mapped[str]=mapped_column(String(120))
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

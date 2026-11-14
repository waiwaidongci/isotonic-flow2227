from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import ForeignKey,String,Integer,JSON,Text,DateTime,UniqueConstraint
from datetime import datetime,timezone
from src.config.database import Base
class DataBatch(Base):
 __tablename__='data_batches'
 __table_args__=(UniqueConstraint('study_id','idempotency_key'),)
 id:Mapped[int]=mapped_column(primary_key=True)
 study_id:Mapped[int]=mapped_column(ForeignKey('flow_studies.id'))
 idempotency_key:Mapped[str]=mapped_column(String(120))
 payload_hash:Mapped[str]=mapped_column(String(64))
 base_version:Mapped[int]=mapped_column(Integer)
 applied_version:Mapped[int|None]=mapped_column(Integer,nullable=True)
 status:Mapped[str]=mapped_column(String(16),default='rejected')
 report:Mapped[dict]=mapped_column(JSON,default=dict)
 note:Mapped[str]=mapped_column(Text,default='')
 created_by:Mapped[str]=mapped_column(String(120))
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import String,Text,Integer
from src.config.database import Base
class FlowStudy(Base):
 __tablename__='flow_studies'
 id:Mapped[int]=mapped_column(primary_key=True)
 name:Mapped[str]=mapped_column(String(150),unique=True)
 current_version:Mapped[int]=mapped_column(Integer,default=1,server_default='1')
 filename:Mapped[str]=mapped_column(String(180))
 description:Mapped[str]=mapped_column(Text,default='')
 direction:Mapped[str]=mapped_column(String(30),default='nondecreasing')

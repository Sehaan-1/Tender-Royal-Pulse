from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class QueueItem(Base):
    __tablename__ = 'queue'
    id = Column(Integer, primary_key=True)
    status = Column(String)

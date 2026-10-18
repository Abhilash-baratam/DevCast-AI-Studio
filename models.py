from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime
from database import Base

class Episode(Base):
    __tablename__ = "episodes"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    summary = Column(Text, nullable=False)
    audio_path = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
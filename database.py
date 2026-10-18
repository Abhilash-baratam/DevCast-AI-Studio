import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 1. Address of our database file
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./podcast_app.db")

# 2. Connection bridge to the database
connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)

# 3. Session factory to open temporary working pages
SessionLocal = sessionmaker(
    autocommit=False, 
    autoflush=False, 
    bind=engine
)

# 4. Base blueprint template for tables
Base = declarative_base()

# 5. Helper function to open and safely close sessions
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
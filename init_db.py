from database import engine, Base
import models

def create_tables():
    print("Creating tables in the database...")
    # This checks your models and creates any missing tables
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully!")

if __name__ == "__main__":
    create_tables()
from database import SessionLocal
from models import Episode

def read_all_episodes():
    # 1. Open database session
    db = SessionLocal()
    try:
        # 2. Query all records from the episodes table
        episodes = db.query(Episode).all()

        print(f"Total episodes found: {len(episodes)}\n")

        # 3. Print details of each stored episode
        for ep in episodes:
            print(f"--- Episode #{ep.id} ---")
            print(f"File Name: {ep.filename}")
            print(f"Audio Path: {ep.audio_path}")
            print(f"Created At: {ep.created_at}")
            print(f"Script: {ep.summary}\n")
    finally:
        # 4. Safely close session
        db.close()

if __name__ == "__main__":
    read_all_episodes()
from database import SessionLocal
from models import Episode

def run_insert():
    # 1. Open our writing session
    db = SessionLocal()
    try:
        # 2. Fill in our sample podcast record
        new_episode = Episode(
            filename="calculator.py",
            summary="Welcome! Today we break down calculator.py, an elegant script handling basic math operations.",
            audio_path="audio/episode_1.mp3"
        )

        # 3. Add to staging and commit permanently to database
        db.add(new_episode)
        db.commit()
        db.refresh(new_episode)

        # 4. Print confirmation
        print("Success! Episode saved.")
        print(f"Assigned ID: {new_episode.id}")
        print(f"Filename: {new_episode.filename}")
        print(f"Timestamp: {new_episode.created_at}")
    finally:
        # 5. Always close the session
        db.close()

if __name__ == "__main__":
    run_insert()
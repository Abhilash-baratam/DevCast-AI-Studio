import edge_tts

async def text_to_speech(text: str, output_path: str):
    communicate = edge_tts.Communicate(text, voice="en-US-GuyNeural")
    await communicate.save(output_path)
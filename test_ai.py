import ai_service

print("Testing Gemini connection...")
result = ai_service.generate_podcast_script("test.py", "x = 10")
print("SUCCESS! Output:")
print(result)
from google import genai
from google.genai import types
import os
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
prompt = "Write a 3 paragraph cover letter for a Senior Software Engineer position."

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        temperature=0.4,
        max_output_tokens=1500,
    ),
)
print("FINISH REASON:", response.candidates[0].finish_reason)
print("TEXT:", response.text)

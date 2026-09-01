import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

model = os.getenv("OPENAI_VISUAL_MODEL") or "gpt-5.6-luna"
print(f"Checking model: {model}")

try:
    result = OpenAI().models.retrieve(model)
except Exception as error:
    print(f"Error type: {type(error).__name__}")
    print(f"Status: {getattr(error, 'status_code', None)}")
    print(f"Code: {getattr(error, 'code', None)}")
    print(f"Message: {error}")
else:
    print(f"Model available: {result.id}")

import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    base_url="https://api.tokenfactory.nebius.com/v1/",
    api_key=os.getenv("NEBIUS_API_KEY")
)

def call_nemotron(messages, model):
    response = client.chat.completions.create(
        model=model,
        messages=messages,
    )
    choice = response.choices[0]
    message = choice.message

    if message.content:
        return message.content
    elif hasattr(message, 'reasoning_content') and message.reasoning_content:
        return message.reasoning_content
    else:
        return None

if __name__ == "__main__":
    test_messages = [
        {"role": "user", "content": "Say hello in one sentence"}
    ]
    response_text = call_nemotron(test_messages, "PASTE_REAL_MODEL_ID_HERE")
    print(f"Response: {response_text}")
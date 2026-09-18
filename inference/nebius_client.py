import os
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env file
load_dotenv()

# Initialize OpenAI client with custom base URL
client = OpenAI(
    base_url="https://api.tokenfactory.nebius.com/v1/",
    api_key=os.getenv("serviceaccount-e00jxwjhaf3sphvvzq")
)

def call_nemotron(messages, model):
    """
    Calls the Nemotron model and returns the response text from either
    message.content or message.reasoning_content if available.
    """
    response = client.chat.completions.create(
        model=model,
        messages=messages,
    )
    # Get the first response choice
    choice = response.choices[0]
    message = choice.message
    
    # Check both content and reasoning_content for populated response
    if hasattr(message, 'reasoning_content') and message.reasoning_content:
        return message.reasoning_content
    elif message.content:
        return message.content
    else:
        return None  # Handle case where no response is available

if __name__ == "__main__":
    # Test message
    test_messages = [
        {"role": "user", "content": "Say hello in one sentence"}
    ]
    
    response_text = call_nemotron(test_messages, "nemotron-3-200k-base-model")
    print(f"Response: {response_text}")
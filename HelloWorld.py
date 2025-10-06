import os
import openai

openai.api_key = os.environ["OPENAI_API_KEY"]
client = openai.OpenAI()
response = client.responses.create(
    model="gpt-5",
    input="Say 'Hello World' in an ascii art style"
)   
print(response.output[1].content[0].text)
import requests
import json

def test_generate():
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": "llama3.2:latest",
        "prompt": "Say hello world and output valid JSON. {\"message\": \"Hello World!\"}",
        "stream": False,
        "format": "json"
    }
    
    print("Sending request to Ollama...")
    try:
        response = requests.post(url, json=payload, timeout=60)
        print(f"Status: {response.status_code}")
        print("Response data:")
        try:
            print(json.dumps(response.json(), indent=2))
        except:
            print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_generate()

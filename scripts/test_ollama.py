import requests
import sys

def check_ollama():
    url = "http://localhost:11434/api/tags"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        models = [model['name'] for model in data.get('models', [])]
        print(f"Ollama is running. Available models: {models}")
    except requests.exceptions.ConnectionError:
        print("ConnectionError: Could not connect to Ollama at http://localhost:11434. Connection refused.")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("Timeout: Ollama is taking too long to respond.")
        sys.exit(1)
    except Exception as e:
        print(f"Error connecting to Ollama: {e}")
        sys.exit(1)

if __name__ == "__main__":
    check_ollama()

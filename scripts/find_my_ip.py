import socket

def get_local_ip():
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    
    # Also attempt to connect outward to get the preferred outgoing IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        outgoing_ip = s.getsockname()[0]
        s.close()
        return outgoing_ip
    except Exception:
        pass
        
    return local_ip

if __name__ == "__main__":
    ip = get_local_ip()
    print("="*40)
    print("        NETWORK CONFIGURATION        ")
    print("="*40)
    print(f"Your Local IP Address is:")
    print(f"    {ip}")
    print()
    print(f"FastAPI Start Command:")
    print(f"    python -m uvicorn api.main:app --host 0.0.0.0 --port 8000")
    print()
    print(f"Next.js .env.local entry:")
    print(f"    NEXT_PUBLIC_API_URL=http://{ip}:8000")
    print()
    print(f"Pi Client Target URL:")
    print(f"    http://{ip}:8000")
    print("="*40)

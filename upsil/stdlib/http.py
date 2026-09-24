import urllib.request

def get(url: str) -> str:
    with urllib.request.urlopen(url) as response:
        return response.read().decode('utf-8')

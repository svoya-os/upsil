def read_file(path: str) -> str:
    with open(path, 'r') as f:
        return f.read()

def write_file(path: str, content: str):
    with open(path, 'w') as f:
        f.write(content)

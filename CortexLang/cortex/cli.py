import sys
import os
import subprocess
from cortex.compiler import compile_cortex

def main():
    if len(sys.argv) < 3:
        print("Usage: cortex [run|build] <file.ctx>")
        sys.exit(1)
        
    command = sys.argv[1]
    file_path = sys.argv[2]
    
    if not file_path.endswith('.ctx'):
        print("Error: Cortex files must end with .ctx")
        sys.exit(1)
        
    with open(file_path, 'r', encoding='utf-8') as f:
        code = f.read()
        
    py_code = compile_cortex(code)
    
    out_file = file_path.replace('.ctx', '.py')
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(py_code)
        
    if command == 'run':
        subprocess.run([sys.executable, out_file])
    elif command == 'build':
        print(f"Built to {out_file}")

if __name__ == '__main__':
    main()

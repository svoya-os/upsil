import sys
import os
import subprocess
from upsil.compiler import compile_upsil
from upsil.llvm_compiler import run_llvm

def main():
    if len(sys.argv) < 3:
        print("Usage: upsil [run|build] <file.upl>")
        sys.exit(1)
        
    command = sys.argv[1]
    file_path = sys.argv[2]
    
    if not file_path.endswith('.upl'):
        print("Error: UpsiL files must end with .upl")
        sys.exit(1)
        
    with open(file_path, 'r', encoding='utf-8') as f:
        code = f.read()
        
    if command == 'run':
        # Smart Engine Routing
        if any(im in code for im in ["import ui", "import llm", "import rag"]):
            print(f"UpsiL AI Engine: Executing {file_path} via High-Level Runtime...")
            py_code = compile_upsil(code)
            out_file = file_path.replace('.upl', '.py')
            with open(out_file, 'w', encoding='utf-8') as f:
                f.write(py_code)
            subprocess.run([sys.executable, out_file])
        else:
            # Native JIT Compilation & Execution
            print(f"UpsiL JIT Engine: Executing {file_path}...")
            try:
                res = run_llvm(code, "main")
                print(f"Process Exited with return code: {res}")
            except Exception as e:
                print(f"Runtime Error: {e}")
    elif command == 'build':
        # Compile to PyTorch bindings
        py_code = compile_upsil(code)
        out_file = file_path.replace('.upl', '.py')
        with open(out_file, 'w', encoding='utf-8') as f:
            f.write(py_code)
        print(f"Built to {out_file}")
    else:
        print("Unknown command. Use 'run' or 'build'.")

if __name__ == '__main__':
    main()

from upsil.parser import Parser, FunctionDef, VarDecl, ReturnStmt, BinOp, Identifier, Number, FuncCall, Block, ImportStmt, ModelDef, StringLit, PromptCall, IfStmt, ForStmt, RangeExpr, ListLit, DictLit, BoolLit, LogicOp, GpuKernel
from upsil.lexer import lex
import numba

class PyTorchCompiler:
    def __init__(self):
        self.indent = 0
        
    def compile(self, ast):
        code = "import torch\nimport torch.nn as nn\nimport torch.nn.functional as F\nfrom numba import cuda\n\n"
        code += self.visit(ast)
        return code
        
    def visit(self, node):
        if isinstance(node, Block):
            res = ""
            for stmt in node.statements:
                res += "    " * self.indent + self.visit(stmt) + "\n"
            return res
        elif isinstance(node, ImportStmt):
            mod = node.module
            if mod in ['ui', 'llm', 'rag', 'net', 'io']:
                mod = f"upsil.stdlib.{mod}"
            elif mod.startswith("upsil."):
                mod = mod.replace("upsil.", "upsil.stdlib.")
            
            # For modules mapped to upsil.stdlib, we should import the module specifically
            # However, if we do `import upsil.stdlib.ui`, then in Python code we'd need to use `upsil.stdlib.ui.Window`
            # But the user code uses `ui.Window`. So we must use `import upsil.stdlib.ui as ui`!
            if mod.startswith("upsil.stdlib."):
                base_name = mod.split(".")[-1]
                return f"import {mod} as {base_name}"
            return f"import {mod}"
        elif isinstance(node, ModelDef):
            res = f"class {node.name}(nn.Module):\n"
            self.indent += 1
            res += "    " * self.indent + "def __init__(self):\n"
            self.indent += 1
            res += "    " * self.indent + "super().__init__()\n"
            
            # Find variable declarations to put in __init__
            has_init = False
            for stmt in node.body.statements:
                if isinstance(stmt, VarDecl):
                    res += "    " * self.indent + f"self.{stmt.name} = {self.visit(stmt.expr)}\n"
                    has_init = True
            
            if not has_init:
                res += "    " * self.indent + "pass\n"
                
            self.indent -= 1
            
            # Now add the methods
            for stmt in node.body.statements:
                if isinstance(stmt, FunctionDef):
                    res += self.visit(stmt)
                    
            self.indent -= 1
            return res
        elif isinstance(node, FunctionDef):
            params = ", ".join(f"{p[0]}" for p in node.params)
            res = f"def {node.name}(self, {params}):\n" if "self." in str(node.body) or node.name == 'forward' else f"def {node.name}({params}):\n"
            self.indent += 1
            res += self.visit(node.body)
            self.indent -= 1
            return res
        elif isinstance(node, GpuKernel):
            params = ", ".join(f"{p[0]}" for p in node.params)
            res = f"@cuda.jit\ndef {node.name}({params}):\n"
            self.indent += 1
            res += self.visit(node.body)
            self.indent -= 1
            return res
        elif isinstance(node, VarDecl):
            return f"{node.name} = {self.visit(node.expr)}"
        elif isinstance(node, ReturnStmt):
            return f"return {self.visit(node.expr)}"
        elif isinstance(node, IfStmt):
            res = f"if {self.visit(node.cond)}:\n"
            self.indent += 1
            res += self.visit(node.true_block)
            self.indent -= 1
            if node.false_block:
                res += "    " * self.indent + "else:\n"
                self.indent += 1
                res += self.visit(node.false_block)
                self.indent -= 1
            return res
        elif isinstance(node, ForStmt):
            res = f"for {node.var_name} in {self.visit(node.iterable)}:\n"
            self.indent += 1
            res += self.visit(node.body)
            self.indent -= 1
            return res
        elif isinstance(node, RangeExpr):
            return f"range({self.visit(node.start)}, {self.visit(node.end)})"
        elif isinstance(node, BinOp):
            return f"{self.visit(node.left)} {node.op} {self.visit(node.right)}"
        elif isinstance(node, LogicOp):
            return f"{self.visit(node.left)} {node.op} {self.visit(node.right)}"
        elif isinstance(node, PromptCall):
            return f"{self.visit(node.llm_expr)}.prompt({self.visit(node.prompt_string)})"
        elif isinstance(node, Identifier):
            return node.name
        elif isinstance(node, Number):
            return node.value
        elif isinstance(node, StringLit):
            val = node.value
            if '{' in val and '}' in val:
                return f'f"{val}"'
            return f'"{val}"'
        elif isinstance(node, BoolLit):
            return "True" if node.value else "False"
        elif isinstance(node, ListLit):
            elems = ", ".join(self.visit(e) for e in node.elements)
            return f"[{elems}]"
        elif isinstance(node, DictLit):
            pairs = ", ".join(f"{self.visit(k)}: {self.visit(v)}" for k, v in node.pairs)
            return f"{{{pairs}}}"
        elif isinstance(node, FuncCall):
            args = []
            for k, v in node.kwargs:
                if k:
                    args.append(f"{k}={self.visit(v)}")
                else:
                    args.append(self.visit(v))
            args_str = ", ".join(args)
            
            name = node.name
            if name.startswith("upsil."):
                name = name.replace("upsil.", "upsil.stdlib.")
            elif name == 'VectorStore':
                name = 'upsil.stdlib.rag.VectorStore'
            elif name == 'LLM':
                name = 'upsil.stdlib.llm.LLM'
            elif name == 'nn.Linear':
                name = 'nn.Linear'
                
            return f"{name}({args_str})"
        else:
            raise Exception(f"Unknown node {type(node)}")

def compile_upsil(code: str) -> str:
    tokens = lex(code)
    parser = Parser(tokens)
    ast = parser.parse()
    compiler = PyTorchCompiler()
    return compiler.compile(ast)

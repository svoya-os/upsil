from cortex.parser import *
from cortex.lexer import lex

class CortexTypeError(Exception):
    pass

class SymbolTable:
    def __init__(self, parent=None):
        self.symbols = {}
        self.parent = parent
        
    def set(self, name, type_name):
        self.symbols[name] = type_name
        
    def get(self, name):
        if name in self.symbols:
            return self.symbols[name]
        if self.parent:
            return self.parent.get(name)
        return None

class TypeChecker:
    def __init__(self):
        self.global_env = SymbolTable()
        # built-ins
        self.global_env.set("print", "void")
        self.global_env.set("str", "string")
        self.global_env.set("len", "int")
        self.global_env.set("int", "int")
        
    def check(self, ast):
        self.visit(ast, self.global_env)
        
    def visit(self, node, env):
        if isinstance(node, Block):
            for stmt in node.statements:
                self.visit(stmt, env)
        elif isinstance(node, VarDecl):
            # Evaluate expression type
            expr_type = self.visit(node.expr, env)
            if node.var_type and expr_type and node.var_type != expr_type and node.var_type != "Any":
                raise CortexTypeError(f"Type mismatch: cannot assign {expr_type} to variable of type {node.var_type}")
            env.set(node.name, node.var_type or expr_type or "Any")
            return env.get(node.name)
        elif isinstance(node, FunctionDef):
            func_env = SymbolTable(parent=env)
            for p_name, p_type in node.params:
                func_env.set(p_name, p_type)
            env.set(node.name, f"func->{node.return_type or 'void'}")
            self.visit(node.body, func_env)
        elif isinstance(node, ModelDef):
            model_env = SymbolTable(parent=env)
            self.visit(node.body, model_env)
            env.set(node.name, "model")
        elif isinstance(node, ReturnStmt):
            return self.visit(node.expr, env)
        elif isinstance(node, FuncCall):
            func_type = env.get(node.name)
            if not func_type and not node.name.startswith("nn.") and not node.name.startswith("db."):
                # We relax check for stdlib for now
                pass
            return "Any"
        elif isinstance(node, Identifier):
            t = env.get(node.name)
            if not t:
                raise CortexTypeError(f"Undefined variable: {node.name}")
            return t
        elif isinstance(node, Number):
            return "float" if "." in str(node.value) else "int"
        elif isinstance(node, StringLit):
            return "string"
        elif isinstance(node, BoolLit):
            return "bool"
        elif isinstance(node, BinOp):
            l_type = self.visit(node.left, env)
            r_type = self.visit(node.right, env)
            if l_type == "string" or r_type == "string":
                return "string"
            if l_type == "float" or r_type == "float":
                return "float"
            return "int"
        elif isinstance(node, IfStmt):
            self.visit(node.cond, env)
            self.visit(node.true_block, SymbolTable(parent=env))
            if node.false_block:
                self.visit(node.false_block, SymbolTable(parent=env))
        elif isinstance(node, ForStmt):
            for_env = SymbolTable(parent=env)
            for_env.set(node.var_name, "int") # range usually
            self.visit(node.iterable, for_env)
            self.visit(node.body, for_env)
        elif isinstance(node, ListLit):
            if len(node.elements) > 0:
                t = self.visit(node.elements[0], env)
                return f"list[{t}]"
            return "list[Any]"
        elif isinstance(node, DictLit):
            return "dict"
        return "Any"

def check_types(code: str):
    tokens = lex(code)
    parser = Parser(tokens)
    ast = parser.parse()
    checker = TypeChecker()
    checker.check(ast)
    return True

from cortex.lexer import Token

class ASTNode: pass

class Block(ASTNode):
    def __init__(self, statements): self.statements = statements

class ImportStmt(ASTNode):
    def __init__(self, module): self.module = module

class ModelDef(ASTNode):
    def __init__(self, name, body):
        self.name = name
        self.body = body

class FunctionDef(ASTNode):
    def __init__(self, name, params, return_type, body):
        self.name = name
        self.params = params  
        self.return_type = return_type
        self.body = body

class VarDecl(ASTNode):
    def __init__(self, is_mut, name, var_type, expr):
        self.is_mut = is_mut
        self.name = name
        self.var_type = var_type
        self.expr = expr

class ReturnStmt(ASTNode):
    def __init__(self, expr): self.expr = expr

class IfStmt(ASTNode):
    def __init__(self, cond, true_block, false_block=None):
        self.cond = cond
        self.true_block = true_block
        self.false_block = false_block

class ForStmt(ASTNode):
    def __init__(self, var_name, iterable, body):
        self.var_name = var_name
        self.iterable = iterable
        self.body = body

class RangeExpr(ASTNode):
    def __init__(self, start, end):
        self.start = start
        self.end = end

class BinOp(ASTNode):
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right

class LogicOp(ASTNode):
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right

class PromptCall(ASTNode):
    def __init__(self, llm_expr, prompt_string):
        self.llm_expr = llm_expr
        self.prompt_string = prompt_string

class Identifier(ASTNode):
    def __init__(self, name): self.name = name

class Number(ASTNode):
    def __init__(self, value): self.value = value

class StringLit(ASTNode):
    def __init__(self, value): self.value = value

class BoolLit(ASTNode):
    def __init__(self, value): self.value = value

class ListLit(ASTNode):
    def __init__(self, elements): self.elements = elements

class DictLit(ASTNode):
    def __init__(self, pairs): self.pairs = pairs

class FuncCall(ASTNode):
    def __init__(self, name, kwargs):
        self.name = name
        self.kwargs = kwargs 

class MallocExpr(ASTNode):
    def __init__(self, size_expr):
        self.size_expr = size_expr

class FreeStmt(ASTNode):
    def __init__(self, ptr_expr):
        self.ptr_expr = ptr_expr

class GpuKernel(ASTNode):
    def __init__(self, name, params, body):
        self.name = name
        self.params = params
        self.body = body

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def current(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def consume(self, expected_type=None, expected_val=None):
        curr = self.current()
        if expected_type and (not curr or curr.type != expected_type):
            raise SyntaxError(f"Expected type {expected_type}, got {curr.type if curr else 'EOF'} at line {curr.line if curr else 'end'}")
        if expected_val and (not curr or curr.value != expected_val):
            raise SyntaxError(f"Expected val {expected_val}, got {curr.value if curr else 'EOF'} at line {curr.line if curr else 'end'}")
        self.pos += 1
        return curr

    def parse(self):
        statements = []
        while self.current():
            statements.append(self.parse_statement())
        return Block(statements)

    def parse_block(self):
        self.consume('PUNC', '{')
        statements = []
        while self.current() and (self.current().type != 'PUNC' or self.current().value != '}'):
            statements.append(self.parse_statement())
        self.consume('PUNC', '}')
        return Block(statements)

    def parse_statement(self):
        curr = self.current()
        if curr.type == 'IMPORT':
            self.consume('IMPORT')
            mod = self.consume('ID').value
            return ImportStmt(mod)
        elif curr.type == 'MODEL':
            self.consume('MODEL')
            name = self.consume('ID').value
            return ModelDef(name, self.parse_block())
        elif curr.type == 'GPU_KERNEL':
            self.consume('GPU_KERNEL')
            name = self.consume('ID').value
            self.consume('PUNC', '(')
            params = []
            while self.current().type != 'PUNC' or self.current().value != ')':
                p_name = self.consume('ID').value
                self.consume('PUNC', ':')
                p_type = self.consume().value
                params.append((p_name, p_type))
                if self.current().type == 'PUNC' and self.current().value == ',':
                    self.consume('PUNC')
            self.consume('PUNC', ')')
            body = self.parse_block()
            return GpuKernel(name, params, body)
        elif curr.type == 'FUN' or curr.type == 'GRAPH':
            self.consume()
            return self.parse_function()
        elif curr.type in ('VAL', 'VAR', 'VECTOR_STORE', 'LLM'):
            return self.parse_var_decl()
        elif curr.type == 'IF':
            self.consume('IF')
            cond = self.parse_expression()
            true_block = self.parse_block()
            false_block = None
            if self.current() and self.current().type == 'ELSE':
                self.consume('ELSE')
                false_block = self.parse_block()
            return IfStmt(cond, true_block, false_block)
        elif curr.type == 'FOR':
            self.consume('FOR')
            self.consume('PUNC', '(')
            var_name = self.consume('ID').value
            self.consume('IN')
            iterable = self.parse_expression()
            self.consume('PUNC', ')')
            body = self.parse_block()
            return ForStmt(var_name, iterable, body)
        elif curr.type == 'RETURN':
            self.consume('RETURN')
            expr = self.parse_expression()
            return ReturnStmt(expr)
        elif curr.type == 'FREE':
            self.consume('FREE')
            self.consume('PUNC', '(')
            expr = self.parse_expression()
            self.consume('PUNC', ')')
            return FreeStmt(expr)
        else:
            return self.parse_expression()
            
    def parse_function(self):
        name = self.consume('ID').value
        self.consume('PUNC', '(')
        params = []
        while self.current().type != 'PUNC' or self.current().value != ')':
            p_name = self.consume('ID').value
            self.consume('PUNC', ':')
            p_type = self.consume().value 
            params.append((p_name, p_type))
            if self.current().type == 'PUNC' and self.current().value == ',':
                self.consume('PUNC')
        self.consume('PUNC', ')')
        
        return_type = None
        if self.current() and self.current().type == 'ARROW':
            self.consume('ARROW')
            return_type = self.consume().value
            
        body = self.parse_block()
        return FunctionDef(name, params, return_type, body)

    def parse_var_decl(self):
        kind_tok = self.consume()
        var_type = kind_tok.value if kind_tok.type in ('VECTOR_STORE', 'LLM') else None
        name = self.consume('ID').value
        if not var_type and self.current() and self.current().type == 'PUNC' and self.current().value == ':':
            self.consume('PUNC')
            var_type = self.consume().value
        self.consume('ASSIGN')
        expr = self.parse_expression()
        return VarDecl(kind_tok.type == 'VAR', name, var_type, expr)

    def parse_expression(self):
        curr = self.current()
        if curr and curr.type == 'PUNC' and curr.value == '[':
            # Check if this is a prompt call: [llm] => "prompt"
            if self.pos+2 < len(self.tokens) and self.tokens[self.pos+2].type == 'RAG_OP':
                self.consume('PUNC', '[')
                llm_expr = self.parse_term()
                self.consume('PUNC', ']')
                self.consume('RAG_OP')
                prompt_str = self.parse_expression()
                return PromptCall(llm_expr, prompt_str)
            # Else, it's a ListLit
            self.consume('PUNC', '[')
            elements = []
            while self.current() and (self.current().type != 'PUNC' or self.current().value != ']'):
                elements.append(self.parse_expression())
                if self.current() and self.current().type == 'PUNC' and self.current().value == ',':
                    self.consume('PUNC')
            self.consume('PUNC', ']')
            return ListLit(elements)

        if curr and curr.type == 'PUNC' and curr.value == '{':
            # DictLit
            self.consume('PUNC', '{')
            pairs = []
            while self.current() and (self.current().type != 'PUNC' or self.current().value != '}'):
                key = self.parse_expression()
                self.consume('PUNC', ':')
                val = self.parse_expression()
                pairs.append((key, val))
                if self.current() and self.current().type == 'PUNC' and self.current().value == ',':
                    self.consume('PUNC')
            self.consume('PUNC', '}')
            return DictLit(pairs)

        left = self.parse_term()
        while self.current():
            if self.current().type == 'OP' or self.current().type == 'EQEQ':
                op = self.consume().value
                right = self.parse_term()
                left = BinOp(left, op, right)
            elif self.current().type in ('AND', 'OR'):
                op = self.consume().value
                right = self.parse_term()
                left = LogicOp(left, op, right)
            elif self.current().type == 'RANGE':
                self.consume('RANGE')
                right = self.parse_term()
                left = RangeExpr(left, right)
            else:
                break
        return left

    def parse_term(self):
        curr = self.current()
        if curr.type == 'NUMBER':
            return Number(self.consume().value)
        elif curr.type == 'STRING':
            return StringLit(self.consume().value)
        elif curr.type == 'TRUE':
            self.consume()
            return BoolLit(True)
        elif curr.type == 'FALSE':
            self.consume()
            return BoolLit(False)
        elif curr.type == 'MALLOC':
            self.consume('MALLOC')
            self.consume('PUNC', '(')
            expr = self.parse_expression()
            self.consume('PUNC', ')')
            return MallocExpr(expr)
        elif curr.type == 'ID':
            name = self.consume().value
            if self.current() and self.current().type == 'PUNC' and self.current().value == '(':
                self.consume('PUNC')
                args = []
                while self.current() and (self.current().type != 'PUNC' or self.current().value != ')'):
                    if self.pos+1 < len(self.tokens) and self.tokens[self.pos+1].type == 'ASSIGN':
                        k = self.consume().value
                        self.consume('ASSIGN')
                        v = self.parse_expression()
                        args.append((k, v))
                    else:
                        args.append((None, self.parse_expression()))
                    if self.current() and self.current().type == 'PUNC' and self.current().value == ',':
                        self.consume('PUNC')
                self.consume('PUNC', ')')
                return FuncCall(name, args)
            return Identifier(name)
        else:
            raise SyntaxError(f"Unexpected token {curr.value} at line {curr.line}")

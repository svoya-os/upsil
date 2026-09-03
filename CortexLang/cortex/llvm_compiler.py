from llvmlite import ir
import llvmlite.binding as llvm
from cortex.parser import *
from ctypes import CFUNCTYPE, c_double, c_void_p

class LLVMCompiler:
    def __init__(self):
        llvm.initialize_native_target()
        llvm.initialize_native_asmprinter()
        self.module = ir.Module(name="cortex_module")
        
        self.malloc_func = ir.Function(
            self.module, 
            ir.FunctionType(ir.IntType(8).as_pointer(), [ir.IntType(32)]), 
            name="malloc"
        )
        self.free_func = ir.Function(
            self.module, 
            ir.FunctionType(ir.VoidType(), [ir.IntType(8).as_pointer()]), 
            name="free"
        )
        
        self.builder = None
        self.func = None
        self.vars = {}
        # Simple GC tracker
        self.allocated_ptrs = []
        
    def compile(self, ast):
        self.visit(ast)
        return self.module
        
    def visit(self, node):
        if isinstance(node, Block):
            for stmt in node.statements:
                self.visit(stmt)
        elif isinstance(node, FunctionDef) or isinstance(node, GpuKernel):
            fnty = ir.FunctionType(ir.DoubleType(), [ir.DoubleType() for _ in node.params])
            self.func = ir.Function(self.module, fnty, name=node.name)
            block = self.func.append_basic_block(name="entry")
            self.builder = ir.IRBuilder(block)
            self.vars = {}
            self.allocated_ptrs = []
            
            for i, p in enumerate(node.params):
                self.vars[p[0]] = self.func.args[i]
            
            self.visit(node.body)
            
            # GC: Auto-free any remaining allocated pointers at end of function
            for ptr in self.allocated_ptrs:
                if not self.builder.block.is_terminated:
                    self.builder.call(self.free_func, [ptr])
                
            if not self.builder.block.is_terminated:
                self.builder.ret(ir.Constant(ir.DoubleType(), 0.0))
                
        elif isinstance(node, ReturnStmt):
            val = self.visit(node.expr)
            # GC: Auto-free before return
            for ptr in self.allocated_ptrs:
                self.builder.call(self.free_func, [ptr])
            self.builder.ret(val)
            
        elif isinstance(node, VarDecl):
            val = self.visit(node.expr)
            self.vars[node.name] = val
            
        elif isinstance(node, MallocExpr):
            size = self.visit(node.size_expr)
            size_i32 = self.builder.fptosi(size, ir.IntType(32))
            ptr = self.builder.call(self.malloc_func, [size_i32])
            # Track pointer for GC
            self.allocated_ptrs.append(ptr)
            return self.builder.ptrtoint(ptr, ir.IntType(64))
            
        elif isinstance(node, FreeStmt):
            ptr_int = self.visit(node.ptr_expr)
            ptr = self.builder.inttoptr(ptr_int, ir.IntType(8).as_pointer())
            self.builder.call(self.free_func, [ptr])
            # If manually freed, remove from GC tracking
            if ptr in self.allocated_ptrs:
                self.allocated_ptrs.remove(ptr)
                
        elif isinstance(node, BinOp):
            l = self.visit(node.left)
            r = self.visit(node.right)
            if node.op == '+': return self.builder.fadd(l, r, name="addtmp")
            if node.op == '-': return self.builder.fsub(l, r, name="subtmp")
            if node.op == '*': return self.builder.fmul(l, r, name="multmp")
            if node.op == '/': return self.builder.fdiv(l, r, name="divtmp")
        elif isinstance(node, Number):
            return ir.Constant(ir.DoubleType(), float(node.value))
        elif isinstance(node, Identifier):
            return self.vars.get(node.name, ir.Constant(ir.DoubleType(), 0.0))

def run_llvm(code: str, func_name: str, *args):
    from cortex.lexer import lex
    ast = Parser(lex(code)).parse()
    compiler = LLVMCompiler()
    mod = compiler.compile(ast)
    
    llvm_ir = str(mod)
    
    target = llvm.Target.from_default_triple()
    target_machine = target.create_target_machine()
    backing_mod = llvm.parse_assembly(llvm_ir)
    engine = llvm.create_mcjit_compiler(backing_mod, target_machine)
    engine.finalize_object()
    
    func_ptr = engine.get_function_address(func_name)
    cfunc = CFUNCTYPE(c_double, *[c_double for _ in args])(func_ptr)
    return cfunc(*args)

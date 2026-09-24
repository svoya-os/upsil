import llvmlite.ir as ir
import llvmlite.binding as llvm
import ctypes

llvm.initialize_native_target()
llvm.initialize_native_asmprinter()
target_machine = llvm.Target.from_default_triple().create_target_machine()
from upsil.parser import *
from ctypes import CFUNCTYPE, c_double, c_void_p

class LLVMCompiler:
    def __init__(self):
        self.module = ir.Module(name="upsil_module")
        
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
        self.printf_func = ir.Function(
            self.module,
            ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer()], var_arg=True),
            name="printf"
        )
        
        # File I/O Bindings
        self.fopen_func = ir.Function(
            self.module,
            ir.FunctionType(ir.IntType(8).as_pointer(), [ir.IntType(8).as_pointer(), ir.IntType(8).as_pointer()]),
            name="fopen"
        )
        self.fprintf_func = ir.Function(
            self.module,
            ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer(), ir.IntType(8).as_pointer()], var_arg=True),
            name="fprintf"
        )
        self.fclose_func = ir.Function(
            self.module,
            ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer()]),
            name="fclose"
        )
        
        # Networking Bindings
        self.socket_func = ir.Function(
            self.module,
            ir.FunctionType(ir.IntType(32), [ir.IntType(32), ir.IntType(32), ir.IntType(32)]),
            name="socket"
        )
        self.listen_func = ir.Function(
            self.module,
            ir.FunctionType(ir.IntType(32), [ir.IntType(32), ir.IntType(32)]),
            name="listen"
        )
        
        # Windows GUI Binding: MessageBoxA
        self.msgbox_func = ir.Function(
            self.module,
            ir.FunctionType(ir.IntType(32), [
                ir.IntType(8).as_pointer(),  # hWnd (NULL)
                ir.IntType(8).as_pointer(),  # lpText
                ir.IntType(8).as_pointer(),  # lpCaption
                ir.IntType(32)               # uType
            ]),
            name="MessageBoxA"
        )
        
        # Format string for doubles
        fmt_val = "%f" + '\0'
        fmt_c_str = ir.Constant(ir.ArrayType(ir.IntType(8), len(fmt_val)), bytearray(fmt_val.encode("utf8")))
        self.double_fmt = ir.GlobalVariable(self.module, fmt_c_str.type, name=".str_fmt_double")
        self.double_fmt.linkage = 'internal'
        self.double_fmt.global_constant = True
        self.double_fmt.initializer = fmt_c_str
        
        # Bounds error string
        bounds_val = "Panic: Array index out of bounds!\n" + '\0'
        bounds_c_str = ir.Constant(ir.ArrayType(ir.IntType(8), len(bounds_val)), bytearray(bounds_val.encode("utf8")))
        self.bounds_err_fmt = ir.GlobalVariable(self.module, bounds_c_str.type, name=".str_fmt_bounds")
        self.bounds_err_fmt.linkage = 'internal'
        self.bounds_err_fmt.global_constant = True
        self.bounds_err_fmt.initializer = bounds_c_str
        
        self.abort_func = ir.Function(
            self.module,
            ir.FunctionType(ir.VoidType(), []),
            name="abort"
        )
        
        self.builder = None
        self.func = None
        self.vars = {}
        self.structs = {} # Stores struct types and field offsets
        self.struct_instances = {} # Tracks which variable is of which struct type
        # Simple GC tracker
        self.allocated_ptrs = []
        
    def compile(self, ast):
        self.visit(ast)
        return self.module
        
    def visit(self, node):
        if isinstance(node, Block):
            for stmt in node.statements:
                self.visit(stmt)
        elif isinstance(node, ClassDef):
            # Compile a struct definition
            fields = {}
            llvm_types = []
            idx = 0
            for stmt in node.body.statements:
                if isinstance(stmt, VarDecl):
                    fields[stmt.name] = idx
                    llvm_types.append(ir.DoubleType())
                    idx += 1
            struct_type = ir.LiteralStructType(llvm_types)
            self.structs[node.name] = {'type': struct_type, 'fields': fields}
            
        elif isinstance(node, FunctionDef) or isinstance(node, GpuKernel):
            fnty = ir.FunctionType(ir.DoubleType(), [ir.DoubleType() for _ in node.params])
            self.func = ir.Function(self.module, fnty, name=node.name)
            block = self.func.append_basic_block(name="entry")
            self.builder = ir.IRBuilder(block)
            self.vars = {}
            self.allocated_ptrs = []
            
            # Store params as alloca pointers (like clang does)
            for i, p in enumerate(node.params):
                param_ptr = self.builder.alloca(ir.DoubleType(), name=p[0])
                self.builder.store(self.func.args[i], param_ptr)
                self.vars[p[0]] = param_ptr
            
            self.visit(node.body)
            
            # GC: Auto-free any remaining allocated pointers at end of function
            for ptr in self.allocated_ptrs:
                if not self.builder.block.is_terminated:
                    self.builder.call(self.free_func, [ptr])
                
            if not self.builder.block.is_terminated:
                self.builder.ret(ir.Constant(ir.DoubleType(), 0.0))
                
        elif isinstance(node, IfStmt):
            cond_val = self.visit(node.cond)
            cond_bool = self.builder.fcmp_ordered("!=", cond_val, ir.Constant(ir.DoubleType(), 0.0))
            
            if node.false_block:
                # if/else
                true_block = self.builder.append_basic_block("if.then")
                false_block = self.builder.append_basic_block("if.else")
                merge_block = self.builder.append_basic_block("if.merge")
                
                self.builder.cbranch(cond_bool, true_block, false_block)
                
                self.builder.position_at_end(true_block)
                for stmt in node.true_block.statements:
                    self.visit(stmt)
                if not self.builder.block.is_terminated:
                    self.builder.branch(merge_block)
                
                self.builder.position_at_end(false_block)
                for stmt in node.false_block.statements:
                    self.visit(stmt)
                if not self.builder.block.is_terminated:
                    self.builder.branch(merge_block)
                
                self.builder.position_at_end(merge_block)
            else:
                # if without else
                true_block = self.builder.append_basic_block("if.then")
                merge_block = self.builder.append_basic_block("if.merge")
                
                self.builder.cbranch(cond_bool, true_block, merge_block)
                
                self.builder.position_at_end(true_block)
                for stmt in node.true_block.statements:
                    self.visit(stmt)
                if not self.builder.block.is_terminated:
                    self.builder.branch(merge_block)
                
                self.builder.position_at_end(merge_block)
            
            return ir.Constant(ir.DoubleType(), 0.0)

        elif isinstance(node, WhileStmt):
            cond_block = self.builder.append_basic_block("while.cond")
            body_block = self.builder.append_basic_block("while.body")
            end_block = self.builder.append_basic_block("while.end")
            
            self.builder.branch(cond_block)
            
            self.builder.position_at_end(cond_block)
            cond_val = self.visit(node.cond)
            cond_bool = self.builder.fcmp_ordered("!=", cond_val, ir.Constant(ir.DoubleType(), 0.0))
            self.builder.cbranch(cond_bool, body_block, end_block)
            
            self.builder.position_at_end(body_block)
            for stmt in node.body.statements:
                self.visit(stmt)
            if not self.builder.block.is_terminated:
                self.builder.branch(cond_block)
                
            self.builder.position_at_end(end_block)
            return ir.Constant(ir.DoubleType(), 0.0)
            
        elif isinstance(node, ReturnStmt):
            val = self.visit(node.expr)
            # GC: Auto-free before return
            for ptr in self.allocated_ptrs:
                self.builder.call(self.free_func, [ptr])
            self.builder.ret(val)
            
        elif isinstance(node, VarDecl):
            val = self.visit(node.expr) if node.expr else ir.Constant(ir.DoubleType(), 0.0)
            ptr = self.builder.alloca(val.type, name=node.name)
            self.builder.store(val, ptr)
            self.vars[node.name] = ptr
            return val
            
        elif isinstance(node, AssignStmt):
            val = self.visit(node.expr)
            if node.name in self.vars:
                ptr = self.vars[node.name]
                if val.type != ptr.type.pointee:
                    if isinstance(val.type, ir.DoubleType) and isinstance(ptr.type.pointee, ir.PointerType):
                         val = self.builder.inttoptr(self.builder.fptoui(val, ir.IntType(64)), ptr.type.pointee)
                    elif isinstance(val.type, ir.PointerType) and isinstance(ptr.type.pointee, ir.DoubleType):
                         val = self.builder.uitofp(self.builder.ptrtoint(val, ir.IntType(64)), ir.DoubleType())
                self.builder.store(val, ptr)
            return val
            
        elif isinstance(node, IndexAssignStmt):
            val = self.visit(node.expr)
            if node.name in self.vars:
                arr_ptr = self.builder.load(self.vars[node.name])
                idx_val = self.visit(node.index)
                idx_i32 = self.builder.fptosi(idx_val, ir.IntType(32))
                
                # Bounds check
                cmp = self.builder.icmp_signed("<", idx_i32, ir.Constant(ir.IntType(32), 0))
                with self.builder.if_then(cmp):
                    fmt_ptr = self.builder.bitcast(self.bounds_err_fmt, ir.IntType(8).as_pointer())
                    self.builder.call(self.printf_func, [fmt_ptr])
                    self.builder.call(self.abort_func, [])
                    
                elem_ptr = self.builder.gep(arr_ptr, [idx_i32])
                self.builder.store(val, elem_ptr)
            return val

        elif isinstance(node, FuncCall):
            if node.name in self.structs:
                # Instantiate struct
                struct_info = self.structs[node.name]
                struct_size = struct_info['type'].get_abi_size(target_machine.target_data)
                size_val = ir.Constant(ir.IntType(32), struct_size)
                ptr_i8 = self.builder.call(self.malloc_func, [size_val])
                # cast to struct pointer
                struct_ptr = self.builder.bitcast(ptr_i8, struct_info['type'].as_pointer())
                
                # Populate kwargs if provided
                for kw in node.kwargs:
                    field_name = kw[0]
                    val_expr = kw[1]
                    if field_name in struct_info['fields']:
                        field_idx = struct_info['fields'][field_name]
                        ptr = self.builder.gep(struct_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), field_idx)])
                        val = self.visit(val_expr)
                        self.builder.store(val, ptr)
                        
                self.allocated_ptrs.append(ptr_i8)
                return struct_ptr
            elif node.name == "print":
                arg_val = self.visit(node.kwargs[0][1])
                if arg_val.type == ir.DoubleType():
                    fmt_ptr = self.builder.bitcast(self.double_fmt, ir.IntType(8).as_pointer())
                    self.builder.call(self.printf_func, [fmt_ptr, arg_val])
                else:
                    self.builder.call(self.printf_func, [arg_val])
                return ir.Constant(ir.DoubleType(), 0.0)
            elif node.name == "fopen":
                filename = self.visit(node.kwargs[0][1])
                mode = self.visit(node.kwargs[1][1])
                return self.builder.call(self.fopen_func, [filename, mode])
            elif node.name == "fprintf":
                file_ptr = self.visit(node.kwargs[0][1])
                content = self.visit(node.kwargs[1][1])
                self.builder.call(self.fprintf_func, [file_ptr, content])
                return ir.Constant(ir.DoubleType(), 0.0)
            elif node.name == "fclose":
                file_ptr = self.visit(node.kwargs[0][1])
                self.builder.call(self.fclose_func, [file_ptr])
                return ir.Constant(ir.DoubleType(), 0.0)
            elif node.name == "socket":
                domain = self.visit(node.kwargs[0][1])
                type_ = self.visit(node.kwargs[1][1])
                protocol = self.visit(node.kwargs[2][1])
                # Convert doubles to i32
                d_i32 = self.builder.fptosi(domain, ir.IntType(32))
                t_i32 = self.builder.fptosi(type_, ir.IntType(32))
                p_i32 = self.builder.fptosi(protocol, ir.IntType(32))
                res = self.builder.call(self.socket_func, [d_i32, t_i32, p_i32])
                return self.builder.sitofp(res, ir.DoubleType())
            elif node.name == "listen":
                sock = self.visit(node.kwargs[0][1])
                backlog = self.visit(node.kwargs[1][1])
                s_i32 = self.builder.fptosi(sock, ir.IntType(32))
                b_i32 = self.builder.fptosi(backlog, ir.IntType(32))
                res = self.builder.call(self.listen_func, [s_i32, b_i32])
                return self.builder.sitofp(res, ir.DoubleType())
            elif node.name == "msgbox":
                text = self.visit(node.kwargs[0][1])
                caption = self.visit(node.kwargs[1][1])
                null_ptr = ir.Constant(ir.IntType(8).as_pointer(), None)
                mb_type = ir.Constant(ir.IntType(32), 0x40)  # MB_ICONINFORMATION
                res = self.builder.call(self.msgbox_func, [null_ptr, text, caption, mb_type])
                return self.builder.sitofp(res, ir.DoubleType())
            else:
                # Try to call a user-defined function
                try:
                    target_func = self.module.get_global(node.name)
                    if target_func is not None:
                        call_args = [self.visit(kw[1]) for kw in node.kwargs]
                        return self.builder.call(target_func, call_args)
                except KeyError:
                    pass
                return ir.Constant(ir.DoubleType(), 0.0)
            
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
            left = self.visit(node.left)
            right = self.visit(node.right)
            if node.op == '+': return self.builder.fadd(left, right)
            if node.op == '-': return self.builder.fsub(left, right)
            if node.op == '*': return self.builder.fmul(left, right)
            if node.op == '/': return self.builder.fdiv(left, right)
            if node.op == '==':
                cmp = self.builder.fcmp_ordered("==", left, right)
                return self.builder.uitofp(cmp, ir.DoubleType())
            if node.op == '>':
                cmp = self.builder.fcmp_ordered(">", left, right)
                return self.builder.uitofp(cmp, ir.DoubleType())
            if node.op == '<':
                cmp = self.builder.fcmp_ordered("<", left, right)
                return self.builder.uitofp(cmp, ir.DoubleType())
        elif isinstance(node, UnaryOp):
            expr = self.visit(node.expr)
            if node.op == '-':
                return self.builder.fsub(ir.Constant(ir.DoubleType(), 0.0), expr)
            elif node.op == '!':
                is_zero = self.builder.fcmp_ordered("==", expr, ir.Constant(ir.DoubleType(), 0.0))
                return self.builder.uitofp(is_zero, ir.DoubleType())
        elif isinstance(node, Number):
            return ir.Constant(ir.DoubleType(), float(node.value))
        elif isinstance(node, StringLit):
            c_str_val = node.value + '\0'
            c_str = ir.Constant(ir.ArrayType(ir.IntType(8), len(c_str_val)), bytearray(c_str_val.encode("utf8")))
            global_name = f".str_{len(self.vars)}_{id(node)}"
            c_str_global = ir.GlobalVariable(self.module, c_str.type, name=global_name)
            c_str_global.linkage = 'internal'
            c_str_global.global_constant = True
            c_str_global.initializer = c_str
            # cast array to i8* pointer
            return self.builder.bitcast(c_str_global, ir.IntType(8).as_pointer())
        elif isinstance(node, ListLit):
            # Dynamic array allocated on heap
            size_val = ir.Constant(ir.IntType(32), len(node.elements) * 8)
            ptr_i8 = self.builder.call(self.malloc_func, [size_val])
            ptr_double = self.builder.bitcast(ptr_i8, ir.DoubleType().as_pointer())
            for i, elem in enumerate(node.elements):
                val = self.visit(elem)
                elem_ptr = self.builder.gep(ptr_double, [ir.Constant(ir.IntType(32), i)])
                self.builder.store(val, elem_ptr)
            self.allocated_ptrs.append(ptr_i8)
            return ptr_double
            
        elif isinstance(node, IndexExpr):
            # Array index access
            if node.name in self.vars:
                arr_ptr = self.vars[node.name]
                idx_val = self.visit(node.index)
                idx_i32 = self.builder.fptosi(idx_val, ir.IntType(32))
                
                # BOUNDS CHECKING: Check if index is < 0 (simplest bounds check)
                cmp = self.builder.icmp_signed("<", idx_i32, ir.Constant(ir.IntType(32), 0))
                with self.builder.if_then(cmp):
                    fmt_ptr = self.builder.bitcast(self.bounds_err_fmt, ir.IntType(8).as_pointer())
                    self.builder.call(self.printf_func, [fmt_ptr])
                    self.builder.call(self.abort_func, [])
                
                elem_ptr = self.builder.gep(arr_ptr, [idx_i32])
                return self.builder.load(elem_ptr)
            return ir.Constant(ir.DoubleType(), 0.0)

        elif isinstance(node, Identifier):
            if '.' in node.name:
                var_name, field = node.name.split('.')
                if var_name in self.vars and var_name in self.struct_instances:
                    struct_name = self.struct_instances[var_name]
                    struct_info = self.structs[struct_name]
                    field_idx = struct_info['fields'][field]
                    struct_ptr = self.vars[var_name]
                    ptr = self.builder.gep(struct_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), field_idx)])
                    return self.builder.load(ptr)
            if node.name in self.vars:
                return self.builder.load(self.vars[node.name])
            return ir.Constant(ir.DoubleType(), 0.0)

def run_llvm(code: str, func_name: str, *args):
    from upsil.lexer import lex
    ast = Parser(lex(code)).parse()
    compiler = LLVMCompiler()
    mod = compiler.compile(ast)
    
    llvm_ir = str(mod)
    # print(llvm_ir)
    
    backing_mod = llvm.parse_assembly(llvm_ir)
    engine = llvm.create_mcjit_compiler(backing_mod, target_machine)
    
    # We must explicitly add printf to the JIT so it finds the C runtime function
    from ctypes import CDLL, util, cast, c_void_p
    libc = CDLL(util.find_library('c') or 'msvcrt')
    
    printf_gv = backing_mod.get_function("printf")
    printf_addr = cast(libc.printf, c_void_p).value
    engine.add_global_mapping(printf_gv, printf_addr)
    
    fopen_gv = backing_mod.get_function("fopen")
    fopen_addr = cast(libc.fopen, c_void_p).value
    engine.add_global_mapping(fopen_gv, fopen_addr)

    fprintf_gv = backing_mod.get_function("fprintf")
    fprintf_addr = cast(libc.fprintf, c_void_p).value
    engine.add_global_mapping(fprintf_gv, fprintf_addr)

    fclose_gv = backing_mod.get_function("fclose")
    fclose_addr = cast(libc.fclose, c_void_p).value
    engine.add_global_mapping(fclose_gv, fclose_addr)
    
    abort_gv = backing_mod.get_function("abort")
    abort_addr = cast(libc.abort, c_void_p).value
    engine.add_global_mapping(abort_gv, abort_addr)
    
    # Load Networking Library (WinSock2)
    try:
        from ctypes import wintypes
        ws2 = CDLL('ws2_32.dll')
        
        # Initialize WinSock (WSAStartup)
        class WSADATA(ctypes.Structure):
            _fields_ = [("wVersion", wintypes.WORD),
                        ("wHighVersion", wintypes.WORD),
                        ("szDescription", ctypes.c_char * 257),
                        ("szSystemStatus", ctypes.c_char * 129),
                        ("iMaxSockets", ctypes.c_ushort),
                        ("iMaxUdpDg", ctypes.c_ushort),
                        ("lpVendorInfo", ctypes.c_char_p)]
        wsa_data = WSADATA()
        ws2.WSAStartup(0x0202, ctypes.byref(wsa_data))
        
        socket_gv = backing_mod.get_function("socket")
        socket_addr = cast(ws2.socket, c_void_p).value
        engine.add_global_mapping(socket_gv, socket_addr)
        
        listen_gv = backing_mod.get_function("listen")
        listen_addr = cast(ws2.listen, c_void_p).value
        engine.add_global_mapping(listen_gv, listen_addr)
    except:
        pass
    
    # Load Windows GUI Library (User32)
    try:
        user32 = CDLL('user32.dll')
        msgbox_gv = backing_mod.get_function("MessageBoxA")
        msgbox_addr = cast(user32.MessageBoxA, c_void_p).value
        engine.add_global_mapping(msgbox_gv, msgbox_addr)
    except:
        pass
    
    engine.finalize_object()
    
    func_ptr = engine.get_function_address(func_name)
    cfunc = CFUNCTYPE(c_double, *[c_double for _ in args])(func_ptr)
    return cfunc(*args)

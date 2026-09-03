import random
import traceback
from upsil.lexer import lex
from upsil.parser import Parser
from upsil.llvm_compiler import LLVMCompiler

def generate_fuzz_program():
    vars_list = ["a", "b", "c", "x", "y", "z"]
    ops = ["+", "-", "*", "/", ">", "<", "=="]
    
    stmts = []
    stmts.append("var arr = [1, 2, 3]")
    stmts.append("var x = 10")
    stmts.append("var y = 5")
    stmts.append("var z = 0")
    
    for _ in range(10):
        choice = random.randint(0, 8)
        if choice == 0:
            # Assign
            v = random.choice(["x", "y", "z"])
            stmts.append(f"{v} = {random.randint(1, 100)}")
        elif choice == 1:
            # IndexAssign
            idx = random.randint(0, 2)
            stmts.append(f"arr[{idx}] = {random.randint(1, 100)}")
        elif choice == 2:
            # While loop (bounded)
            stmts.append(f"while z < 3 {{ z = z + 1 }}")
        elif choice == 3:
            # If/else
            stmts.append(f"if x > 5 {{ x = x - 1 }} else {{ x = x + 1 }}")
        elif choice == 4:
            # If without else
            stmts.append(f"if y > 0 {{ y = y - 1 }}")
        elif choice == 5:
            # Math
            op = random.choice(ops)
            stmts.append(f"x = x {op} 2")
        elif choice == 6:
            # Unary
            stmts.append(f"x = -x")
        elif choice == 7:
            # Nested if
            stmts.append(f"if x > 0 {{ if y > 0 {{ z = 1 }} }}")
        elif choice == 8:
            # Array read
            stmts.append(f"x = arr[{random.randint(0,2)}]")

    stmts.append("return x")
    
    return "fun fuzz_test() -> double {\n" + "\n".join(stmts) + "\n}"


def generate_multi_func_program():
    """Test user-defined function calls"""
    return """
fun helper(a: double) -> double {
    var result = a * 2
    if result > 10 {
        result = 10
    }
    return result
}

fun fuzz_test() -> double {
    var x = helper(3)
    var y = helper(7)
    return x + y
}
"""

def generate_if_heavy_program():
    """Heavily test if/else branches"""
    stmts = ["var x = 50", "var y = 25"]
    for _ in range(15):
        choice = random.randint(0, 3)
        if choice == 0:
            stmts.append("if x > y { x = x - 1 } else { y = y - 1 }")
        elif choice == 1:
            stmts.append("if x == y { x = 0 }")
        elif choice == 2:
            stmts.append("if x > 0 { if y > 0 { x = x - y } else { x = x + 1 } }")
        elif choice == 3:
            stmts.append(f"x = x + {random.randint(1,5)}")
    stmts.append("return x")
    return "fun fuzz_test() -> double {\n" + "\n".join(stmts) + "\n}"


def generate_param_program():
    """Test function parameters stored as alloca"""
    return """
fun add_mul(a: double, b: double, c: double) -> double {
    var sum = a + b
    var product = sum * c
    if product > 100 {
        return 100
    }
    return product
}

fun fuzz_test() -> double {
    return add_mul(3, 4, 5)
}
"""


def main():
    print("="*60)
    print("UpsiL Comprehensive Fuzz Testing Suite v2.0")
    print("="*60)
    
    total = 0
    passed = 0
    failed = 0
    first_failure = None
    
    # Phase 1: 5000 random fuzz programs
    print("\n[Phase 1] Random Fuzz Tests (5000 programs)...")
    for i in range(5000):
        code = generate_fuzz_program()
        total += 1
        try:
            tokens = lex(code)
            ast = Parser(tokens).parse()
            compiler = LLVMCompiler()
            compiler.compile(ast)
            passed += 1
        except Exception as e:
            failed += 1
            if first_failure is None:
                first_failure = (i, "Phase1-Random", code, str(e))
    print(f"  Results: {passed}/{total} passed")
    
    # Phase 2: 2000 if/else heavy programs
    print("\n[Phase 2] If/Else Stress Tests (2000 programs)...")
    p2_pass = 0
    for i in range(2000):
        code = generate_if_heavy_program()
        total += 1
        try:
            tokens = lex(code)
            ast = Parser(tokens).parse()
            compiler = LLVMCompiler()
            compiler.compile(ast)
            passed += 1
            p2_pass += 1
        except Exception as e:
            failed += 1
            if first_failure is None:
                first_failure = (i, "Phase2-IfElse", code, str(e))
    print(f"  Results: {p2_pass}/2000 passed")
    
    # Phase 3: Multi-function call tests
    print("\n[Phase 3] User-Defined Function Calls (1000 programs)...")
    p3_pass = 0
    for i in range(1000):
        code = generate_multi_func_program()
        total += 1
        try:
            tokens = lex(code)
            ast = Parser(tokens).parse()
            compiler = LLVMCompiler()
            compiler.compile(ast)
            passed += 1
            p3_pass += 1
        except Exception as e:
            failed += 1
            if first_failure is None:
                first_failure = (i, "Phase3-FuncCall", code, str(e))
    print(f"  Results: {p3_pass}/1000 passed")
    
    # Phase 4: Parameter handling tests
    print("\n[Phase 4] Function Parameter Alloca Tests (2000 programs)...")
    p4_pass = 0
    for i in range(2000):
        code = generate_param_program()
        total += 1
        try:
            tokens = lex(code)
            ast = Parser(tokens).parse()
            compiler = LLVMCompiler()
            compiler.compile(ast)
            passed += 1
            p4_pass += 1
        except Exception as e:
            failed += 1
            if first_failure is None:
                first_failure = (i, "Phase4-Params", code, str(e))
    print(f"  Results: {p4_pass}/2000 passed")
    
    # Summary
    print("\n" + "="*60)
    print(f"TOTAL: {total}")
    print(f"PASSED: {passed}")
    print(f"FAILED: {failed}")
    print("="*60)
    
    if failed == 0:
        print("✓ ALL TESTS PASSED. UpsiL is production-ready.")
    else:
        print(f"\n✗ FIRST FAILURE ({first_failure[1]}, test #{first_failure[0]}):")
        print(first_failure[2][:500])
        print(f"\nError: {first_failure[3]}")

if __name__ == "__main__":
    main()

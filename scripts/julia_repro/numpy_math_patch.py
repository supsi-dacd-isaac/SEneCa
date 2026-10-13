"""Match the frozen arm64 NumPy EXP implementation through native libSystem."""
from __future__ import annotations

import ctypes
import platform


def platform_contract():
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("NumPy EXP compatibility is verified only on macOS arm64")
    library = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    version = library.NSVersionOfRunTimeLibrary
    version.argtypes, version.restype = [ctypes.c_char_p], ctypes.c_int32
    result = {"system": "Darwin", "machine": "arm64", "macos_version": platform.mac_ver()[0],
              "libsystem_version": version(b"System"), "libsystem_m_version": version(b"system_m")}
    if min(result["libsystem_version"], result["libsystem_m_version"]) < 0:
        raise RuntimeError("Cannot identify native math library versions")
    return result


def apply():
    from pysd.builders.julia.julia_model_builder import JuliaSectionBuilder
    from pysd.builders.julia.julia_expressions_builder import BUILTIN_FUNCTIONS, JuliaASTVisitor, ARITHMETIC_OPS
    from .indexing_patch import _vector_expression_axes
    if getattr(JuliaSectionBuilder, "_seneca_numpy_math_applied", False):
        return
    contract = platform_contract()
    JuliaSectionBuilder._seneca_numpy_math_applied = True
    BUILTIN_FUNCTIONS["EXP"] = "seneca_numpy_exp"
    original = JuliaSectionBuilder._full_file_content
    original_arithmetic = JuliaASTVisitor._arithmetic
    original_call = JuliaASTVisitor._call

    def call(self, node):
        if node.function.reference.upper() == "POWER":
            # The Python translator emits np.power even for scalar POWER(),
            # whereas the ^ operator preserves Python float exponentiation.
            return f"seneca_numpy_power({', '.join(self.visit(arg) for arg in node.arguments)})"
        return original_call(self, node)
    JuliaASTVisitor._call = call

    def arithmetic(self, node):
        if not any(ARITHMETIC_OPS.get(op, op) == "^" for op in node.operators):
            return original_arithmetic(self, node)
        args = [self.visit(argument) for argument in node.arguments]
        axes = _vector_expression_axes(self, node.arguments[0])
        result = args[0]
        for operator, argument, ast_argument in zip(node.operators, args[1:], node.arguments[1:]):
            right_axes = _vector_expression_axes(self, ast_argument)
            if axes is None or right_axes is None:
                raise ValueError("Cannot prove scalar/array semantics of POWER operands")
            axes = axes | right_axes
            operator = ARITHMETIC_OPS.get(operator, operator)
            if operator == "^":
                helper = "seneca_numpy_power" if axes else "seneca_python_power"
                result = f"{helper}({result}, {argument})"
            else:
                result = f"({result} {operator} {argument})"
        return result
    JuliaASTVisitor._arithmetic = arithmetic

    def content(self, equations):
        from .common import CONFIG
        self._seneca_numpy_math = {"operations": ["EXP", "POWER"], "platform": contract,
                                  "semantics": "Float64 native Apple libSystem exp/pow with explicit NumPy array power specializations"}
        guard = (f"seneca_verify_numpy_math({contract['macos_version']!r}, "
                 f"{contract['libsystem_version']}, {contract['libsystem_m_version']})\n").replace("'", '"')
        return (CONFIG / "numpy_math.jl").read_text() + "\n" + guard + original(self, equations)
    JuliaSectionBuilder._full_file_content = content

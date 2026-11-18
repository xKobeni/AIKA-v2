import ast
import re
from decimal import Context, Decimal, DecimalException, ROUND_HALF_EVEN, localcontext

from src.capabilities.contracts import Permission, ToolDefinition, ToolExecutionError, ToolInputError


MAX_EXPRESSION = 512
MAX_NODES = 128
MAX_DEPTH = 16
NUMBER = r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"


def _parse(expression: str) -> tuple[str, ast.Expression]:
    if not expression.strip() or len(expression) > MAX_EXPRESSION:
        raise ToolInputError("Use an arithmetic expression of 1 to 512 characters.")
    text = expression.strip()
    percentage = re.fullmatch(rf"([+-]?{NUMBER})\s*%\s+of\s+([+-]?{NUMBER})", text, re.IGNORECASE)
    if percentage:
        text = f"({percentage[1]} / 100) * ({percentage[2]})"
    if not re.fullmatch(r"[0-9.\s()+*/-]+", text):
        raise ToolInputError("Invalid calculator expression. Use numbers and +, -, *, /, parentheses, or a simple percentage.")
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        raise ToolInputError("Invalid arithmetic syntax.") from None
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise ToolInputError("Calculator expression is too large.")

    def validate(node: ast.AST, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            raise ToolInputError("Calculator expression is too deeply nested.")
        if isinstance(node, ast.Expression):
            validate(node.body, depth + 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in (ast.Add, ast.Sub, ast.Mult, ast.Div):
            validate(node.left, depth + 1)
            validate(node.right, depth + 1)
        elif isinstance(node, ast.UnaryOp) and type(node.op) in (ast.UAdd, ast.USub):
            validate(node.operand, depth + 1)
        elif isinstance(node, ast.Constant) and type(node.value) in (int, float):
            literal = ast.get_source_segment(text, node)
            if not literal or not re.fullmatch(NUMBER, literal) or sum(c.isdigit() for c in literal) > 50:
                raise ToolInputError("Numbers must be decimal literals with at most 50 digits.")
        else:
            raise ToolInputError("Unsupported calculator operation.")

    # Parentheses disappear from the AST, so bound their nesting separately.
    depth = 0
    for char in text:
        depth += (char == "(") - (char == ")")
        if depth > MAX_DEPTH:
            raise ToolInputError("Calculator expression is too deeply nested.")
    validate(tree)
    return text, tree


def validate_arguments(arguments: dict) -> dict:
    if set(arguments) != {"expression"} or not isinstance(arguments["expression"], str):
        raise ToolInputError("Calculator requires exactly one string argument: expression.")
    _parse(arguments["expression"])
    return arguments


def _bounded(value: Decimal) -> Decimal:
    if not value.is_finite() or (value and not Decimal("1e-100") <= value.copy_abs() <= Decimal("1e100")):
        raise ToolExecutionError("Calculator result exceeds the supported size range.")
    return value


def _evaluate(arguments: dict) -> dict:
    text, tree = _parse(arguments["expression"])

    def visit(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Constant):
            return _bounded(Decimal(ast.get_source_segment(text, node)))
        if isinstance(node, ast.UnaryOp):
            value = visit(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        left, right = visit(node.left), visit(node.right)
        if isinstance(node.op, ast.Add):
            value = left + right
        elif isinstance(node.op, ast.Sub):
            value = left - right
        elif isinstance(node.op, ast.Mult):
            value = left * right
        else:
            if not right:
                raise ToolExecutionError("Division by zero is not allowed.")
            value = left / right
        return _bounded(value)

    try:
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN, Emin=-200, Emax=200)):
            value = visit(tree.body)
            formatted = format(value, "f")
    except DecimalException:
        raise ToolExecutionError("Calculator numerical limits were exceeded.") from None
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    if value == 0:
        formatted = "0"
    if len(formatted) > 128:
        raise ToolExecutionError("Calculator result is too long.")
    return {"result": formatted}


def validate_output(data: object) -> dict:
    if (not isinstance(data, dict) or set(data) != {"result"}
            or not isinstance(data["result"], str) or len(data["result"]) > 128
            or not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", data["result"])):
        raise ValueError("Invalid calculator output.")
    _bounded(Decimal(data["result"]))
    return data


def calculator_tool() -> ToolDefinition:
    return ToolDefinition(
        "calculator.evaluate", "Evaluate bounded arithmetic expressions.",
        validate_arguments, validate_output, Permission.READ_ONLY, _evaluate,
    )

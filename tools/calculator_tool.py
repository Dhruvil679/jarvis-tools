import ast
import operator as op
from core.logger import get_logger

logger = get_logger(__name__)

# safe eval: allowed operators
ALLOWED_OPERATORS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.USub: op.neg,
    ast.Mod: op.mod,
}

def _eval(node):
    if isinstance(node, ast.Num):
        return node.n
    if isinstance(node, ast.BinOp):
        left = _eval(node.left)
        right = _eval(node.right)
        return ALLOWED_OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp):
        return ALLOWED_OPERATORS[type(node.op)](_eval(node.operand))
    raise TypeError(node)

def calculate(expression: str) -> str:
    """Safely evaluate simple arithmetic expressions."""
    try:
        node = ast.parse(expression, mode="eval").body
        result = _eval(node)
        return str(result)
    except Exception as e:
        logger.exception("Calculator failed: %s", e)
        return "Error evaluating expression"

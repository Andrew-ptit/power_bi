"""Deterministic Typed expressions, with ordinal case-sensitive text comparison.

Numbers remain Decimal until the public result is serialized. Null arithmetic
propagates null, logical operators use three-valued short-circuit evaluation,
and if/coalesce evaluate only the branch that is needed.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_EVEN


def number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Expected a numeric value")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Non-finite numbers are unsupported")
    return result


def numeric(value):
    """Numeric expression operands never implicitly parse text or logicals."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("Expected a numeric operand")
    return number(value)


def text(value):
    """Ordinal Text.From subset for scalar values emitted by this executor."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return str(value)


def ordered(value):
    """A deterministic total sort key; null sorts before all present values."""
    if value is None:
        return (0, "")
    if isinstance(value, bool):
        return (1, value)
    if isinstance(value, (int, float, Decimal)):
        return (2, number(value))
    if isinstance(value, str):
        return (3, value.encode("utf-8"))
    if isinstance(value, timedelta):
        return (4, 3, (value.days * 86400 + value.seconds) * 1_000_000 + value.microseconds)
    if isinstance(value, (datetime, time)):
        micros = ((value.hour * 60 + value.minute) * 60 + value.second) * 1_000_000 + value.microsecond
        offset = value.utcoffset()
        if offset is not None:
            micros -= (offset.days * 86400 + offset.seconds) * 1_000_000 + offset.microseconds
        if isinstance(value, datetime):
            return (4, 1, value.toordinal() * 86_400_000_000 + micros)
        return (4, 2, micros)
    if isinstance(value, date):
        return (4, 0, value.toordinal())
    raise ValueError("Nested values cannot be sorted")


def identity(value):
    """Typed equality/hash key (logical true is distinct from numeric one)."""
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return ("number", number(value))
    if isinstance(value, (str, bool, date, datetime, time, timedelta)) or value is None:
        return (type(value).__name__, value)
    if hasattr(value, "rows"):
        return ("table", tuple(tuple(identity(row[c["columnId"]]) for c in value.columns) for row in value.rows))
    raise ValueError("Unsupported cell value")


def logical(value):
    if value is not None and not isinstance(value, bool):
        raise ValueError("Expected a logical value")
    return value


def evaluate(node, row):
    kind = node["kind"]
    if kind == "literal":
        value = node["value"]
        if node["valueType"] in {"number", "integer"}:
            return number(value)
        if node["valueType"] == "date":
            return date.fromisoformat(value)
        if node["valueType"] == "datetime":
            return datetime.fromisoformat(value)
        return value
    if kind == "columnRef":
        return row[node["columnId"]]
    if kind == "compare":
        left = evaluate(node["left"], row)
        operator = node["operator"]
        if operator == "isNull":
            return left is None
        if operator == "isNotNull":
            return left is not None
        right = evaluate(node["right"], row)
        if operator in {"eq", "ne"}:
            equal = identity(left) == identity(right)
            return equal if operator == "eq" else not equal
        if operator in {"contains", "startsWith", "endsWith"}:
            if left is None:
                return None
            if right is None:
                raise ValueError("Text pattern cannot be null")
            left, right = text(left), text(right)
            return right in left if operator == "contains" else left.startswith(right) if operator == "startsWith" else left.endswith(right)
        if left is not None and right is not None and type(left) is not type(right):
            numeric_pair = all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in (left, right))
            if not numeric_pair:
                raise ValueError("Comparison operands have incompatible types")
        a, b = ordered(left), ordered(right)
        return {"gt": lambda: a > b, "gte": lambda: a >= b, "lt": lambda: a < b, "lte": lambda: a <= b}[operator]()
    if kind == "arithmetic":
        left, right = evaluate(node["left"], row), evaluate(node["right"], row)
        if left is None or right is None:
            return None
        a, b = numeric(left), numeric(right)
        return {"add": lambda: a + b, "subtract": lambda: a - b, "multiply": lambda: a * b}[node["operator"]]()
    if kind == "boolean":
        unknown = False
        decisive = node["operator"] == "or"
        for operand in node["operands"]:
            value = logical(evaluate(operand, row))
            if value is decisive:
                return decisive
            unknown |= value is None
        return None if unknown else not decisive
    if kind == "not":
        value = logical(evaluate(node["operand"], row))
        return None if value is None else not value
    if kind == "ifThenElse":
        condition = logical(evaluate(node["condition"], row))
        if condition is None:
            raise ValueError("If condition cannot be null")
        return evaluate(node["then"] if condition else node["else"], row)
    if kind == "coalesce":
        for item in node["values"]:
            value = evaluate(item, row)
            if value is not None:
                return value
        return None
    if kind == "safeDivide":
        denominator = evaluate(node["denominator"], row)
        if denominator is None or numeric(denominator) == 0:
            policy = node["onZero"]
            if policy == "error":
                raise ValueError("Division by zero")
            return Decimal(0) if policy == "zero" else None
        numerator = evaluate(node["numerator"], row)
        return None if numerator is None else numeric(numerator) / numeric(denominator)
    if kind == "functionCall":
        args = [evaluate(item, row) for item in node["args"]]
        value, function = args[0], node["function"]
        if value is None:
            return None
        if function.startswith("text."):
            if not isinstance(value, str):
                raise ValueError("Text function requires text")
            return {"text.trim": lambda: value.strip(), "text.upper": lambda: value.upper(), "text.lower": lambda: value.lower(), "text.length": lambda: Decimal(len(value))}[function]()
        if function == "number.round":
            digits = numeric(args[1]) if len(args) == 2 else Decimal(0)
            if digits != digits.to_integral_value() or abs(digits) > 100:
                raise ValueError("Invalid rounding precision")
            return numeric(value).quantize(Decimal(1).scaleb(-int(digits)), rounding=ROUND_HALF_EVEN)
        if not isinstance(value, (date, datetime)):
            raise ValueError("Date function requires a date")
        return Decimal(getattr(value, function.split(".")[1]))
    raise ValueError("Unsupported expression")

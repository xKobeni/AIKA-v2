"""Fixed system-byte projections into the existing calculator; no tool execution."""

import re
from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext

from src.capabilities.contracts import ToolRequest, ToolStatus
from src.capabilities.system_info import validate_snapshot_output
from src.capabilities.calculator import validate_output as validate_calculator_output


FIELDS = frozenset({"storage.free_bytes", "storage.used_bytes", "storage.total_bytes",
                    "memory.used_bytes", "memory.total_bytes"})
WORDS = frozenset("calculate check get show what percentage percent of my the system drive c is free used in how much "
                  "storage remaining available disk space and explain it result ram memory usage information currently "
                  "please can you could for me on total capacity has left as a".split())


class BindingError(ValueError):
    """Fixed safe category, with no observed values or raw exceptions."""


METRICS = frozenset({"storage.free_percentage", "storage.used_percentage", "memory.used_percentage"})
OPERATORS = {"below": "lt", "under": "lt", "less than": "lt", "above": "gt", "over": "gt",
             "greater than": "gt", "exceeds": "gt", "at least": "ge", "greater than or equal to": "ge",
             "at most": "le", "less than or equal to": "le"}


@dataclass(frozen=True)
class VerifiedCondition:
    metric: str
    operator: str
    threshold_percent: Decimal
    true_response: str = "warning"
    false_response: str = "normal"

    def __post_init__(self):
        if (type(self.metric) is not str or self.metric not in METRICS
                or type(self.operator) is not str or self.operator not in {"lt", "gt", "le", "ge"}
                or self.true_response != "warning" or self.false_response != "normal"):
            raise BindingError("unsupported_condition")
        value = self.threshold_percent
        if (type(value) is not Decimal or not value.is_finite() or not 0 <= value <= 100
                or value.as_tuple().exponent < -3 or len(value.as_tuple().digits) > 6):
            raise BindingError("condition_threshold")


@dataclass(frozen=True)
class VerifiedBinding:
    source_step: int
    source_field: str
    expected_type: str = "number"
    unit: str = "bytes"


@dataclass(frozen=True)
class PercentageCalculation:
    numerator: VerifiedBinding
    denominator: VerifiedBinding
    operation: str = "percentage"


@dataclass(frozen=True)
class PercentageIntent:
    group: str
    quantity: str
    drive: str | None = None
    condition: VerifiedCondition | None = None

    @property
    def field(self):
        return f"{self.group}.{self.quantity}_bytes"

    @property
    def metric(self):
        return f"{self.group}.{self.quantity}_percentage"


def _condition_text(text):
    text = " ".join(text.strip().replace("’", "'").split()).casefold()
    text = re.sub(r"^(?:hey )?aika[, :]\s*", "", text)
    text = re.sub(r"^warn me when\b", "warn me if", text)
    check = re.fullmatch(r"(?:check whether|tell me if) (.+?)[.?!]?", text)
    if check:
        text = "if " + check[1].rstrip(".?!") + ", warn me"
    return text


def conditional_candidate(text):
    if text.startswith("/"):
        return False
    plain = _condition_text(text)
    plain = re.sub(r"^(?:please |can you |could you )", "", plain)
    return bool(re.search(r"\bif\b", plain)
                and re.match(r"^(?:if|check|get|show|calculate|warn|notify|alert|send|delete|install|open|launch|run|monitor)\b", plain)
                and re.search(r"\b(?:storage|disk|drive|ram|memory|cpu|process|processes|battery|temperature|"
                              r"free space|delete|remove|modify|send|remember|configuration|permissions|background|"
                              r"website|url|install|powershell|shell|credentials|open|launch)\b", plain))


def conditional_intent(text):
    if not conditional_candidate(text):
        return None
    if any(not char.isprintable() and char not in "\r\n\t" for char in text):
        raise BindingError("unsupported_condition")
    plain = _condition_text(text)
    plain = re.sub(r"^(?:please |can you |could you )", "", plain)
    if len(re.findall(r"\bif\b", plain)) != 1 or len(re.findall(r"\botherwise\b", plain)) > 1:
        raise BindingError("unsupported_condition")
    portions = re.split(r"\botherwise\b", plain)
    main = portions[0].strip(" ,;.")
    if len(portions) == 2:
        alternate = portions[1].strip(" ,;.")
        if alternate not in {"tell me everything is fine", "tell me everything is okay", "tell me it's okay",
                             "tell me it is okay", "say normal", "tell me normal", "say everything is fine"}:
            raise BindingError("unsupported_condition")
    prefix, clause = re.split(r"\bif\b", main)
    prefix, clause = prefix.strip(" ,;.").strip(), clause.strip()
    suffix_warning = re.fullmatch(r"(?:(.*?)\s+and\s+)?warn me", prefix)
    if suffix_warning:
        prefix = (suffix_warning[1] or "").strip(" ,;.")
    else:
        branch = re.fullmatch(r"(.+?)\s*[,;.]\s*warn me", clause)
        if branch is None:
            raise BindingError("unsupported_condition")
        clause = branch[1].strip()
    # Every prefix/metric/branch token must be accounted for: no discarded action text.
    if prefix and not re.fullmatch(r"(?:check|get|show) (?:my |the )?(?:system )?(?:free )?"
                                  r"(?:storage|disk(?: space)?|ram(?: usage| information)?|memory(?: usage)?)", prefix):
        raise BindingError("unsupported_condition")
    operator_words = "|".join(re.escape(word) for word in sorted(OPERATORS, key=len, reverse=True))
    if prefix and re.match(rf"^(?:{operator_words})\s", clause):
        clause = "it " + clause
    match = re.fullmatch(rf"(.+?)\s+({operator_words})\s+(\S+)\s*(?:%| percent)", clause)
    if match is None or not re.fullmatch(r"(?:0|[1-9][0-9]{0,2})(?:\.[0-9]{1,3})?", match[3]):
        raise BindingError("unsupported_condition")
    phrase = match[1].replace("it's", "it is")
    if re.search(r"[^a-z\s:]", phrase):
        raise BindingError("unsupported_condition")
    words = set(re.findall(r"[a-z]+", prefix + " " + phrase))
    allowed = set("check get show my the system c drive disk storage space free used usage ram memory information "
                  "available remaining percentage percent it is currently".split())
    if words - allowed:
        raise BindingError("unsupported_condition")
    memory = bool(words & {"ram", "memory"})
    storage = bool(words & {"storage", "disk", "drive", "space"})
    if memory == storage:
        raise BindingError("unsupported_condition")
    free = bool(words & {"free", "available", "remaining"})
    used = "used" in words or bool(words & {"usage"})
    if memory:
        used = True
    if free == used:
        raise BindingError("unsupported_condition")
    intent = PercentageIntent("memory" if memory else "storage", "free" if free else "used", "C:\\" if "c" in words else None)
    condition = VerifiedCondition(intent.metric, OPERATORS[match[2]], Decimal(match[3]))
    return PercentageIntent(intent.group, intent.quantity, intent.drive, condition)


def requested_percentage(text):
    return conditional_intent(text) if conditional_candidate(text) else percentage_intent(text)


def dataflow_candidate(text):
    return bool(re.search(r"\b(?:percent|percentage)\b|%", text, re.I)
                and re.search(r"\b(?:storage|disk|drive|ram|memory)\b", text, re.I))


def percentage_intent(text):
    if text.startswith("/") or not dataflow_candidate(text):
        return None
    plain = re.sub(r"^aika[, :]\s*", "", text.strip(), flags=re.I).casefold()
    if not re.match(r"^(?:please |can you |could you )?(?:calculate|check|get|show|how|what)\b", plain):
        return None
    if re.search(r"[^a-z\s,:?.!%]", plain):
        return None
    words = set(re.findall(r"[a-z]+", plain))
    if words - WORDS or not ("my" in words or "system" in words or "c" in words):
        return None
    memory = bool(words & {"memory", "ram"})
    storage = bool(words & {"storage", "disk", "drive"})
    if memory == storage:
        return None
    free = bool(words & {"free", "remaining", "available", "left"})
    used = "used" in words or memory and "usage" in words
    if free == used or memory and free:
        return None
    return PercentageIntent("memory" if memory else "storage", "used" if used else "free",
                            "C:\\" if "c" in words else None)


def calculation_for(intent, source_step):
    return PercentageCalculation(VerifiedBinding(source_step, intent.field),
                                 VerifiedBinding(source_step, f"{intent.group}.total_bytes"))


def validate_calculation(calculation, consumer, earlier):
    if (not isinstance(calculation, PercentageCalculation) or calculation.operation != "percentage"
            or consumer.request != ToolRequest("calculator.evaluate", {}) or consumer.research is not None):
        raise BindingError("unsupported_binding")
    intent = requested_percentage(consumer.instruction)
    if intent is None:
        raise BindingError("unauthorized_binding")
    for reference in (calculation.numerator, calculation.denominator):
        if (not isinstance(reference, VerifiedBinding) or type(reference.source_step) is not int
                or not 1 <= reference.source_step < consumer.number or reference.source_step > len(earlier)
                or reference.source_step not in consumer.depends_on):
            raise BindingError("binding_dependency")
        if (type(reference.source_field) is not str or reference.source_field not in FIELDS
                or reference.expected_type != "number" or reference.unit != "bytes"):
            raise BindingError("binding_field_or_type")
        producer = earlier[reference.source_step - 1]
        if (producer.request is None or producer.request.tool != "system.snapshot" or producer.research is not None
                or producer.calculation is not None
                or not isinstance(producer.request.arguments, dict)
                or producer.request.arguments.get("section", "all") not in {intent.group, "all"}):
            raise BindingError("binding_producer")
    if calculation != calculation_for(intent, calculation.numerator.source_step):
        raise BindingError("binding_operation")
    return intent


def resolve_calculation(calculation, intent, evidence, source_state):
    if (not isinstance(calculation, PercentageCalculation) or not isinstance(calculation.numerator, VerifiedBinding)
            or type(calculation.numerator.source_step) is not int or calculation.numerator.source_step < 1
            or calculation != calculation_for(intent, calculation.numerator.source_step)):
        raise BindingError("unsupported_binding")
    number = calculation.numerator.source_step
    result = evidence.get(number)
    if (source_state != "succeeded" or result is None or result.tool != "system.snapshot"
            or result.status != ToolStatus.SUCCESS or result.verified is not True or not isinstance(result.data, dict)):
        raise BindingError("binding_unverified")
    data = result.data
    try:
        validate_snapshot_output(data)
    except Exception:
        raise BindingError("binding_invalid_source") from None
    unavailable = set(data["unavailable_fields"])
    if unavailable & {intent.group, intent.field, f"{intent.group}.total_bytes"}:
        raise BindingError("binding_missing_value")
    values = data["measurements"].get(intent.group)
    if not isinstance(values, dict):
        raise BindingError("binding_missing_value")
    if intent.drive and values.get("system_drive", "").casefold() != intent.drive.casefold():
        raise BindingError("binding_drive_mismatch")
    # Fixed projection branches, not traversal of a caller-supplied field path.
    if intent.group == "storage":
        numerator = values["free_bytes"] if intent.quantity == "free" else values["used_bytes"]
    else:
        numerator = values["used_bytes"]
    denominator = values["total_bytes"]
    if numerator is None or denominator is None:
        raise BindingError("binding_missing_value")
    if any(type(value) is not int or not 0 <= value <= 2**64 - 1 for value in (numerator, denominator)):
        raise BindingError("binding_invalid_number")
    if denominator <= 0 or numerator > denominator:
        raise BindingError("binding_invalid_denominator")
    complement = values.get("free_bytes" if intent.group == "storage" else "available_bytes")
    used = values.get("used_bytes")
    if complement is not None and used is not None and used + complement != denominator:
        raise BindingError("binding_inconsistent_values")
    request = ToolRequest("calculator.evaluate", {"expression": f"({numerator} / {denominator}) * 100"})
    return request, numerator, denominator, data


def provenance(calculation, consumer, *, verified=False, collected_at=None):
    return {"operation": "percentage", "calculator_step": consumer, "verified": verified,
            "collected_at": collected_at, "input_sources": [
                {"step": ref.source_step, "tool": "system.snapshot", "field": ref.source_field,
                 "expected_type": ref.expected_type, "unit": ref.unit, "verified": collected_at is not None}
                for ref in (calculation.numerator, calculation.denominator)]}


def format_percentage(result, intent, numerator, denominator, data, source_step, consumer):
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        percent = Decimal(result.data["result"]).quantize(Decimal("0.01"))
        amount = Decimal(numerator) / Decimal(2**30)
        capacity = Decimal(denominator) / Decimal(2**30)
        title = f"Storage on {data['measurements']['storage']['system_drive']}" if intent.group == "storage" else "RAM (used = total minus available)"
        label = "Free" if intent.quantity == "free" else "Used"
        return (f"{title}\n{label}: {amount:.2f} GiB ({numerator} bytes)\n"
                f"Total: {capacity:.2f} GiB ({denominator} bytes)\n{label} percentage: {percent:.2f}%\n"
                "Calculated from exact byte counts; GiB and percentage displays are rounded.\n"
                f"Source: system.snapshot step {source_step}, collected {data['collected_at']}; "
                f"calculator.evaluate step {consumer}, verified.")


def evaluate_condition(condition, calculation, intent, evidence, source_state, calculator, consumer):
    if not isinstance(condition, VerifiedCondition) or condition != intent.condition or condition.metric != intent.metric:
        raise BindingError("condition_mismatch")
    if (calculator is None or calculator.tool != "calculator.evaluate" or calculator.status != ToolStatus.SUCCESS
            or calculator.verified is not True):
        raise BindingError("condition_unverified")
    try:
        validate_calculator_output(calculator.data)
    except Exception:
        raise BindingError("condition_unverified") from None
    _, numerator, denominator, data = resolve_calculation(calculation, intent, evidence, source_state)
    # Exact integer cross-products, independent of Decimal context or display rounding.
    threshold_num, threshold_den = condition.threshold_percent.as_integer_ratio()
    left, right = numerator * 100 * threshold_den, threshold_num * denominator
    outcome = {"lt": left < right, "gt": left > right, "le": left <= right, "ge": left >= right}[condition.operator]
    return {"metric": condition.metric, "operator": condition.operator,
            "threshold_percent": format(condition.threshold_percent, "f"), "condition_result": outcome,
            "selected_branch": condition.true_response if outcome else condition.false_response,
            "source_step": calculation.numerator.source_step, "calculator_step": consumer,
            "collected_at": data["collected_at"], "calculated_percentage": calculator.data["result"], "verified": True}


def format_condition(record, intent, data):
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        displayed = Decimal(record["calculated_percentage"]).quantize(Decimal("0.01"))
    label = "RAM used" if intent.group == "memory" else "Free storage" if intent.quantity == "free" else "Used storage"
    scope = "" if intent.group == "memory" else f"Drive: {data['measurements']['storage']['system_drive']}\n"
    comparison = {"lt": "below", "gt": "above", "le": "at most", "ge": "at least"}[record["operator"]]
    state = "TRUE" if record["condition_result"] else "FALSE"
    message = ("The measured percentage meets your warning condition." if record["condition_result"] else
               "The measured percentage does not meet your warning condition; this is not an overall system-health assessment.")
    return (f"AIKA {'RAM' if intent.group == 'memory' else 'Storage'} {'Warning' if record['condition_result'] else 'Status'}\n"
            f"{scope}{label}: {displayed:.2f}%\nThreshold: {comparison} {record['threshold_percent']}%\n"
            f"Condition: {state}\nResponse: {record['selected_branch']}\n{message}\n"
            "Displayed percentage is rounded; the condition used exact measured byte counts.\n"
            f"Verified from system.snapshot step {record['source_step']} (collected {record['collected_at']}) "
            f"and calculator.evaluate step {record['calculator_step']}.")

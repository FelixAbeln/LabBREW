from __future__ import annotations

from ..models import OperatorMetadata
from .shared import CallableOperator, as_float

PLUGINS = [
    CallableOperator(
        metadata=OperatorMetadata(
            name="in_range",
            label="In range",
            description="Inclusive numeric range check",
            value_type="number",
            param_schema={
                "min": {"type": "number", "required": True},
                "max": {"type": "number", "required": True},
            },
        ),
        fn=lambda value, params: (
            as_float(params["min"]) <= as_float(value) <= as_float(params["max"])
        ),
    ),
    CallableOperator(
        metadata=OperatorMetadata(
            name="out_of_range",
            label="Out of range",
            description="True when outside inclusive numeric range",
            value_type="number",
            param_schema={
                "min": {"type": "number", "required": True},
                "max": {"type": "number", "required": True},
            },
        ),
        fn=lambda value, params: (
            not (as_float(params["min"]) <= as_float(value) <= as_float(params["max"]))
        ),
    ),
]

from ..models import OperatorMetadata
from .shared import CallableOperator

PLUGINS = [
    CallableOperator(
        metadata=OperatorMetadata(
            name="always_true",
            label="Is always True",
            description="Always returns True",
            value_type="any",
            param_schema={},
        ),
        fn=lambda value, params: True,
    ),
]
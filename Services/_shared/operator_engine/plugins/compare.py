from __future__ import annotations

from ..models import OperatorMetadata
from .shared import CallableOperator, as_float, loosely_equal


PLUGINS = [
    CallableOperator(
        metadata=OperatorMetadata(
            name='>',
            label='Greater than',
            description='Numeric comparison: value > threshold',
            value_type='number',
            param_schema={'threshold': {'type': 'number', 'required': True}},
        ),
        fn=lambda value, params: as_float(value) > as_float(params['threshold']),
    ),
    CallableOperator(
        metadata=OperatorMetadata(
            name='>=',
            label='Greater than or equal',
            description='Numeric comparison: value >= threshold',
            value_type='number',
            param_schema={'threshold': {'type': 'number', 'required': True}},
        ),
        fn=lambda value, params: as_float(value) >= as_float(params['threshold']),
    ),
    CallableOperator(
        metadata=OperatorMetadata(
            name='<',
            label='Less than',
            description='Numeric comparison: value < threshold',
            value_type='number',
            param_schema={'threshold': {'type': 'number', 'required': True}},
        ),
        fn=lambda value, params: as_float(value) < as_float(params['threshold']),
    ),
    CallableOperator(
        metadata=OperatorMetadata(
            name='<=',
            label='Less than or equal',
            description='Numeric comparison: value <= threshold',
            value_type='number',
            param_schema={'threshold': {'type': 'number', 'required': True}},
        ),
        fn=lambda value, params: as_float(value) <= as_float(params['threshold']),
    ),
    CallableOperator(
        metadata=OperatorMetadata(
            name='==',
            label='Equals',
            description='Loose equality for bools, numbers, and simple values',
            value_type='any',
            param_schema={'threshold': {'type': 'any', 'required': True}},
        ),
        fn=lambda value, params: loosely_equal(value, params['threshold']),
    ),
    CallableOperator(
        metadata=OperatorMetadata(
            name='!=',
            label='Not equal',
            description='Loose inequality for bools, numbers, and simple values',
            value_type='any',
            param_schema={'threshold': {'type': 'any', 'required': True}},
        ),
        fn=lambda value, params: not loosely_equal(value, params['threshold']),
    ),
]

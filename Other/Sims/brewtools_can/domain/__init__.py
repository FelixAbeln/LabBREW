from __future__ import annotations

from ..domain_factory import DomainFactory
from ..enums import MsgType
from .calibration import (
    CalibrationAck,
    CalibrationCmd,
    CalibrationCmdReceived,
    decode_calibration_ack,
    decode_calibration_cmd,
)
from .control import (
    ControlMessage,
    decode_control_raw,
)
from .measurements import (
    DensityMeasurement,
    LevelMeasurement,
    MaxValue,
    MinValue,
    PressureMeasurement,
    RpmMeasurement,
    TemperatureMeasurement,
    decode_density,
    decode_level,
    decode_max,
    decode_min,
    decode_pressure,
    decode_rpm,
    decode_temperature,
)
from .node_management import (
    NodeIdUpdate,
    decode_node_id_update,
)
from .start_measurement import (
    StartMeasurementCmd,
    StartMeasurementCmdReceived,
    decode_start_measurement_cmd,
)

# This is what your top-level package wants to import:
DomainObject = (
    TemperatureMeasurement
    | PressureMeasurement
    | DensityMeasurement
    | LevelMeasurement
    | RpmMeasurement
    | MinValue
    | MaxValue
    | NodeIdUpdate
    | CalibrationAck
    | CalibrationCmd
    | CalibrationCmdReceived
    | ControlMessage
    | StartMeasurementCmd
    | StartMeasurementCmdReceived
)


def register_default_domain_handlers() -> None:
    # measurements
    DomainFactory.register(MsgType.MSG_TYPE_TEMPERATURE, decode_temperature)
    DomainFactory.register(MsgType.MSG_TYPE_PRESSURE, decode_pressure)
    DomainFactory.register(MsgType.MSG_TYPE_DENSITY, decode_density)
    DomainFactory.register(MsgType.MSG_TYPE_LEVEL, decode_level)
    DomainFactory.register(MsgType.MSG_TYPE_RPM, decode_rpm)
    DomainFactory.register(MsgType.MSG_TYPE_MIN, decode_min)
    DomainFactory.register(MsgType.MSG_TYPE_MAX, decode_max)

    DomainFactory.register(
        int(MsgType.MSG_TYPE_START_MEASUREMENT_CMD), decode_start_measurement_cmd
    )

    # node mgmt
    DomainFactory.register(MsgType.MSG_TYPE_NODE_ID, decode_node_id_update)

    # calibration
    DomainFactory.register(MsgType.MSG_TYPE_CALIBRATION_ACK, decode_calibration_ack)
    DomainFactory.register(MsgType.MSG_TYPE_CALIBRATION_CMD, decode_calibration_cmd)

    # control / io (raw for now)
    DomainFactory.register(MsgType.MSG_TYPE_PWM, decode_control_raw)
    DomainFactory.register(MsgType.MSG_TYPE_DCC, decode_control_raw)
    DomainFactory.register(MsgType.MSG_TYPE_ACC, decode_control_raw)
    DomainFactory.register(MsgType.MSG_TYPE_START_MEASUREMENT_CMD, decode_control_raw)
    DomainFactory.register(MsgType.MSG_TYPE_PORT_STATE, decode_control_raw)
    DomainFactory.register(MsgType.MSG_TYPE_POLARITY_STATE, decode_control_raw)
    DomainFactory.register(MsgType.MSG_TYPE_EXTERNAL_RELAY_STATE, decode_control_raw)
    DomainFactory.register(MsgType.MSG_TYPE_CAN_TERMINATION, decode_control_raw)

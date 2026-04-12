from enum import IntEnum


class Priority(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


class NodeType(IntEnum):
    NODE_TYPE_INVALID = 0
    NODE_TYPE_FCS_IOM = 2
    NODE_TYPE_PRESSURE_SENSOR = 3
    NODE_TYPE_DENSITY_SENSOR = 4
    NODE_TYPE_LEVEL_SENSOR = 5
    NODE_TYPE_AGITATOR_ACTUATOR = 6
    NODE_TYPE_PLC = 8


class MsgType(IntEnum):
    # Measurements
    MSG_TYPE_TEMPERATURE = 12
    MSG_TYPE_PRESSURE = 13
    MSG_TYPE_DENSITY = 14
    MSG_TYPE_LEVEL = 16
    MSG_TYPE_RPM = 17

    # Control/config
    MSG_TYPE_DCC = 18
    MSG_TYPE_ACC = 19
    MSG_TYPE_PORT_STATE = 21
    MSG_TYPE_POLARITY_STATE = 22
    MSG_TYPE_EXTERNAL_RELAY_STATE = 23
    MSG_TYPE_CAN_TERMINATION = 25
    MSG_TYPE_PWM = 27

    # Calibration/measurement
    MSG_TYPE_CALIBRATION_CMD = 28
    MSG_TYPE_CALIBRATION_ACK = 29
    MSG_TYPE_START_MEASUREMENT_CMD = 33

    # Node management
    MSG_TYPE_NODE_ID = 36

    # Limits
    MSG_TYPE_MIN = 41
    MSG_TYPE_MAX = 42


class AckType(IntEnum):
    ACK_TYPE_NONE = 0
    ACK_TYPE_CALIBRATING = 1
    ACK_TYPE_OK = 2
    ACK_TYPE_ERROR = 3

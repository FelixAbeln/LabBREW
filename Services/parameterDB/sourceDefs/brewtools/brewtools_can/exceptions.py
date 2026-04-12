class BrewtoolsCanError(Exception):
    pass


class DecodeError(BrewtoolsCanError):
    pass


class EncodeError(BrewtoolsCanError):
    pass

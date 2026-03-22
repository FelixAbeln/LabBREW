from parameterdb_core.client import SignalClient

c = SignalClient()

with c.session() as s:
    print("Ping:", s.ping())
    print("Parameter types:", s.list_parameter_types())
    print("Parameters:", s.list_parameters())

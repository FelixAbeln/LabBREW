"""Built-in operator plugins live here.

Drop new modules into this package and expose either:
- a module-level PLUGINS iterable, or
- instantiated objects/classes with `metadata` and `evaluate(...)`

The loader discovers them automatically.
"""

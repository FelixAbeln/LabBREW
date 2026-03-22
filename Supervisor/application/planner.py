from __future__ import annotations

from collections import deque

from ..domain.errors import ResolutionError


class StartupPlanner:
    def order(self, dependencies: dict[str, set[str]]) -> list[str]:
        indegree = {name: len(deps) for name, deps in dependencies.items()}
        reverse: dict[str, set[str]] = {name: set() for name in dependencies}
        for svc, deps in dependencies.items():
            for dep in deps:
                reverse.setdefault(dep, set()).add(svc)

        queue = deque(sorted(name for name, degree in indegree.items() if degree == 0))
        ordered: list[str] = []

        while queue:
            current = queue.popleft()
            ordered.append(current)
            for child in sorted(reverse.get(current, ())):
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)

        if len(ordered) != len(dependencies):
            raise ResolutionError("Cycle detected in service dependency graph")
        return ordered

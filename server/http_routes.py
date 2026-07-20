"""Declarative API route registry used before HTTP handler dispatch."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    method: str
    pattern: str

    def matches(self, path: str) -> bool:
        return bool(re.fullmatch(self.pattern, path))


class ApiRouteRegistry:
    def __init__(self, routes: tuple[Route, ...]):
        self.routes = routes

    def matches(self, method: str, raw_path: str) -> bool:
        path = raw_path.split("?", 1)[0]
        return any(route.method == method and route.matches(path) for route in self.routes)


def routes(method: str, *patterns: str) -> tuple[Route, ...]:
    return tuple(Route(method, pattern) for pattern in patterns)


API_ROUTES = ApiRouteRegistry(sum((
    routes("GET", r"/api/health", r"/api/me", r"/api/models", r"/api/metrics", r"/api/agent-rollout", r"/api/retrieval-diagnostics", r"/api/retrieval-suggestions", r"/api/retrieval-policies", r"/api/apps", r"/api/tools", r"/api/tool-invocations", r"/api/(?:memories|knowledge|artifacts|threads|folders|skills|runs)", r"/api/knowledge/search", r"/api/artifacts/[^/]+/download", r"/api/folders/[^/]+", r"/api/runs/[^/]+", r"/api/threads/[^/]+(?:/(?:runs|context|skills))?", r"/api/skills/[^/]+(?:/versions)?"),
    routes("POST", r"/api/login", r"/api/logout", r"/api/logout-all", r"/api/(?:skills|knowledge|memories|threads|folders|chat|route-preview)", r"/api/memories/candidates", r"/api/skills/[^/]+/restore", r"/api/folders/[^/]+/(?:knowledge|invitations)", r"/api/runs/[^/]+/(?:confirmation|cancel|feedback)", r"/api/retrieval-suggestions/[^/]+/candidate", r"/api/retrieval-policies/[^/]+/(?:evaluate|publish)", r"/api/retrieval-policies/rollback", r"/api/tools/[^/]+/execute"),
    routes("PATCH", r"/api/me", r"/api/(?:memories|knowledge|folders|skills)/[^/]+", r"/api/threads/[^/]+(?:/skills)?"),
    routes("DELETE", r"/api/(?:memories|knowledge|skills|artifacts|threads|folders)/[^/]+", r"/api/folders/[^/]+/members/[^/]+"),
), ()))

"""Test client that retains the concrete FastAPI application type."""

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient as StarletteTestClient


class TestClient(StarletteTestClient):
    __test__ = False
    app: FastAPI

    def __init__(self, app: FastAPI, **kwargs: Any) -> None:
        super().__init__(app, **kwargs)
        self.app = app

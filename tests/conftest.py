"""
tests/conftest.py
~~~~~~~~~~~~~~~~~
Shared Pytest fixtures for SafePass 2026 test suites.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.engine import StadiumGraph


@pytest.fixture(scope="module")
def test_client():
    """Provides a module-scoped FastAPI TestClient instance."""
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def clean_graph():
    """Provides a fresh, empty StadiumGraph instance."""
    return StadiumGraph()


@pytest.fixture
def simple_evac_graph():
    """
    Provides a simple evacuated layout:
    Stand_A -> Concourse_1 -> Exit_1 (len 5, cap 100)
    Stand_A -> Concourse_2 -> Exit_2 (len 5, cap 100)
    Concourse_2 -> Exit_2 has a baseline length of 8.
    """
    g = StadiumGraph()
    g.add_node("Exit_1", is_exit=True)
    g.add_node("Exit_2", is_exit=True)
    g.add_node("Concourse_1")
    g.add_node("Concourse_2")
    g.add_node("Stand_A")

    g.add_edge("Stand_A", "Concourse_1", length=5.0, capacity=100.0)
    g.add_edge("Concourse_1", "Exit_1", length=5.0, capacity=100.0)
    g.add_edge("Stand_A", "Concourse_2", length=5.0, capacity=100.0)
    g.add_edge("Concourse_2", "Exit_2", length=8.0, capacity=100.0)
    return g

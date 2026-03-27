import os
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests that hit real external APIs",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--integration"):
        skip = pytest.mark.skip(reason="Pass --integration to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Isolated SQLite DB for each test — never touches the real DB."""
    db_file = str(tmp_path / "test_trading.db")
    monkeypatch.setattr("stock_agent.memory.DB_PATH", db_file)
    from stock_agent.memory import initialize_db
    initialize_db()
    return db_file

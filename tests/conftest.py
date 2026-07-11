import pytest
from passmodel import db


@pytest.fixture
def conn(tmp_path):
    c = db.get_conn(tmp_path / "test.db")
    db.init_db(c)
    yield c
    c.close()

import os
import tempfile

import pytest

from app.db import init_db


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)  # init_db recreates it
    init_db(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def conn(db_path):
    from app.db import get_connection

    c = get_connection(db_path)
    yield c
    c.close()

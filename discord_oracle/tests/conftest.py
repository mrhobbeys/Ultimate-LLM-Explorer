import pytest

from discord_oracle.state import Store
from discord_oracle.world import instantiate_world


@pytest.fixture()
def store():
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture()
def player(store):
    key = "dm:tester"
    store.create_player(key, None, "tester")
    instantiate_world(store, key)
    return store.get_player(key)

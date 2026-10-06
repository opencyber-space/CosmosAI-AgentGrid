import pytest
from xchange_pysdk.client import XchangeClient


@pytest.fixture
def client():
    return XchangeClient(base_url="http://mock-xchange:5000")

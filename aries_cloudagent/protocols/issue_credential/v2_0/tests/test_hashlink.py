from multiprocessing.dummy import Value
import pytest
from ..hashlink import (
    _cbor_uri_decoder,
    Hashlink,
)
from cbor2.decoder import CBORDecoder
from cbor2.types import CBORTag

EXAMPLE_DATA = b"Hello World!"
EXAMPLE_LINK = "hl:zQmWvQxTqbG2Z9HPJgG57jjwR154cKhbtJenbyYTWkjgF3e:zuh8iaLobXC8g9tfma1CSTtYBakXeSTkHrYA5hmD4F7dCLw8XYwZ1GWyJ3zwF"
EXAMPLE_LINK_EXP = "hl:zQmWvQxTqbG2Z9HPJgG57jjwR154cKhbtJenbyYTWkjgF3e:z31XeTsU3iTMcU7nEUtDwneu6SvNFk45JUV6rdVmfSN4DX5QJxzp9cehwTghrJ5zAmH8BM"
EXAMPLE_DATA_SHA = bytes.fromhex(
    "7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069"
)
EXAMPLE_METADATA = {"url": ["http://example.org/hw.txt"], "content-type": "text/plain", "experimental": "test"}



def test_example_link():
    hashlink = Hashlink(
        "sha2-256",
        "base58btc",
        EXAMPLE_DATA,
        {"url": ["http://example.org/hw.txt"], "content-type": "text/plain"},
    )
    assert hashlink.link == EXAMPLE_LINK


def test_cbor_decoder():
    class tag():
        def __init__(self, tag: int) -> None:
            self.tag = tag
            self.value = "value"
    test_tag1 = tag(tag=0)
    test_tag2 = tag(tag=32)
    assert _cbor_uri_decoder(CBORDecoder, test_tag1) == test_tag1
    assert _cbor_uri_decoder(CBORDecoder, test_tag2) == test_tag2.value


def test_bad_hashlink_alg():
    with pytest.raises(ValueError):
        Hashlink(
        alg="not_sha2_256",
        enc=EXAMPLE_LINK, 
        data=EXAMPLE_DATA, 
        metadata={"testkey": "testval"}
        )


def test_hashlink_str():
    hashlink = Hashlink(
        alg="sha2-256",
        enc=EXAMPLE_LINK, 
        data=EXAMPLE_DATA, 
        metadata={"testkey": "testval"},
    )
    hashlink._link = "Hello there"
    assert hashlink.__str__() == hashlink.link


def test_serialize_metadata():
    hashlink = Hashlink(
        "sha2-256",
        "base58btc",
        EXAMPLE_DATA,
        {"url": ["http://example.org/hw.txt"], "content-type": "text/plain", "experimental": "test"},
    )

    assert hashlink._serialize_metadata() == EXAMPLE_LINK_EXP.split(":")[2]

    hashlink.metadata = None 
    assert hashlink._serialize_metadata() == None


def test_deserialize_metadata():
    
    metadata = EXAMPLE_LINK_EXP.split(":")[2]

    assert Hashlink._deserialize_metadata(metadata) == EXAMPLE_METADATA


def test_deserialize_data():

    data = EXAMPLE_LINK.split(":")[1]

    assert Hashlink._deserialize_data(data) == EXAMPLE_DATA_SHA
    
    with pytest.raises(Exception):
        data = EXAMPLE_LINK.split(":")[2]
        Hashlink._deserialize_data(data)


def test_verify_link():

    assert Hashlink.verify(EXAMPLE_LINK, EXAMPLE_DATA)
    assert Hashlink.verify("Bad Link!", EXAMPLE_DATA) == False
    assert Hashlink.verify(EXAMPLE_LINK, b"Bad Data!") == False
    assert Hashlink.verify(EXAMPLE_LINK) == False

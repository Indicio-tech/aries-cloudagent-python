from unittest import IsolatedAsyncioTestCase

from ....protocols.trustping.v1_0.messages.ping import Ping
from ....utils.testing import create_test_profile
from ....wallet.base import BaseWallet
from ....wallet.key_type import ED25519
from ..signature_decorator import SignatureDecorator

TEST_VERKEY = "3Dn1SJNPaCXcvvJvSbsFWP2xaCjMom3can8CQNhWrTRx"


class TestSignatureDecorator(IsolatedAsyncioTestCase):
    async def test_init(self):
        decorator = SignatureDecorator()
        assert decorator.signature_type is None
        assert decorator.signature is None
        assert decorator.sig_data is None
        assert decorator.signer is None
        assert "SignatureDecorator" in str(decorator)

    async def test_serialize_load(self):
        TEST_SIG = "IkJvYiI="
        TEST_SIG_DATA = "MTIzNDU2Nzg5MCJCb2Ii"

        decorator = SignatureDecorator(
            signature_type=SignatureDecorator.TYPE_ED25519SHA512,
            signature=TEST_SIG,
            sig_data=TEST_SIG_DATA,
            signer=TEST_VERKEY,
        )

        dumped = decorator.serialize()
        loaded = SignatureDecorator.deserialize(dumped)

        assert loaded.signature_type == SignatureDecorator.TYPE_ED25519SHA512
        assert loaded.signature == TEST_SIG
        assert loaded.sig_data == TEST_SIG_DATA
        assert loaded.signer == TEST_VERKEY

    async def test_create_decode_verify(self):
        TEST_MESSAGE = "Hello world"
        TEST_TIMESTAMP = 1234567890

        self.profile = await create_test_profile()
        async with self.profile.session() as session:
            wallet = session.inject(BaseWallet)
            key_info = await wallet.create_signing_key(ED25519)

            deco = await SignatureDecorator.create(
                Ping(), key_info.verkey, wallet, timestamp=None
            )
            assert deco

            deco = await SignatureDecorator.create(
                TEST_MESSAGE, key_info.verkey, wallet, TEST_TIMESTAMP
            )

            (msg, timestamp) = deco.decode()
            assert msg == TEST_MESSAGE
            assert timestamp == TEST_TIMESTAMP

            await deco.verify(wallet)
            deco.signature_type = "unsupported-sig-type"
            assert not await deco.verify(wallet)

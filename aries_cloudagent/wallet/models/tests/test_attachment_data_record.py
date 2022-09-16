from base64 import urlsafe_b64encode
from datetime import datetime
from typing import cast
from uuid import uuid4

import pytest
from aries_cloudagent.config.injection_context import InjectionContext
from aries_cloudagent.indy.sdk.profile import IndySdkProfile, IndySdkProfileManager
from aries_cloudagent.wallet.base import BaseWallet

from aries_cloudagent.wallet.indy import IndySdkWallet

from ....core.event_bus import EventBus
from ....core.in_memory import InMemoryProfile
from ....messaging.decorators.attach_decorator import AttachDecoratorData
from ....messaging.decorators.attach_decorator import AttachDecorator
from ....messaging.responder import BaseResponder, MockResponder
from ....protocols.issue_credential.v2_0.messages.inner.supplement import (
    Supplement,
    SupplementAttribute,
)
from ....protocols.issue_credential.v2_0.tests.test_hashlink import (
    EXAMPLE_DATA,
    EXAMPLE_LINK,
)
from ...models.attachment_data_record import AttachmentDataRecord
from ..attachment_data_record import (
    AttachDecorator,
    AttachmentDataRecord,
    Supplement,
)
from asynctest import mock


@pytest.fixture
def attachment_id():
    yield str(uuid4())


@pytest.fixture
def event_bus():
    """Event bus fixture."""
    yield EventBus()


@pytest.fixture
def mock_responder():
    """Mock responder fixture."""
    yield MockResponder()


@pytest.fixture
def profile(event_bus, mock_responder):
    """Profile fixture."""
    yield InMemoryProfile.test_profile(
        bind={EventBus: event_bus, BaseResponder: mock_responder}
    )


@pytest.fixture
def attachment(attachment_id):
    yield AttachDecorator(
        ident=attachment_id,
        description="asdf",
        filename="asdf",
        mime_type="image/jpeg",
        lastmod_time=str(datetime.now()),
        data=AttachDecoratorData(base64_=urlsafe_b64encode(EXAMPLE_DATA).decode()),
    )


@pytest.fixture
def supplement(attachment_id):
    yield Supplement(
        type="hashlink-data",
        ref=attachment_id,
        attrs=[SupplementAttribute("field", "test")],
    )


@pytest.fixture
def record(attachment, supplement):
    yield AttachmentDataRecord(
        supplement=supplement,
        attachment=attachment,
        cred_id="test-cred-id",
        attribute="test",
    )


@pytest.fixture
def create_supplement():
    def _create_supplement(num):
        return Supplement(
            type="hashlink_data",
            attrs=[SupplementAttribute("field", "<fieldname>")],
            ref="attachment_id_" + str(num),
        )

    return _create_supplement


@pytest.fixture
def create_attachment():
    def _create_attachment(num):
        return AttachDecorator(
            ident="attachment_id_" + str(num),
            data=AttachDecoratorData(base64_="data_" + str(num)),
        )

    return _create_attachment


def test_records_from_supplements_attachments(create_supplement, create_attachment):

    supplements = [create_supplement(i) for i in range(2)]
    attachments = [create_attachment(i) for i in range(2)]
    records = AttachmentDataRecord.records_from_supplements_attachments(
        supplements, attachments, cred_id="test_cred_id"
    )

    for record in records:
        assert type(record) == AttachmentDataRecord
        assert record.attribute == "<fieldname>"


@pytest.mark.asyncio
async def test_save_attachments(create_supplement, create_attachment, profile):

    async with profile.session() as session:
        supplements = [create_supplement(i) for i in range(2)]
        attachments = [create_attachment(i) for i in range(2)]
        result = await AttachmentDataRecord.save_attachments(
            session, supplements, attachments, cred_id="test_cred_id"
        )

        assert type(result) == list
        assert len(result) == 2


@pytest.fixture()
async def indy_profile():
    key = await IndySdkWallet.generate_wallet_key()
    context = InjectionContext()
    with mock.patch.object(IndySdkProfile, "_make_finalizer"):
        profile = cast(
            IndySdkProfile,
            await IndySdkProfileManager().provision(
                context,
                {
                    "auto_recreate": True,
                    "auto_remove": True,
                    "name": "test-wallet",
                    "key": key,
                    "key_derivation_method": "RAW",  # much slower tests with argon-hashed keys
                },
            ),
        )
    yield profile
    await profile.close()


@pytest.mark.indy
@pytest.mark.asyncio
async def test_query_by_cred_id_attribute(indy_profile: IndySdkProfile, record):
    async with indy_profile.session() as session:
        await record.save(session)
        record = await AttachmentDataRecord.query_by_cred_id_attribute(
            session, cred_id="test-cred-id", attribute=["test", "fake", "another"]
        )
        assert record.supplement
        assert record.attachment

"""Test handler for keylist-update message."""

from unittest import IsolatedAsyncioTestCase

import pytest

from ......connections.models.conn_record import ConnRecord
from ......messaging.base_handler import HandlerException
from ......messaging.request_context import RequestContext
from ......messaging.responder import MockResponder
from ......utils.testing import create_test_profile
from ...messages.inner.keylist_update_rule import KeylistUpdateRule
from ...messages.keylist_update import KeylistUpdate
from ...messages.keylist_update_response import KeylistUpdateResponse
from ...messages.problem_report import CMProblemReport
from ...models.mediation_record import MediationRecord
from ..keylist_update_handler import KeylistUpdateHandler

TEST_CONN_ID = "conn-id"
TEST_VERKEY = "3Dn1SJNPaCXcvvJvSbsFWP2xaCjMom3can8CQNhWrTRx"


class TestKeylistUpdateHandler(IsolatedAsyncioTestCase):
    """Test handler for keylist-update message."""

    async def asyncSetUp(self):
        """Setup test dependencies."""
        self.context = RequestContext.test_context(await create_test_profile())
        self.session = await self.context.session()
        self.context.message = KeylistUpdate(
            updates=[
                KeylistUpdateRule(
                    recipient_key=TEST_VERKEY, action=KeylistUpdateRule.RULE_ADD
                )
            ]
        )
        self.context.connection_ready = True
        self.context.connection_record = ConnRecord(connection_id=TEST_CONN_ID)

    async def test_handler_no_active_connection(self):
        handler, responder = KeylistUpdateHandler(), MockResponder()
        self.context.connection_ready = False
        with pytest.raises(HandlerException):
            await handler.handle(self.context, responder)

    async def test_handler_no_record(self):
        handler, responder = KeylistUpdateHandler(), MockResponder()
        await handler.handle(self.context, responder)
        assert len(responder.messages) == 1
        result, _target = responder.messages[0]
        assert isinstance(result, CMProblemReport)

    async def test_handler_mediation_not_granted(self):
        handler, responder = KeylistUpdateHandler(), MockResponder()
        await MediationRecord(connection_id=TEST_CONN_ID).save(self.session)
        await handler.handle(self.context, responder)
        assert len(responder.messages) == 1
        result, _target = responder.messages[0]
        assert isinstance(result, CMProblemReport)

    async def test_handler(self):
        handler, responder = KeylistUpdateHandler(), MockResponder()
        await MediationRecord(
            state=MediationRecord.STATE_GRANTED, connection_id=TEST_CONN_ID
        ).save(self.session)
        await handler.handle(self.context, responder)
        assert len(responder.messages) == 1
        result, _target = responder.messages[0]
        assert isinstance(result, KeylistUpdateResponse)

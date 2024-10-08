from unittest import IsolatedAsyncioTestCase

from acapy_agent.tests import mock

from ......messaging.request_context import RequestContext
from ......messaging.responder import MockResponder
from .. import menu_request_handler as handler


class TestMenuRequestHandler(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.context = RequestContext.test_context()

    async def test_called(self):
        MenuService = mock.MagicMock(handler.BaseMenuService, autospec=True)
        self.menu_service = MenuService()
        self.context.injector.bind_instance(handler.BaseMenuService, self.menu_service)

        self.context.connection_record = mock.MagicMock()
        self.context.connection_record.connection_id = "dummy"
        self.context.connection_ready = True

        responder = MockResponder()
        self.context.message = handler.MenuRequest()
        self.menu_service.get_active_menu = mock.CoroutineMock(return_value="menu")

        handler_inst = handler.MenuRequestHandler()
        await handler_inst.handle(self.context, responder)

        messages = responder.messages
        assert len(messages) == 1
        (result, target) = messages[0]
        assert result == "menu"
        assert target == {}

    async def test_called_no_active_menu(self):
        MenuService = mock.MagicMock(handler.BaseMenuService, autospec=True)
        self.menu_service = MenuService()
        self.context.injector.bind_instance(handler.BaseMenuService, self.menu_service)

        self.context.connection_record = mock.MagicMock()
        self.context.connection_record.connection_id = "dummy"
        self.context.connection_ready = True

        responder = MockResponder()
        self.context.message = handler.MenuRequest()
        self.menu_service.get_active_menu = mock.CoroutineMock(return_value=None)

        handler_inst = handler.MenuRequestHandler()
        await handler_inst.handle(self.context, responder)

        messages = responder.messages
        assert not messages

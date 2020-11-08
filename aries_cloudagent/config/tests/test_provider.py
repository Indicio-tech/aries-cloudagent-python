from aries_cloudagent.wallet.provider import WalletProvider
from tempfile import NamedTemporaryFile

from asynctest import TestCase as AsyncTestCase, mock as async_mock

from ...storage.provider import StorageProvider
from ...utils.stats import Collector
from ...wallet.base import BaseWallet
from ...wallet.basic import BasicWallet

from ..injection_context import InjectionContext
from ..provider import CachedProvider, StatsProvider
from ..settings import Settings


class TestProvider(AsyncTestCase):
    async def test_stats_provider_init_x(self):
        """Cover stats provider init error on no provider."""
        with self.assertRaises(ValueError):
            StatsProvider(None, ["method"])

    async def test_stats_provider_provide_collector(self):
        """Cover call to provide with collector."""

        timing_log = NamedTemporaryFile().name
        settings = {"timing.enabled": True, "timing.log.file": timing_log}
        stats_provider = StatsProvider(
            StorageProvider(), ("add_record", "get_record", "search_records")
        )
        collector = Collector(log_path=timing_log)

        wallet = BasicWallet()
        context = InjectionContext(settings=settings, enforce_typing=False)
        context.injector.bind_instance(Collector, collector)
        context.injector.bind_instance(BaseWallet, wallet)

        await stats_provider.provide(Settings(settings), context.injector)

    async def test_cached_provider_same_unique_settings(self):
        """Cover same unique keys returns same instance."""
        first_settings = Settings(
            {"wallet.name": "wallet.name", "wallet.key": "wallet.key"}
        )
        second_settings = first_settings.extend({"wallet.key": "another.wallet.key"})

        cached_provider = CachedProvider(WalletProvider(), ("wallet.name",))
        context = InjectionContext()

        first_instance = await cached_provider.provide(first_settings, context.injector)
        second_instance = await cached_provider.provide(
            second_settings, context.injector
        )

        assert first_instance is second_instance

    async def test_cached_provider_different_unique_settings(self):
        """Cover two different unique keys returns different instance."""
        first_settings = Settings(
            {"wallet.name": "wallet.name", "wallet.key": "wallet.key"}
        )
        second_settings = first_settings.extend({"wallet.name": "another.wallet.name"})

        cached_provider = CachedProvider(WalletProvider(), ("wallet.name",))
        context = InjectionContext()

        first_instance = await cached_provider.provide(first_settings, context.injector)
        second_instance = await cached_provider.provide(
            second_settings, context.injector
        )

        assert first_instance is not second_instance

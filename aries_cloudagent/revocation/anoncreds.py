"""Indy revocation registry management."""

from typing import Optional, Sequence, Tuple
from uuid import uuid4

from ..anoncreds.registry import AnonCredsRegistry
from ..core.profile import Profile
from ..protocols.endorse_transaction.v1_0.util import (
    get_endorser_connection_id,
    is_author_role,
)
from ..storage.base import StorageNotFoundError
from .error import (
    RevocationError,
    RevocationNotSupportedError,
    RevocationRegistryBadSizeError,
)
from .models.issuer_rev_reg_record import IssuerRevRegRecord
from .models.revocation_registry import RevocationRegistry
from .util import notify_revocation_reg_init_event


class AnonCredsRevocation:
    """Class for managing Indy credential revocation."""

    REV_REG_CACHE = {}

    def __init__(self, profile: Profile):
        """Initialize the AnonCredsRevocation instance."""
        self._profile = profile

    async def init_issuer_registry(
        self,
        issuer_id: str,
        cred_def_id: str,
        max_cred_num: int = None,
        revoc_def_type: str = None,
        tag: str = None,
        create_pending_rev_reg: bool = False,
        endorser_connection_id: str = None,
        options: Optional[dict] = None,
        notify: bool = True,
    ) -> IssuerRevRegRecord:
        """Create a new revocation registry record for a credential definition."""
        anoncreds_registry = self._profile.inject(AnonCredsRegistry)
        result = await anoncreds_registry.get_credential_definition(
            self._profile, cred_def_id
        )
        if not result.credential_definition.value.revocation:
            raise RevocationNotSupportedError(
                "Credential definition does not support revocation"
            )
        if max_cred_num and not (
            RevocationRegistry.MIN_SIZE <= max_cred_num <= RevocationRegistry.MAX_SIZE
        ):
            raise RevocationRegistryBadSizeError(
                f"Bad revocation registry size: {max_cred_num}"
            )

        record_id = str(uuid4())
        record = IssuerRevRegRecord(
            new_with_id=True,
            record_id=record_id,
            cred_def_id=cred_def_id,
            issuer_id=issuer_id,
            max_cred_num=max_cred_num,
            revoc_def_type=revoc_def_type,
            tag=tag or record_id,
            options=options,
        )
        async with self._profile.session() as session:
            await record.save(session, reason="Init revocation registry")

        if endorser_connection_id is None and is_author_role(self._profile):
            endorser_connection_id = await get_endorser_connection_id(self._profile)
            if not endorser_connection_id:
                raise RevocationError(reason="Endorser connection not found")

        if notify:
            await notify_revocation_reg_init_event(
                self._profile,
                record.record_id,
                create_pending_rev_reg=create_pending_rev_reg,
                endorser_connection_id=endorser_connection_id,
            )

        return record

    async def handle_full_registry(self, revoc_reg_id: str):
        """Update the registry status and start the next registry generation."""
        async with self._profile.transaction() as txn:
            registry = await IssuerRevRegRecord.retrieve_by_revoc_reg_id(
                txn, revoc_reg_id, for_update=True
            )
            if registry.state == IssuerRevRegRecord.STATE_FULL:
                return
            await registry.set_state(
                txn,
                IssuerRevRegRecord.STATE_FULL,
            )
            await txn.commit()

        await self.init_issuer_registry(
            registry.issuer_id,
            registry.cred_def_id,
            registry.max_cred_num,
            registry.revoc_def_type,
        )

    async def get_active_issuer_rev_reg_record(
        self, cred_def_id: str
    ) -> IssuerRevRegRecord:
        """Return current active registry for issuing a given credential definition.

        Args:
            cred_def_id: ID of the base credential definition
        """
        async with self._profile.session() as session:
            current = sorted(
                await IssuerRevRegRecord.query_by_cred_def_id(
                    session, cred_def_id, IssuerRevRegRecord.STATE_ACTIVE
                )
            )
        if current:
            return current[0]  # active record is oldest published but not full
        raise StorageNotFoundError(
            f"No active issuer revocation record found for cred def id {cred_def_id}"
        )

    async def get_issuer_rev_reg_record(self, revoc_reg_id: str) -> IssuerRevRegRecord:
        """Return a revocation registry record by identifier.

        Args:
            revoc_reg_id: ID of the revocation registry
        """
        async with self._profile.session() as session:
            return await IssuerRevRegRecord.retrieve_by_revoc_reg_id(
                session, revoc_reg_id
            )

    async def list_issuer_registries(self) -> Sequence[IssuerRevRegRecord]:
        """List the issuer's current revocation registries."""
        async with self._profile.session() as session:
            return await IssuerRevRegRecord.query(session)

    async def get_or_create_active_registry(
        self, cred_def_id: str, max_cred_num: int = None
    ) -> Optional[Tuple[IssuerRevRegRecord, RevocationRegistry]]:
        """Fetch the active revocation registry.

        If there is no active registry then creation of a new registry will be
        triggered and the caller should retry after a delay.
        """
        try:
            active_rev_reg_rec = await self.get_active_issuer_rev_reg_record(
                cred_def_id
            )
            rev_reg = active_rev_reg_rec.get_registry()
            await rev_reg.get_or_fetch_local_tails_path()
            return active_rev_reg_rec, rev_reg
        except StorageNotFoundError:
            pass

        async with self._profile.session() as session:
            rev_reg_recs = await IssuerRevRegRecord.query_by_cred_def_id(
                session, cred_def_id, {"$neq": IssuerRevRegRecord.STATE_FULL}
            )
            if not rev_reg_recs:
                await self.init_issuer_registry(
                    cred_def_id,
                    max_cred_num=max_cred_num,
                )
        return None

    async def get_revocation_registry(self, revoc_reg_id: str) -> RevocationRegistry:
        """Return a revocation registry by identifier and hydrate."""
        anoncreds_registry = self._profile.inject(AnonCredsRegistry)
        result = await anoncreds_registry.get_revocation_registry_definition(
            self._profile, revoc_reg_id
        )
        rev_reg = RevocationRegistry.from_definition(
            result.revocation_registry.serialize(), True
        )
        AnonCredsRevocation.REV_REG_CACHE[revoc_reg_id] = rev_reg
        return rev_reg

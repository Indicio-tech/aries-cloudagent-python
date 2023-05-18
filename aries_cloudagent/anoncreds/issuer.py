"""anoncreds-rs issuer implementation."""

import asyncio
import logging
import os
from pathlib import Path
from time import time
from typing import NamedTuple, Optional, Sequence, Tuple
from urllib.parse import urlparse
import uuid

from anoncreds import (
    AnoncredsError,
    Credential,
    CredentialDefinition,
    CredentialOffer,
    CredentialRevocationConfig,
    RevocationRegistryDefinition,
    RevocationStatusList,
    Schema,
)
from aries_askar import AskarError
from aries_cloudagent.revocation.error import RevocationError
from aries_cloudagent.revocation.models.issuer_rev_reg_record import IssuerRevRegRecord

from ..askar.profile import AskarProfile, AskarProfileSession
from ..core.error import BaseError
from ..tails.base import BaseTailsServer
from .base import AnonCredsRegistrationError, AnonCredsSchemaAlreadyExists
from .models.anoncreds_cred_def import CredDef, CredDefResult
from .models.anoncreds_revocation import (
    RevList,
    RevRegDef,
    RevRegDefResult,
    RevRegDefState,
)
from .models.anoncreds_schema import AnonCredsSchema, SchemaResult, SchemaState
from .registry import AnonCredsRegistry
from .util import indy_client_dir

LOGGER = logging.getLogger(__name__)

DEFAULT_CRED_DEF_TAG = "default"
DEFAULT_SIGNATURE_TYPE = "CL"
CATEGORY_SCHEMA = "schema"
CATEGORY_CRED_DEF = "credential_def"
CATEGORY_CRED_DEF_PRIVATE = "credential_def_private"
CATEGORY_CRED_DEF_KEY_PROOF = "credential_def_key_proof"
CATEGORY_REV_LIST = "revocation_list"
CATEGORY_REV_REG_INFO = "revocation_reg_info"
CATEGORY_REV_REG_DEF = "revocation_reg_def"
CATEGORY_REV_REG_DEF_PRIVATE = "revocation_reg_def_private"
CATEGORY_REV_REG_ISSUER = "revocation_reg_def_issuer"
STATE_FINISHED = "finished"

EVENT_PREFIX = "acapy::anoncreds::"
EVENT_SCHEMA = EVENT_PREFIX + CATEGORY_SCHEMA
EVENT_CRED_DEF = EVENT_PREFIX + CATEGORY_CRED_DEF
EVENT_REV_REG_DEF = EVENT_PREFIX + CATEGORY_REV_REG_DEF
EVENT_REV_LIST = EVENT_PREFIX + CATEGORY_REV_LIST
EVENT_FINISHED_SUFFIX = "::" + STATE_FINISHED


class AnonCredsIssuerError(BaseError):
    """Generic issuer error."""


class AnonCredsIssuerRevocationRegistryFullError(AnonCredsIssuerError):
    """Revocation registry is full when issuing a new credential."""


class RevokeResult(NamedTuple):
    prev: Optional[RevocationStatusList] = None
    curr: Optional[RevocationStatusList] = None
    failed: Optional[Sequence[str]] = None


class AnonCredsIssuer:
    """AnonCreds issuer class.

    This class provides methods for creating and registering AnonCreds objects
    needed to issue credentials. It also provides methods for storing and
    retrieving local representations of these objects from the wallet.

    A general pattern is followed when creating and registering objects:

    1. Create the object locally
    2. Register the object with the anoncreds registry
    3. Store the object in the wallet

    The wallet storage is used to keep track of the state of the object.

    If the object is fully registered immediately after sending to the registry
    (state of `finished`), the object is saved to the wallet with an id
    matching the id returned from the registry.

    If the object is not fully registered but pending (state of `wait`), the
    object is saved to the wallet with an id matching the job id returned from
    the registry.

    If the object fails to register (state of `failed`), the object is saved to
    the wallet with an id matching the job id returned from the registry.

    When an object finishes registration after being in a pending state (moving
    from state `wait` to state `finished`), the wallet entry matching the job id
    is removed and an entry matching the registered id is added.
    """

    def __init__(self, profile: AskarProfile):
        """
        Initialize an AnonCredsIssuer instance.

        Args:
            profile: The active profile instance

        """
        self._profile = profile

    @property
    def profile(self) -> AskarProfile:
        """Accessor for the profile instance."""
        return self._profile

    async def _update_entry_state(self, category: str, name: str, state: str):
        """Update the state tag of an entry in a given category."""
        try:
            async with self._profile.transaction() as txn:
                entry = await txn.handle.fetch(
                    category,
                    name,
                    for_update=True,
                )
                if not entry:
                    raise AnonCredsIssuerError(
                        f"{category} with id {name} could not be found"
                    )

                entry.tags["state"] = state
                await txn.handle.replace(
                    CATEGORY_SCHEMA,
                    name,
                    tags=entry.tags,
                )
        except AskarError as err:
            raise AnonCredsIssuerError(f"Error marking {category} as {state}") from err

    async def _finish_registration(
        self, txn: AskarProfileSession, category: str, job_id: str, registered_id: str
    ):
        entry = await txn.handle.fetch(
            category,
            job_id,
            for_update=True,
        )
        if not entry:
            raise AnonCredsIssuerError(
                f"{category} with job id {job_id} could not be found"
            )

        tags = entry.tags
        tags["state"] = STATE_FINISHED
        await txn.handle.insert(
            category,
            registered_id,
            value=entry.value,
            tags=tags,
        )
        await txn.handle.remove(category, job_id)

    async def _store_schema(
        self,
        result: SchemaResult,
    ):
        """Store schema after reaching finished state."""
        ident = result.schema_state.schema_id or result.job_id
        if not ident:
            raise ValueError("Schema id or job id must be set")

        try:
            async with self._profile.session() as session:
                await session.handle.insert(
                    CATEGORY_SCHEMA,
                    ident,
                    result.schema_state.schema.to_json(),
                    {
                        "name": result.schema_state.schema.name,
                        "version": result.schema_state.schema.version,
                        "issuer_id": result.schema_state.schema.issuer_id,
                        "state": result.schema_state.state,
                    },
                )
        except AskarError as err:
            raise AnonCredsIssuerError("Error storing schema") from err

    async def create_and_register_schema(
        self,
        issuer_id: str,
        name: str,
        version: str,
        attr_names: Sequence[str],
        options: Optional[dict] = None,
    ) -> SchemaResult:
        """
        Create a new credential schema and store it in the wallet.

        Args:
            issuer_id: the DID issuing the credential definition
            name: the schema name
            version: the schema version
            attr_names: a sequence of schema attribute names

        Returns:
            A SchemaResult instance

        """
        # Check if record of a similar schema already exists in our records
        async with self._profile.session() as session:
            # TODO scan?
            schemas = await session.handle.fetch_all(
                CATEGORY_SCHEMA,
                {
                    "name": name,
                    "version": version,
                    "issuer_id": issuer_id,
                },
                limit=1,
            )
            if schemas:
                raise AnonCredsSchemaAlreadyExists(
                    f"Schema with {name}: {version} " f"already exists for {issuer_id}",
                    schemas[0].name,
                    AnonCredsSchema.deserialize(schemas[0].value_json),
                )

        schema = Schema.create(name, version, issuer_id, attr_names)
        try:
            anoncreds_registry = self._profile.inject(AnonCredsRegistry)
            schema_result = await anoncreds_registry.register_schema(
                self.profile,
                AnonCredsSchema.from_native(schema),
                options,
            )

            await self._store_schema(schema_result)

            return schema_result

        except AnonCredsSchemaAlreadyExists as err:
            # If we find that we've previously written a schema that looks like
            # this one before but that schema is not in our wallet, add it to
            # the wallet so we can return from our get schema calls
            await self._store_schema(
                SchemaResult(
                    job_id=None,
                    schema_state=SchemaState(
                        state=SchemaState.STATE_FINISHED,
                        schema_id=err.schema_id,
                        schema=err.schema,
                    ),
                )
            )
            raise AnonCredsIssuerError(
                "Schema already exists but was not in wallet; stored in wallet"
            ) from err
        except AnoncredsError as err:
            raise AnonCredsIssuerError("Error creating schema") from err

    async def finish_schema(self, job_id: str, schema_id: str):
        """Mark a schema as finished."""
        async with self.profile.transaction() as txn:
            await self._finish_registration(txn, CATEGORY_SCHEMA, job_id, schema_id)
            await txn.commit()

    async def get_created_schemas(
        self,
        name: Optional[str] = None,
        version: Optional[str] = None,
        issuer_id: Optional[str] = None,
    ) -> Sequence[str]:
        """Retrieve IDs of schemas previously created."""
        async with self._profile.session() as session:
            # TODO limit? scan?
            schemas = await session.handle.fetch_all(
                CATEGORY_SCHEMA,
                {
                    key: value
                    for key, value in {
                        "name": name,
                        "version": version,
                        "issuer_id": issuer_id,
                        "state": STATE_FINISHED,
                    }.items()
                    if value is not None
                },
            )
        # entry.name was stored as the schema's ID
        return [entry.name for entry in schemas]

    async def credential_definition_in_wallet(
        self, credential_definition_id: str
    ) -> bool:
        """
        Check whether a given credential definition ID is present in the wallet.

        Args:
            credential_definition_id: The credential definition ID to check
        """
        try:
            async with self._profile.session() as session:
                return (
                    await session.handle.fetch(
                        CATEGORY_CRED_DEF_PRIVATE, credential_definition_id
                    )
                ) is not None
        except AskarError as err:
            raise AnonCredsIssuerError(
                "Error checking for credential definition"
            ) from err

    async def create_and_register_credential_definition(
        self,
        issuer_id: str,
        schema_id: str,
        tag: Optional[str] = None,
        signature_type: Optional[str] = None,
        options: Optional[dict] = None,
    ) -> CredDefResult:
        """
        Create a new credential definition and store it in the wallet.

        Args:
            issuer_id: the ID of the issuer creating the credential definition
            schema_id: the schema ID for the credential definition
            tag: the tag to use for the credential definition
            signature_type: the signature type to use for the credential definition
            options: any additional options to use when creating the credential definition

        Returns:
            CredDefResult: the result of the credential definition creation

        """
        anoncreds_registry = self._profile.inject(AnonCredsRegistry)
        schema_result = await anoncreds_registry.get_schema(self.profile, schema_id)

        options = options or {}
        support_revocation = options.get("support_revocation", False)

        try:
            # Create the cred def
            (
                cred_def,
                cred_def_private,
                key_proof,
            ) = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: CredentialDefinition.create(
                    schema_id,
                    schema_result.schema.serialize(),
                    issuer_id,
                    tag or DEFAULT_CRED_DEF_TAG,
                    signature_type or DEFAULT_SIGNATURE_TYPE,
                    support_revocation=support_revocation,
                ),
            )
            cred_def_json = cred_def.to_json()

            # Register the cred def
            result = await anoncreds_registry.register_credential_definition(
                self.profile,
                schema_result,
                CredDef.from_native(cred_def),
                options,
            )
        except AnoncredsError as err:
            raise AnonCredsIssuerError("Error creating credential definition") from err

        # Store the cred def and it's components
        ident = (
            result.credential_definition_state.credential_definition_id or result.job_id
        )
        if not ident:
            raise AnonCredsIssuerError("cred def id or job id required")

        try:
            async with self._profile.transaction() as txn:
                await txn.handle.insert(
                    CATEGORY_CRED_DEF,
                    ident,
                    cred_def_json,
                    tags={
                        "schema_id": schema_id,
                        "schema_issuer_id": schema_result.schema.issuer_id,
                        "issuer_id": issuer_id,
                        "schema_name": schema_result.schema.name,
                        "schema_version": schema_result.schema.version,
                        "state": result.credential_definition_state.state,
                        "epoch": str(int(time())),
                    },
                )
                await txn.handle.insert(
                    CATEGORY_CRED_DEF_PRIVATE,
                    ident,
                    cred_def_private.to_json_buffer(),
                )
                await txn.handle.insert(
                    CATEGORY_CRED_DEF_KEY_PROOF, ident, key_proof.to_json_buffer()
                )
                await txn.commit()
        except AskarError as err:
            raise AnonCredsIssuerError("Error storing credential definition") from err

        return result

    async def finish_cred_def(self, job_id: str, cred_def_id: str):
        """Finish a cred def."""
        async with self.profile.transaction() as txn:
            await self._finish_registration(txn, CATEGORY_CRED_DEF, job_id, cred_def_id)
            await self._finish_registration(
                txn, CATEGORY_CRED_DEF_PRIVATE, job_id, cred_def_id
            )
            await self._finish_registration(
                txn, CATEGORY_CRED_DEF_KEY_PROOF, job_id, cred_def_id
            )
            await txn.commit()

    async def get_created_credential_definitions(
        self,
        issuer_id: Optional[str] = None,
        schema_issuer_id: Optional[str] = None,
        schema_id: Optional[str] = None,
        schema_name: Optional[str] = None,
        schema_version: Optional[str] = None,
        epoch: Optional[str] = None,
    ) -> Sequence[str]:
        """Retrieve IDs of credential definitions previously created."""
        async with self._profile.session() as session:
            # TODO limit? scan?
            credential_definition_entries = await session.handle.fetch_all(
                CATEGORY_CRED_DEF,
                {
                    key: value
                    for key, value in {
                        "issuer_id": issuer_id,
                        "schema_issuer_id": schema_issuer_id,
                        "schema_id": schema_id,
                        "schema_name": schema_name,
                        "schema_version": schema_version,
                        "epoch": epoch,
                        "state": STATE_FINISHED,
                    }.items()
                    if value is not None
                },
            )
        # entry.name is cred def id when state == finished
        return [entry.name for entry in credential_definition_entries]

    async def match_created_credential_definitions(
        self,
        cred_def_id: Optional[str] = None,
        issuer_id: Optional[str] = None,
        schema_issuer_id: Optional[str] = None,
        schema_id: Optional[str] = None,
        schema_name: Optional[str] = None,
        schema_version: Optional[str] = None,
        epoch: Optional[str] = None,
    ) -> Optional[str]:
        """Return cred def id of most recent matching cred def."""
        async with self._profile.session() as session:
            # TODO limit? scan?
            if cred_def_id:
                cred_def_entry = await session.handle.fetch(
                    CATEGORY_CRED_DEF, cred_def_id
                )
            else:
                credential_definition_entries = await session.handle.fetch_all(
                    CATEGORY_CRED_DEF,
                    {
                        key: value
                        for key, value in {
                            "issuer_id": issuer_id,
                            "schema_issuer_id": schema_issuer_id,
                            "schema_id": schema_id,
                            "schema_name": schema_name,
                            "schema_version": schema_version,
                            "state": STATE_FINISHED,
                            "epoch": epoch,
                        }.items()
                        if value is not None
                    },
                )
                cred_def_entry = max(
                    [entry for entry in credential_definition_entries],
                    key=lambda r: int(r.tags["epoch"]),
                )

        if cred_def_entry:
            return cred_def_entry.name

        return None

    async def cred_def_supports_revocation(self, cred_def_id: str) -> bool:
        """Return whether a credential definition supports revocation."""
        anoncreds_registry = self.profile.inject(AnonCredsRegistry)
        cred_def_result = await anoncreds_registry.get_credential_definition(
            self.profile, cred_def_id
        )
        return cred_def_result.credential_definition.value.revocation is not None

    async def create_and_register_revocation_registry_definition(
        self,
        profile,
        issuer_rev_reg_record: IssuerRevRegRecord,
        options: Optional[dict] = None,
    ) -> RevRegDefResult:
        """
        Create a new revocation registry and register on network.

        Args:
            issuer_id (str): issuer identifier
            cred_def_id (str): credential definition identifier
            registry_type (str): revocation registry type
            tag (str): revocation registry tag
            max_cred_num (int): maximum number of credentials supported
            options (dict): revocation registry options

        Returns:
            RevRegDefResult: revocation registry definition result

        """

        if not issuer_rev_reg_record.tag:
            issuer_rev_reg_record.tag = issuer_rev_reg_record._id or str(uuid.uuid4())

        if issuer_rev_reg_record.state != IssuerRevRegRecord.STATE_INIT:
            raise RevocationError(
                "Revocation registry {} in state {}: cannot generate".format(
                    issuer_rev_reg_record.revoc_reg_id, issuer_rev_reg_record.state
                )
            )

        LOGGER.debug(
            "Creating revocation registry with size: %d",
            issuer_rev_reg_record.max_cred_num,
        )

        try:
            async with profile.session() as session:
                cred_def = await session.handle.fetch(
                    CATEGORY_CRED_DEF, issuer_rev_reg_record.cred_def_id
                )
        except AskarError as err:
            raise AnonCredsIssuerError(
                "Error retrieving credential definition"
            ) from err

        if not cred_def:
            raise AnonCredsIssuerError(
                "Credential definition not found for revocation registry"
            )

        tails_dir = indy_client_dir("tails", create=True)

        try:
            (
                rev_reg_def,
                rev_reg_def_private,
            ) = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: RevocationRegistryDefinition.create(
                    issuer_rev_reg_record.cred_def_id,
                    cred_def.raw_value,
                    issuer_rev_reg_record.issuer_id,
                    issuer_rev_reg_record.tag,
                    issuer_rev_reg_record.revoc_def_type,
                    issuer_rev_reg_record.max_cred_num,
                    tails_dir_path=tails_dir,
                ),
            )
        except AnoncredsError as err:
            raise AnonCredsIssuerError("Error creating revocation registry") from err

        rev_reg_def_json = rev_reg_def.to_json()
        rev_reg_def = RevRegDef.from_native(rev_reg_def)

        public_tails_uri = self.get_public_tails_uri(rev_reg_def)
        rev_reg_def.value.tails_location = public_tails_uri
        anoncreds_registry = self.profile.inject(AnonCredsRegistry)
        result = await anoncreds_registry.register_revocation_registry_definition(
            self.profile, rev_reg_def, issuer_rev_reg_record.options
        )

        rev_reg_def_id = result.rev_reg_def_id

        try:
            async with self._profile.transaction() as txn:
                await txn.handle.insert(
                    CATEGORY_REV_REG_INFO,
                    rev_reg_def_id,
                    value_json={"curr_id": 0, "used_ids": []},
                )
                await txn.handle.insert(
                    CATEGORY_REV_REG_DEF,
                    rev_reg_def_id,
                    rev_reg_def_json,
                    tags={"cred_def_id": issuer_rev_reg_record.cred_def_id},
                )
                await txn.handle.insert(
                    CATEGORY_REV_REG_DEF_PRIVATE,
                    rev_reg_def_id,
                    rev_reg_def_private.to_json_buffer(),
                )
                await txn.commit()
        except AskarError as err:
            raise AnonCredsIssuerError("Error saving new revocation registry") from err

        issuer_rev_reg_record.revoc_reg_id = result.rev_reg_def_id
        issuer_rev_reg_record.revoc_reg_def = result.rev_reg_def.serialize()
        issuer_rev_reg_record.state = IssuerRevRegRecord.STATE_POSTED
        issuer_rev_reg_record.tails_hash = result.rev_reg_def.value.tails_hash
        issuer_rev_reg_record.tails_public_uri = result.rev_reg_def.value.tails_location
        issuer_rev_reg_record.tails_local_path = self.get_local_tails_path(
            result.rev_reg_def
        )

        async with profile.session() as session:
            await issuer_rev_reg_record.save(session, reason="Generated registry")

        return result

    def _check_url(self, url) -> None:
        parsed = urlparse(url)
        if not (parsed.scheme and parsed.netloc and parsed.path):
            raise AnonCredsRegistrationError("URI {} is not a valid URL".format(url))

    def get_public_tails_uri(self, rev_reg_def: RevRegDef):
        """Construct tails uri from rev_reg_def."""
        tails_base_url = self._profile.settings.get("tails_server_base_url")
        if not tails_base_url:
            raise AnonCredsRegistrationError("tails_server_base_url not configured")

        public_tails_uri = (
            tails_base_url.rstrip("/") + f"/{rev_reg_def.value.tails_hash}"
        )

        self._check_url(public_tails_uri)
        return public_tails_uri

    def get_local_tails_path(self, rev_reg_def: RevRegDef) -> str:
        """Get the local path to the tails file."""
        tails_dir = indy_client_dir("tails", create=False)
        return os.path.join(tails_dir, rev_reg_def.value.tails_hash)

    async def upload_tails_file(self, rev_reg_def: RevRegDef):
        """Upload the local tails file to the tails server."""
        tails_server = self._profile.inject_or(BaseTailsServer)
        if not tails_server:
            raise AnonCredsIssuerError("Tails server not configured")
        if not Path(self.get_local_tails_path(rev_reg_def)).is_file():
            raise AnonCredsIssuerError("Local tails file not found")

        (upload_success, result) = await tails_server.upload_tails_file(
            self._profile.context,
            rev_reg_def.value.tails_hash,
            self.get_local_tails_path(rev_reg_def),
            interval=0.8,
            backoff=-0.5,
            max_attempts=5,  # heuristic: respect HTTP timeout
        )
        if not upload_success:
            raise AnonCredsIssuerError(
                f"Tails file for rev reg for {rev_reg_def.cred_def_id} "
                "failed to upload: {result}"
            )
        if rev_reg_def.value.tails_location != result:
            raise AnonCredsIssuerError(
                f"Tails file for rev reg for {rev_reg_def.cred_def_id} "
                "uploaded to wrong location: {result}"
            )

    async def update_revocation_registry_definition_state(
        self, rev_reg_def_id: str, state: str
    ):
        """Update the state of a rev reg def."""
        await self._update_entry_state(CATEGORY_REV_REG_DEF, rev_reg_def_id, state)

    async def finish_revocation_registry_definition(self, rev_reg_def_id: str):
        """Mark a rev reg def as finished."""
        await self.update_revocation_registry_definition_state(
            rev_reg_def_id, RevRegDefState.STATE_FINISHED
        )

    async def get_created_revocation_registry_definitions(
        self,
        cred_def_id: Optional[str] = None,
        state: Optional[str] = None,
    ) -> Sequence[str]:
        """Retrieve IDs of rev reg defs previously created."""
        async with self._profile.session() as session:
            # TODO limit? scan?
            rev_reg_defs = await session.handle.fetch_all(
                CATEGORY_REV_REG_DEF,
                {
                    key: value
                    for key, value in {
                        "cred_def_id": cred_def_id,
                        "state": state,
                    }.items()
                    if value is not None
                },
            )
        # entry.name was stored as the credential_definition's ID
        return [entry.name for entry in rev_reg_defs]

    async def create_and_register_revocation_list(
        self, rev_reg_record: IssuerRevRegRecord, options: Optional[dict] = None
    ):
        """Create and register a revocation list."""
        rev_reg_id = rev_reg_record.revoc_reg_id
        if not (
            rev_reg_id and rev_reg_record.revoc_def_type and rev_reg_record.issuer_id
        ):
            raise RevocationError("Revocation registry undefined")

        if rev_reg_record.state not in (IssuerRevRegRecord.STATE_POSTED,):
            raise RevocationError(
                "Revocation registry {} in state {}: cannot publish entry".format(
                    rev_reg_id, rev_reg_record.state
                )
            )

        try:
            async with self._profile.session() as session:
                rev_reg_def_entry = await session.handle.fetch(
                    CATEGORY_REV_REG_DEF, rev_reg_id
                )
        except AskarError as err:
            raise AnonCredsIssuerError(
                "Error retrieving credential definition"
            ) from err

        if not rev_reg_def_entry:
            raise AnonCredsIssuerError(
                f"Revocation registry definition not found for id {rev_reg_id}"
            )

        rev_reg_def = RevRegDef.deserialize(rev_reg_def_entry.value_json)

        rev_list = RevocationStatusList.create(
            rev_reg_id,
            rev_reg_def_entry.raw_value,
            rev_reg_def.issuer_id,
        )

        anoncreds_registry = self.profile.inject(AnonCredsRegistry)
        result = await anoncreds_registry.register_revocation_list(
            self.profile, rev_reg_def, RevList.from_native(rev_list), options
        )

        try:
            async with self._profile.session() as session:
                await session.handle.insert(
                    CATEGORY_REV_LIST,
                    rev_reg_id,
                    result.revocation_list_state.revocation_list.to_json(),
                )
        except AskarError as err:
            raise AnonCredsIssuerError("Error saving new revocation registry") from err

        if rev_reg_record.state == IssuerRevRegRecord.STATE_POSTED:
            rev_reg_record.state = (
                IssuerRevRegRecord.STATE_ACTIVE
            )  # registering rev status list activates
            async with self._profile.session() as session:
                await rev_reg_record.save(
                    session, reason="Published initial revocation registry entry"
                )

        return result

    async def create_credential_offer(self, credential_definition_id: str) -> str:
        """
        Create a credential offer for the given credential definition id.

        Args:
            credential_definition_id: The credential definition to create an offer for

        Returns:
            The new credential offer

        """
        try:
            async with self._profile.session() as session:
                cred_def = await session.handle.fetch(
                    CATEGORY_CRED_DEF, credential_definition_id
                )
                key_proof = await session.handle.fetch(
                    CATEGORY_CRED_DEF_KEY_PROOF, credential_definition_id
                )
        except AskarError as err:
            raise AnonCredsIssuerError(
                "Error retrieving credential definition"
            ) from err
        if not cred_def or not key_proof:
            raise AnonCredsIssuerError(
                "Credential definition not found for credential offer"
            )
        try:
            # The tag holds the full name of the schema,
            # as opposed to just the sequence number
            schema_id = cred_def.tags.get("schema_id")
            cred_def = CredentialDefinition.load(cred_def.raw_value)

            credential_offer = CredentialOffer.create(
                schema_id or cred_def.schema_id,
                credential_definition_id,
                key_proof.raw_value,
            )
        except AnoncredsError as err:
            raise AnonCredsIssuerError("Error creating credential offer") from err

        return credential_offer.to_json()

    async def create_credential(
        self,
        schema_id: str,
        credential_offer: dict,
        credential_request: dict,
        credential_values: dict,
        revoc_reg_id: Optional[str] = None,
        tails_file_path: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Create a credential.

        Args
            schema_id: Schema ID to create credential for
            credential_offer: Credential Offer to create credential for
            credential_request: Credential request to create credential for
            credential_values: Values to go in credential
            revoc_reg_id: ID of the revocation registry
            tails_file_path: The location of the tails file

        Returns:
            A tuple of created credential and revocation id

        """
        anoncreds_registry = self.profile.inject(AnonCredsRegistry)
        schema_result = await anoncreds_registry.get_schema(self.profile, schema_id)
        credential_definition_id = credential_offer["cred_def_id"]
        try:
            async with self._profile.session() as session:
                cred_def = await session.handle.fetch(
                    CATEGORY_CRED_DEF, credential_definition_id
                )
                cred_def_private = await session.handle.fetch(
                    CATEGORY_CRED_DEF_PRIVATE, credential_definition_id
                )
        except AskarError as err:
            raise AnonCredsIssuerError(
                "Error retrieving credential definition"
            ) from err
        if not cred_def or not cred_def_private:
            raise AnonCredsIssuerError(
                "Credential definition not found for credential issuance"
            )

        raw_values = {}
        schema_attributes = schema_result.schema.attr_names
        for attribute in schema_attributes:
            # Ensure every attribute present in schema to be set.
            # Extraneous attribute names are ignored.
            try:
                credential_value = credential_values[attribute]
            except KeyError:
                raise AnonCredsIssuerError(
                    "Provided credential values are missing a value "
                    f"for the schema attribute '{attribute}'"
                )

            raw_values[attribute] = str(credential_value)

        if revoc_reg_id:
            try:
                async with self._profile.transaction() as txn:
                    rev_list = await txn.handle.fetch(CATEGORY_REV_LIST, revoc_reg_id)
                    rev_reg_info = await txn.handle.fetch(
                        CATEGORY_REV_REG_INFO, revoc_reg_id, for_update=True
                    )
                    rev_reg_def = await txn.handle.fetch(
                        CATEGORY_REV_REG_DEF, revoc_reg_id
                    )
                    rev_key = await txn.handle.fetch(
                        CATEGORY_REV_REG_DEF_PRIVATE, revoc_reg_id
                    )
                    if not rev_list:
                        raise AnonCredsIssuerError("Revocation registry not found")
                    if not rev_reg_info:
                        raise AnonCredsIssuerError(
                            "Revocation registry metadata not found"
                        )
                    if not rev_reg_def:
                        raise AnonCredsIssuerError(
                            "Revocation registry definition not found"
                        )
                    if not rev_key:
                        raise AnonCredsIssuerError(
                            "Revocation registry definition private data not found"
                        )
                    # NOTE: we increment the index ahead of time to keep the
                    # transaction short. The revocation registry itself will NOT
                    # be updated because we always use ISSUANCE_BY_DEFAULT.
                    # If something goes wrong later, the index will be skipped.
                    # FIXME - double check issuance type in case of upgraded wallet?
                    rev_info = rev_reg_info.value_json
                    rev_reg_index = rev_info["curr_id"] + 1
                    try:
                        rev_reg_def = RevocationRegistryDefinition.load(
                            rev_reg_def.raw_value
                        )
                        rev_list = RevocationStatusList.load(rev_list.raw_value)
                    except AnoncredsError as err:
                        raise AnonCredsIssuerError(
                            "Error loading revocation registry definition"
                        ) from err
                    if rev_reg_index > rev_reg_def.max_cred_num:
                        raise AnonCredsIssuerRevocationRegistryFullError(
                            "Revocation registry is full"
                        )
                    rev_info["curr_id"] = rev_reg_index
                    await txn.handle.replace(
                        CATEGORY_REV_REG_INFO, revoc_reg_id, value_json=rev_info
                    )
                    await txn.commit()
            except AskarError as err:
                raise AnonCredsIssuerError(
                    "Error updating revocation registry index"
                ) from err

            revoc = CredentialRevocationConfig(
                rev_reg_def,
                rev_key.raw_value,
                rev_reg_index,
                tails_file_path,
            )
            credential_revocation_id = str(rev_reg_index)
        else:
            revoc = None
            credential_revocation_id = None
            rev_list = None

        try:
            credential = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: Credential.create(
                    cred_def.raw_value,
                    cred_def_private.raw_value,
                    credential_offer,
                    credential_request,
                    raw_values,
                    None,
                    revoc_reg_id,
                    rev_list,
                    revoc,
                ),
            )
        except AnoncredsError as err:
            raise AnonCredsIssuerError("Error creating credential") from err

        return credential.to_json(), credential_revocation_id

    async def revoke_credentials(
        self,
        revoc_reg_id: str,
        tails_file_path: str,
        cred_revoc_ids: Sequence[str],
    ) -> RevokeResult:
        """
        Revoke a set of credentials in a revocation registry.

        Args:
            revoc_reg_id: ID of the revocation registry
            tails_file_path: path to the local tails file
            cred_revoc_ids: sequences of credential indexes in the revocation registry

        Returns:
            Tuple with the update revocation list, list of cred rev ids not revoked

        """

        # TODO This method should return the old list, the new list,
        # and the list of changed indices
        prev_list = None
        updated_list = None
        failed_crids = set()
        max_attempt = 5
        attempt = 0

        while True:
            attempt += 1
            if attempt >= max_attempt:
                raise AnonCredsIssuerError(
                    "Repeated conflict attempting to update registry"
                )
            try:
                async with self._profile.session() as session:
                    rev_reg_def_entry = await session.handle.fetch(
                        CATEGORY_REV_REG_DEF, revoc_reg_id
                    )
                    rev_list_entry = await session.handle.fetch(
                        CATEGORY_REV_LIST, revoc_reg_id
                    )
                    rev_reg_info = await session.handle.fetch(
                        CATEGORY_REV_REG_INFO, revoc_reg_id
                    )
                if not rev_reg_def_entry:
                    raise AnonCredsIssuerError(
                        "Revocation registry definition not found"
                    )
                if not rev_list_entry:
                    raise AnonCredsIssuerError("Revocation registry not found")
                if not rev_reg_info:
                    raise AnonCredsIssuerError("Revocation registry metadata not found")
            except AskarError as err:
                raise AnonCredsIssuerError(
                    "Error retrieving revocation registry"
                ) from err

            try:
                rev_reg_def = RevocationRegistryDefinition.load(
                    rev_reg_def_entry.raw_value
                )
            except AnoncredsError as err:
                raise AnonCredsIssuerError(
                    "Error loading revocation registry definition"
                ) from err

            rev_crids = set()
            failed_crids = set()
            max_cred_num = rev_reg_def.max_cred_num
            rev_info = rev_reg_info.value_json
            used_ids = set(rev_info.get("used_ids") or [])

            for rev_id in cred_revoc_ids:
                rev_id = int(rev_id)
                if rev_id < 1 or rev_id > max_cred_num:
                    LOGGER.error(
                        "Skipping requested credential revocation"
                        "on rev reg id %s, cred rev id=%s not in range",
                        revoc_reg_id,
                        rev_id,
                    )
                    failed_crids.add(rev_id)
                elif rev_id > rev_info["curr_id"]:
                    LOGGER.warn(
                        "Skipping requested credential revocation"
                        "on rev reg id %s, cred rev id=%s not yet issued",
                        revoc_reg_id,
                        rev_id,
                    )
                    failed_crids.add(rev_id)
                elif rev_id in used_ids:
                    LOGGER.warn(
                        "Skipping requested credential revocation"
                        "on rev reg id %s, cred rev id=%s already revoked",
                        revoc_reg_id,
                        rev_id,
                    )
                    failed_crids.add(rev_id)
                else:
                    rev_crids.add(rev_id)

            if not rev_crids:
                break

            try:
                prev_list = RevocationStatusList.load(rev_list_entry.raw_value)
            except AnoncredsError as err:
                raise AnonCredsIssuerError("Error loading revocation registry") from err

            try:
                updated_list = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: prev_list.update(
                        int(time.time()),
                        None,  # issued
                        list(rev_crids),  # revoked
                        rev_reg_def,
                    ),
                )
            except AnoncredsError as err:
                raise AnonCredsIssuerError(
                    "Error updating revocation registry"
                ) from err

            try:
                async with self._profile.transaction() as txn:
                    rev_list_upd = await txn.handle.fetch(
                        CATEGORY_REV_LIST, revoc_reg_id, for_update=True
                    )
                    rev_info_upd = await txn.handle.fetch(
                        CATEGORY_REV_REG_INFO, revoc_reg_id, for_update=True
                    )
                    if not rev_list_upd or not rev_reg_info:
                        LOGGER.warn(
                            "Revocation registry missing, skipping update: {}",
                            revoc_reg_id,
                        )
                        updated_list = None
                        break
                    rev_info_upd = rev_info_upd.value_json
                    if rev_info_upd != rev_info:
                        # handle concurrent update to the registry by retrying
                        continue
                    await txn.handle.replace(
                        CATEGORY_REV_LIST,
                        revoc_reg_id,
                        updated_list.to_json_buffer(),
                    )
                    used_ids.update(rev_crids)
                    rev_info_upd["used_ids"] = sorted(used_ids)
                    await txn.handle.replace(
                        CATEGORY_REV_REG_INFO, revoc_reg_id, value_json=rev_info_upd
                    )
                    await txn.commit()
            except AskarError as err:
                raise AnonCredsIssuerError("Error saving revocation registry") from err
            break

        return RevokeResult(
            prev=prev_list,
            curr=updated_list,
            failed=[str(rev_id) for rev_id in sorted(failed_crids)],
        )
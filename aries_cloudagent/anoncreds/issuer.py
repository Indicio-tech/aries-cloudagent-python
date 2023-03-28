"""Base Indy Issuer class."""

from abc import ABC, ABCMeta, abstractmethod
from typing import Optional, Sequence, Tuple

from ..core.error import BaseError
from .models.anoncreds_cred_def import CredDefResult
from .models.anoncreds_schema import SchemaResult


DEFAULT_CRED_DEF_TAG = "default"
DEFAULT_SIGNATURE_TYPE = "CL"


class AnonCredsIssuerError(BaseError):
    """Generic issuer error."""


class AnonCredsIssuerRevocationRegistryFullError(AnonCredsIssuerError):
    """Revocation registry is full when issuing a new credential."""


class AnonCredsIssuer(ABC, metaclass=ABCMeta):
    """Base class for Indy Issuer."""

    def __repr__(self) -> str:
        """
        Return a human readable representation of this class.

        Returns:
            A human readable string for this class

        """
        return "<{}>".format(self.__class__.__name__)

    @staticmethod
    def make_schema_id(origin_did: str, schema_name: str, schema_version: str) -> str:
        """Derive the ID for a schema."""
        return f"{origin_did}:2:{schema_name}:{schema_version}"

    @abstractmethod
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
            origin_did: the DID issuing the credential definition
            schema_name: the schema name
            schema_version: the schema version
            attribute_names: a sequence of schema attribute names

        Returns:
            A tuple of the schema ID and JSON

        """

    @abstractmethod
    async def finish_schema(self, schema_id: str):
        """Mark a schema as finished in the wallet."""

    @abstractmethod
    async def get_created_schemas(
        self,
        name: Optional[str] = None,
        version: Optional[str] = None,
        issuer_id: Optional[str] = None,
    ) -> Sequence[str]:
        """Retrieve stored schemas from the wallet."""

    @staticmethod
    def make_credential_definition_id(
        origin_did: str, schema: dict, signature_type: str = None, tag: str = None
    ) -> str:
        """Derive the ID for a credential definition."""
        signature_type = signature_type or DEFAULT_SIGNATURE_TYPE
        tag = tag or DEFAULT_CRED_DEF_TAG
        return f"{origin_did}:3:{signature_type}:{str(schema['seqNo'])}:{tag}"

    @abstractmethod
    async def credential_definition_in_wallet(
        self, credential_definition_id: str
    ) -> bool:
        """
        Check whether a given credential definition ID is present in the wallet.

        Args:
            credential_definition_id: The credential definition ID to check
        """

    @abstractmethod
    async def create_and_store_credential_definition(
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
            origin_did: the DID issuing the credential definition
            schema_json: the schema used as a basis
            signature_type: the credential definition signature type (default 'CL')
            tag: the credential definition tag
            support_revocation: whether to enable revocation for this credential def

        Returns:
            A tuple of the credential definition ID and JSON

        """

    @abstractmethod
    async def get_created_credential_definitions(
        self,
        issuer_id: Optional[str] = None,
        schema_id: Optional[str] = None,
        schema_name: Optional[str] = None,
        schema_version: Optional[str] = None,
        state: Optional[str] = None,
    ) -> Sequence[str]:
        """Get created credential definitions."""

    @abstractmethod
    async def create_credential_offer(self, credential_definition_id) -> str:
        """
        Create a credential offer for the given credential definition id.

        Args:
            credential_definition_id: The credential definition to create an offer for

        Returns:
            The created credential offer

        """

    @abstractmethod
    async def create_credential(
        self,
        schema: dict,
        credential_offer: dict,
        credential_request: dict,
        credential_values: dict,
        revoc_reg_id: str = None,
        tails_file_path: str = None,
    ) -> Tuple[str, str]:
        """
        Create a credential.

        Args
            schema: Schema to create credential for
            credential_offer: Credential Offer to create credential for
            credential_request: Credential request to create credential for
            credential_values: Values to go in credential
            revoc_reg_id: ID of the revocation registry
            tails_file_path: The location of the tails file

        Returns:
            A tuple of created credential and revocation id

        """

    @abstractmethod
    async def revoke_credentials(
        self,
        revoc_reg_id: str,
        tails_file_path: str,
        cred_rev_ids: Sequence[str],
    ) -> Tuple[str, Sequence[str]]:
        """
        Revoke a set of credentials in a revocation registry.

        Args:
            revoc_reg_id: ID of the revocation registry
            tails_file_path: path to the local tails file
            cred_rev_ids: sequences of credential indexes in the revocation registry

        Returns:
            Tuple with the combined revocation delta, list of cred rev ids not revoked

        """

    @abstractmethod
    async def create_and_store_revocation_registry(
        self,
        origin_did: str,
        cred_def_id: str,
        revoc_def_type: str,
        tag: str,
        max_cred_num: int,
        tails_base_path: str,
    ) -> Tuple[str, str, str]:
        """
        Create a new revocation registry and store it in the wallet.

        Args:
            origin_did: the DID issuing the revocation registry
            cred_def_id: the identifier of the related credential definition
            revoc_def_type: the revocation registry type (default CL_ACCUM)
            tag: the unique revocation registry tag
            max_cred_num: the number of credentials supported in the registry
            tails_base_path: where to store the tails file

        Returns:
            A tuple of the revocation registry ID, JSON, and entry JSON

        """

    @abstractmethod
    async def merge_revocation_registry_deltas(
        self, fro_delta: str, to_delta: str
    ) -> str:
        """
        Merge revocation registry deltas.

        Args:
            fro_delta: original delta in JSON format
            to_delta: incoming delta in JSON format

        Returns:
            Merged delta in JSON format

        """

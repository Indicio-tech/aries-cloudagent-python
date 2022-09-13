"""V2.0 present-proof indy presentation-exchange format handler."""
import json
import logging
from typing import List, Mapping, Tuple

from marshmallow import RAISE

from ......indy.credx.holder import _normalize_attr_name
from ......indy.holder import IndyHolder, IndyHolderError
from ......indy.models.predicate import Predicate
from ......indy.models.proof import IndyProofSchema
from ......indy.models.proof_request import IndyProofRequestSchema
from ......indy.models.xform import indy_proof_req_preview2indy_requested_creds
from ......indy.util import generate_pr_nonce
from ......indy.verifier import IndyVerifier
from ......messaging.decorators.attach_decorator import AttachDecorator
from ......messaging.util import canon
from ......wallet.models.attachment_data_record import AttachmentDataRecord
from ......wallet.util import b64_to_bytes
from .....issue_credential.v2_0.hashlink import Hashlink
from ....indy.pres_exch_handler import IndyPresExchHandler
from ...message_types import (
    ATTACHMENT_FORMAT,
    PRES_20,
    PRES_20_PROPOSAL,
    PRES_20_REQUEST,
)
from ...messages.pres import V20Pres
from ...messages.pres_format import V20PresFormat
from ...models.pres_exchange import V20PresExRecord
from ..handler import V20PresFormatHandler, V20PresFormatHandlerError

LOGGER = logging.getLogger(__name__)


class IndyPresExchangeHandler(V20PresFormatHandler):
    """Indy presentation format handler."""

    format = V20PresFormat.Format.INDY

    @classmethod
    def validate_fields(cls, message_type: str, attachment_data: Mapping):
        """Validate attachment data for a specific message type.

        Uses marshmallow schemas to validate if format specific attachment data
        is valid for the specified message type. Only does structural and type
        checks, does not validate if .e.g. the issuer value is valid.


        Args:
            message_type (str): The message type to validate the attachment data for.
                Should be one of the message types as defined in message_types.py
            attachment_data (Mapping): [description]
                The attachment data to valide

        Raises:
            Exception: When the data is not valid.

        """
        mapping = {
            PRES_20_REQUEST: IndyProofRequestSchema,
            PRES_20_PROPOSAL: IndyProofRequestSchema,
            PRES_20: IndyProofSchema,
        }

        # Get schema class
        Schema = mapping[message_type]

        # Validate, throw if not valid
        Schema(unknown=RAISE).load(attachment_data)

    def get_format_identifier(self, message_type: str) -> str:
        """Get attachment format identifier for format and message combination.

        Args:
            message_type (str): Message type for which to return the format identifier

        Returns:
            str: Issue credential attachment format identifier

        """
        return ATTACHMENT_FORMAT[message_type][IndyPresExchangeHandler.format.api]

    def get_format_data(
        self, message_type: str, data: dict
    ) -> Tuple[V20PresFormat, AttachDecorator]:
        """Get presentation format and attach objects for use in pres_ex messages."""

        return (
            V20PresFormat(
                attach_id=IndyPresExchangeHandler.format.api,
                format_=self.get_format_identifier(message_type),
            ),
            AttachDecorator.data_base64(data, ident=IndyPresExchangeHandler.format.api),
        )

    async def create_bound_request(
        self, pres_ex_record: V20PresExRecord, request_data: dict = None
    ) -> Tuple[V20PresFormat, AttachDecorator]:
        """
        Create a presentation request bound to a proposal.

        Args:
            pres_ex_record: Presentation exchange record for which
                to create presentation request
            request_data: Dict

        Returns:
            A tuple (updated presentation exchange record, presentation request message)

        """
        indy_proof_request = pres_ex_record.pres_proposal.attachment(
            IndyPresExchangeHandler.format
        )
        if request_data:
            indy_proof_request["name"] = request_data.get("name", "proof-request")
            indy_proof_request["version"] = request_data.get("version", "1.0")
            indy_proof_request["nonce"] = (
                request_data.get("nonce") or await generate_pr_nonce()
            )
        else:
            indy_proof_request["name"] = "proof-request"
            indy_proof_request["version"] = "1.0"
            indy_proof_request["nonce"] = await generate_pr_nonce()
        return self.get_format_data(PRES_20_REQUEST, indy_proof_request)

    async def create_pres(
        self, pres_ex_record: V20PresExRecord, request_data: dict = None
    ) -> Tuple[V20PresFormat, AttachDecorator]:
        """Create a presentation."""
        requested_credentials = {}
        if not request_data:
            try:
                proof_request = pres_ex_record.pres_request
                indy_proof_request = proof_request.attachment(
                    IndyPresExchangeHandler.format
                )
                requested_credentials = (
                    await indy_proof_req_preview2indy_requested_creds(
                        indy_proof_request,
                        preview=None,
                        holder=self._profile.inject(IndyHolder),
                    )
                )
            except ValueError as err:
                LOGGER.warning(f"{err}")
                raise V20PresFormatHandlerError(
                    f"No matching Indy credentials found: {err}"
                )
        else:
            if IndyPresExchangeHandler.format.api in request_data:
                indy_spec = request_data.get(IndyPresExchangeHandler.format.api)
                requested_credentials = {
                    "self_attested_attributes": indy_spec["self_attested_attributes"],
                    "requested_attributes": indy_spec["requested_attributes"],
                    "requested_predicates": indy_spec["requested_predicates"],
                }
        indy_handler = IndyPresExchHandler(self._profile)
        indy_proof = await indy_handler.return_presentation(
            pres_ex_record=pres_ex_record, requested_credentials=requested_credentials
        )
        return self.get_format_data(PRES_20, indy_proof)

    async def get_supplements(
        self, pres_ex_record: V20PresExRecord = None, request_data: dict = None
    ) -> List[AttachmentDataRecord]:
        """Retrieve supplements"""

        if not request_data:
            try:
                proof_request = pres_ex_record.pres_request
                indy_proof_request = proof_request.attachment(
                    IndyPresExchangeHandler.format
                )
                requested_credentials = (
                    await indy_proof_req_preview2indy_requested_creds(
                        indy_proof_request,
                        preview=None,
                        holder=self._profile.inject(IndyHolder),
                    )
                )
                requested_attributes = requested_credentials.get(
                    "requested_attributes", {}
                )
            except ValueError as err:
                LOGGER.warning(f"{err}")
                raise V20PresFormatHandlerError(
                    f"No matching Indy credentials found: {err}"
                )
        else:
            requested_attributes: dict = request_data.get("requested_attributes", {})

        indy_pres_request: dict = pres_ex_record.by_format["pres_request"].get(
            V20PresFormat.Format.INDY.api, {}
        )
        records: List[AttachmentDataRecord] = []
        for attr_referent, value in requested_attributes.items():
            cred_id = value["cred_id"]

            if attr_referent not in indy_pres_request["requested_attributes"]:
                raise IndyHolderError(
                    f"Unknown presentation request referent: {attr_referent}"
                )

            attr = indy_pres_request["requested_attributes"][attr_referent]
            if "name" in attr:
                attribute_name = _normalize_attr_name(attr["name"])
            elif "names" in attr:
                attribute_name = [_normalize_attr_name(name) for name in attr["names"]]
            else:
                raise IndyHolderError(f"Unknown presentation request attr: {attr}")
            async with self._profile.session() as session:
                record: AttachmentDataRecord = (
                    await AttachmentDataRecord.query_by_cred_id_attribute(
                        session,
                        cred_id,
                        attribute_name,
                    )
                )
                records.append(record)

        return records

    async def receive_pres(self, message: V20Pres, pres_ex_record: V20PresExRecord):
        """Receive a presentation and check for presented values vs. proposal request."""

        def _check_proof_vs_proposal():
            """Check for bait and switch in presented values vs. proposal request."""
            proof_req = pres_ex_record.pres_request.attachment(
                IndyPresExchangeHandler.format
            )

            # revealed attrs
            for reft, attr_spec in proof["requested_proof"]["revealed_attrs"].items():
                proof_req_attr_spec = proof_req["requested_attributes"].get(reft)
                if not proof_req_attr_spec:
                    raise V20PresFormatHandlerError(
                        f"Presentation referent {reft} not in proposal request"
                    )
                req_restrictions = proof_req_attr_spec.get("restrictions", {})

                name = proof_req_attr_spec["name"]
                proof_value = attr_spec["raw"]
                sub_proof_index = attr_spec["sub_proof_index"]
                schema_id = proof["identifiers"][sub_proof_index]["schema_id"]
                cred_def_id = proof["identifiers"][sub_proof_index]["cred_def_id"]
                criteria = {
                    "schema_id": schema_id,
                    "schema_issuer_did": schema_id.split(":")[-4],
                    "schema_name": schema_id.split(":")[-2],
                    "schema_version": schema_id.split(":")[-1],
                    "cred_def_id": cred_def_id,
                    "issuer_did": cred_def_id.split(":")[-5],
                    f"attr::{name}::value": proof_value,
                }

                if (
                    not any(r.items() <= criteria.items() for r in req_restrictions)
                    and len(req_restrictions) != 0
                ):
                    raise V20PresFormatHandlerError(
                        f"Presented attribute {reft} does not satisfy proof request "
                        f"restrictions {req_restrictions}"
                    )

            # revealed attr groups
            for reft, attr_spec in (
                proof["requested_proof"].get("revealed_attr_groups", {}).items()
            ):
                proof_req_attr_spec = proof_req["requested_attributes"].get(reft)
                if not proof_req_attr_spec:
                    raise V20PresFormatHandlerError(
                        f"Presentation referent {reft} not in proposal request"
                    )
                req_restrictions = proof_req_attr_spec.get("restrictions", {})
                proof_values = {
                    name: values["raw"] for name, values in attr_spec["values"].items()
                }
                sub_proof_index = attr_spec["sub_proof_index"]
                schema_id = proof["identifiers"][sub_proof_index]["schema_id"]
                cred_def_id = proof["identifiers"][sub_proof_index]["cred_def_id"]
                criteria = {
                    "schema_id": schema_id,
                    "schema_issuer_did": schema_id.split(":")[-4],
                    "schema_name": schema_id.split(":")[-2],
                    "schema_version": schema_id.split(":")[-1],
                    "cred_def_id": cred_def_id,
                    "issuer_did": cred_def_id.split(":")[-5],
                    **{
                        f"attr::{name}::value": value
                        for name, value in proof_values.items()
                    },
                }

                if (
                    not any(r.items() <= criteria.items() for r in req_restrictions)
                    and len(req_restrictions) != 0
                ):
                    raise V20PresFormatHandlerError(
                        f"Presented attr group {reft} does not satisfy proof request "
                        f"restrictions {req_restrictions}"
                    )

            # predicate bounds
            for reft, pred_spec in proof["requested_proof"]["predicates"].items():
                proof_req_pred_spec = proof_req["requested_predicates"].get(reft)
                if not proof_req_pred_spec:
                    raise V20PresFormatHandlerError(
                        f"Presentation referent {reft} not in proposal request"
                    )
                req_name = proof_req_pred_spec["name"]
                req_pred = Predicate.get(proof_req_pred_spec["p_type"])
                req_value = proof_req_pred_spec["p_value"]
                req_restrictions = proof_req_pred_spec.get("restrictions", {})
                for req_restriction in req_restrictions:
                    for k in [k for k in req_restriction]:  # cannot modify en passant
                        if k.startswith("attr::"):
                            req_restriction.pop(k)  # let indy-sdk reject mismatch here
                sub_proof_index = pred_spec["sub_proof_index"]
                for ge_proof in proof["proof"]["proofs"][sub_proof_index][
                    "primary_proof"
                ]["ge_proofs"]:
                    proof_pred_spec = ge_proof["predicate"]
                    if proof_pred_spec["attr_name"] != canon(req_name):
                        continue
                    if not (
                        Predicate.get(proof_pred_spec["p_type"]) is req_pred
                        and proof_pred_spec["value"] == req_value
                    ):
                        raise V20PresFormatHandlerError(
                            f"Presentation predicate on {req_name} "
                            "mismatches proposal request"
                        )
                    break
                else:
                    raise V20PresFormatHandlerError(
                        f"Proposed request predicate on {req_name} not in presentation"
                    )

                schema_id = proof["identifiers"][sub_proof_index]["schema_id"]
                cred_def_id = proof["identifiers"][sub_proof_index]["cred_def_id"]
                criteria = {
                    "schema_id": schema_id,
                    "schema_issuer_did": schema_id.split(":")[-4],
                    "schema_name": schema_id.split(":")[-2],
                    "schema_version": schema_id.split(":")[-1],
                    "cred_def_id": cred_def_id,
                    "issuer_did": cred_def_id.split(":")[-5],
                }

                if (
                    not any(r.items() <= criteria.items() for r in req_restrictions)
                    and len(req_restrictions) != 0
                ):
                    raise V20PresFormatHandlerError(
                        f"Presented predicate {reft} does not satisfy proof request "
                        f"restrictions {req_restrictions}"
                    )

        proof = message.attachment(IndyPresExchangeHandler.format)
        _check_proof_vs_proposal()

    async def verify_supplements(self, pres_ex_record: V20PresExRecord) -> bool:
        """Verify the supplements associated with a presentation."""

        valid_supplements = True
        indy_proof = pres_ex_record.pres.attachment(IndyPresExchangeHandler.format)

        def find_attachment(attatchment_id: str) -> str:
            for attachment in pres_ex_record.attach:
                if attachment.ident == attatchment_id:
                    return attachment
            return None

        def find_supplement_attr(supplement, key):
            for attr in supplement.attrs:
                if attr.key == key:
                    return attr.value
            return None

        supplements = pres_ex_record.supplements or []
        for supplement in supplements:

            # Only hashlink data validation is supported at the moment
            if supplement.type != "hashlink-data":
                valid_supplements = False
                break

            attatchment_id = supplements.ref
            attachment = find_attachment(attatchment_id)

            # No matching attachment found
            if not attachment:
                valid_supplements = False
                break

            # Assuming that only B64 data attachment is allowed, retreive the data
            data = attachment.data.base64
            if not data:
                valid_supplements = False
                break

            # Grab the attr that contains the hashlink
            key = find_supplement_attr(supplement, "field")

            # Retrieve the hashlink and the associated decoded data
            hashlink = indy_proof["requested_proof"]["revealed_attrs"][key]["raw"]
            data = b64_to_bytes(data, urlsafe=True)

            # Verify the hashlinks
            valid_supplements = Hashlink.verify(hashlink, data)

            # Don't bother verifying more suppliments if this one failed to validate
            if not valid_supplements:
                break

        return valid_supplements

    async def verify_pres(self, pres_ex_record: V20PresExRecord) -> V20PresExRecord:
        """
        Verify a presentation.

        Args:
            pres_ex_record: presentation exchange record
                with presentation request and presentation to verify

        Returns:
            presentation exchange record, updated

        """
        pres_request_msg = pres_ex_record.pres_request
        indy_proof_request = pres_request_msg.attachment(IndyPresExchangeHandler.format)
        indy_proof = pres_ex_record.pres.attachment(IndyPresExchangeHandler.format)
        indy_handler = IndyPresExchHandler(self._profile)
        (
            schemas,
            cred_defs,
            rev_reg_defs,
            rev_reg_entries,
        ) = await indy_handler.process_pres_identifiers(indy_proof["identifiers"])

        verifier = self._profile.inject(IndyVerifier)
        verified = await verifier.verify_presentation(
            indy_proof_request,
            indy_proof,
            schemas,
            cred_defs,
            rev_reg_defs,
            rev_reg_entries,
        )

        valid_supplements = await self.verify_supplements(pres_ex_record)
        if verified and not valid_supplements:
            verified = valid_supplements

        pres_ex_record.verified = json.dumps(verified)
        return pres_ex_record

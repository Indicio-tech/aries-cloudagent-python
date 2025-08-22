"""Indy-Credx verifier implementation."""

import asyncio
import logging
from typing import Tuple

from indy_credx import CredxError, Presentation

from ...core.profile import Profile
from ..verifier import IndyVerifier, PresVerifyMsg

LOGGER = logging.getLogger(__name__)


class IndyCredxVerifier(IndyVerifier):
    """Indy-Credx verifier class."""

    def __init__(self, profile: Profile):
        """Initialize an IndyCredxVerifier instance.

        Args:
            profile: an active profile instance

        """
        self.profile = profile

    async def verify_presentation(
        self,
        pres_req,
        pres,
        schemas,
        credential_definitions,
        rev_reg_defs,
        rev_reg_entries,
    ) -> Tuple[bool, list]:
        """Verify a presentation.

        Args:
            pres_req: Presentation request data
            pres: Presentation data
            schemas: Schema data
            credential_definitions: credential definition data
            rev_reg_defs: revocation registry definitions
            rev_reg_entries: revocation registry entries
        """

        LOGGER.debug("[Indicio:Colton:Indy:CredX] <presentation_verification_started>")
        accept_legacy_revocation = (
            self.profile.settings.get("revocation.anoncreds_legacy_support", "accept")
            == "accept"
        )
        msgs = []
        try:
            LOGGER.debug("[Indicio:Colton:Indy:CredX] getting non-revocation intervals")
            msgs += self.non_revoc_intervals(pres_req, pres, credential_definitions)
            LOGGER.debug("[Indicio:Colton:Indy:CredX] msgs: %s", msgs)
            LOGGER.debug("[Indicio:Colton:Indy:CredX] checking timestamps")
            msgs += await self.check_timestamps(
                self.profile, pres_req, pres, rev_reg_defs
            )
            LOGGER.debug("[Indicio:Colton:Indy:CredX] msgs: %s", msgs)
            LOGGER.debug("[Indicio:Colton:Indy:CredX] pre-verifying")
            msgs += await self.pre_verify(pres_req, pres)
            LOGGER.debug("[Indicio:Colton:Indy:CredX] msgs: %s", msgs)
        except ValueError as err:
            LOGGER.debug("[Indicio:Colton:Indy:CredX] Value Error detected: %s", str(err))
            s = str(err)
            msgs.append(f"{PresVerifyMsg.PRES_VALUE_ERROR.value}::{s}")
            LOGGER.error(
                f"Presentation on nonce={pres_req['nonce']} "
                f"cannot be validated (presentation will be marked as Invalid)"
                f": {str(err)}"
            )
            return (False, msgs)

        try:
            LOGGER.debug("[Indicio:Colton:Indy:CredX] loading presentation")
            presentation = Presentation.load(pres)
            LOGGER.debug("[Indicio:Colton:Indy:CredX] verifying presentation")
            verified = await asyncio.get_event_loop().run_in_executor(
                None,
                presentation.verify,
                pres_req,
                schemas.values(),
                credential_definitions.values(),
                rev_reg_defs.values(),
                rev_reg_entries,
                accept_legacy_revocation,
            )
            LOGGER.debug(
                "[Indicio:Colton:Indy:CredX] presentation verified: %s", verified
            )
        except CredxError as err:
            LOGGER.debug("[Indicio:Colton:Indy:CredX] CredxError detected: %s", str(err))
            s = str(err)
            msgs.append(f"{PresVerifyMsg.PRES_VERIFY_ERROR.value}::{s}")
            LOGGER.exception(
                f"Validation of presentation on nonce={pres_req['nonce']} "
                "failed with error"
            )
            verified = False

        LOGGER.debug("[Indicio:Colton:Indy:CredX] verified: %s, msgs: %s", verified, msgs)
        return (verified, msgs)

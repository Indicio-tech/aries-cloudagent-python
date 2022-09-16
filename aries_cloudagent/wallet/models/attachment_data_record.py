"""Attachment Data Record"""

from typing import List, Mapping, Sequence, Union

from marshmallow import fields

from ...core.profile import ProfileSession
from ...messaging.decorators.attach_decorator import (
    AttachDecorator,
    AttachDecoratorSchema,
)
from ...messaging.models.base_record import BaseRecord, BaseRecordSchema
from ...messaging.valid import UUIDFour
from ...protocols.issue_credential.v2_0.messages.inner.supplement import (
    Supplement,
    SupplementSchema,
)


class AttachmentDataRecord(BaseRecord):
    """Represents an attachment data record."""

    class Meta:
        """AttachmentDataRecord metadata."""

        schema_class = "AttachmentDataRecordSchema"

    RECORD_TOPIC = "attachment-data"
    RECORD_ID_NAME = "record_id"
    RECORD_TYPE = "attachment_data_record"
    TAG_NAMES = {"cred_id", "attribute"}

    def __init__(
        self,
        record_id: str = None,
        supplement: Union[Mapping, Supplement] = None,
        attachment: Union[Mapping, AttachDecorator] = None,
        cred_id: str = None,
        attribute: str = None,
        **kwargs,
    ):
        super().__init__(record_id, **kwargs)
        self.supplement = Supplement.serde(supplement).de
        self.attachment = AttachDecorator.serde(attachment).de
        self.cred_id: str = cred_id
        self.attribute = attribute

    @property
    def record_id(self) -> str:
        """Return record id."""
        return self._id

    @property
    def record_value(self) -> dict:
        """Return the record value."""
        return {
            **{prop: getattr(self, prop) for prop in ("cred_id", "attribute")},
            **{
                prop: getattr(self, prop).serialize()
                for prop in (
                    "supplement",
                    "attachment",
                )
                if getattr(self, prop)
            },
        }

    @classmethod
    async def query_by_cred_id_attribute(
        cls, session: ProfileSession, cred_id: str, attribute: Union[str, List[str]]
    ):
        """Query by cred_id."""
        if isinstance(attribute, list):
            attrs = [{"attribute": attr} for attr in attribute]
            tag_filter = {"cred_id": cred_id, "$or": attrs}
        else:
            tag_filter = {"cred_id": cred_id, "attribute": attribute}
        return await cls.retrieve_by_tag_filter(session, tag_filter)

    @classmethod
    def records_from_supplements_attachments(
        cls,
        supplements: Sequence[Supplement],
        attachments: Sequence[AttachDecorator],
        cred_id: str,
    ):
        """Match supplement and attachment by record_id and store in
        AttachmentDataRecord."""

        ats: dict[str, AttachDecorator] = {
            attachment.ident: attachment for attachment in attachments
        }
        # TODO We should validate that sup.ref actual exists in ats
        # This should probably be done on message validation
        return [
            cls(
                supplement=sup,
                attachment=ats[sup.ref],
                cred_id=cred_id,
                attribute=sup.attrs[0].value,
            )
            for sup in supplements
        ]

    @classmethod
    async def save_attachments(
        cls,
        session: ProfileSession,
        supplements: Sequence[Supplement],
        attachments: Sequence[AttachDecorator],
        cred_id: str,
    ) -> Sequence[str]:
        """Save all attachments."""
        return [
            await record.save(session)
            for record in cls.records_from_supplements_attachments(
                supplements, attachments, cred_id
            )
        ]


class AttachmentDataRecordSchema(BaseRecordSchema):
    """AttachmentDataRecord schema"""

    class Meta:
        """AttachmentDataRecordSchema metadata."""

        model_class = AttachmentDataRecord

    record_id = fields.Str(
        description="Record identifier.",
        example=UUIDFour.EXAMPLE,
        required=False,
        allow_none=False,
    )
    supplement = fields.Nested(
        SupplementSchema,
        description="Supplement to the credential",
        required=False,
    )
    attachment = fields.Nested(
        AttachDecoratorSchema,
        required=False,
        description="Attachments of other data associated with the credential",
    )
    cred_id = fields.Str(
        example="3fa85f64-5717-4562-b3fc-2c963f66afa6",
        description=(
            "Wallet credential identifier (typically but not necessarily a UUID)"
        ),
        required=True,
    )
    attribute = fields.Str(description="Attribute", required=True)

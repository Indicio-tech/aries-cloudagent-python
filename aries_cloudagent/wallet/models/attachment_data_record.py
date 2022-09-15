"""Attachment Data Record"""

from typing import List, Sequence, Union

from marshmallow import fields

from ...core.profile import ProfileSession
from ...messaging.decorators.attach_decorator import (
    AttachDecorator,
    AttachDecoratorData,
    AttachDecoratorSchema,
)
from ...messaging.models.base_record import BaseRecord, BaseRecordSchema
from ...messaging.valid import UUIDFour
from ...protocols.issue_credential.v2_0.messages.inner.supplement import (
    Supplement,
    SupplementAttribute,
    SupplementSchema,
)


class AttachmentDataRecord(BaseRecord):
    """Represents an attachment data record."""

    class Meta:
        """AttachmentDataRecord metadata."""

        schema_class = "AttachmentDataRecordSchema"

    RECORD_TYPE = "attachment_data_record"
    TAG_NAMES = {"attachment_id", "cred_id", "attribute"}

    def __init__(
        self,
        attachment_id: str = None,
        supplement: Supplement = None,
        attachment: AttachDecoratorData = None,
        cred_id: str = None,
        attribute: Sequence[SupplementAttribute] = None,
    ):
        super().__init__()
        self.attachment_id = attachment_id
        self.supplement: Supplement = supplement
        self.attachment: AttachDecoratorData = attachment
        self.cred_id: str = cred_id
        self.attribute = attribute

    async def get_attachment_data_record(
        self, session: ProfileSession, attachment_id: str
    ):
        """Query by attachment_id."""
        tag_filter = {"attachment_id": attachment_id}
        return await self.retrieve_by_tag_filter(session, tag_filter)

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
    def attachment_lookup(cls, attachments: Sequence[AttachDecorator]) -> dict:
        """Create mapping from attachment identifier to attachment data."""

        return {attachment.ident: attachment for attachment in attachments}

    @classmethod
    def match_by_attachment_id(
        cls,
        supplements: Sequence[Supplement],
        attachments: Sequence[AttachDecorator],
        cred_id: str,
    ):
        """Match supplement and attachment by attachment_id and store in
        AttachmentDataRecord."""

        ats: dict[str, AttachDecoratorData] = AttachmentDataRecord.attachment_lookup(
            attachments
        )

        return [
            AttachmentDataRecord(
                attachment_id=sup.ref,
                supplement=sup,
                attachment=ats[sup.ref],
                cred_id=cred_id,
                attribute=sup.attrs[0].value,
            )
            for sup in supplements
        ]

    @classmethod
    async def save_attachments(cls, session, supplements, attachments, cred_id):
        """Save all attachments."""
        return [
            await attachment.save(session)
            for attachment in AttachmentDataRecord.match_by_attachment_id(
                supplements, attachments, cred_id
            )
        ]


class AttachmentDataRecordSchema(BaseRecordSchema):
    """AttachmentDataRecord schema"""

    class Meta:
        """AttachmentDataRecordSchema metadata."""

        model_class = AttachmentDataRecord

    attachment_id = fields.Str(
        description="Attachment identifier.",
        example=UUIDFour.EXAMPLE,
        required=False,
        allow_none=False,
        data_key="@id",
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

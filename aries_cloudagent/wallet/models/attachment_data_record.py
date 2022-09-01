"""Attachment Data Record"""

from typing import Sequence
from marshmallow import fields

from ...messaging.models.base_record import BaseRecord, BaseRecordSchema
from ...messaging.valid import UUIDFour
from ...protocols.issue_credential.v2_0.messages.inner.supplement import (
    Supplement,
    SupplementSchema,
)
from ...messaging.decorators.attach_decorator import (
    AttachDecorator,
    AttachDecoratorData,
    AttachDecoratorSchema,
)


class AttachmentDataRecord(BaseRecord):
    """Represents an attachment data record"""

    class Meta:
        """AttachmentDataRecord metadata"""

        schema_class = "AttachmentDataRecordSchema"

    RECORD_TYPE = "attachment_data_record"
    RECORD_ID_NAME = "attachment_data_id"

    TAG_NAMES = {"attachment_data_name"}

    def __init__(
        self,
        attachment_id: str = None,
        supplement: Supplement = None,
        attachment: AttachDecoratorData = None,
    ):
        super().__init__()
        self.attachment_id = attachment_id
        self.supplement: Supplement = supplement
        self.attachment: AttachDecoratorData = attachment

    @classmethod
    def attachment_lookup(
        cls, attachments: Sequence[AttachDecorator]
    ) -> dict[str, AttachDecoratorData]:
        """Create mapping from attachment identifier to attachment data."""

        return {attachment.ident: attachment.data for attachment in attachments}

    @classmethod
    def match_by_attachment_id(
        cls, supplements: Sequence[Supplement], attachments: Sequence[AttachDecorator]
    ):
        """Match supplement and attachment by attachment_id and store in
        AttachmentDataRecord."""

        ats: dict[str, AttachDecoratorData] = AttachmentDataRecord.attachment_lookup(
            attachments
        )
        return [
            AttachmentDataRecord(
                attachment_id=sup.id, supplement=sup, attachment=ats[sup.id]
            )
            for sup in supplements
        ]

    @classmethod
    async def save_attachments(cls, session, supplements, attachments):
        """ "Save all attachments"""
        return [
            await attachment.save(session)
            for attachment in AttachmentDataRecord.match_by_attachment_id(
                supplements, attachments
            )
        ]


class AttachmentDataRecordSchema(BaseRecordSchema):
    """AttachmentDataRecord schema"""

    class Meta:
        """AttachmentDataRecordSchema metadata"""

        model_class = AttachmentDataRecord

    attachment_id = fields.Str(
        description="Attachment identifier",
        example=UUIDFour.EXAMPLE,
        required=False,
        allow_none=False,
        data_key="@id",
    )
    supplements = fields.Nested(
        SupplementSchema,
        description="Supplements to the credential",
        many=True,
        required=False,
    )
    attachments = fields.Nested(
        AttachDecoratorSchema,
        many=True,
        required=False,
        description="Attachments of other data associated with the credential",
        data_key="~attach",
    )

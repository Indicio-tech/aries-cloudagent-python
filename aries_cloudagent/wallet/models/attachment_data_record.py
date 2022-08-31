"""Attachment Data Record"""

from marshmallow import fields

from ...messaging.models.base_record import BaseRecord, BaseRecordSchema
from ...protocols.issue_credential.v2_0.messages.inner.supplement import (
    Supplement,
    SupplementSchema,
)
from ...messaging.decorators.attach_decorator import (
    AttachDecorator,
    AttachDecoratorSchema,
)


class AttachmentDataRecord(BaseRecord):
    """Represents an attachment data record"""

    class Meta:
        """AttachmentDataRecord metadata"""

        schema_class = "AttachmentDataRecordSchema"

    def __init__(
        self, supplement: Supplement = None, attachment: AttachDecorator = None
    ):
        super().__init__()
        self.supplement = supplement
        self.attachment = attachment


class AttachmentDataRecordSchema(BaseRecordSchema):
    """AttachmentDataRecord schema"""

    class Meta:
        """AttachmentDataRecordSchema metadata"""

        model_class = AttachmentDataRecord

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

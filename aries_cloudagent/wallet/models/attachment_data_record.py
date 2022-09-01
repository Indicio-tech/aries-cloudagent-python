"""Attachment Data Record"""

from typing import Sequence
from marshmallow import fields

from ...messaging.models.base_record import BaseRecord, BaseRecordSchema
from ...protocols.issue_credential.v2_0.messages.inner.supplement import (
    Supplement,
    SupplementAttribute,
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

    RECORD_TYPE = "attachment_data_record"
    RECORD_ID_NAME = "attachment_data_id"
 
    TAG_NAMES = {"attachment_data_name"}

    def __init__(
        self,
        supplement: Supplement = None,
        attachments: Sequence[AttachDecorator] = None
    ):
        super().__init__()
        self.supplement = supplement
        self.attachments = attachments

    def attachment_lookup(self):
        """Create mapping from attachment identifier to attachment data"""

        attach_dict = {}
        for attachment in self.attachments:
            attach_dict[attachment.ident] = attachment.data
        return attach_dict

    def save(self):
        """For each element in the supplements array, store to the record both
        the supplement attribute itself and the referenced attachment"""

        for supplement_attribute in self.supplement.attrs:
            assert isinstance(supplement_attribute, SupplementAttribute)

        # TODO: store supplement attribute with referenced attachment


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

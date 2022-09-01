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
    AttachDecoratorSchema,
)


class AttachmentDataContainer():
    """Represents an attachment data container"""

    def __init__(
        self,
        supplements: Sequence[Supplement] = None,
        attachments: Sequence[AttachDecorator] = None,
    ):
        super().__init__()
        self.supplements = supplements
        self.attachments = attachments

    def attachment_lookup(self):
        """Create mapping from attachment identifier to attachment data."""

        attach_dict = {}
        for attachment in self.attachments:
            attach_dict[attachment.ident] = attachment.data
        return attach_dict

    def match_by_attachment_id(self):
        """Match supplement and attachment by attachment_id and store in
        AttachmentDataRecord."""

        attachment_dictionary = self.attachment_lookup()
        for supplement in self.supplements:
            record = AttachmentDataRecord(
                attachment_id=supplement.id,
                supplement=supplement,
                attachment=attachment_dictionary[supplement.id]
            )
        # TODO: return list (?) of records


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
        supplements: Supplement = None,
        attachments: AttachDecorator = None,
    ):
        super().__init__()
        self.attachment_id = attachment_id
        self.supplements = supplements
        self.attachments = attachments


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

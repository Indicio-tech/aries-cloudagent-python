from ..models.attachment_data_record import AttachmentDataRecord
from ...messaging.decorators.attach_decorator import AttachDecorator, AttachDecoratorData
from ...protocols.issue_credential.v2_0.messages.inner.supplement import Supplement


def test_attachment_lookup():

    supplement = Supplement
    attachments = [
        AttachDecorator(ident="ident_test_1", data="payload_test_1"),
        AttachDecorator(ident="ident_test_2", data="payload_test_2"),
    ]
    record = AttachmentDataRecord(supplement, attachments)

    result = record.attachment_lookup()
    assert result == {'ident_test_1': 'payload_test_1', 'ident_test_2': 'payload_test_2'}


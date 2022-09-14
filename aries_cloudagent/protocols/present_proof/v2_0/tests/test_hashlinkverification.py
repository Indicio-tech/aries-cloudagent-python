import pytest
from unittest import mock
from typing import Dict


from ..formats.indy.handler import (
    IndyPresExchangeHandler, 
    IndyPresExchHandler
)
from ..models.pres_exchange import V20PresExRecord
from ..messages.pres_request import V20PresRequest
from ..messages.pres import V20Pres, V20PresFormat
from .....core.profile import Profile
from .....messaging.decorators.attach_decorator import AttachDecorator
from ....issue_credential.v2_0.messages.inner.supplement import (
    Supplement,
    SupplementAttribute
)

@pytest.fixture
def attach():
    return [
            AttachDecorator(
                ident="pres_ident",
                data="hashlink_data"
            )
        ]

@pytest.fixture
def supplements():
    return [Supplement(
    type="test_supplement",
    attrs=[SupplementAttribute(
        key="test_key",
        value="test_supp_value")],
    ref="test_attach_id"
)]
    

@pytest.fixture
def req():
    return V20PresRequest(
        _id="request_id",
        comment="pres_request",
        request_presentations_attach=[
            AttachDecorator(
                ident="pres_ident",
                data="hashlink_data"
            )
        ],
        formats=[V20PresFormat(attach_id="indy", format_=V20PresFormat.Format.INDY.aries)]
    )
    

@pytest.fixture
def pres(supplements, attach):
    return V20Pres(
        comment="test_pres",
        presentations_attach=[
            AttachDecorator(
                ident="pres_ident",
                data="hashlink_data"
            )
        ],
        formats=[V20PresFormat(attach_id="indy", format_=V20PresFormat.Format.INDY.aries)],
        supplements=supplements,
        attach=attach
    )


@pytest.fixture
async def pres_ex_record(req, pres, supplements, attach):
    """PresExchangeRecord fixture
    """
    return V20PresExRecord(
        pres_request=req,
        pres=pres,
        supplements=supplements,
        attach=attach
    )


@pytest.mark.asyncio 
async def test_hlverify(
    pres_ex_record: V20PresExRecord
    ):
    """Testing hashlink verification for the 
    v2 present_proof IndyPresExchangeHandler
    
    Args:
        pres_ex_record: Presentation Exchange 
        Record. 

    """
    indy_pres_ex = IndyPresExchangeHandler(profile=Profile)
    
    verify = await indy_pres_ex.verify_pres(pres_ex_record=pres_ex_record)

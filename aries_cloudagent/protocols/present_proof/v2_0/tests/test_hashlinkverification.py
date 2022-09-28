import json
import pytest
from unittest import mock
from asynctest import mock as async_mock, TestCase as AsyncTestCase
from typing import Dict


from ..formats.indy.handler import (
    IndyPresExchangeHandler, 
    IndyPresExchHandler
)
from ..models.pres_exchange import V20PresExRecord
from ..messages.pres_request import V20PresRequest
from ..messages.pres import V20Pres, V20PresFormat
from .....core.profile import Profile
from .....core.in_memory import InMemoryProfile
from .....ledger.base import BaseLedger
from .....messaging.decorators.attach_decorator import AttachDecorator
from ....issue_credential.v2_0.messages.inner.supplement import (
    Supplement,
    SupplementAttribute
)
from .....ledger.multiple_ledger.ledger_requests_executor import (
    IndyLedgerRequestsExecutor,
)
from .....indy.holder import IndyHolder
from .....indy.verifier import IndyVerifier

from .test_manager import RR_ID, CD_ID, NOW, S_ID

EXAMPLE_DATA = b"Hello World!"
EXAMPLE_LINK = "hl:zQmaD38CLH97P6WnuZFzJY7LnoSDSFqppAa5K7h7zBUSm6E"

INDY_PROOF = {
    "proof": {
        "proofs": [
            {
                "primary_proof": {
                    "eq_proof": {
                        "revealed_attrs": {
                            "player": "51643998292319337989",
                            "screencapture": "124831723185628395682368329568235681",
                        },
                        "a_prime": "98381845469564775640588",
                        "e": "2889201651469315129053056279820725958192110265136",
                        "v": "337782521199137176224",
                        "m": {
                            "master_secret": "88675074759262558623",
                            "date": "3707627155679953691027082306",
                            "highscore": "251972383037120760793174059437326",
                        },
                        "m2": "2892781443118611948331343540849982215419978654911341",
                    },
                    "ge_proofs": [
                        {
                            "u": {
                                "0": "99189584890680947709857922351898933228959",
                                "3": "974568160016086782335901983921278203",
                                "2": "127290395299",
                                "1": "7521808223922",
                            },
                            "r": {
                                "3": "247458",
                                "2": "263046",
                                "1": "285214",
                                "DELTA": "4007402",
                                "0": "12066738",
                            },
                            "mj": "1507606",
                            "alpha": "20251550018805200",
                            "t": {
                                "1": "1262519732727",
                                "3": "82102416",
                                "0": "100578099981822",
                                "2": "47291",
                                "DELTA": "556736142765",
                            },
                            "predicate": {
                                "attr_name": "highscore",
                                "p_type": "GE",
                                "value": 1000000,
                            },
                        }
                    ],
                },
                "non_revoc_proof": {
                    "x_list": {
                        "rho": "128121489ACD4D778ECE",
                        "r": "1890DEFBB8A254",
                        "r_prime": "0A0861FFE96C",
                        "r_prime_prime": "058376CE",
                        "r_prime_prime_prime": "188DF30745A595",
                        "o": "0D0F7FA1",
                        "o_prime": "28165",
                        "m": "0187A9817897FC",
                        "m_prime": "91261D96B",
                        "t": "10FE96",
                        "t_prime": "10856A",
                        "m2": "B136089AAF",
                        "s": "018969A6D",
                        "c": "09186B6A",
                    },
                    "c_list": {
                        "e": "6 1B161",
                        "d": "6 19E861869",
                        "a": "6 541441EE2",
                        "g": "6 7601B068C",
                        "w": "21 10DE6 4 AAAA 5 2458 6 16161",
                        "s": "21 09616 4 1986 5 9797 6 BBBBB",
                        "u": "21 3213123 4 0616FFE 5 323 6 110861861",
                    },
                },
            }
        ],
        "aggregated_proof": {
            "c_hash": "81147637626525127013830996",
            "c_list": [
                [3, 18, 46, 12],
                [3, 136, 2, 39],
                [100, 111, 148, 193],
                [1, 123, 11, 152],
                [2, 138, 162, 227],
                [1, 239, 33, 47],
            ],
        },
    },
    "requested_proof": {
        "revealed_attrs": {
            "0_player_uuid": {
                "sub_proof_index": 0,
                "raw": "Richie Knucklez",
                "encoded": "516439982",
            },
            "0_player_picture": {
                "sub_proof_index": 0,
                "raw": EXAMPLE_LINK,
                "encoded": "4434954949",
            },
        },
        "self_attested_attrs": {},
        "unrevealed_attrs": {},
        "predicates": {},
    },
    "identifiers": [
        {
            "schema_id": S_ID,
            "cred_def_id": CD_ID,
            "rev_reg_id": RR_ID,
            "timestamp": NOW,
        }
    ],
}

@pytest.fixture
def attachments():
    return [
            AttachDecorator.data_base64(
                {
                    "data": EXAMPLE_DATA.decode()
                },
                ident="test_attach_id",
            )
        ]

@pytest.fixture
def supplements():
    return [Supplement(
    type="hashlink-data",
    attrs=[SupplementAttribute(
        key="field",
        value="0_player_picture")],
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
def pres(supplements, attachments):
    return V20Pres(
        comment="test_pres",
        # presentations_attach=[
        #     AttachDecorator(
        #         ident="pres_ident",
        #         data="hashlink_data"
        #     )
        # ],
        formats=[V20PresFormat(attach_id="indy", format_=V20PresFormat.Format.INDY.aries)],
            presentations_attach=[
                AttachDecorator.data_base64(INDY_PROOF, ident="indy")
            ],
        supplements=supplements,
        attachments=attachments
    )


@pytest.fixture
async def pres_ex_record(req, pres, supplements, attachments):
    """PresExchangeRecord fixture
    """
    return V20PresExRecord(
        pres_request=req,
        pres=pres,
        supplements=supplements,
        attachments=attachments
    )


@pytest.fixture
async def profile():
    """PresExchangeRecord fixture
    """
    _profile = InMemoryProfile.test_profile()
    injector = _profile.context.injector

    Ledger = async_mock.MagicMock(BaseLedger, autospec=True)
    ledger = Ledger()
    ledger.get_schema = async_mock.CoroutineMock(
        return_value=async_mock.MagicMock()
    )
    ledger.get_credential_definition = async_mock.CoroutineMock(
        return_value={"value": {"revocation": {"...": "..."}}}
    )
    ledger.get_revoc_reg_def = async_mock.CoroutineMock(
        return_value={
            "ver": "1.0",
            "id": RR_ID,
            "revocDefType": "CL_ACCUM",
            "tag": RR_ID.split(":")[-1],
            "credDefId": CD_ID,
            "value": {
                "IssuanceType": "ISSUANCE_BY_DEFAULT",
                "maxCredNum": 1000,
                "publicKeys": {"accumKey": {"z": "1 ..."}},
                "tailsHash": "3MLjUFQz9x9n5u9rFu8Ba9C5bo4HNFjkPNc54jZPSNaZ",
                "tailsLocation": "http://sample.ca/path",
            },
        }
    )
    ledger.get_revoc_reg_delta = async_mock.CoroutineMock(
        return_value=(
            {
                "ver": "1.0",
                "value": {"prevAccum": "1 ...", "accum": "21 ...", "issued": [1]},
            },
            NOW,
        )
    )
    ledger.get_revoc_reg_entry = async_mock.CoroutineMock(
        return_value=(
            {
                "ver": "1.0",
                "value": {"prevAccum": "1 ...", "accum": "21 ...", "issued": [1]},
            },
            NOW,
        )
    )
    injector.bind_instance(BaseLedger, ledger)
    injector.bind_instance(
        IndyLedgerRequestsExecutor,
        async_mock.MagicMock(
            get_ledger_for_identifier=async_mock.CoroutineMock(
                return_value=(None, ledger)
            )
        ),
    )

    Holder = async_mock.MagicMock(IndyHolder, autospec=True)
    holder = Holder()
    get_creds = async_mock.CoroutineMock(
        return_value=(
            {
                "cred_info": {
                    "referent": "dummy_reft",
                    "attrs": {
                        "player": "Richie Knucklez",
                        "screenCapture": "aW1hZ2luZSBhIHNjcmVlbiBjYXB0dXJl",
                        "highScore": "1234560",
                    },
                }
            },  # leave this comma: return a tuple
        )
    )
    holder.get_credentials_for_presentation_request_by_referent = get_creds
    holder.get_credential = async_mock.CoroutineMock(
        return_value=json.dumps(
            {
                "schema_id": S_ID,
                "cred_def_id": CD_ID,
                "rev_reg_id": RR_ID,
                "cred_rev_id": 1,
            }
        )
    )
    holder.create_presentation = async_mock.CoroutineMock(return_value="{}")
    holder.create_revocation_state = async_mock.CoroutineMock(
        return_value=json.dumps(
            {
                "witness": {"omega": "1 ..."},
                "rev_reg": {"accum": "21 ..."},
                "timestamp": NOW,
            }
        )
    )
    injector.bind_instance(IndyHolder, holder)

    Verifier = async_mock.MagicMock(IndyVerifier, autospec=True)
    verifier = Verifier()
    verifier.verify_presentation = async_mock.CoroutineMock(
        return_value=(True, [])
    )
    injector.bind_instance(IndyVerifier, verifier)
    return _profile


@pytest.mark.asyncio 
async def test_hlverify(
    profile,
    pres_ex_record: V20PresExRecord
    ):
    """Testing hashlink verification for the 
    v2 present_proof IndyPresExchangeHandler
    
    Args:
        pres_ex_record: Presentation Exchange 
        Record. 

    """
    indy_pres_ex = IndyPresExchangeHandler(profile=profile)
    
    verify = await indy_pres_ex.verify_pres(pres_ex_record=pres_ex_record)
    print(verify)
    assert verify.verified == 'true'
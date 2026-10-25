"""Declared new-chain, exact candidate and bounded codec tests; never a site.

Certificates/XML are deliberately synthetic and not cryptographically signed.
The tests do not authenticate enrollment, authorize dispatch or migrate counters.
"""

import base64
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from uuid import NAMESPACE_URL, uuid5
from types import SimpleNamespace
from unittest.mock import Mock

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import issuing_chain as chain
from zatca_erpgulf.zatca_erpgulf import issuing_chain_repository as storage
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import PreparedIssuanceCandidate
from zatca_erpgulf.zatca_erpgulf.invoice_xml_core import INITIAL_PREVIOUS_HASH
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import (
    CHAIN_ID, EPOCH_ID, OTHER_ID, content, context, scope,
)
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import NS


def registration(der, **changes):
    values = dict(chain_id=CHAIN_ID, registration_id=OTHER_ID, company_name="TEST",
        seller_tax_id="300000000000003", environment="Production",
        credential_epoch=context(der).credential_epoch,
        enrollment_evidence_sha256=hashlib.sha256(b"synthetic enrollment, not authenticated").hexdigest())
    values.update(changes)
    return chain.DeclaredChainRegistration(**values)


def prepared_for(der, registered=None, *, icv=1, pih=INITIAL_PREVIOUS_HASH,
                 name=None, code="388", indicator="0200000"):
    registered = registered or registration(der)
    name = name or "SYNTHETIC-" + str(icv)
    selected = scope(invoice_name=name, company_name=registered.company_name,
        seller_tax_id=registered.seller_tax_id, environment=registered.environment,
        chain_id=registered.chain_id)
    root = etree.fromstring(content(der, code=code, indicator=indicator, invoice_name=name,
                                   seller=registered.seller_tax_id))
    root.find("cbc:UUID", NS).text = str(uuid5(NAMESPACE_URL, registered.chain_id + name))
    root.xpath("./cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID", namespaces=NS)[0].text = str(icv)
    root.xpath("./cac:AdditionalDocumentReference[cbc:ID='PIH']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject", namespaces=NS)[0].text = pih
    digest = root.xpath(".//ds:Reference[@Id='invoiceSignedData']/ds:DigestValue", namespaces=NS)[0]
    digest.text = base64.b64encode(hashlib.sha256(name.encode()).digest()).decode()
    endpoint = "invoices/reporting/single" if indicator.startswith("02") else "invoices/clearance/single"
    ctx = context(der, selected_scope=selected, endpoint=endpoint)
    ctx = replace(ctx, credential_epoch=registered.credential_epoch)
    return PreparedIssuanceCandidate(ctx, etree.tostring(root, encoding="UTF-8", xml_declaration=True))


def assert_code(call, code):
    with pytest.raises(chain.IssuingChainError) as error:
        call()
    assert error.value.code == code and str(error.value) == code


def test_published_seed_is_hex_digest_encoding_not_raw_digest_or_empty_string():
    assert INITIAL_PREVIOUS_HASH == (
        "NWZlY2ViNjZmZmM4NmYzOGQ5NTI3ODZjNmQ2OTZjNzljMmRiYzIzOWRkNGU5MWI0NjcyOWQ3M2EyN2ZiNTdlOQ=="
    )
    assert base64.b64decode(INITIAL_PREVIOUS_HASH) == hashlib.sha256(b"0").hexdigest().encode()
    assert INITIAL_PREVIOUS_HASH != base64.b64encode(hashlib.sha256(b"0").digest()).decode()
    assert INITIAL_PREVIOUS_HASH != base64.b64encode(hashlib.sha256(b"").hexdigest().encode()).decode()


def test_declared_new_registration_starts_at_zero_then_records_one_without_response(certificates):
    registered = registration(certificates[0])
    before = chain.initialize_declared_chain(registered)
    original = prepared_for(certificates[0], registered)
    after = chain.record_generated_candidate(before, original)
    assert before.last_icv == 0 and before.previous_hash == INITIAL_PREVIOUS_HASH
    assert after.last_icv == 1 and after.previous_hash == original.artifact.invoice_digest
    assert after.tail_key_sha256 == original.key_sha256
    assert after.state_sha256 != before.state_sha256
    assert original.xml_bytes == prepared_for(certificates[0], registered).xml_bytes
    assert all(after.diagnostic_projection()[name] is False for name in (
        "registration_verified", "persistence_verified", "signature_verified", "dispatch_authorized"))


@pytest.mark.parametrize("environment", ["Production", "Simulation", "Sandbox"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("code,indicator", [("388","0100000"),("388","0200000"),
    ("381","0100000"),("381","0200000"),("383","0100000"),("383","0211000"),("386","0100000")])
def test_first_record_source_type_and_environment_matrix(certificates, environment, doctype, code, indicator):
    registered = registration(certificates[0], environment=environment)
    original = prepared_for(certificates[0], registered, code=code, indicator=indicator)
    original = replace(original, context=replace(original.context,
        scope=replace(original.context.scope, doctype=doctype)))
    state = chain.record_generated_candidate(chain.initialize_declared_chain(registered), original)
    assert state.last_icv == 1 and state.registration.environment == environment


def test_second_artifact_links_to_generated_predecessor_without_http_acceptance(certificates):
    before = chain.initialize_declared_chain(registration(certificates[0]))
    first = prepared_for(certificates[0])
    one = chain.record_generated_candidate(before, first)
    second = prepared_for(certificates[0], icv=2, pih=one.previous_hash, code="381")
    two = chain.record_generated_candidate(one, second)
    assert two.last_icv == 2 and two.previous_hash == second.artifact.invoice_digest
    assert first.artifact.uuid != second.artifact.uuid


@pytest.mark.parametrize("origin", ["RENEWAL", "MIGRATION", "RESTORE", "", None, True])
def test_other_origins_are_not_assumed_to_be_genesis(certificates, origin):
    assert_code(lambda: registration(certificates[0], origin=origin), "chain_origin_requires_review")


@pytest.mark.parametrize("field,code", [("chain_id","chain_id"),("registration_id","chain_registration_id")])
@pytest.mark.parametrize("value", [None, "", "Basic PRIVATE", "00000000-0000-0000-0000-000000000000", []])
def test_identity_is_explicit_not_derived_from_auth(certificates, field, code, value):
    assert_code(lambda: registration(certificates[0], **{field:value}), code)


@pytest.mark.parametrize("value", [None, "", "Production ", "Debug", "Compliance", []])
def test_api_environment_is_not_debug_or_compliance_purpose(certificates, value):
    assert_code(lambda: registration(certificates[0], environment=value), "chain_environment")


@pytest.mark.parametrize("field,code", [("company_name","chain_company"),("seller_tax_id","chain_seller"),
    ("enrollment_evidence_sha256","chain_enrollment_evidence")])
@pytest.mark.parametrize("value", [None, "", " PRIVATE\n", []])
def test_registration_declarations_are_bounded(certificates, field, code, value):
    assert_code(lambda: registration(certificates[0], **{field:value}), code)


@pytest.mark.parametrize("field,value,code", [("last_icv", True, "chain_counter"),
    ("last_icv", -1, "chain_counter"), ("last_icv", "0", "chain_counter"),
    ("previous_hash", "", "chain_genesis"), ("previous_hash", None, "chain_genesis"),
    ("tail_key_sha256", "a"*64, "chain_genesis"),
    ("tail_manifest_sha256", "a"*64, "chain_genesis")])
def test_genesis_cannot_hide_an_empty_hash_or_existing_tail(certificates, field, value, code):
    state = chain.initialize_declared_chain(registration(certificates[0]))
    assert_code(lambda: replace(state, **{field:value}), code)


@pytest.mark.parametrize("icv", [2, 77, 100])
def test_first_position_cannot_skip_ahead_without_reviewed_migration(certificates, icv):
    state = chain.initialize_declared_chain(registration(certificates[0]))
    assert_code(lambda: chain.record_generated_candidate(state, prepared_for(certificates[0], icv=icv)),
                "chain_candidate_counter")


def test_missing_history_is_not_genesis_and_new_registered_unit_is_independent(certificates):
    first_registration = registration(certificates[0])
    other_registration = registration(certificates[2], chain_id=EPOCH_ID, registration_id=CHAIN_ID)
    old = chain.IssuingChainState(first_registration, 100, base64.b64encode(b"x"*32).decode(), "a"*64,"b"*64)
    new = chain.initialize_declared_chain(other_registration)
    assert old.last_icv == 100 and new.last_icv == 0
    assert chain.record_generated_candidate(new, prepared_for(certificates[2], other_registration)).last_icv == 1
    assert_code(lambda: replace(old, previous_hash=""), "chain_digest")


@pytest.mark.parametrize("change", ["company", "seller", "environment", "chain", "epoch"])
def test_candidate_drift_is_not_new_registration_or_implicit_rotation(certificates, change):
    registered = registration(certificates[0])
    state = chain.initialize_declared_chain(registered)
    changed = {"company":dict(company_name="OTHER"), "seller":dict(seller_tax_id="300000000000013"),
        "environment":dict(environment="Simulation"), "chain":dict(chain_id=EPOCH_ID),
        "epoch":dict(credential_epoch=registration(certificates[1]).credential_epoch)}[change]
    other = replace(registered, **changed)
    original = prepared_for(certificates[1] if change == "epoch" else certificates[0], other)
    assert_code(lambda: chain.record_generated_candidate(state, original),
        "chain_candidate_epoch" if change == "epoch" else "chain_candidate_scope")


def test_wrong_predecessor_and_counter_exhaustion_never_reset(certificates):
    registered = registration(certificates[0])
    state = chain.initialize_declared_chain(registered)
    assert_code(lambda: chain.record_generated_candidate(state,
        prepared_for(certificates[0], pih=base64.b64encode(b"x"*32).decode())), "chain_candidate_previous_hash")
    full = chain.IssuingChainState(registered, chain.MAX_CHAIN_ICV, base64.b64encode(b"x"*32).decode(), "a"*64,"b"*64)
    assert_code(lambda: chain.record_generated_candidate(full, prepared_for(certificates[0])), "chain_counter_exhausted")


@pytest.mark.parametrize("field", ["last_icv", "previous_hash", "registration", "state_sha256"])
def test_frozen_state_and_codec_roundtrip(certificates, field):
    original = prepared_for(certificates[0])
    state = chain.record_generated_candidate(chain.initialize_declared_chain(registration(certificates[0])), original)
    assert storage.decode_chain_state(storage.encode_chain_state(state)) == state
    with pytest.raises(FrozenInstanceError):
        setattr(state, field, None)
    assert state.previous_hash not in repr(state)
    assert original.xml_bytes.decode() not in repr(state)


@pytest.mark.parametrize("value", [b"", None, b"PRIVATE", b"[]", b"{}", b"x"*(storage.MAX_STATE_BYTES+1)])
def test_codec_refuses_unbounded_or_invalid_payload(value):
    with pytest.raises(chain.IssuingChainError) as error:
        storage.decode_chain_state(value)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("change", ["extra", "version", "epoch", "registration", "counter", "hash"])
def test_codec_revalidates_nested_types_and_genesis(certificates, change):
    body = chain.initialize_declared_chain(registration(certificates[0])).storage_projection()
    if change == "extra": body["extra"] = True
    elif change == "version": body["schema_version"] = True
    elif change == "epoch": body["registration"]["credential_epoch"]["secret"] = "PRIVATE"
    elif change == "registration": body["registration"] = []
    elif change == "counter": body["last_icv"] = True
    else: body["previous_hash"] = ""
    with pytest.raises(chain.IssuingChainError):
        storage.decode_chain_state(json.dumps(body).encode())


def mock_repository(certificates, monkeypatch, *, autocommit=0):
    cursor = Mock()
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    cursor.fetchone.return_value = (autocommit,)
    cursor.rowcount = 1
    connection = Mock()
    connection.cursor.return_value = cursor
    repo = storage.MariaDBIssuingChainRepository(connection, OTHER_ID)
    state = chain.initialize_declared_chain(registration(certificates[0]))
    monkeypatch.setattr(repo, "_load", Mock(return_value=state))
    monkeypatch.setattr(repo, "_has_candidate", Mock(return_value=False))
    repo._artifacts = SimpleNamespace(put=Mock(return_value=SimpleNamespace(events=())))
    return repo, connection, cursor, state, prepared_for(certificates[0])


@pytest.mark.parametrize("invalid", [None, "", "PRIVATE", OTHER_ID.upper(), []])
def test_invalid_namespace_is_rejected_before_connection_acquisition(invalid):
    connection = Mock()
    assert_code(lambda: storage.MariaDBIssuingChainRepository(connection, invalid), "chain_namespace")
    connection.cursor.assert_not_called()


def test_invalid_transition_poisoning_precedes_sql(certificates, monkeypatch):
    repo, connection, _, _, original = mock_repository(certificates, monkeypatch)
    assert_code(lambda: repo.record(None, original), "chain_state")
    assert_code(lambda: repo.load(registration(certificates[0])), "chain_transaction_unusable")
    connection.cursor.assert_not_called()


def test_repository_never_owns_commit_rollback_or_connection_lifecycle(certificates, monkeypatch):
    repo, connection, cursor, before, original = mock_repository(certificates, monkeypatch)
    after = repo.record(before, original)
    assert after.last_icv == 1
    repo._artifacts.put.assert_called_once_with(original)
    connection.commit.assert_not_called()
    connection.rollback.assert_not_called()
    connection.close.assert_not_called()
    query, values = cursor.execute.call_args.args
    assert query.startswith("UPDATE zatca_issuing_chain_v1")
    assert storage.encode_chain_state(after) in values and before.state_sha256 in values
    assert original.xml_bytes not in values  # Exact bytes are delegated to the shared artifact store.


def test_autocommit_refused_without_session_reconfiguration(certificates, monkeypatch):
    repo, connection, cursor, _, original = mock_repository(certificates, monkeypatch, autocommit=1)
    assert_code(lambda: repo.create(registration(certificates[0])), "chain_autocommit")
    assert [call.args[0] for call in cursor.execute.call_args_list] == ["SELECT @@session.autocommit"]
    repo._artifacts.put.assert_not_called()
    connection.commit.assert_not_called()


@pytest.mark.parametrize("number,expected", [(1062,"chain_unique_conflict"),(1205,"chain_lock_timeout"),
    (1213,"chain_deadlock"),(2006,"chain_database_error"),("PRIVATE","chain_database_error")])
def test_driver_failure_is_redacted_and_handle_is_poisoned(certificates, monkeypatch, number, expected):
    repo, connection, cursor, before, original = mock_repository(certificates, monkeypatch)
    cursor.execute.side_effect = RuntimeError(number,"PRIVATE SQL/credential/XML details")
    with pytest.raises(chain.IssuingChainError) as error:
        repo.record(before, original)
    assert str(error.value) == expected and error.value.__suppress_context__ is True
    assert_code(lambda: repo.load(before.registration), "chain_transaction_unusable")
    connection.commit.assert_not_called()
    connection.rollback.assert_not_called()


@pytest.mark.parametrize("failure", ["cas", "unbound", "interruption", "already_attempted"])
def test_selected_partial_or_ambiguous_boundaries_never_claim_completion(certificates, monkeypatch, failure):
    repo, connection, cursor, before, original = mock_repository(certificates, monkeypatch)
    if failure == "cas":
        cursor.rowcount = 0
        expected = "chain_compare_and_swap"
    elif failure == "unbound":
        repo._has_candidate.return_value = True
        expected = "chain_unbound_candidate"
    elif failure == "already_attempted":
        repo._artifacts.put.return_value = SimpleNamespace(events=("TEST EVENT",))
        expected = "chain_candidate_already_attempted"
    else:
        repo._artifacts.put.side_effect = KeyboardInterrupt
        expected = None
    if expected:
        assert_code(lambda: repo.record(before, original), expected)
    else:
        with pytest.raises(KeyboardInterrupt): repo.record(before, original)
    assert_code(lambda: repo.load(before.registration), "chain_transaction_unusable")
    connection.commit.assert_not_called()
    connection.rollback.assert_not_called()

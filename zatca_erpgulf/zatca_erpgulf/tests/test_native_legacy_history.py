"""Exact declared-link accounting; no claims about computed cryptographic hashes."""

from dataclasses import FrozenInstanceError, replace
import pickle

import pytest

from zatca_erpgulf.zatca_erpgulf import native_legacy_history as history
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import ArtifactEvidence
from zatca_erpgulf.zatca_erpgulf.chain_registration import ChainRegistrationError
from zatca_erpgulf.zatca_erpgulf.invoice_xml_core import INITIAL_PREVIOUS_HASH


def records(indices=(1, 2, 3)):
    rows, observations = [], {}
    for index in indices:
        dt = 'Sales Invoice' if index % 2 else 'POS Invoice'
        name = 'SYNTHETIC-' + str(index)
        rows.append(dict(doctype=dt, name=name, icv=str(index)))
        evidence = ArtifactEvidence(name, 'UUID', index, 'VAT', 'f'*64, 100, 'HASH-'+str(index),
            INITIAL_PREVIOUS_HASH if index == 1 else 'HASH-'+str(index-1))
        observations[dt, name] = evidence, 'KEY'
    return rows, observations


def summary(rows, observations, **overrides):
    options = dict(complete=True, attempted={(row['doctype'], row['name']) for row in rows},
        tail_icv=rows[-1]['icv'], tail_digest='HASH-'+rows[-1]['icv'], public_key='KEY', xml_bytes=0)
    options.update(overrides)
    return history.summarize_history(rows, observations, **options)


def test_matching_declarations_are_frozen_nonserializable_and_never_an_activation_grant():
    rows, obs = records(); result = summary(rows, obs)
    assert (result.sources_seen, result.inspected_sources, result.unresolved_sources, result.unprobed_sources) == (3, 3, 0, 0)
    assert result.source_scan_complete and result.missing_positions == '0'
    assert result.matched_links == 2 and result.broken_links == 0
    assert result.genesis_match is True and result.tail_match is True
    assert not hasattr(result, 'active') and not hasattr(result, 'accepted') and not hasattr(result, 'complete')
    with pytest.raises(FrozenInstanceError): result.tail_match = False
    with pytest.raises(TypeError): pickle.dumps(result)


@pytest.mark.parametrize('indices', [(2, 3), (1, 3), (3,)])
def test_absent_positions_are_exact_and_are_not_implicitly_joined(indices):
    rows, obs = records(indices); result = summary(rows, obs)
    assert result.missing_positions == str(3-len(indices))
    assert result.matched_links == (1 if indices == (2, 3) else 0)
    assert result.genesis_match is (True if 1 in indices else None)


@pytest.mark.parametrize('fault', ['pih', 'genesis', 'tail', 'rotated-key', 'unresolved', 'unprobed', 'source-limit'])
def test_distinct_review_reasons_are_not_collapsed_into_a_success_boolean(fault):
    rows, obs = records(); options = {}
    if fault in ('pih', 'genesis'):
        key = ('POS Invoice', 'SYNTHETIC-2') if fault == 'pih' else ('Sales Invoice', 'SYNTHETIC-1')
        evidence, signing_key = obs[key]; obs[key] = replace(evidence, previous_hash='OTHER'), signing_key
    elif fault == 'tail': options['tail_digest'] = 'OTHER'
    elif fault == 'rotated-key':
        evidence, _key = obs['POS Invoice', 'SYNTHETIC-2']; obs['POS Invoice', 'SYNTHETIC-2'] = evidence, 'OLDER-KEY'
    elif fault == 'unresolved': obs['POS Invoice', 'SYNTHETIC-2'] = None
    elif fault == 'unprobed':
        del obs['POS Invoice', 'SYNTHETIC-2']; options['attempted'] = set(obs)
    else: options['complete'] = False
    result = summary(rows, obs, **options)
    if fault == 'pih': assert result.broken_links == 1
    elif fault == 'genesis': assert result.genesis_match is False
    elif fault == 'tail': assert result.tail_match is False
    elif fault == 'rotated-key': assert result.rotated_key_sources == 1
    elif fault == 'unresolved': assert result.unresolved_sources == 1 and result.matched_links == 0
    elif fault == 'unprobed': assert result.unprobed_sources == 1 and result.unresolved_sources == 0
    else: assert result.missing_positions is None and not result.source_scan_complete


def test_identity_arithmetic_above_float_precision_stays_exact():
    rows, obs = records((9007199254740992, 9007199254740993))
    result = summary(rows, obs)
    assert result.missing_positions == '9007199254740991' and result.matched_links == 1


def test_duplicate_position_never_makes_negative_missing_history():
    rows, obs = records(); rows.append(dict(doctype='POS Invoice', name='DUPLICATE', icv='3'))
    with pytest.raises(ChainRegistrationError, match='registration_history_duplicate_slot'):
        summary(rows, obs)

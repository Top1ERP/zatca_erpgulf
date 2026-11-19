"""Initial CSR intent policy; no source, certificate request or authority I/O."""

from types import SimpleNamespace

import pytest

from zatca_erpgulf.zatca_erpgulf import native_onboarding as onboarding


@pytest.mark.parametrize('value,expected',[(None,False),(False,False),(0,False),(True,True),(1,True)])
def test_rollout_mode_is_explicit_and_never_guesses_from_a_truthy_string(value,expected):
    assert onboarding.native_mode_enabled(SimpleNamespace(conf={onboarding.MODE:value})) is expected


@pytest.mark.parametrize('value',['0','1','false','true',2,[],{}])
def test_unknown_rollout_values_are_review_conditions(value):
    with pytest.raises(onboarding.NativeOnboardingError,match='native_onboarding_mode_review'):
        onboarding.native_mode_enabled(SimpleNamespace(conf={onboarding.MODE:value}))


def test_public_preparation_error_drops_private_exception_context(monkeypatch):
    class PrivateFailure(Exception):
        def __str__(self):raise AssertionError('Do not stringify secret context')
    def broken(*args,**kwargs):raise PrivateFailure()
    monkeypatch.setattr(onboarding,'_prepare_new_unit',broken)
    with pytest.raises(onboarding.NativeOnboardingError) as failed:
        onboarding.prepare_new_unit('TC',{},'Production',runtime=object())
    assert failed.value.code=='native_onboarding_preparation_review'
    assert failed.value.__context__ is None


def test_pending_csr_value_is_redacted_and_not_queue_material():
    import pickle
    value=onboarding.PreparedNewUnit('ID','PRIVATE-CSR-EXAMPLE',False)
    assert 'PRIVATE' not in repr(value)
    with pytest.raises(TypeError,match='not_serializable'):pickle.dumps(value)


def test_declared_unit_key_is_stable_across_owners_and_key_rotation_but_not_taxpayer_or_environment():
    key=onboarding.egs_identity_key('Production','TEST-VAT','1-A|2-B|3-C')
    assert key==onboarding.egs_identity_key('Production','TEST-VAT','1-A|2-B|3-C')
    assert len(key)==64
    assert key!=onboarding.egs_identity_key('Simulation','TEST-VAT','1-A|2-B|3-C')
    assert key!=onboarding.egs_identity_key('Production','OTHER-VAT','1-A|2-B|3-C')
    assert key!=onboarding.egs_identity_key('Production','TEST-VAT','1-A|2-B|3-D')

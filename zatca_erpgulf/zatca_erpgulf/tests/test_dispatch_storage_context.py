"""Storage readiness domain/key/site binding, not an installed bootstrap."""

import base64
import pytest

from zatca_erpgulf.zatca_erpgulf import dispatch_storage_context as storage
from zatca_erpgulf.zatca_erpgulf.worker_transaction import WorkerTransactionError,owned_worker_transaction
from zatca_erpgulf.zatca_erpgulf.tests.test_worker_transaction import boundary


NAMESPACE='30000000-0000-4000-8000-000000000001'
KEY=base64.urlsafe_b64encode(b'T'*32).decode()


def test_readiness_probe_is_bound_to_the_existing_site_key_and_namespace():
    cipher=storage.derive_storage_cipher(KEY,site='fictional.invalid',namespace=NAMESPACE)
    proof=storage.make_storage_probe(cipher,NAMESPACE)
    storage.verify_storage_probe(cipher,NAMESPACE,proof)
    assert len(proof)<512 and 'zatca-native' not in proof
    for key,site,namespace in ((base64.urlsafe_b64encode(b'X'*32).decode(),'fictional.invalid',NAMESPACE),
        (KEY,'other.invalid',NAMESPACE),(KEY,'fictional.invalid','30000000-0000-4000-8000-000000000002')):
        other=storage.derive_storage_cipher(key,site=site,namespace=namespace)
        with pytest.raises(storage.StorageContextError) as failed:storage.verify_storage_probe(other,namespace,proof)
        assert failed.value.__context__ is None


@pytest.mark.parametrize('value',[None,'','invalid','v1.'+'X'*600])
def test_missing_or_malformed_probe_is_not_repaired(value):
    cipher=storage.derive_storage_cipher(KEY,site='fictional.invalid',namespace=NAMESPACE)
    with pytest.raises(storage.StorageContextError):storage.verify_storage_probe(cipher,NAMESPACE,value)


@pytest.mark.parametrize('fault',['key','site','probe','missing','duplicate'])
def test_worker_refuses_unbound_storage_before_it_can_append_a_record(boundary,fault):
    runtime,db,_=boundary;sql=db.sql.side_effect
    if fault=='key':runtime.conf['encryption_key']=base64.urlsafe_b64encode(b'X'*32).decode()
    elif fault=='site':runtime.local.site='other.invalid'
    else:
        def changed(statement,values=(),**kwargs):
            rows=sql(statement,values,**kwargs)
            if 'tabSingles' not in statement:return rows
            rows=[dict(row) for row in rows]
            if fault=='probe':rows[-1]['value']='INVALID'
            elif fault=='missing':rows.pop()
            else:rows.append(dict(rows[-1]))
            return rows
        db.sql.side_effect=changed
    with pytest.raises(WorkerTransactionError):
        with owned_worker_transaction(runtime):pytest.fail('Unbound store admitted')
    db.commit.assert_not_called()

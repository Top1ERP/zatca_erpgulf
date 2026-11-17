"""Internal native preparation ticket and exact-request handoff, without HTTP.

An owned coordinator supplies the locked registration/predecessor and saved
source. This module does not create enrollment evidence, allocate database state,
commit or send. Its ContextVar is synchronous/request-local and never queued.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
from uuid import UUID

from .issuing_attempt import IssuingAttemptError


ACTIVE_PREPARATION = ContextVar('zatca_native_preparation', default=None)
REVIEW = 'ZATCA invoice preparation could not be completed safely. No request was sent. Review the saved source, issuing-unit registration and credentials.'


class NativePreparationError(IssuingAttemptError):
    def __init__(self,code):
        super().__init__(code)
        self.template=REVIEW
        self.args=(REVIEW,)


@dataclass(frozen=True,repr=False)
class PreparedNativeRequest:
    """Protected local output, not committed custody or authority acceptance."""
    source_doctype: str
    source_name: str
    company_name: str
    chain_id: str
    environment: str
    invoice_uuid: str
    icv: str
    previous_hash: str
    invoice_hash: str
    endpoint: str
    base_url_sha256: str
    certificate_sha256: str
    public_key_sha256: str
    source_sha256: str
    request_sha256: str
    request_bytes: bytes = field(repr=False)

    def __reduce_ex__(self,protocol):raise TypeError('prepared_native_request_not_serializable')


class PreparedRequestHandoff(BaseException):
    """Internal control signal outside legacy generic failure/status writers."""
    def __init__(self,packet):
        self.packet=packet
        super().__init__('prepared_request_ready')
    def __reduce_ex__(self,protocol):raise TypeError('prepared_handoff_not_serializable')


def _site(runtime):
    site=getattr(getattr(runtime,'local',None),'site',None)
    return ('site',site) if isinstance(site,str) and site else ('runtime',id(runtime))


def source_observation_sha256(identity,observation):
    """Stream the existing typed immutable observation; do not round/rebuild it.

    Explicit type/length markers avoid repr/pickle, float conversion, large JSON
    copies and ambiguous concatenation. Decimal/date/float values were already
    tagged by the native observer. This is provenance, not a trusted DB epoch.
    """
    digest=hashlib.sha256(b'zatca-native-source-observation/v1\0')
    def feed(value):
        if value is None:digest.update(b'N');return
        if type(value) is bool:digest.update(b'Z1' if value else b'Z0');return
        if isinstance(value,int):raw=str(int(value)).encode('ascii');tag=b'I'
        elif type(value) is str:raw=value.encode('utf-8');tag=b'S'
        elif type(value) is bytes:raw=value;tag=b'B'
        elif isinstance(value,tuple):
            digest.update(b'T'+str(len(value)).encode('ascii')+b':')
            for child in value:feed(child)
            return
        else:raise NativePreparationError('native_source_observation_type')
        digest.update(tag+str(len(raw)).encode('ascii')+b':');digest.update(raw)
    feed((identity,observation))
    return digest.hexdigest()


class NativePreparation:
    """One locked source's scalar issuance inputs; no stored auth/private key."""
    def __init__(self,runtime,*,source_identity,company_name,chain,invoice_uuid,owner_check):
        if (type(source_identity) is not tuple or len(source_identity)!=2
                or source_identity[0] not in ('Sales Invoice','POS Invoice')
                or type(source_identity[1]) is not str or not source_identity[1]
                or not callable(owner_check)):
            raise NativePreparationError('native_preparation_source')
        try:
            valid_uuid=type(invoice_uuid) is str and str(UUID(invoice_uuid))==invoice_uuid
        except (ValueError,TypeError,AttributeError):
            valid_uuid=False
        if not valid_uuid:
            raise NativePreparationError('native_preparation_uuid')
        last=chain['last_icv']
        if (type(last) is not str or not last.isascii() or not last.isdecimal()
                or len(last)>64 or str(int(last))!=last):
            raise NativePreparationError('native_preparation_counter')
        self.runtime=runtime;self.site=_site(runtime);self.source_identity=source_identity
        self.company_name=company_name;self.chain_id=chain['record_id'];self.environment=chain['environment']
        self.owner_identity=(chain['owner_doctype'],chain['owner_name'])
        self.expected_material=(chain['certificate_sha256'],chain['public_key_sha256'])
        self.invoice_uuid=invoice_uuid;self.icv=str(int(last)+1);self.previous_hash=chain['previous_hash']
        self.seller_tax_id=chain['seller_tax_id']
        if len(self.icv)>64:raise NativePreparationError('native_preparation_counter_exhausted')
        self._owner_check=owner_check;self._material=None;self._route=None;self._payload=None
        self._scratch=None;self._path=None;self.closed=False;self._handed_off=False

    def __repr__(self):return '<NativePreparation protected>'
    def __reduce_ex__(self,protocol):raise TypeError('native_preparation_not_serializable')

    def require(self,runtime):
        failed=False
        try:owned=self._owner_check() is True
        except Exception:failed=True
        if self.closed or _site(runtime)!=self.site or failed or not owned:
            raise NativePreparationError('native_preparation_owner')

    def require_source(self,document,runtime):
        self.require(runtime)
        getter=getattr(document,'get',None)
        if (not callable(getter) or (getter('doctype'),getter('name'))!=self.source_identity
                or getter('company')!=self.company_name):
            raise NativePreparationError('native_preparation_source')

    def bind_material(self,snapshot):
        self.require(self.runtime)
        owner=snapshot.owner
        if ((owner.doctype,owner.name)!=self.owner_identity or snapshot.route.environment!=self.environment
                or snapshot.authorization.purpose!='production'
                or (snapshot.certificate_der_sha256,snapshot.public_key_sha256)!=self.expected_material):
            raise NativePreparationError('native_preparation_material')
        self._material=self.expected_material

    def bind_selection(self,route,authorization):
        self.require(self.runtime)
        if (route.environment!=self.environment or route.required_credential!='production'
                or (authorization.owner_doctype,authorization.owner_name)!=self.owner_identity):
            raise NativePreparationError('native_preparation_route')
        if self._route is not None and self._route!=route:
            raise NativePreparationError('native_preparation_route_changed')
        self._route=route

    def write_signed_xml(self,invoice_number,xml):
        self.require(self.runtime)
        if invoice_number!=self.source_identity[1] or self._scratch is None or self._path is not None:
            raise NativePreparationError('native_preparation_artifact')
        path=Path(self._scratch)/'invoice.xml'
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'wb') as output:output.write(xml.encode('utf-8'))
        self._path=str(path)
        return self._path

    def observe_payload(self,payload):
        self.require(self.runtime)
        if (payload.uuid!=self.invoice_uuid or type(payload.invoice_hash) is not str
                or type(payload.invoice_base64) is not str or self._payload is not None):
            raise NativePreparationError('native_preparation_request')
        self._payload=payload

    def handoff(self,issuing_scope):
        self.require(self.runtime)
        if (self._handed_off or self._material is None or self._route is None or self._payload is None
                or issuing_scope.source_identity!=self.source_identity or issuing_scope.purpose!='production'):
            raise NativePreparationError('native_preparation_incomplete')
        from .artifact_evidence import inspect_invoice_artifact, ArtifactEvidenceError
        from .certificate_evidence import inspect_embedded_certificate
        invalid=None
        try:
            xml=base64.b64decode(self._payload.invoice_base64,validate=True)
            observed=inspect_invoice_artifact(xml)
            certificate=inspect_embedded_certificate(xml)
            if (observed.invoice_id!=self.source_identity[1] or observed.uuid!=self.invoice_uuid
                    or observed.icv!=int(self.icv) or observed.previous_hash!=self.previous_hash
                    or observed.invoice_digest!=self._payload.invoice_hash
                    or observed.seller_tax_id!=self.seller_tax_id):
                invalid='native_preparation_xml_binding'
            elif (certificate.der_sha256,certificate.public_key_sha256)!=self._material:
                invalid='native_preparation_xml_certificate'
        except ArtifactEvidenceError as error:
            invalid='native_preparation_'+error.code
        except (ValueError,TypeError):
            invalid='native_preparation_xml_structure'
        if invalid is not None:raise NativePreparationError(invalid)
        # Match Requests' existing three-string JSON body contract. Keep this exact
        # value for storage and dispatch; never re-sign/re-serialize an unknown retry.
        body=json.dumps(self._payload.as_payload(),allow_nan=False).encode('utf-8')
        base=self._route.url.removesuffix('/'+self._route.endpoint)
        packet=PreparedNativeRequest(*self.source_identity,self.company_name,self.chain_id,self.environment,
            self.invoice_uuid,self.icv,self.previous_hash,self._payload.invoice_hash,self._route.endpoint,
            hashlib.sha256(base.encode()).hexdigest(),*self._material,
            source_observation_sha256(self.source_identity,issuing_scope.source_observation),
            hashlib.sha256(body).hexdigest(),body)
        self._handed_off=True
        raise PreparedRequestHandoff(packet)


def active_preparation(runtime):
    current=ACTIVE_PREPARATION.get()
    if current is not None:current.require(runtime)
    return current


def reject_legacy_native_preparation(document, runtime):
    """A retained native source must not fall back to legacy UUID/ICV/HTTP.

    This guards server-loaded source documents, not hostile Python or arbitrary
    client objects. Public dispatcher admission must still reload and authorize
    the saved source. Debug and Compliance callers choose their separate paths.
    """
    if active_preparation(runtime) is not None:
        return
    getter = getattr(document, 'get', None)
    marker = getter('custom_zatca_issuing_unit') if callable(getter) else None
    if type(marker) is str and marker.startswith('egs:'):
        from .issuing_attempt import ACTIVE, IssuingAttemptError
        current = ACTIVE.get()
        raise IssuingAttemptError('native_dispatch_required',
            transport_started=bool(current is not None and current.transport_started))


@contextmanager
def native_preparation(runtime,*,source_identity,company_name,chain,invoice_uuid,owner_check):
    """One internal lifetime and private scratch directory, never a queue payload."""
    if ACTIVE_PREPARATION.get() is not None:
        raise NativePreparationError('native_preparation_nested')
    current=NativePreparation(runtime,source_identity=source_identity,company_name=company_name,
        chain=chain,invoice_uuid=invoice_uuid,owner_check=owner_check)
    with tempfile.TemporaryDirectory(prefix='zatca-native-preparation-') as scratch:
        current._scratch=scratch
        token=ACTIVE_PREPARATION.set(current)
        try:yield current
        finally:
            current.closed=True
            current._scratch=None
            ACTIVE_PREPARATION.reset(token)

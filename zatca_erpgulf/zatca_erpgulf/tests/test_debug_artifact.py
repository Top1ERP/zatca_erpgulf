"""Synthetic ACL/attachment fixtures; no site, disk, ORM or authority access."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf.debug_artifact import (
    DebugArtifactError, prepare_debug_source, save_debug_artifact,
)
from zatca_erpgulf.zatca_erpgulf.operation_messages import DEBUG_ACCESS_DENIED, DEBUG_ATTACHMENT_REVIEW


class Document(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


@pytest.fixture(params=[(15, "Sales Invoice"), (15, "POS Invoice"), (16, "Sales Invoice"), (16, "POS Invoice")])
def model(request):
    version, doctype = request.param
    source = Document(doctype=doctype, name="MOCK-INVOICE", company="MOCK COMPANY", modified="2026-10-23 09:00:00")
    company = Document(doctype="Company", name=source.company, modified="2026-10-23 08:00:00")
    app = SimpleNamespace(session=SimpleNamespace(user="mock.operator"),
                          db=SimpleNamespace(commit=Mock(), rollback=Mock(), set_value=Mock()),
                          delete_doc=Mock(), get_all=Mock())
    case = SimpleNamespace(app=app, source=source, company=company, docs=[], calls=[],
                           acl={}, construct_hook=None, save_hook=None)

    def check(dt, op, doc, user, quiet):
        assert quiet is False
        case.calls.append((dt, op, doc, user))
        value = case.acl.get((dt, op), True)
        if isinstance(value, Exception):
            raise value
        return value

    def v15(dt, op, doc=None, user=None, raise_exception=True):
        return check(dt, op, doc, user, raise_exception)

    def v16(dt, op, doc=None, user=None, *, print_logs=True):
        return check(dt, op, doc, user, print_logs)

    app.has_permission = v15 if version == 15 else v16

    def get_doc(dt, name=None):
        if isinstance(dt, dict):
            file_doc = Document(**dt, flags={})
            case.docs.append(file_doc)

            def save():
                file_doc.name = f"MOCK-FILE-{len(case.docs)}"
                if case.save_hook:
                    case.save_hook(file_doc)

            file_doc.save = Mock(side_effect=save)
            if case.construct_hook:
                case.construct_hook(file_doc)
            return file_doc
        doc = source if dt == source.doctype else company
        if doc.doctype != dt or doc.name != name:
            raise KeyError("PRIVATE saved-loader detail")
        return doc

    app.get_doc = Mock(side_effect=get_doc)
    return case


def prepare(case):
    return prepare_debug_source(case.app, case.source.doctype, case.source.name)[2]


def assert_no_cleanup(case):
    case.app.delete_doc.assert_not_called()
    case.app.get_all.assert_not_called()
    case.app.db.commit.assert_not_called()
    case.app.db.rollback.assert_not_called()
    case.app.db.set_value.assert_not_called()


def test_repeat_runs_preserve_history_and_use_normal_private_file_saves(model):
    binding = prepare(model)
    assert model.calls[:4] == [
        (model.source.doctype, "read", model.source, "mock.operator"),
        (model.source.doctype, "write", model.source, "mock.operator"),
        ("Company", "read", model.company, "mock.operator"),
        ("File", "create", None, "mock.operator"),
    ]
    first = save_debug_artifact(model.app, binding, b"SYNTHETIC XML")
    second = save_debug_artifact(model.app, binding, b"SYNTHETIC XML")
    assert first != second and first.startswith("DEBUG_INVOICE_") and second.endswith(".xml")
    assert len(model.docs) == 2
    for doc in model.docs:
        assert doc.is_private == 1 and doc.content == b"SYNTHETIC XML"
        assert doc.attached_to_doctype == binding.doctype and doc.attached_to_name == binding.name
        assert not doc.get("attached_to_field") and not doc.flags
        doc.save.assert_called_once_with()
    assert_no_cleanup(model)


@pytest.mark.parametrize("operation", ["read", "write", "company-read", "file-create"])
@pytest.mark.parametrize("value", [False, None, 1, "yes"])
def test_every_source_and_create_permission_requires_literal_true(model, operation, value):
    key = {"read": (model.source.doctype, "read"), "write": (model.source.doctype, "write"),
           "company-read": ("Company", "read"), "file-create": ("File", "create")}[operation]
    model.acl[key] = value
    with pytest.raises(DebugArtifactError) as raised:
        prepare(model)
    assert str(raised.value) == DEBUG_ACCESS_DENIED
    assert not model.docs
    assert_no_cleanup(model)


@pytest.mark.parametrize("user", [None, "", "Guest", " operator "])
def test_invalid_or_guest_actor_cannot_load_or_attach(model, user):
    model.app.session.user = user
    with pytest.raises(DebugArtifactError):
        prepare(model)
    model.app.get_doc.assert_not_called()


@pytest.mark.parametrize("fault", ["engine-error", "engine-signature", "unsaved", "revision", "doctype"])
def test_unknown_acl_or_source_fault_is_redacted_without_fallback(model, fault):
    if fault == "engine-error":
        model.acl[(model.source.doctype, "write")] = TypeError("PRIVATE credential-like engine detail")
    elif fault == "engine-signature":
        model.app.has_permission = Mock(return_value=True)
    elif fault == "unsaved":
        model.source.__islocal = True
    elif fault == "revision":
        model.source.modified = None
    else:
        model.app.get_doc.side_effect = lambda *args: Document(doctype="Other", name=model.source.name)
    with pytest.raises(DebugArtifactError) as raised:
        prepare(model)
    assert str(raised.value) == DEBUG_ATTACHMENT_REVIEW
    assert raised.value.__context__ is None
    if fault == "engine-error":
        assert "PRIVATE" in str(raised.value.__cause__)
    assert not model.docs
    assert_no_cleanup(model)


@pytest.mark.parametrize("drift", ["source-revision", "company-revision", "company-link", "actor", "write", "create"])
def test_observed_source_actor_or_permission_drift_prevents_creation(model, drift):
    binding = prepare(model)
    if drift == "source-revision":
        model.source.modified = "2026-10-23 10:00:00"
    elif drift == "company-revision":
        model.company.modified = "2026-10-23 10:00:00"
    elif drift == "company-link":
        model.source.company = "OTHER COMPANY"
    elif drift == "actor":
        model.app.session.user = "another.operator"
    else:
        model.acl[(model.source.doctype, "write") if drift == "write" else ("File", "create")] = False
    with pytest.raises(DebugArtifactError):
        save_debug_artifact(model.app, binding, "SYNTHETIC XML")
    assert not model.docs
    assert_no_cleanup(model)


def test_file_constructor_drift_is_rechecked_before_save(model):
    binding = prepare(model)
    model.construct_hook = lambda doc: setattr(model.source, "modified", "2026-10-23 10:00:00")
    with pytest.raises(DebugArtifactError):
        save_debug_artifact(model.app, binding, "SYNTHETIC XML")
    model.docs[0].save.assert_not_called()
    assert_no_cleanup(model)


@pytest.mark.parametrize("field,value", [("name", "EXISTING"), ("doctype", "Other"),
    ("attached_to_name", "OTHER"), ("attached_to_doctype", "Other"), ("is_private", 0),
    ("attached_to_field", "ksa_einv_qr"), ("file_url", "/private/files/original.xml"),
    ("file_name", "../original.xml"), ("content", "OTHER CONTENT")])
def test_constructor_cannot_redirect_the_new_attachment_before_save(model, field, value):
    binding = prepare(model)
    model.construct_hook = lambda doc: setattr(doc, field, value)
    with pytest.raises(DebugArtifactError):
        save_debug_artifact(model.app, binding, "SYNTHETIC XML")
    model.docs[0].save.assert_not_called()
    assert_no_cleanup(model)


@pytest.mark.parametrize("fault", ["raised", "owner", "privacy", "field", "actor", "override", "filename", "unsaved"])
def test_post_save_faults_require_review_without_cleanup_retry_or_parent_rollback(model, fault):
    binding = prepare(model)

    def save_hook(doc):
        if fault == "raised":
            raise OSError("PRIVATE storage-provider failure")
        if fault == "owner":
            doc.attached_to_name = "OTHER-INVOICE"
        elif fault == "privacy":
            doc.is_private = 0
        elif fault == "field":
            doc.attached_to_field = "ksa_einv_qr"
        elif fault == "actor":
            model.app.session.user = "another.operator"
        elif fault == "filename":
            doc.file_name = "DEBUG_INVOICE_bad\t.xml"
        elif fault == "unsaved":
            doc.__islocal = True
        else:
            doc.flags["ignore_permissions"] = True

    model.save_hook = save_hook
    with pytest.raises(DebugArtifactError) as raised:
        save_debug_artifact(model.app, binding, b"SYNTHETIC XML")
    assert str(raised.value) == DEBUG_ATTACHMENT_REVIEW
    assert len(model.docs) == 1
    model.docs[0].save.assert_called_once_with()
    assert_no_cleanup(model)


def test_filename_is_independent_of_invoice_path_characters_and_returns_framework_name(model):
    model.source.name = "INV/../%_العربية"
    binding = prepare(model)
    model.save_hook = lambda doc: setattr(doc, "file_name", doc.file_name[:-4] + "_content.xml")
    filename = save_debug_artifact(model.app, binding, "SYNTHETIC XML")
    assert filename.isascii() and "/" not in filename and "%" not in filename
    assert filename == model.docs[0].file_name
    assert model.docs[0].attached_to_name == binding.name


@pytest.mark.parametrize("value", [None, "", b"", {}, 1])
def test_invalid_content_cannot_construct_a_file(model, value):
    binding = prepare(model)
    with pytest.raises(DebugArtifactError):
        save_debug_artifact(model.app, binding, value)
    assert not model.docs


@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_file_save_cancellation_propagates_without_cleanup_or_retry(model, stop):
    binding = prepare(model)
    interrupt = stop("synthetic cancellation")

    def stop_save(doc):
        raise interrupt

    model.save_hook = stop_save
    with pytest.raises(stop) as raised:
        save_debug_artifact(model.app, binding, "SYNTHETIC XML")
    assert raised.value is interrupt
    model.docs[0].save.assert_called_once_with()
    assert_no_cleanup(model)


@pytest.mark.parametrize("changed", ["doctype", "name", "modified", "company_modified", "user"])
def test_mismatched_source_binding_never_constructs_a_file(model, changed):
    binding = replace(prepare(model), **{changed: "OTHER"})
    with pytest.raises(DebugArtifactError):
        save_debug_artifact(model.app, binding, b"SYNTHETIC XML")
    assert not model.docs

"""Permissioned, non-destructive local Debug attachments; explicit runtime only.

No deletes, filename queries, permission overrides, invoice saves, commits,
rollback, HTTP or retries. Rechecks detect observed drift, not an atomic lock
or trusted File-hook/physical-storage provenance guarantee.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from .operation_messages import DEBUG_ACCESS_DENIED, DEBUG_ATTACHMENT_REVIEW
from .permission_compat import doctype_has_create_permission, saved_row_has_permission


class DebugArtifactError(ValueError):
    """Canonical English app diagnostic, never a loader/ACL/secret export."""


@dataclass(frozen=True)
class DebugSource:
    doctype: str
    name: str
    company: str
    modified: str
    company_modified: str
    user: str


def _name(value):
    return (type(value) is str and 0 < len(value) <= 140 and value == value.strip()
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _actor(runtime):
    user = runtime.session.user
    if not _name(user) or user == "Guest":
        raise DebugArtifactError(DEBUG_ACCESS_DENIED)
    return user


def _revision(doc):
    value = doc.get("modified")
    if not isinstance(value, (str, datetime)) or not str(value).strip():
        raise DebugArtifactError(DEBUG_ATTACHMENT_REVIEW)
    return str(value)


def _saved(runtime, doctype, name, user, operations):
    if not _name(name) or _actor(runtime) != user:
        raise DebugArtifactError(DEBUG_ACCESS_DENIED)
    doc = runtime.get_doc(doctype, name)
    if (doc.doctype != doctype or doc.name != name or doc.get("__islocal")
            or not _revision(doc)):
        raise DebugArtifactError(DEBUG_ATTACHMENT_REVIEW)
    for operation in operations:
        if not saved_row_has_permission(runtime.has_permission, doctype, operation, doc=doc, user=user):
            raise DebugArtifactError(DEBUG_ACCESS_DENIED)
        if _actor(runtime) != user:
            raise DebugArtifactError(DEBUG_ACCESS_DENIED)
    return doc


def prepare_debug_source(runtime, doctype, name):
    """Read exact saved source/Company and normal File-create ACL before work."""
    try:
        if doctype not in ("Sales Invoice", "POS Invoice"):
            raise DebugArtifactError(DEBUG_ACCESS_DENIED)
        user = _actor(runtime)
        source = _saved(runtime, doctype, name, user, ("read", "write"))
        company = _saved(runtime, "Company", source.get("company"), user, ("read",))
        if not doctype_has_create_permission(runtime.has_permission, "File", user=user):
            raise DebugArtifactError(DEBUG_ACCESS_DENIED)
        if _actor(runtime) != user:
            raise DebugArtifactError(DEBUG_ACCESS_DENIED)
        binding = DebugSource(doctype, name, company.name, _revision(source), _revision(company), user)
        return source, company, binding
    except DebugArtifactError:
        raise
    except Exception as error:
        failure = error
    # Preserve the cause for the existing server log; the UI receives str(error)
    # only, which is the canonical redacted review message.
    raise DebugArtifactError(DEBUG_ATTACHMENT_REVIEW) from failure


def _recheck(runtime, binding):
    if type(binding) is not DebugSource:
        raise DebugArtifactError(DEBUG_ATTACHMENT_REVIEW)
    _, _, current = prepare_debug_source(runtime, binding.doctype, binding.name)
    if current != binding:
        raise DebugArtifactError(DEBUG_ATTACHMENT_REVIEW)


def save_debug_artifact(runtime, binding, content):
    """Create a new private File with normal permissions; preserve all history.

Frappe may deduplicate identical content internally. Never delete or select an
old File or claim that a local Debug artifact is an accepted authority response.
No cleanup is guessed if File.save/hooks fail after partial effects.
"""
    try:
        if type(content) not in (str, bytes) or not content:
            raise DebugArtifactError(DEBUG_ATTACHMENT_REVIEW)
        _recheck(runtime, binding)
        filename = "DEBUG_INVOICE_" + uuid4().hex + ".xml"
        file_doc = runtime.get_doc({
            "doctype": "File", "file_name": filename, "content": content,
            "attached_to_doctype": binding.doctype, "attached_to_name": binding.name,
            "is_private": 1,
        })
        if (file_doc.get("name") or file_doc.flags.get("ignore_permissions")
                or file_doc.doctype != "File" or file_doc.get("is_private") != 1
                or file_doc.get("attached_to_doctype") != binding.doctype
                or file_doc.get("attached_to_name") != binding.name
                or file_doc.get("attached_to_field") or file_doc.get("file_url")
                or file_doc.get("file_name") != filename or file_doc.get("content") != content):
            raise DebugArtifactError(DEBUG_ATTACHMENT_REVIEW)
        _recheck(runtime, binding)
        file_doc.save()  # Normal File create checks and hooks, no ignore flag.
        actual = file_doc.get("file_name")
        if (runtime.session.user != binding.user or not _name(file_doc.get("name"))
                or file_doc.flags.get("ignore_permissions")
                or file_doc.get("__islocal")
                or file_doc.doctype != "File" or file_doc.get("is_private") != 1
                or file_doc.get("attached_to_doctype") != binding.doctype
                or file_doc.get("attached_to_name") != binding.name
                or file_doc.get("attached_to_field")
                or not isinstance(actual, str) or not actual.startswith("DEBUG_INVOICE_")
                or not actual.endswith(".xml") or len(actual) > 255
                or any(ord(char) < 32 or ord(char) == 127 or char in "/\\" for char in actual)):
            raise DebugArtifactError(DEBUG_ATTACHMENT_REVIEW)
        return actual
    except DebugArtifactError:
        raise
    except Exception as error:
        failure = error
    raise DebugArtifactError(DEBUG_ATTACHMENT_REVIEW) from failure

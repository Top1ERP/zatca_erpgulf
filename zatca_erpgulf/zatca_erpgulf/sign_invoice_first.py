"""
This module facilitates the generation, validation, and submission of
 ZATCA-compliant e-invoices for companies
using ERPNext
"""

import hashlib
import base64
import json
import binascii
import re
from datetime import datetime
from lxml import etree
import lxml.etree as MyTree
from frappe import _
import frappe
from cryptography import x509
from cryptography.x509.oid import NameOID, ObjectIdentifier
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ec
import requests
import asn1

from zatca_erpgulf.ksa_compliance.field_compat import get_alias_value
from zatca_erpgulf.zatca_erpgulf.compliance_result import (
    compliance_result_status,
    is_already_completed_response,
)
from zatca_erpgulf.zatca_erpgulf.qr_timestamp import format_zatca_qr_timestamp

SUPPORTED_INVOICES = ["Sales Invoice", "POS Invoice"]


def encode_customoid(custom_string):
    """Encoding of a custom string"""
    # Create an encoder
    encoder = asn1.Encoder()
    encoder.start()
    encoder.write(custom_string, asn1.Numbers.UTF8String)
    return encoder.output()


def parse_csr_config(csr_config_string):
    """Parse the csr config data"""
    csr_config = {}
    lines = csr_config_string.splitlines()
    for line in lines:
        key, value = line.split("=", 1)
        csr_config[key.strip()] = value.strip()
    return csr_config


def get_csr_data_multiple(zatca_doc):
    """Getting csr data from the config for multiple"""
    try:
        csr_config_string = zatca_doc.custom_csr_config

        if not csr_config_string:
            frappe.throw(_("No CSR config found in company settings"))

        csr_config = parse_csr_config(csr_config_string)

        csr_values = {
            "csr.common.name": csr_config.get("csr.common.name"),
            "csr.serial.number": csr_config.get("csr.serial.number"),
            "csr.organization.identifier": csr_config.get(
                "csr.organization.identifier"
            ),
            "csr.organization.unit.name": csr_config.get("csr.organization.unit.name"),
            "csr.organization.name": csr_config.get("csr.organization.name"),
            "csr.country.name": csr_config.get("csr.country.name"),
            "csr.invoice.type": csr_config.get("csr.invoice.type"),
            "csr.location.address": csr_config.get("csr.location.address"),
            "csr.industry.business.category": csr_config.get(
                "csr.industry.business.category"
            ),
        }

        return csr_values

    except (frappe.ValidationError, frappe.DoesNotExistError) as e:
        frappe.throw(_(f"Error in fetching CSR data multipe: {e}"))
        return None


def get_csr_data(company_abbr):
    """Getting csr data from the config"""
    try:
        company_name = frappe.db.get_value("Company", {"abbr": company_abbr}, "name")
        if not company_name:
            frappe.throw(_(f"Company with abbreviation {company_abbr} not found."))

        company_doc = frappe.get_doc("Company", company_name)
        csr_config_string = company_doc.custom_csr_config

        if not csr_config_string:
            frappe.throw(_("No CSR config found in company settings"))

        csr_config = parse_csr_config(csr_config_string)

        csr_values = {
            "csr.common.name": csr_config.get("csr.common.name"),
            "csr.serial.number": csr_config.get("csr.serial.number"),
            "csr.organization.identifier": csr_config.get(
                "csr.organization.identifier"
            ),
            "csr.organization.unit.name": csr_config.get("csr.organization.unit.name"),
            "csr.organization.name": csr_config.get("csr.organization.name"),
            "csr.country.name": csr_config.get("csr.country.name"),
            "csr.invoice.type": csr_config.get("csr.invoice.type"),
            "csr.location.address": csr_config.get("csr.location.address"),
            "csr.industry.business.category": csr_config.get(
                "csr.industry.business.category"
            ),
        }

        return csr_values

    except (frappe.ValidationError, frappe.DoesNotExistError) as e:
        frappe.throw(_(f"Error in fetching CSR data: {e}"))
        return None


def create_private_keys(company_abbr, zatca_doc):
    """the function is for creating the private key"""
    try:
        if isinstance(zatca_doc, str):
            zatca_doc = json.loads(zatca_doc)
        # frappe.msgprint(f"Using OTP (Company): {zatca_doc}")
        # Validate zatca_doc structure
        if (
            not isinstance(zatca_doc, dict)
            or "doctype" not in zatca_doc
            or "name" not in zatca_doc
        ):
            frappe.throw(
                _("Invalid 'zatca_doc' format. Must include 'doctype' and 'name'.")
            )

        # Fetch the document based on doctype and name
        doc = frappe.get_doc(zatca_doc.get("doctype"), zatca_doc.get("name"))
        if doc.doctype == "ZATCA Multiple Setting":
            multiple_setting_doc = frappe.get_doc("ZATCA Multiple Setting", doc.name)
        elif doc.doctype == "Company":
            company_name = frappe.db.get_value(
                "Company", {"abbr": company_abbr}, "name"
            )
            company_doc = frappe.get_doc("Company", company_name)
        private_key = ec.generate_private_key(ec.SECP256K1(), backend=default_backend())
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        if doc.doctype == "ZATCA Multiple Setting":
            multiple_setting_doc.custom_private_key = private_key_pem.decode("utf-8")
            multiple_setting_doc.save(ignore_permissions=True)
        elif doc.doctype == "Company":
            company_doc.custom_private_key = private_key_pem.decode("utf-8")
            company_doc.save(ignore_permissions=True)

        return private_key_pem
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(
            _(
                "error while creating the private key for company {company_abbr} "
                + str(e)
            )
        )
        return None


@frappe.whitelist(allow_guest=False)
def create_csr(zatca_doc, portal_type, company_abbr):
    """
    Function defining the create csr method with the config csr data
    """
    try:
        # frappe.throw("hi")

        if isinstance(zatca_doc, str):
            zatca_doc = json.loads(zatca_doc)
        # frappe.msgprint(f"Using OTP (Company): {zatca_doc}")
        # Validate zatca_doc structure
        if (
            not isinstance(zatca_doc, dict)
            or "doctype" not in zatca_doc
            or "name" not in zatca_doc
        ):
            frappe.throw(
                _("Invalid 'zatca_doc' format. Must include 'doctype' and 'name'.")
            )

        # Fetch the document based on doctype and name
        doc = frappe.get_doc(zatca_doc.get("doctype"), zatca_doc.get("name"))
        # Fetch CSR data based on document type
        if doc.doctype == "ZATCA Multiple Setting":
            csr_values = get_csr_data_multiple(doc)
            # frappe.msgprint(f"Using OTP (Multiple Setting): {csr_values}")
        elif doc.doctype == "Company":
            csr_values = get_csr_data(company_abbr)
            # frappe.msgprint(f"Using OTP (Company): {csr_values}")
        else:
            frappe.throw(_("Unsupported document type for CSR creation."))

        company_csr_data = csr_values

        csr_common_name = company_csr_data.get("csr.common.name")
        csr_serial_number = company_csr_data.get("csr.serial.number")
        csr_organization_identifier = company_csr_data.get(
            "csr.organization.identifier"
        )
        csr_organization_unit_name = company_csr_data.get("csr.organization.unit.name")
        csr_organization_name = company_csr_data.get("csr.organization.name")
        csr_country_name = company_csr_data.get("csr.country.name")
        csr_invoice_type = company_csr_data.get("csr.invoice.type")
        csr_location_address = company_csr_data.get("csr.location.address")
        csr_industry_business_category = company_csr_data.get(
            "csr.industry.business.category"
        )

        if portal_type == "Sandbox":
            customoid = encode_customoid("TESTZATCA-Code-Signing")
        elif portal_type == "Simulation":
            customoid = encode_customoid("PREZATCA-Code-Signing")
        else:
            customoid = encode_customoid("ZATCA-Code-Signing")
        if doc.doctype == "ZATCA Multiple Setting":
            private_key_pem = create_private_keys(doc, zatca_doc)
            # frappe.msgprint(f"Using OTP (Multiple Setting): {csr_values}")
        elif doc.doctype == "Company":
            private_key_pem = create_private_keys(company_abbr, zatca_doc)
            # frappe.msgprint(f"Using OTP (Company): {csr_values}")
        else:
            frappe.throw("no private key.")

        private_key = serialization.load_pem_private_key(
            private_key_pem, password=None, backend=default_backend()
        )

        custom_oid_string = "1.3.6.1.4.1.311.20.2"
        oid = ObjectIdentifier(custom_oid_string)
        custom_extension = x509.extensions.UnrecognizedExtension(oid, customoid)

        dn = x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, csr_country_name),
                x509.NameAttribute(
                    NameOID.ORGANIZATIONAL_UNIT_NAME, csr_organization_unit_name
                ),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, csr_organization_name),
                x509.NameAttribute(NameOID.COMMON_NAME, csr_common_name),
            ]
        )
        alt_name = x509.SubjectAlternativeName(
            [
                x509.DirectoryName(
                    x509.Name(
                        [
                            x509.NameAttribute(NameOID.SURNAME, csr_serial_number),
                            x509.NameAttribute(
                                NameOID.USER_ID, csr_organization_identifier
                            ),
                            x509.NameAttribute(NameOID.TITLE, csr_invoice_type),
                            x509.NameAttribute(
                                ObjectIdentifier("2.5.4.26"), csr_location_address
                            ),
                            x509.NameAttribute(
                                NameOID.BUSINESS_CATEGORY,
                                csr_industry_business_category,
                            ),
                        ]
                    )
                ),
            ]
        )

        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(dn)
            .add_extension(custom_extension, critical=False)
            .add_extension(alt_name, critical=False)
            .sign(private_key, hashes.SHA256(), backend=default_backend())
        )
        mycsr = csr.public_bytes(serialization.Encoding.PEM)
        base64csr = base64.b64encode(mycsr)
        encoded_string = base64csr.decode("utf-8")
        if doc.doctype == "ZATCA Multiple Setting":
            multiple_setting_doc = frappe.get_doc("ZATCA Multiple Setting", doc.name)
            multiple_setting_doc.custom_csr_data = encoded_string.strip()
            multiple_setting_doc.save(ignore_permissions=True)
        elif doc.doctype == "Company":
            company_doc = frappe.get_doc("Company", {"abbr": company_abbr})
            company_doc.custom_csr_data = encoded_string.strip()
            # Save the updated company document
            company_doc.save(ignore_permissions=True)
        return encoded_string
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(
            _("error occurred while creating csr for company {company_abbr} " + str(e))
        )
        return None


def get_api_url(company_abbr, base_url):
    """There are many api susing in zatca which can be defined by a feild in settings"""
    try:
        company_doc = frappe.get_doc("Company", {"abbr": company_abbr})
        if company_doc.custom_select == "Sandbox":
            url = (company_doc.custom_sandbox_url or "").strip() + base_url
        elif company_doc.custom_select == "Simulation":
            url = (company_doc.custom_simulation_url or "").strip() + base_url
        else:
            url = (company_doc.custom_production_url or "").strip() + base_url
        return url

    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(
            _("unexpected error occurred api for company {company_abbr} " + str(e))
        )
        return None


def get_compliance_api_url(company_abbr, base_url="compliance/invoices", environment=None):
    """Return the compliance/onboarding URL for the selected environment."""
    try:
        company_doc = frappe.get_doc("Company", {"abbr": company_abbr})
        selected_environment = (
            environment or company_doc.custom_select or "Production"
        ).strip()
        if selected_environment == "Sandbox":
            base_url_value = (company_doc.custom_sandbox_url or "").strip()
        elif selected_environment == "Simulation":
            base_url_value = (company_doc.custom_simulation_url or "").strip()
        else:
            base_url_value = (company_doc.custom_production_url or "").strip()
        if not base_url_value:
            frappe.throw(
                _(
                    "ZATCA {0} URL is required for company {1}."
                ).format(selected_environment, company_abbr)
            )
        return base_url_value.rstrip("/") + "/" + base_url.lstrip("/")
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("Unexpected error getting compliance API URL: {0}").format(e))
        return None


@frappe.whitelist(allow_guest=False)
def create_csid(zatca_doc, company_abbr, portal_type=None):
    """creating csid"""
    try:
        if isinstance(zatca_doc, str):
            zatca_doc = json.loads(zatca_doc)
        # frappe.msgprint(f"Using OTP (Company): {zatca_doc}")
        # Validate zatca_doc structure
        if (
            not isinstance(zatca_doc, dict)
            or "doctype" not in zatca_doc
            or "name" not in zatca_doc
        ):
            frappe.throw(
                _("Invalid 'zatca_doc' format. Must include 'doctype' and 'name'.")
            )
        # Fetch the document based on doctype and name
        doc = frappe.get_doc(zatca_doc.get("doctype"), zatca_doc.get("name"))
        if doc.doctype == "ZATCA Multiple Setting":
            multiple_setting_doc = frappe.get_doc("ZATCA Multiple Setting", doc.name)
            csr_data_str = multiple_setting_doc.get("custom_csr_data", "")
        elif doc.doctype == "Company":
            company_name = frappe.db.get_value(
                "Company", {"abbr": company_abbr}, "name"
            )

            company_doc = frappe.get_doc("Company", company_name)
            csr_data_str = company_doc.get("custom_csr_data", "")

            # frappe.msgprint(f"Using OTP (Company): {csr_values}")
        else:
            frappe.throw(_("Unsupported document type for CSR creation."))

        csr_contents = csr_data_str.strip()

        if not csr_contents:
            frappe.throw(_(f"No valid CSR data found for company {company_name}"))

        payload = json.dumps({"csr": csr_contents})
        # frappe.msgprint(f"Using OTP: {company_doc.custom_otp}")
        if doc.doctype == "ZATCA Multiple Setting":
            otp = str(multiple_setting_doc.get("custom_otp", "") or "").strip()
            # frappe.msgprint(f"Using OTP (Multiple Setting): {csr_values}")
        elif doc.doctype == "Company":
            otp = str(company_doc.get("custom_otp", "") or "").strip()

            # frappe.msgprint(f"Using OTP (Company): {csr_values}")
        else:
            frappe.throw(_("no otp."))
        headers = {
            "accept": "application/json",
            "OTP": otp,
            "Accept-Version": "V2",
            "Content-Type": "application/json",
        }

        frappe.publish_realtime(
            "show_gif",
            {"gif_url": "/assets/zatca_erpgulf/js/loading.gif"},
            user=frappe.session.user,
        )

        selected_environment = portal_type
        if not selected_environment and doc.doctype == "Company":
            selected_environment = company_doc.get("custom_select") or "Production"
        api_url = get_compliance_api_url(
            company_abbr,
            base_url="compliance",
            environment=selected_environment,
        )
        response = requests.post(
            url=api_url,
            headers=headers,
            data=payload,
            timeout=300,
        )
        frappe.publish_realtime("hide_gif", user=frappe.session.user)

        request_id = response.headers.get("x-request-id") or response.headers.get(
            "X-Request-ID"
        )
        request_context = _(
            "Environment: {0}; endpoint: {1}; OTP length: {2}; CSR payload length: {3}"
        ).format(
            selected_environment or "Production",
            api_url,
            len(otp),
            len(csr_contents),
        )

        if response.status_code == 400:
            details = response.text
            if request_id:
                details += _(" (request id: {0})").format(request_id)
            frappe.throw(
                _("Error: OTP is not valid. {0}\n{1}").format(
                    details, request_context
                )
            )
        if response.status_code != 200:
            details = response.text
            if request_id:
                details += _(" (request id: {0})").format(request_id)
            frappe.throw(
                _("Error: Issue with Certificate or OTP. {0}\n{1}").format(
                    details, request_context
                )
            )
        frappe.msgprint(_(str(response.text)))
        data = json.loads(response.text)

        concatenated_value = data["binarySecurityToken"] + ":" + data["secret"]
        encoded_value = base64.b64encode(concatenated_value.encode()).decode()
        if doc.doctype == "ZATCA Multiple Setting":
            multiple_setting_doc.custom_certficate = base64.b64decode(
                data["binarySecurityToken"]
            ).decode("utf-8")
            multiple_setting_doc.custom_basic_auth_from_csid = encoded_value
            multiple_setting_doc.custom_compliance_request_id_ = data["requestID"]
            multiple_setting_doc.save(ignore_permissions=True)
        elif doc.doctype == "Company":
            company_doc.custom_certificate = base64.b64decode(
                data["binarySecurityToken"]
            ).decode("utf-8")
            company_doc.custom_basic_auth_from_csid = encoded_value
            company_doc.custom_compliance_request_id_ = data["requestID"]
            company_doc.save(ignore_permissions=True)
        return response.text

    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("Error in creating CSID: " + str(e)))
        return None


def _csid_material_diagnostics(company_name):
    """Return non-secret diagnostics for the saved OTP/CSR material."""
    company_doc = frappe.get_doc("Company", company_name)
    environment = company_doc.get("custom_select") or "Production"
    endpoint = get_compliance_api_url(
        company_doc.abbr, base_url="compliance", environment=environment
    )
    csr_contents = str(company_doc.get("custom_csr_data") or "").strip()
    otp = str(company_doc.get("custom_otp") or "").strip()
    result = {
        "environment": environment,
        "endpoint": endpoint,
        "otp_length": len(otp),
        "otp_is_six_digits": bool(re.fullmatch(r"\d{6}", otp)),
        "csr_encoded_length": len(csr_contents),
        "compliance_request_id": company_doc.get("custom_compliance_request_id_"),
    }
    if not csr_contents:
        result["csr_error"] = "missing"
        return result

    try:
        csr = x509.load_pem_x509_csr(
            base64.b64decode(csr_contents), default_backend()
        )
        result["csr_signature_valid"] = bool(csr.is_signature_valid)
        result["csr_subject"] = csr.subject.rfc4514_string()
        result["csr_oid"] = ""
        for extension in csr.extensions:
            if extension.oid.dotted_string == "1.3.6.1.4.1.311.20.2":
                result["csr_oid"] = extension.value.value.decode(
                    "utf-8", errors="replace"
                )
            if isinstance(extension.value, x509.SubjectAlternativeName):
                for value in extension.value:
                    if isinstance(value, x509.DirectoryName):
                        result["csr_directory_name"] = value.value.rfc4514_string()
        private_key = company_doc.get("custom_private_key")
        if private_key:
            key = serialization.load_pem_private_key(
                private_key.encode(), password=None, backend=default_backend()
            )
            result["csr_private_key_match"] = (
                csr.public_key().public_numbers() == key.public_key().public_numbers()
            )

        basic_auth = str(company_doc.get("custom_basic_auth_from_csid") or "").strip()
        if basic_auth:
            auth_bytes = base64.b64decode(basic_auth).decode("utf-8")
            auth_parts = auth_bytes.split(":", 1)
            result["basic_auth_has_separator"] = len(auth_parts) == 2
            result["basic_auth_csid_length"] = len(auth_parts[0])
            result["basic_auth_secret_length"] = len(auth_parts[1]) if len(auth_parts) == 2 else 0

        certificate_value = str(company_doc.get("custom_certificate") or "").strip()
        if certificate_value:
            certificate_candidates = [certificate_value.encode()]
            try:
                decoded_certificate = base64.b64decode(certificate_value)
                certificate_candidates.append(decoded_certificate)
                try:
                    certificate_candidates.append(base64.b64decode(decoded_certificate))
                except Exception:
                    pass
            except Exception:
                pass
            certificate = None
            for candidate in certificate_candidates:
                for loader in (
                    x509.load_pem_x509_certificate,
                    x509.load_der_x509_certificate,
                ):
                    try:
                        certificate = loader(candidate, default_backend())
                        break
                    except Exception:
                        continue
                if certificate:
                    break
            result["csid_certificate_found"] = bool(certificate)
            if certificate:
                result["csid_certificate_subject"] = certificate.subject.rfc4514_string()
                result["csid_certificate_issuer"] = certificate.issuer.rfc4514_string()
                result["csid_certificate_serial"] = str(certificate.serial_number)
                if private_key:
                    result["csid_private_key_match"] = (
                        certificate.public_key().public_numbers()
                        == key.public_key().public_numbers()
                    )
    except Exception as error:
        result["csr_error"] = str(error)
    return result


def create_public_key(company_abbr, source_doc):
    """Create a public key based on the company abbreviation and source document."""
    try:
        # Get the company name using the provided abbreviation
        company_name = frappe.db.get_value("Company", {"abbr": company_abbr}, "name")
        if not company_name:
            frappe.throw(_(f"Company with abbreviation {company_abbr} not found."))

        # Fetch the company document
        company_doc = frappe.get_doc("Company", company_name)

        # Initialize certificate_data_str based on the document type
        certificate_data_str = ""

        if source_doc:
            if source_doc.doctype in SUPPORTED_INVOICES:
                if source_doc.custom_zatca_pos_name:
                    # Fetch Zatca settings and use its certificate

                    zatca_settings = frappe.get_doc(
                        "ZATCA Multiple Setting", source_doc.custom_zatca_pos_name
                    )
                    certificate_data_str = zatca_settings.get("custom_certficate", "")
                else:
                    # Use company certificate as fallback
                    certificate_data_str = company_doc.get("custom_certificate", "")
            elif source_doc.doctype == "Company":
                certificate_data_str = company_doc.get("custom_certificate", "")
            elif source_doc.doctype == "ZATCA Multiple Setting":
                certificate_data_str = source_doc.get("custom_certficate") 
            else:
                frappe.throw(_(f"Unsupported document type: {source_doc.doctype}"))

        if not certificate_data_str:
            frappe.throw(_("No certificate data found."))

        # Build the PEM certificate
        cert_base64 = f"""
        -----BEGIN CERTIFICATE-----
        {certificate_data_str.strip()}
        -----END CERTIFICATE-----
        """
        # Load the certificate and extract the public key
        cert = x509.load_pem_x509_certificate(cert_base64.encode(), default_backend())
        public_key = cert.public_key()
        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        if source_doc.doctype in SUPPORTED_INVOICES:
            if source_doc.custom_zatca_pos_name:
                zatca_settings = frappe.get_doc(
                    "ZATCA Multiple Setting", source_doc.custom_zatca_pos_name
                )

                if not hasattr(zatca_settings, "custom_public_key"):
                    frappe.throw(
                        _(
                            "Field `custom_public_key` not found in ZATCA Multiple Setting Doctype."
                        )
                    )

                zatca_settings.custom_public_key = public_key_pem
                zatca_settings.save(ignore_permissions=True)

            else:
                if not hasattr(company_doc, "custom_public_key"):
                    frappe.throw(
                        _("Field `custom_public_key` not found in Company Doctype.")
                    )

                company_doc.custom_public_key = public_key_pem
                company_doc.save(ignore_permissions=True)
        elif source_doc.doctype == "Company":
            if not hasattr(company_doc, "custom_public_key"):
                frappe.throw(
                    _("Field `custom_public_key` not found in Company Doctype.")
                )

            company_doc.custom_public_key = public_key_pem
            company_doc.save(ignore_permissions=True)

        # Ensure data is committed to the database
        frappe.db.commit()

    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("Error occurred while creating public key: " + str(e)))


def removetags(finalzatcaxml):
    """remove the unwanted tags from created xml"""
    try:
        # lxml does not accept a Unicode string containing an encoding
        # declaration.  The synthetic onboarding flow serializes XML with
        # ``encoding='utf-8'``; convert text to bytes before parsing so both
        # normal invoices and temporary onboarding documents use the same path.
        xml_input = (
            finalzatcaxml.encode("utf-8")
            if isinstance(finalzatcaxml, str)
            else finalzatcaxml
        )
        xml_file = MyTree.fromstring(xml_input)
        xsl_file = MyTree.fromstring(
            """<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
                                    xmlns:xs="http://www.w3.org/2001/XMLSchema"
                                    xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
                                    xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
                                    xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
                                    xmlns:ext="urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
                                    exclude-result-prefixes="xs"
                                    version="2.0">
                                    <xsl:output omit-xml-declaration="yes" encoding="utf-8" indent="no"/>
                                    <xsl:template match="node() | @*">
                                        <xsl:copy>
                                            <xsl:apply-templates select="node() | @*"/>
                                        </xsl:copy>
                                    </xsl:template>
                                    <xsl:template match="//*[local-name()='Invoice']//*[local-name()='UBLExtensions']"></xsl:template>
                                    <xsl:template match="//*[local-name()='AdditionalDocumentReference'][cbc:ID[normalize-space(text()) = 'QR']]"></xsl:template>
                                        <xsl:template match="//*[local-name()='Invoice']/*[local-name()='Signature']"></xsl:template>
                                    </xsl:stylesheet>"""
        )
        transform = MyTree.XSLT(xsl_file.getroottree())
        transformed_xml = transform(xml_file.getroottree())
        return transformed_xml
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("error occurred win removing tags " + str(e)))
        return None


def canonicalize_xml(tag_removed_xml):
    """canonicalisation of the xml"""
    try:
        canonical_xml = etree.tostring(tag_removed_xml, method="c14n").decode()
        return canonical_xml
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("error occurred in canonicalise xml " + str(e)))
        return None


def getinvoicehash(canonicalized_xml):
    """Getting the invoice hash of the xml"""
    try:
        hash_object = hashlib.sha256(canonicalized_xml.encode())
        hash_hex = hash_object.hexdigest()
        # print(hash_hex)
        hash_base64 = base64.b64encode(bytes.fromhex(hash_hex)).decode("utf-8")
        return hash_hex, hash_base64
    except Exception as e:
        raise frappe.ValidationError(
            f"error occurred while invoice hash {str(e)}"
        ) from e


def digital_signature(hash1, company_abbr, source_doc):
    """find digital signature of xml"""
    try:
        company_name = frappe.db.get_value("Company", {"abbr": company_abbr}, "name")
        if not company_name:
            frappe.throw(_(f"Company with abbreviation {company_abbr} not found."))

        company_doc = frappe.get_doc("Company", company_name)
        # frappe.throw(f"Source doc type: {type(source_doc)}, value: {source_doc}")
        private_key_data_str = None

        if source_doc:
            if source_doc.doctype in SUPPORTED_INVOICES:
                # Use certificate from the company document for Sales Invoice
                if source_doc.custom_zatca_pos_name:
                    zatca_settings = frappe.get_doc(
                        "ZATCA Multiple Setting", source_doc.custom_zatca_pos_name
                    )
                    if zatca_settings.custom__use_company_certificate__keys != 1:
                        private_key_data_str = zatca_settings.get("custom_private_key")
                    else:
                        linked_doc = frappe.get_doc("Company", zatca_settings.custom_linked_doctype)
                        private_key_data_str = linked_doc.get("custom_private_key")
                else:
                    private_key_data_str = company_doc.get("custom_private_key")
            elif source_doc.doctype == "Company":
                private_key_data_str = company_doc.get("custom_private_key")
            elif source_doc.doctype == "ZATCA Multiple Setting":
                private_key_data_str = source_doc.get("custom_private_key")

        if not private_key_data_str:
            frappe.throw(_("No private key data found for the company."))
        private_key_bytes = private_key_data_str.encode("utf-8")
        private_key = serialization.load_pem_private_key(
            private_key_bytes, password=None, backend=default_backend()
        )
        hash_bytes = bytes.fromhex(hash1)
        signature = private_key.sign(hash_bytes, ec.ECDSA(hashes.SHA256()))
        encoded_signature = base64.b64encode(signature).decode()

        return encoded_signature

    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("Error in digital signature: ") + str(e))
        return None


def extract_certificate_details(company_abbr, source_doc):
    """extracting the certificate details from the certificate data"""
    try:
        company_name = frappe.db.get_value("Company", {"abbr": company_abbr}, "name")
        if not company_name:
            frappe.throw(_(f"Company with abbreviation {company_abbr} not found."))

        company_doc = frappe.get_doc("Company", company_name)
        certificate_data_str = None     
        if source_doc:
            if source_doc.doctype in SUPPORTED_INVOICES:
                # Use certificate from the company document for Sales Invoice
                if source_doc.custom_zatca_pos_name:
                    # Fetch Zatca settings and use its certificate
                    zatca_settings = frappe.get_doc(
                        "ZATCA Multiple Setting", source_doc.custom_zatca_pos_name
                    )
                    if zatca_settings.custom__use_company_certificate__keys != 1:
                        certificate_data_str = zatca_settings.get("custom_certficate")
                    else:
                        linked_doc = frappe.get_doc("Company", zatca_settings.custom_linked_doctype)
                        certificate_data_str = linked_doc.get("custom_certificate")
                else:
                    certificate_data_str = company_doc.get("custom_certificate")
            elif source_doc.doctype == "Company":
                certificate_data_str = company_doc.get("custom_certificate")
            elif source_doc.doctype == "ZATCA Multiple Setting":
                certificate_data_str = source_doc.get("custom_certficate")

        if not certificate_data_str:
            frappe.throw(_(f"No certificate data found for company {source_doc}"))

        certificate_content = certificate_data_str.strip()

        if not certificate_content:
            frappe.throw(
                _(f"No valid certificate content found for company {company_name}")
            )
        # Format the certificate string to PEM format if not already in correct PEM format
        formatted_certificate = "-----BEGIN CERTIFICATE-----\n"
        formatted_certificate += "\n".join(
            certificate_content[i : i + 64]
            for i in range(0, len(certificate_content), 64)
        )
        formatted_certificate += "\n-----END CERTIFICATE-----\n"
        # Load the certificate using cryptography
        certificate_bytes = formatted_certificate.encode("utf-8")
        cert = x509.load_pem_x509_certificate(certificate_bytes, default_backend())
        formatted_issuer_name = cert.issuer.rfc4514_string()
        issuer_name = ", ".join([x.strip() for x in formatted_issuer_name.split(",")])
        serial_number = cert.serial_number
        return issuer_name, serial_number

    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("Error inextracting certificate details" + str(e)))
        return None


def certificate_hash(company_abbr, source_doc):
    """Find the certificate hash and returning the value"""
    try:
        company_name = frappe.db.get_value("Company", {"abbr": company_abbr}, "name")
        if not company_name:
            frappe.throw(_(f"Company with abbreviation {company_abbr} not found."))

        company_doc = frappe.get_doc("Company", company_name)
        certificate_data_str = None
        if source_doc:
            if source_doc.doctype in SUPPORTED_INVOICES:
                # Use certificate from the company document for Sales Invoice
                if source_doc.custom_zatca_pos_name:
                    zatca_settings = frappe.get_doc(
                        "ZATCA Multiple Setting", source_doc.custom_zatca_pos_name
                    )
                    if zatca_settings.custom__use_company_certificate__keys != 1:
                        certificate_data_str = zatca_settings.get("custom_certficate", "")
                    else:
                        linked_doc = frappe.get_doc("Company", zatca_settings.custom_linked_doctype)
                        certificate_data_str = linked_doc.get("custom_certificate", "")
                else:
                    certificate_data_str = company_doc.get("custom_certificate", "")
            elif source_doc.doctype == "Company":
                certificate_data_str = company_doc.get("custom_certificate", "")
            elif source_doc.doctype == "ZATCA Multiple Setting":
                certificate_data_str = source_doc.get("custom_certficate")

        if not certificate_data_str:
            frappe.throw(_(f"No certificate data found for company {company_name}"))
        certificate_data = certificate_data_str.strip()
        if not certificate_data:
            frappe.throw(
                _(f"No valid certificate data found for company {company_name}")
            )

        # ZATCA's implementation guide specifies hashing the certificate
        # value as stored (the base64 certificate content), then encoding the
        # hexadecimal hash text as Base64.
        certificate_data_bytes = certificate_data.encode("utf-8")
        sha256_hash = hashlib.sha256(certificate_data_bytes).hexdigest()
        base64_encoded_hash = base64.b64encode(sha256_hash.encode("utf-8")).decode(
            "utf-8"
        )
        return base64_encoded_hash

    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(
            _("Error in obtaining certificate hash chcek cert data: " + str(e))
        )
        return None


def xml_base64_decode(signed_xmlfile_name):
    """xml base64 decode"""
    try:
        with open(signed_xmlfile_name, "r", encoding="utf-8") as file:
            xml = file.read().lstrip()
            base64_encoded = base64.b64encode(xml.encode("utf-8"))
            base64_decoded = base64_encoded.decode("utf-8")
            return base64_decoded
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.msgprint(_("Error in xml base64:  " + str(e)))
        return None


def signxml_modify(company_abbr,finalzatcaxml,source_doc):
    """modify the signed xml by adding the values like signing time,serial number etc"""
    try:
        encoded_certificate_hash = certificate_hash(company_abbr, source_doc)
        issuer_name, serial_number = extract_certificate_details(
            company_abbr, source_doc
        )
        
        # original_invoice_xml = etree.parse(
        #     f"{frappe.local.site}/private/files/finalzatcaxml_{invoice_number}.xml"
        # # )
        # original_invoice_xml = etree.fromstring(
        #     finalzatcaxml.encode("utf-8")
        # )       
        # root = original_invoice_xml.getroot()
        root_element = etree.fromstring(finalzatcaxml.encode("utf-8"))
        original_invoice_xml = etree.ElementTree(root_element)
        root = original_invoice_xml.getroot()

        namespaces = {
            "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
            "sig": "urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2",
            "sac": "urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2",
            "xades": "http://uri.etsi.org/01903/v1.3.2#",
            "ds": "http://www.w3.org/2000/09/xmldsig#",
        }

        xpath_dv = "ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sig:UBLDocumentSignatures/sac:SignatureInformation/ds:Signature/ds:Object/xades:QualifyingProperties/xades:SignedProperties/xades:SignedSignatureProperties/xades:SigningCertificate/xades:Cert/xades:CertDigest/ds:DigestValue"
        xpath_signtime = "ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sig:UBLDocumentSignatures/sac:SignatureInformation/ds:Signature/ds:Object/xades:QualifyingProperties/xades:SignedProperties/xades:SignedSignatureProperties/xades:SigningTime"
        xpath_issuername = "ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sig:UBLDocumentSignatures/sac:SignatureInformation/ds:Signature/ds:Object/xades:QualifyingProperties/xades:SignedProperties/xades:SignedSignatureProperties/xades:SigningCertificate/xades:Cert/xades:IssuerSerial/ds:X509IssuerName"
        xpath_serialnum = "ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sig:UBLDocumentSignatures/sac:SignatureInformation/ds:Signature/ds:Object/xades:QualifyingProperties/xades:SignedProperties//xades:SignedSignatureProperties/xades:SigningCertificate/xades:Cert/xades:IssuerSerial/ds:X509SerialNumber"
        element_dv = root.find(xpath_dv, namespaces)
        element_st = root.find(xpath_signtime, namespaces)
        element_in = root.find(xpath_issuername, namespaces)
        element_sn = root.find(xpath_serialnum, namespaces)
        element_dv.text = encoded_certificate_hash
        element_st.text = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        signing_time = element_st.text
        element_in.text = issuer_name
        element_sn.text = str(serial_number)
        modified_xml_string = etree.tostring(
            root,
            encoding="utf-8",
            xml_declaration=True,
            pretty_print=True,
        ).decode("utf-8")
        # with open(f"{frappe.local.site}/private/files/after_step_4_{invoice_number}.xml", "wb") as file:
        #     original_invoice_xml.write(
        #         file,
        #         encoding="utf-8",
        #         xml_declaration=True,
        #     )
        return modified_xml_string,namespaces, signing_time
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_(" error in modification of xml sign part: " + str(e)))
        return None


def generate_signed_properties_hash(
    signing_time, issuer_name, serial_number, encoded_certificate_hash
):
    """generate the signed property hash of the xml using a part
    of the xml"""
    try:
        xml_string = """<xades:SignedProperties xmlns:xades="http://uri.etsi.org/01903/v1.3.2#" Id="xadesSignedProperties">
                                    <xades:SignedSignatureProperties>
                                        <xades:SigningTime>{signing_time}</xades:SigningTime>
                                        <xades:SigningCertificate>
                                            <xades:Cert>
                                                <xades:CertDigest>
                                                    <ds:DigestMethod xmlns:ds="http://www.w3.org/2000/09/xmldsig#" Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>
                                                    <ds:DigestValue xmlns:ds="http://www.w3.org/2000/09/xmldsig#">{certificate_hash}</ds:DigestValue>
                                                </xades:CertDigest>
                                                <xades:IssuerSerial>
                                                    <ds:X509IssuerName xmlns:ds="http://www.w3.org/2000/09/xmldsig#">{issuer_name}</ds:X509IssuerName>
                                                    <ds:X509SerialNumber xmlns:ds="http://www.w3.org/2000/09/xmldsig#">{serial_number}</ds:X509SerialNumber>
                                                </xades:IssuerSerial>
                                            </xades:Cert>
                                        </xades:SigningCertificate>
                                    </xades:SignedSignatureProperties>
                                </xades:SignedProperties>"""
        xml_string_rendered = xml_string.format(
            signing_time=signing_time,
            certificate_hash=encoded_certificate_hash,
            issuer_name=issuer_name,
            serial_number=str(serial_number),
        )
        return _zatca_property_hash_to_base64(xml_string_rendered)
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_(" error in generating signed properties hash: " + str(e)))
        return None


def _zatca_property_hash_to_base64(xml_value):
    """Hash a ZATCA property tag using its documented HEX-to-Base64 flow."""
    if isinstance(xml_value, etree._Element):
        xml_value = etree.tostring(xml_value, encoding="utf-8").decode("utf-8")
    # ZATCA validates the exact SignedProperties block that is submitted.
    # In particular, its indentation/newlines are significant.  Normalize
    # only the platform line ending; do not strip or collapse whitespace.
    signed_properties_xml = str(xml_value).replace("\r\n", "\n")
    hex_digest = hashlib.sha256(signed_properties_xml.encode("utf-8")).hexdigest()
    return base64.b64encode(hex_digest.encode("utf-8")).decode("utf-8")


def format_zatca_signed_xml(xml_string):
    """Apply the fixed SignedProperties indentation expected by ZATCA."""
    indentations = {
        29: [
            '<xades:QualifyingProperties xmlns:xades="http://uri.etsi.org/01903/v1.3.2#" Target="signature">',
            "</xades:QualifyingProperties>",
        ],
        33: [
            '<xades:SignedProperties Id="xadesSignedProperties">',
            "</xades:SignedProperties>",
        ],
        37: [
            "<xades:SignedSignatureProperties>",
            "</xades:SignedSignatureProperties>",
        ],
        41: [
            "<xades:SigningTime>",
            "<xades:SigningCertificate>",
            "</xades:SigningCertificate>",
        ],
        45: ["<xades:Cert>", "</xades:Cert>"],
        49: [
            "<xades:CertDigest>",
            "<xades:IssuerSerial>",
            "</xades:CertDigest>",
            "</xades:IssuerSerial>",
        ],
        53: [
            '<ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>',
            "<ds:DigestValue>",
            "<ds:X509IssuerName>",
            "<ds:X509SerialNumber>",
        ],
    }

    def adjust_indentation(line):
        for column, tags in indentations.items():
            for tag in tags:
                if line.strip().startswith(tag):
                    return " " * (column - 1) + line.lstrip()
        return line

    return "".join(
        adjust_indentation(line)
        for line in str(xml_string).splitlines(keepends=True)
    )


def signed_properties_hash_from_xml(modified_xml_string):
    """Create the ZATCA SignedProperties DigestValue from the actual XML node."""
    formatted_xml = format_zatca_signed_xml(modified_xml_string)
    start = formatted_xml.find("<xades:SignedProperties")
    end_tag = "</xades:SignedProperties>"
    end = formatted_xml.find(end_tag, start)
    if start < 0 or end < 0:
        frappe.throw(_("SignedProperties was not found in the signed XML."))
    signed_properties = formatted_xml[start : end + len(end_tag)]
    return _zatca_property_hash_to_base64(signed_properties)


def populate_the_ubl_extensions_output(
    modified_xml_string,
    encoded_signature,
    namespaces,
    signed_properties_base64,
    encoded_hash,
    company_abbr,
    source_doc,
):
    """populate the ubl extension output by giving the signature values and digest values"""
    try:
        # updated_invoice_xml = etree.parse(
        #     f"{frappe.local.site}/private/files/after_step_4_{invoice_number}.xml"
        # )
        # root3 = updated_invoice_xml.getroot()
        root3 = etree.fromstring(modified_xml_string.encode("utf-8"))
        updated_invoice_xml = etree.ElementTree(root3)
        company_name = frappe.db.get_value("Company", {"abbr": company_abbr}, "name")
        if not company_name:
            frappe.throw(_(f"Company with abbreviation {company_abbr} not found."))

        company_doc = frappe.get_doc("Company", company_name)
        certificate_data_str = None
        if source_doc:
            if source_doc.doctype in SUPPORTED_INVOICES:
                # Use certificate from the company document for Sales Invoice
                if source_doc.custom_zatca_pos_name:
                    # Fetch Zatca settings and use its certificate
                    zatca_settings = frappe.get_doc(
                        "ZATCA Multiple Setting", source_doc.custom_zatca_pos_name
                    )
                    if zatca_settings.custom__use_company_certificate__keys != 1:
                        certificate_data_str = zatca_settings.get("custom_certficate")
                    else:
                        linked_doc = frappe.get_doc("Company", zatca_settings.custom_linked_doctype)
                        certificate_data_str = linked_doc.get("custom_certificate")
                else:
                    certificate_data_str = company_doc.get("custom_certificate")
            elif source_doc.doctype == "Company":
                certificate_data_str = company_doc.get("custom_certificate")
            elif source_doc.doctype == "ZATCA Multiple Setting":
                certificate_data_str = source_doc.get("custom_certficate") 

        if not certificate_data_str:
            frappe.throw(_(f"No certificate data found for company {company_name}"))
        content = certificate_data_str.strip()

        if not content:
            frappe.throw(
                _(f"No valid certificate content found for company {company_name}")
            )

        xpath_signvalue = "ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sig:UBLDocumentSignatures/sac:SignatureInformation/ds:Signature/ds:SignatureValue"
        xpath_x509certi = "ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sig:UBLDocumentSignatures/sac:SignatureInformation/ds:Signature/ds:KeyInfo/ds:X509Data/ds:X509Certificate"
        xpath_digvalue = "ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sig:UBLDocumentSignatures/sac:SignatureInformation/ds:Signature/ds:SignedInfo/ds:Reference[@URI='#xadesSignedProperties']/ds:DigestValue"
        xpath_digvalue2 = "ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sig:UBLDocumentSignatures/sac:SignatureInformation/ds:Signature/ds:SignedInfo/ds:Reference[@Id='invoiceSignedData']/ds:DigestValue"

        signvalue6 = root3.find(xpath_signvalue, namespaces)
        x509certificate6 = root3.find(xpath_x509certi, namespaces)
        digestvalue6 = root3.find(xpath_digvalue, namespaces)
        digestvalue6_2 = root3.find(xpath_digvalue2, namespaces)

        signvalue6.text = encoded_signature
        x509certificate6.text = content
        digestvalue6.text = signed_properties_base64
        digestvalue6_2.text = encoded_hash
        final_xml_string = etree.tostring(
            root3,
            encoding="utf-8",
            xml_declaration=True,
            pretty_print=True,
        ).decode("utf-8")
        # with open(
        #     f"{frappe.local.site}/private/files/final_xml_after_sign_{invoice_number}.xml", "wb"
        # ) as file:
        #     updated_invoice_xml.write(file, encoding="utf-8", xml_declaration=True)
        return final_xml_string
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("Error in populating UBL extension output: " + str(e)))
        return


def extract_public_key_data(company_abbr, source_doc):
    """extract public key"""
    try:
        company_name = frappe.db.get_value("Company", {"abbr": company_abbr}, "name")
        if not company_name:
            frappe.throw(_(f"Company with abbreviation {company_abbr} not found."))

        company_doc = frappe.get_doc("Company", company_name)
        public_key_pem = None
        if source_doc:
            if source_doc.doctype in SUPPORTED_INVOICES:
                # Use certificate from the company document for Sales Invoice
                if source_doc.custom_zatca_pos_name:
                    # Fetch Zatca settings and use its certificate
                    zatca_settings = frappe.get_doc(
                        "ZATCA Multiple Setting", source_doc.custom_zatca_pos_name
                    )
                    if zatca_settings.custom__use_company_certificate__keys != 1:
                        public_key_pem = zatca_settings.get("custom_public_key", "")
                    else:
                        linked_doc = frappe.get_doc("Company", zatca_settings.custom_linked_doctype)
                        public_key_pem = linked_doc.get("custom_public_key", "")
                else:
                    public_key_pem = company_doc.get("custom_public_key", "")
            elif source_doc.doctype == "Company":
                public_key_pem = company_doc.get("custom_public_key", "")
            elif source_doc.doctype == "ZATCA Multiple Setting":
                public_key_pem = source_doc.get("custom_public_key", "")
        if not public_key_pem:
            frappe.throw(_(f"No public key found for company {source_doc}"))

        lines = public_key_pem.splitlines()
        key_data = "".join(lines[1:-1])
        key_data = key_data.replace("-----BEGIN PUBLIC KEY-----", "").replace(
            "-----END PUBLIC KEY-----", ""
        )
        key_data = key_data.replace(" ", "").replace("\n", "")

        return key_data

    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("Error in extracting public key data: " + str(e)))
        return None


def get_tlv_for_value(tag_num, tag_value):
    """get the tlv data value for teh qr"""
    try:
        tag_num_buf = bytes([tag_num])
        if tag_value is None:
            frappe.throw(f"Error: Tag value for tag number {tag_num} is None")
        if isinstance(tag_value, str):
            tag_value = tag_value.encode("utf-8")
            if len(tag_value) < 256:
                tag_value_len_buf = bytes([len(tag_value)])
            else:
                tag_value_len_buf = bytes(
                    [0xFF, (len(tag_value) >> 8) & 0xFF, len(tag_value) & 0xFF]
                )
        else:
            tag_value_len_buf = bytes([len(tag_value)])
        return tag_num_buf + tag_value_len_buf + tag_value
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_(" error in getting the tlv data value: " + str(e)))
        return None




def _is_simplified_document(source_doc):
    """Resolve Simplified/B2C using existing document/customer fields."""
    if not source_doc:
        return False

    getter = getattr(source_doc, "get", None)
    get_value = getter if callable(getter) else lambda key, default=None: getattr(source_doc, key, default)

    explicit_type = get_value("custom_zatca_invoice_type") or get_value("zatca_invoice_type")
    if explicit_type:
        normalized = str(explicit_type).strip().lower()
        if "simplified" in normalized:
            return True
        if "standard" in normalized:
            return False

    if get_value("doctype") == "POS Invoice":
        return True

    customer = get_value("customer")
    if not customer:
        return False

    try:
        customer_doc = frappe.get_cached_doc("Customer", customer)
        return bool(get_alias_value("customer_b2c", customer_doc, 0))
    except Exception:
        return False


def tag8_publickey(company_abbr, source_doc):
    """tag 8 of qr from public key"""
    try:
        create_public_key(company_abbr, source_doc)
        base64_encoded = extract_public_key_data(company_abbr, source_doc)
        byte_data = base64.b64decode(base64_encoded)
        hex_data = binascii.hexlify(byte_data).decode("utf-8")
        chunks = [hex_data[i : i + 2] for i in range(0, len(hex_data), 2)]
        value = "".join(chunks)
        binary_data = bytes.fromhex(value)
        return binary_data
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("Error in tag 8 from public key: " + str(e)))
        return None


def tag9_signature_ecdsa(company_abbr, source_doc):
    """tag 9 of signature"""
    try:
        company_name = frappe.db.get_value("Company", {"abbr": company_abbr}, "name")
        if not company_name:
            frappe.throw(_(f"Company with abbreviation {company_abbr} not found."))

        company_doc = frappe.get_doc("Company", company_name)
        certificate_content = None
        if source_doc:
            if source_doc.doctype in SUPPORTED_INVOICES:
                # Use certificate from the company document for Sales Invoice
                if source_doc.custom_zatca_pos_name:
                    # Fetch Zatca settings and use its certificate
                    zatca_settings = frappe.get_doc(
                        "ZATCA Multiple Setting", source_doc.custom_zatca_pos_name
                    )
                    if zatca_settings.custom__use_company_certificate__keys != 1:
                        certificate_content = zatca_settings.custom_certficate or ""
                    else:
                        linked_doc = frappe.get_doc("Company", zatca_settings.custom_linked_doctype)
                        certificate_content = linked_doc.custom_certificate or ""
                else:
                    certificate_content = company_doc.custom_certificate or ""
            elif source_doc.doctype == "Company":
                certificate_content = company_doc.custom_certificate or ""
            elif source_doc.doctype == "ZATCA Multiple Setting":
                certificate_content = source_doc.custom_certficate

        if not certificate_content:
            frappe.throw(_(f"No certificate found for company in tag9 {company_abbr}"))

        formatted_certificate = "-----BEGIN CERTIFICATE-----\n"
        formatted_certificate += "\n".join(
            certificate_content[i : i + 64]
            for i in range(0, len(certificate_content), 64)
        )
        formatted_certificate += "\n-----END CERTIFICATE-----\n"

        certificate_bytes = formatted_certificate.encode("utf-8")
        cert = x509.load_pem_x509_certificate(certificate_bytes, default_backend())
        signature = cert.signature
        signature_hex = "".join("{:02x}".format(byte) for byte in signature)
        signature_bytes = bytes.fromhex(signature_hex)

        return signature_bytes

    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("Error in tag 9 (signaturetag): " + str(e)))
        return None


def generate_tlv_xml(final_xml_string,company_abbr,source_doc):
    """generate xml by adding the tlv data"""
    try:

        # with open(
        #     f"{frappe.local.site}/private/files/final_xml_after_sign_{invoice_number}.xml", "rb"
        # ) as file:
        #     xml_data = file.read()
        # root = etree.fromstring(xml_data)
        root = etree.fromstring(final_xml_string.encode("utf-8"))
        namespaces = {
            "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
            "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
            "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
            "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
            "sig": "urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2",
            "sac": "urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2",
            "ds": "http://www.w3.org/2000/09/xmldsig#",
        }
        issue_date_xpath = "/ubl:Invoice/cbc:IssueDate"
        issue_time_xpath = "/ubl:Invoice/cbc:IssueTime"
        issue_date_results = root.xpath(issue_date_xpath, namespaces=namespaces)
        issue_time_results = root.xpath(issue_time_xpath, namespaces=namespaces)
        issue_date = (
            issue_date_results[0].text.strip() if issue_date_results else "Missing Data"
        )
        issue_time = (
            issue_time_results[0].text.strip() if issue_time_results else "Missing Data"
        )
        # ZATCA requires QR Tag 3 to be an ISO-8601 UTC timestamp.
        issue_date_time = format_zatca_qr_timestamp(issue_date, issue_time)
        tags_xpaths = [
            (
                1,
                "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName",
            ),
            (
                2,
                "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID",
            ),
            (3, None),
            # QR Tag 4 follows BT-115 (PayableAmount). For ordinary invoices
            # it normally equals TaxInclusiveAmount; with prepayments or
            # rounding it is the final amount due.
            (4, "/ubl:Invoice/cac:LegalMonetaryTotal/cbc:PayableAmount"),
            (5, "/ubl:Invoice/cac:TaxTotal/cbc:TaxAmount"),
            (
                6,
                "/ubl:Invoice/ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sig:UBLDocumentSignatures/sac:SignatureInformation/ds:Signature/ds:SignedInfo/ds:Reference/ds:DigestValue",
            ),
            (
                7,
                "/ubl:Invoice/ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sig:UBLDocumentSignatures/sac:SignatureInformation/ds:Signature/ds:SignatureValue",
            ),
            (8, None),
            (9, None),
        ]
        result_dict = {}
        for tag, xpath in tags_xpaths:
            if isinstance(xpath, str):
                elements = root.xpath(xpath, namespaces=namespaces)
                if elements:
                    value = (
                        elements[0].text
                        if isinstance(elements[0], etree._Element)
                        else elements[0]
                    )
                    if tag == 4 and not str(value or "").strip():
                        frappe.throw(
                            _(
                                "Cannot generate QR Tag 4: "
                                "cbc:PayableAmount is empty."
                            )
                        )
                    result_dict[tag] = value
                else:
                    if tag == 4:
                        frappe.throw(
                            _(
                                "Cannot generate QR Tag 4: "
                                "cbc:PayableAmount is missing from the XML."
                            )
                        )
                    result_dict[tag] = "Not found"
            else:
                result_dict[tag] = xpath
        result_dict[3] = issue_date_time
        result_dict[8] = tag8_publickey(company_abbr, source_doc)
        # Tag 9 is defined only for Simplified Tax Invoices and their notes.
        invoice_typecode = root.xpath(
            "/ubl:Invoice/cbc:InvoiceTypeCode", namespaces=namespaces
        )
        invoice_type_name = (
            (invoice_typecode[0].get("name") or "").strip()
            if invoice_typecode
            else ""
        )
        is_simplified_xml = invoice_type_name.startswith("02")
        if is_simplified_xml or _is_simplified_document(source_doc):
            result_dict[9] = tag9_signature_ecdsa(company_abbr, source_doc)
        else:
            result_dict.pop(9, None)
        result_dict[1] = result_dict[1].encode(
            "utf-8"
        )  # Handling Arabic company name in QR Code
        return result_dict
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("Error in getting the entire TLV data: " + str(e)))
        return None


def update_qr_toxml(final_xml_string,qrcodeb64, company_abbr):
    """updating the  alla values of qr to xml"""
    try:
        # xml_file_path = f"{frappe.local.site}/private/files/final_xml_after_sign_{invoice_number}.xml"
        # xml_tree = etree.parse(xml_file_path)
        xml_tree = etree.fromstring(final_xml_string.encode("utf-8"))
        namespaces = {
            "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
            "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
        }
        qr_code_element = xml_tree.find(
            './/cac:AdditionalDocumentReference[cbc:ID="QR"]/cac:Attachment/cbc:EmbeddedDocumentBinaryObject',
            namespaces=namespaces,
        )
        if qr_code_element is not None:
            qr_code_element.text = qrcodeb64
        else:
            frappe.msgprint(
                _(f"QR code element not found in the XML for company {company_abbr}")
            )
        # xml_tree.write(xml_file_path, encoding="UTF-8", xml_declaration=True)
        updated_xml_string = etree.tostring(
            xml_tree,
            encoding="utf-8",
            xml_declaration=True,
            pretty_print=True,
        ).decode("utf-8")
        return updated_xml_string
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(
            _(f"Error in saving TLV data to XML for company {company_abbr}: " + str(e))
        )


def structuring_signedxml(invoice_number,updated_xml_string):
    """structuring the signed xml"""
    try:
        adjusted_xml_content = format_zatca_signed_xml(updated_xml_string)

        with open(
            f"{frappe.local.site}/private/files/final_xml_after_indent_{invoice_number}.xml",
            "w",
            encoding="utf-8",
        ) as file:
            file.write(adjusted_xml_content)
    

        # adjusted_xml_content = [adjust_indentation(line) for line in updated_xml_string]
        # with open(
        #     f"{frappe.local.site}/private/files/final_xml_after_indent_{invoice_number}.xml",
        #     "w",
        #     encoding="utf-8",
        # ) as file:
        #     file.writelines(adjusted_xml_content)
        signed_xmlfile_name = (
            f"{frappe.local.site}/private/files/final_xml_after_indent_{invoice_number}.xml"
        )
        return signed_xmlfile_name
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_(" error in structuring signed xml: " + str(e)))
        return None


def compliance_api_call(
    uuid1, encoded_hash, signed_xmlfile_name, company_abbr, source_doc
):
    """Submit a compliance sample in the company's configured environment.

    This is not a production clearance/reporting call. Return only confirmed
    validation or previous completion; transport and ambiguous outcomes raise.
    """
    try:

        company_name = frappe.db.get_value("Company", {"abbr": company_abbr}, "name")
        if not company_name:
            frappe.throw(_(f"Company with abbreviation {company_abbr} not found."))

        company_doc = frappe.get_doc("Company", company_name)
        payload = json.dumps(
            {
                "invoiceHash": encoded_hash,
                "uuid": uuid1,
                "invoice": xml_base64_decode(signed_xmlfile_name),
            }
        )

        auth_source = "company"
        if (
            hasattr(source_doc, "custom_zatca_pos_name")
            and source_doc.custom_zatca_pos_name
        ):
            auth_source = "multiple_setting"
            zatca_settings = frappe.get_doc(
                "ZATCA Multiple Setting", source_doc.custom_zatca_pos_name
            )
            if zatca_settings.custom__use_company_certificate__keys != 1:
                csid = zatca_settings.custom_basic_auth_from_csid
            else:
                auth_source = "linked_company"
                linked_doc = frappe.get_doc("Company", zatca_settings.custom_linked_doctype)
                csid = linked_doc.custom_basic_auth_from_csid
        else:
            csid = company_doc.custom_basic_auth_from_csid
        if not csid:
            frappe.throw(_((f"CSID for company {company_abbr} not foundor not found in multpile setting page")))

        # CSID values are stored as the base64 portion of HTTP Basic Auth.
        # Normalize legacy values that may contain copied whitespace or the
        # complete ``Basic ...`` prefix before constructing the header.
        csid = str(csid).strip()
        if csid.lower().startswith("basic "):
            authorization = csid
        else:
            authorization = "Basic " + "".join(csid.split())

        api_url = get_compliance_api_url(company_abbr)

        headers = {
            "accept": "application/json",
            "Accept-Language": "en",
            "Accept-Version": "V2",
            "Authorization": authorization,
            "Content-Type": "application/json",
        }
        response = requests.request(
            "POST",
            url=api_url,
            headers=headers,
            data=payload,
            timeout=300,
        )

        try:
            response_data = response.json()
        except ValueError:
            response_data = response.text

        if is_already_completed_response(response.status_code, response_data):
            response_data["_zatca_compliance_status"] = "ALREADY_COMPLETED"
            return response_data

        if response.status_code not in (200, 202):
            response_body = (response.text or "").strip()
            request_id = response.headers.get("x-request-id") or response.headers.get(
                "X-Request-ID"
            )
            details = response_body or response.reason or "No response body"
            if request_id:
                details += f" (request id: {request_id})"
            if response.status_code == 401:
                details += _(
                    " [environment: {0}; endpoint: {1}; auth source: {2}; CSID length: {3}]"
                ).format(
                    company_doc.get("custom_select") or "Production",
                    api_url,
                    auth_source,
                    len(authorization.removeprefix("Basic ").strip()),
                )
            frappe.throw(
                _(
                    f"Error in compliance [HTTP {response.status_code}]: {details}"
                )
            )

        if isinstance(response_data, dict):
            validation_results = response_data.get("validationResults")
            if (
                isinstance(validation_results, dict)
                and validation_results.get("status") == "ERROR"
            ):
                frappe.throw(json.dumps(response_data, ensure_ascii=False))

        if compliance_result_status(response_data) != "PASS":
            frappe.throw(
                _("ZATCA did not confirm compliance. This check cannot be marked as passed.")
            )

        return response_data
    except requests.exceptions.RequestException:
        # A timeout is an unknown remote outcome, not proof of rejection or
        # success. Never return an error tuple that a caller can treat as PASS.
        frappe.throw(
            _(
                "The ZATCA compliance request could not be completed. "
                "Check the connection and try again; compliance has not been confirmed."
            )
        )

    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_(f"ERROR in clearance invoice, ZATCA validation: {str(e)}"))
        return None


@frappe.whitelist(allow_guest=False)
def production_csid(zatca_doc, company_abbr):
    """production csid button and api"""
    try:

        if isinstance(zatca_doc, str):
            zatca_doc = json.loads(zatca_doc)

        if (
            not isinstance(zatca_doc, dict)
            or "doctype" not in zatca_doc
            or "name" not in zatca_doc
        ):
            frappe.throw(
                _("Invalid 'zatca_doc' format. Must include 'doctype' and 'name'.")
            )
        # Fetch the document based on doctype and name
        doc = frappe.get_doc(zatca_doc.get("doctype"), zatca_doc.get("name"))
        if doc.doctype == "ZATCA Multiple Setting":
            multiple_setting_doc = frappe.get_doc("ZATCA Multiple Setting", doc.name)
            csid = multiple_setting_doc.custom_basic_auth_from_csid
            request_id = multiple_setting_doc.custom_compliance_request_id_
        elif doc.doctype == "Company":
            company_name = frappe.db.get_value(
                "Company", {"abbr": company_abbr}, "name"
            )

            company_doc = frappe.get_doc("Company", company_name)
            csid = company_doc.custom_basic_auth_from_csid
            request_id = company_doc.custom_compliance_request_id_

        if not csid:
            frappe.throw(_(("CSID for company not found")))

        if not request_id:
            frappe.throw(_("Compliance request ID for company  not found"))
        payload = {"compliance_request_id": request_id}

        headers = {
            "accept": "application/json",
            "Accept-Version": "V2",
            "Authorization": "Basic " + csid,
            "Content-Type": "application/json",
        }
        frappe.publish_realtime(
            "show_gif",
            {"gif_url": "/assets/zatca_erpgulf/js/loading.gif"},
            user=frappe.session.user,
        )

        # This button is part of the pre-onboarding test flow. The Developer
        # Portal Sandbox exposes the Production CSID onboarding endpoint and
        # accepts the test Compliance CSID generated there.
        response = requests.post(
            url=get_compliance_api_url(company_abbr, base_url="production/csids"),
            headers=headers,
            json=payload,
            timeout=300,
        )
        frappe.publish_realtime("hide_gif", user=frappe.session.user)

        if response.status_code != 200:
            response_body = (response.text or "").strip()
            request_id = response.headers.get("x-request-id") or response.headers.get(
                "X-Request-ID"
            )
            details = response_body or response.reason or "No response body"
            if request_id:
                details += f" (request id: {request_id})"
            frappe.throw(_(f"Error in production [HTTP {response.status_code}]: {details}"))

        data = response.json()
        company_vat = ""
        if doc.doctype == "Company":
            company_vat = (company_doc.tax_id or "").strip()

        # Never save a test/production certificate for a different taxpayer.
        # ZATCA rejects subsequent invoice calls with certificate-permissions,
        # which is otherwise surfaced to users as a misleading HTTP 401.
        if company_vat and data.get("binarySecurityToken"):
            token_bytes = base64.b64decode(data["binarySecurityToken"])
            certificate_candidates = [token_bytes]
            try:
                certificate_candidates.append(base64.b64decode(token_bytes))
            except Exception:
                pass

            certificate = None
            for candidate in certificate_candidates:
                for loader in (
                    x509.load_der_x509_certificate,
                    x509.load_pem_x509_certificate,
                ):
                    try:
                        certificate = loader(candidate, default_backend())
                        break
                    except Exception:
                        continue
                if certificate is not None:
                    break

            if certificate is not None:
                certificate_text = certificate.subject.rfc4514_string()
                try:
                    certificate_text += " " + str(
                        certificate.extensions.get_extension_for_class(
                            x509.SubjectAlternativeName
                        ).value
                    )
                except Exception:
                    pass
                certificate_vat_match = re.search(
                    r"(?<!\d)3\d{13}3(?!\d)", certificate_text
                )
                certificate_vat = (
                    certificate_vat_match.group(0)
                    if certificate_vat_match
                    else ""
                )
                if certificate_vat and certificate_vat != company_vat:
                    frappe.throw(
                        _(
                            "ZATCA returned a Production CSID for VAT {0}, "
                            "but company {1} uses VAT {2}. Generate the CSID "
                            "with the company's VAT number."
                        ).format(certificate_vat, company_abbr, company_vat)
                    )

        concatenated_value = data["binarySecurityToken"] + ":" + data["secret"]
        encoded_value = base64.b64encode(concatenated_value.encode()).decode()
        if doc.doctype == "ZATCA Multiple Setting":
            multiple_setting_doc.custom_certificate = base64.b64decode(
                data["binarySecurityToken"]
            ).decode("utf-8")
            multiple_setting_doc.custom_final_auth_csid = encoded_value

            multiple_setting_doc.save(ignore_permissions=True)
        elif doc.doctype == "Company":
            company_doc.custom_certificate = base64.b64decode(
                data["binarySecurityToken"]
            ).decode("utf-8")
            company_doc.custom_basic_auth_from_production = encoded_value

            company_doc.save(ignore_permissions=True)

        return json.dumps(
            {"status": "SUCCESS", "request_id": data.get("requestID")},
            ensure_ascii=False,
        )

    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("Error in production CSID formation: " + str(e)))
        return None

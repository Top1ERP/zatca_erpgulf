import hashlib
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import frappe
from frappe import _
from frappe.utils import now_datetime, cint


def _setting_for(doc):
	name = getattr(doc, "custom_zatca_pos_name", None)
	if name:
		return frappe.get_doc("ZATCA Multiple Setting", name)
	return None


def _issuing_unit(doc, environment):
	setting = _setting_for(doc)
	if setting:
		credential = setting.get("custom_final_auth_csid") or setting.get("custom_basic_auth_from_csid") or setting.name
		return "setting:" + hashlib.sha256(str(credential).encode()).hexdigest()[:24]
	company = frappe.get_doc("Company", doc.company)
	credential = company.get("custom_basic_auth_from_production") if environment == "Production" else company.get("custom_basic_auth_from_csid")
	return "company:" + hashlib.sha256(str(credential or doc.company).encode()).hexdigest()[:24]


def _counter_key(company, issuing_unit, environment):
	return "{}-{}-{}".format(company, issuing_unit, environment).replace("/", "-")[:140]


def _get_or_create_counter(company, issuing_unit, environment):
	key = _counter_key(company, issuing_unit, environment)
	if not frappe.db.exists("ZATCA ICV Counter", key):
		try:
			frappe.get_doc({
				"doctype": "ZATCA ICV Counter",
				"name": key,
				"counter_key": key,
				"company": company,
				"issuing_unit": issuing_unit,
				"environment": environment,
				"last_issued_icv": 0,
				"active": 1,
			}).insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			pass
	return key


def get_icv(doc, environment="Production", debug=False):
	"""Allocate within the selected chain; only production owns invoice fields.

	Compliance keeps its dedicated counter for compatibility, but must never
	overwrite the source invoice's live ICV or issuing unit. Debug only reads.
	"""
	if environment == "Debug" or debug:
		if doc and frappe.get_meta(doc.doctype).has_field(fieldname := "custom_zatca_icv") and doc.get(fieldname):
			return str(cint(doc.get(fieldname)))
		issuing_unit = _issuing_unit(doc, "Production")
		name = _counter_key(doc.company, issuing_unit, "Production")
		last = frappe.db.get_value("ZATCA ICV Counter", name, "last_issued_icv") or 0
		return str(cint(last) + 1)

	if not doc or not getattr(doc, "company", None):
		frappe.throw(_("Company is required before generating ZATCA ICV."))

	fieldname = "custom_zatca_icv"
	if environment == "Production" and frappe.get_meta(doc.doctype).has_field(fieldname) and doc.get(fieldname):
		return str(cint(doc.get(fieldname)))

	issuing_unit = _issuing_unit(doc, environment)
	name = _get_or_create_counter(doc.company, issuing_unit, environment)
	if environment == "Production":
		setting = _setting_for(doc)
		if setting and frappe.get_meta("ZATCA Multiple Setting").has_field("custom_zatca_icv_counter"):
			frappe.db.set_value("ZATCA Multiple Setting", setting.name, "custom_zatca_icv_counter", name, update_modified=False)
		elif frappe.get_meta("Company").has_field("custom_zatca_icv_counter"):
			frappe.db.set_value("Company", doc.company, "custom_zatca_icv_counter", name, update_modified=False)

	# Lock the row so concurrent workers cannot receive the same ICV.
	row = frappe.db.sql(
		"select last_issued_icv from `tabZATCA ICV Counter` where name=%s for update",
		(name,), as_dict=True,
	)[0]
	next_icv = cint(row.last_issued_icv) + 1
	frappe.db.set_value("ZATCA ICV Counter", name, {
		"last_issued_icv": next_icv,
		"last_invoice": doc.name,
		"last_invoice_doctype": doc.doctype,
		"last_issued_at": now_datetime(),
	}, update_modified=False)
	if environment == "Production" and frappe.get_meta(doc.doctype).has_field(fieldname):
		doc.db_set(fieldname, next_icv, commit=True, update_modified=False)
	if environment == "Production" and frappe.get_meta(doc.doctype).has_field("custom_zatca_issuing_unit"):
		doc.db_set("custom_zatca_issuing_unit", issuing_unit, commit=True, update_modified=False)
	return str(next_icv)


def seed_company_counter(company, last_icv):
	"""One-time migration helper; never lowers an existing production counter."""
	company_doc = frappe.get_doc("Company", company)
	class _Doc:
		pass
	doc = _Doc()
	doc.company = company
	doc.custom_zatca_pos_name = None
	issuing_unit = _issuing_unit(doc, "Production")
	name = _get_or_create_counter(company, issuing_unit, "Production")
	current = cint(frappe.db.get_value("ZATCA ICV Counter", name, "last_issued_icv") or 0)
	if cint(last_icv) > current:
		frappe.db.set_value("ZATCA ICV Counter", name, "last_issued_icv", cint(last_icv), update_modified=False)
	if frappe.get_meta("Company").has_field("custom_zatca_icv_counter"):
		frappe.db.set_value("Company", company, "custom_zatca_icv_counter", name, update_modified=False)
	return {"counter": name, "last_issued_icv": max(current, cint(last_icv))}


def seed_phase2_counters_from_existing_xml():
	"""Initialize Phase-2 company counters from stored production XML, never lowering values."""
	files_path = Path(frappe.get_site_path("private", "files"))
	max_by_company = {}
	results = []
	for path in files_path.glob("*.xml"):
		if "DEBUG" in path.name.upper() or not ("Cleared xml file" in path.name or "final_xml_after_indent" in path.name):
			continue
		try:
			content = path.read_text(encoding="utf-8", errors="ignore")
			content = content[content.find("<Invoice"):]
			root = ET.fromstring(content)
			ns = "urn:oasis:names:specification:ubl:schema:xsd:"
			vat_node = root.find(".//{" + ns + "CommonBasicComponents-2}CompanyID")
			if vat_node is None or not vat_node.text:
				continue
			company = frappe.db.get_value("Company", {"tax_id": vat_node.text.strip()}, "name")
			if not company:
				continue
			for ref in root.findall(".//{" + ns + "CommonAggregateComponents-2}AdditionalDocumentReference"):
				id_node = ref.find("{" + ns + "CommonBasicComponents-2}ID")
				value_node = ref.find("{" + ns + "CommonBasicComponents-2}UUID")
				if id_node is not None and id_node.text == "ICV" and value_node is not None and re.fullmatch(r"\d+", value_node.text or ""):
					max_by_company[company] = max(max_by_company.get(company, 0), cint(value_node.text))
		except (OSError, ET.ParseError, ValueError, TypeError):
			continue

	for company in frappe.get_all("Company", filters={"custom_phase_1_or_2": "Phase-2"}, pluck="name"):
		# Do not initialize an unknown company to zero: absence of a stored XML
		# file is not proof that no production invoice was issued.
		if company in max_by_company:
			results.append(seed_company_counter(company, max_by_company[company]))
	return {"companies": len(results), "results": results, "xml_companies": len(max_by_company)}

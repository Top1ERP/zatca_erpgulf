import ast
import csv
from collections import Counter
from pathlib import Path
from string import Formatter
import unittest


APP_ROOT = Path(__file__).resolve().parents[2]
TRANSLATION_FILE = APP_ROOT / "translations" / "ar.csv"
ADVANCE_SOURCE_FILES = (
    APP_ROOT / "overrides" / "sales_invoice.py",
    APP_ROOT / "overrides" / "advance_receivables.py",
    APP_ROOT / "zatca_erpgulf" / "advance_deduction.py",
    APP_ROOT / "zatca_erpgulf" / "advance_payment_entry.py",
    APP_ROOT / "zatca_erpgulf" / "advance_lifecycle.py",
    APP_ROOT / "zatca_erpgulf" / "advance_credit_note.py",
)
CORE_TRANSLATIONS = {"Paid"}
REQUIRED_UI_SOURCES = {
    "Use this only for the initial advance payment invoice, not for the final invoice.",
    (
        "Select only one invoice type: Is Return (Credit Note), "
        "Is Rate Adjustment Entry (Debit Note), or Is Advance Payment Invoice."
    ),
}


def _translation_catalog() -> dict[str, str]:
    with TRANSLATION_FILE.open(encoding="utf-8", newline="") as source:
        return {
            row[0]: row[1]
            for row in csv.reader(source)
            if len(row) >= 2 and row[0]
        }


def _translated_python_sources(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def _placeholders(value: str) -> set[str]:
    return {
        field_name
        for _literal, field_name, _format_spec, _conversion in Formatter().parse(value)
        if field_name is not None
    }


class TestTranslationCatalogIntegrity(unittest.TestCase):
    def test_arabic_catalog_has_exactly_two_columns_and_unique_keys(self):
        with TRANSLATION_FILE.open(encoding="utf-8", newline="") as source:
            rows = list(csv.reader(source))

        malformed = [row for row in rows if len(row) != 2 or not row[0].strip()]
        self.assertEqual(malformed, [])

        keys = [row[0] for row in rows]
        duplicates = {key: count for key, count in Counter(keys).items() if count > 1}
        self.assertEqual(duplicates, {})

    def test_arabic_catalog_values_are_not_empty(self):
        with TRANSLATION_FILE.open(encoding="utf-8", newline="") as source:
            rows = list(csv.reader(source))

        empty_values = [row[0] for row in rows if len(row) == 2 and not row[1].strip()]
        self.assertEqual(empty_values, [])


class TestAdvanceTranslationContract(unittest.TestCase):
    def test_advance_python_messages_have_arabic_translations(self):
        catalog = _translation_catalog()
        sources = set().union(
            *(_translated_python_sources(path) for path in ADVANCE_SOURCE_FILES)
        ) - CORE_TRANSLATIONS

        missing = sorted(
            source
            for source in sources
            if not str(catalog.get(source) or "").strip()
        )
        self.assertEqual(missing, [])

    def test_advance_translation_placeholders_are_preserved(self):
        catalog = _translation_catalog()
        sources = set().union(
            *(_translated_python_sources(path) for path in ADVANCE_SOURCE_FILES)
        ) - CORE_TRANSLATIONS

        mismatches = {
            source: catalog[source]
            for source in sources
            if _placeholders(source) != _placeholders(catalog[source])
        }
        self.assertEqual(mismatches, {})

    def test_required_advance_ui_messages_have_arabic_translations(self):
        catalog = _translation_catalog()
        missing = sorted(
            source
            for source in REQUIRED_UI_SOURCES
            if not str(catalog.get(source) or "").strip()
        )
        self.assertEqual(missing, [])

"""Read-only request-local cache inspection alongside NEW owned SQL fixtures."""

import os

import pytest

from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import (
    empty_sources, native_case, combined_schema, format_schema, financial_schema, metadata_schema,
    defaults_schema, isolated_server, connections, untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_cache import capture, documents, set_currency
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, InspectionFailed, one_failure,
)
from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned TCP-disabled temporary SQL only; no tenant/authority access")


@pytest.mark.parametrize("major", [15, 16])
def test_native_source_and_selected_caches_use_one_owned_pipeline(defaults_operator, connections, major):
    case = native_case(defaults_operator, connections, major=major)
    set_currency(defaults_operator, case)
    precision = 2 if major == 15 else case.expected_precision
    for doc in documents(case): doc._precision = {"main": {"amount": precision}}
    result = capture(case, major)
    assert result.resolve_precision().precision == precision
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", ["callback", "close"])
def test_cache_changes_withhold_native_result_after_owned_cleanup(defaults_operator, connections, boundary):
    case = native_case(defaults_operator, connections, major=15)
    set_currency(defaults_operator, case)
    def mutate(): documents(case)[0]._precision = {"main": {"amount": 3}}
    if boundary == "callback":
        case.cache.side_effect = lambda *args: (mutate() if case.cache.call_count == 2 else None, {"currency_precision": "2"})[1]
    else:
        original = case.factory.side_effect
        def acquire(*args):
            owned = original(*args)
            close = owned.close.side_effect
            def finish():
                close()
                mutate()
            owned.close.side_effect = finish
            return owned
        case.factory.side_effect = acquire
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)

from zatca_erpgulf.zatca_erpgulf import zatca_response


def test_zatca_response_is_preserved_verbatim():
    raw_response = (
        '{"validationResults":{"infoMessages":[{"message":"Complied with UBL 2.1 '
        'standards in line with ZATCA specifications","category":"XSD validation",'
        '"status":"PASS"}]},"clearanceStatus":"CLEARED",'
        '"clearedInvoice":"BASE64_XML_PAYLOAD","customField":{"a":1}}'
    )

    assert zatca_response.format_zatca_response(raw_response, 200) == raw_response


def test_zatca_response_preserves_non_json_and_empty_values():
    assert zatca_response.format_zatca_response("Not Submitted", 400) == "Not Submitted"
    assert zatca_response.format_zatca_response("", 200) == ""

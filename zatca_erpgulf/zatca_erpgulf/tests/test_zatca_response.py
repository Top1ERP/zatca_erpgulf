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



def test_extract_raw_response_keeps_http_body_verbatim():
    raw_response = '  {"clearanceStatus": "CLEARED", "value": 1}  '

    assert zatca_response.extract_raw_response(raw_response) == raw_response


def test_extract_raw_response_removes_display_wrapper_only():
    raw_response = '{"validationResults":{"status":"PASS"},"clearanceStatus":"REPORTED"}'
    display_message = (
        "تم الإرسال بنجاح<br>Status Code: 200<br>"
        f"ZATCA Response: {raw_response}"
    )

    assert zatca_response.extract_raw_response(display_message) == raw_response


def test_normalize_zatca_full_response_updates_document_without_saving():
    class FakeDocument:
        def __init__(self, value):
            self.values = {"custom_zatca_full_response": value}

        def get(self, fieldname):
            return self.values.get(fieldname)

        def set(self, fieldname, value):
            self.values[fieldname] = value

    raw_response = '{"reportingStatus":"REPORTED"}'
    doc = FakeDocument(f"ZATCA Response: {raw_response}")

    zatca_response.normalize_zatca_full_response(doc)

    assert doc.get("custom_zatca_full_response") == raw_response


def test_normalize_zatca_full_response_leaves_non_json_status_unchanged():
    class FakeDocument:
        def __init__(self):
            self.value = "Not Submitted"

        def get(self, fieldname):
            return self.value if fieldname == "custom_zatca_full_response" else None

        def set(self, fieldname, value):
            self.value = value

    doc = FakeDocument()
    zatca_response.normalize_zatca_full_response(doc)

    assert doc.value == "Not Submitted"


def test_set_zatca_full_response_normalizes_before_db_set():
    class FakeDocument:
        def __init__(self):
            self.calls = []

        def db_set(self, fieldname, value, **kwargs):
            self.calls.append((fieldname, value, kwargs))

    raw_response = '{"clearanceStatus":"CLEARED"}'
    doc = FakeDocument()

    returned = zatca_response.set_zatca_full_response(
        doc, f"Status Code: 200; ZATCA Response: {raw_response}", commit=True
    )

    assert returned == raw_response
    assert doc.calls == [
        ("custom_zatca_full_response", raw_response, {"commit": True})
    ]

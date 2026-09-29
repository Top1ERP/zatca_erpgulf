import unittest
from types import SimpleNamespace
from unittest.mock import patch

from zatca_erpgulf.zatca_erpgulf import createxml


class TestBuyerAddressValidation(unittest.TestCase):
    @staticmethod
    def _customer_address(country, pincode="", **values):
        return SimpleNamespace(
            country=country,
            address_line1=values.get("address_line1", "Main Street"),
            custom_building_number=values.get("custom_building_number", "1234"),
            city=values.get("city", "Dubai"),
            pincode=pincode,
            address_line2=values.get("address_line2", "Business District"),
        )

    def test_country_mapping_supports_erpnext_15_and_16_values(self):
        invoice = SimpleNamespace()
        customer = SimpleNamespace()

        self.assertEqual(
            createxml._get_customer_country_code(
                invoice, customer, self._customer_address("Saudi Arabia", "12345")
            ),
            "SA",
        )
        self.assertEqual(
            createxml._get_customer_country_code(
                invoice, customer, self._customer_address("SA", "12345")
            ),
            "SA",
        )
        self.assertEqual(
            createxml._get_customer_country_code(
                invoice, customer, self._customer_address("AE")
            ),
            "AE",
        )

    def test_foreign_b2b_does_not_require_postal_code(self):
        customer = SimpleNamespace(custom_b2c=0)
        address = self._customer_address("AE")

        with patch.object(createxml, "_", side_effect=lambda value: value), patch.object(
            createxml.frappe, "throw"
        ) as throw:
            createxml._validate_customer_b2b_address_for_zatca(customer, address, "AE")

        throw.assert_not_called()

    def test_saudi_b2b_still_requires_postal_code(self):
        customer = SimpleNamespace(custom_b2c=0)
        address = self._customer_address("Saudi Arabia")

        with patch.object(createxml, "_", side_effect=lambda value: value), patch.object(
            createxml.frappe, "throw"
        ) as throw:
            createxml._validate_customer_b2b_address_for_zatca(customer, address, "SA")

        throw.assert_called_once()
        self.assertIn("Buyer postal code is mandatory", throw.call_args.args[0])


if __name__ == "__main__":
    unittest.main()

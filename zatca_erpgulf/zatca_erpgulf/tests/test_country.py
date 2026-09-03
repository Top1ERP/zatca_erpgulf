import unittest

from zatca_erpgulf.zatca_erpgulf.country import is_saudi_country, normalize_country_code


class TestCountryNormalization(unittest.TestCase):
    def test_saudi_aliases(self):
        for value in ("SA", "sa", "S.A.", "Saudi Arabia", "Kingdom of Saudi Arabia"):
            self.assertEqual(normalize_country_code(value), "SA")
            self.assertTrue(is_saudi_country(value))

    def test_known_non_saudi_country(self):
        self.assertEqual(normalize_country_code("United Arab Emirates"), "AE")
        self.assertFalse(is_saudi_country("United Arab Emirates"))

    def test_empty_value_is_not_saudi(self):
        self.assertEqual(normalize_country_code(None), "")
        self.assertFalse(is_saudi_country(None))


if __name__ == "__main__":
    unittest.main()

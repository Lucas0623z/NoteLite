#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signature coverage regressions for the JavaCPP JNI audit."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("jni_audit", Path(__file__).with_name("verify-jni-bindings.py"))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class BindingAuditTests(unittest.TestCase):
    owner = "org/bytedeco/tesseract/TessBaseAPI"
    prefix = "Java_org_bytedeco_tesseract_TessBaseAPI_Init"
    declarations = [(owner, "Init", "(I)I"), (owner, "Init", "(Ljava/lang/String;)I")]

    def test_all_overloads_have_distinct_bindings(self):
        symbols = {self.prefix + "__I", self.prefix + "__Ljava_lang_String_2"}
        self.assertTrue(audit.audit_declarations(self.declarations, symbols)["passed"])

    def test_missing_overload_fails_while_sibling_remains(self):
        result = audit.audit_declarations(self.declarations, {self.prefix + "__I"})
        self.assertFalse(result["passed"])
        self.assertEqual(["(Ljava/lang/String;)I"], [entry["descriptor"] for entry in result["missing"]])

    def test_short_alias_cannot_hide_missing_overload(self):
        result = audit.audit_declarations(self.declarations, {self.prefix, self.prefix + "__I"})
        self.assertFalse(result["passed"])
        self.assertEqual(1, len(result["missing"]))
        self.assertTrue(result["missing"][0]["requiresLongName"])

    def test_single_declaration_accepts_short_or_long_name(self):
        for name in (self.prefix, self.prefix + "__I"):
            with self.subTest(symbol=name):
                self.assertTrue(audit.audit_declarations(self.declarations[:1], {name})["passed"])

    def test_jni_array_underscore_and_unicode_mangling(self):
        self.assertEqual("_3Lpkg_Name_1with_1underscores_2_0fedc", audit.mangle("[Lpkg/Name_with_underscores;\ufedc"))

    def test_empty_audit_rejected(self):
        with self.assertRaises(ValueError):
            audit.audit_declarations([], set())


if __name__ == "__main__":
    unittest.main()

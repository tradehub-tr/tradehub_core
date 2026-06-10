"""ECA condition_compiler testleri — builder JSON -> güvenli Python ifadesi.

Motor (dispatcher._evaluate_condition_v2) DEĞİŞMEZ; bu testler sadece
compiler'ın safe_eval-uyumlu ifade ürettiğini ve güvenlik whitelist'inin
çalıştığını doğrular.

Üretilen ifade `doc` dict context'inde çalışır; bu yüzden alan erişimi
`doc.get('field')` biçimindedir (plain dict üzerinde `doc.base_price`
attribute erişimi PATLAR — bkz. dispatcher context'i). Testler hem ÜRETİLEN
string'i hem de bu string'in `eval` ile DOĞRU sonuç verdiğini kontrol eder.

Gerçek koşum:
    bench --site dev.localhost run-tests \
        --module tradehub_core.eca.tests.test_condition_compiler
"""

import unittest

from tradehub_core.eca.condition_compiler import (
	CompileError,
	compile_condition,
	describe_condition,
)


def _eval(expr: str, doc: dict):
	"""compile_condition çıktısını dispatcher context'ine benzer şekilde değerlendir."""
	return eval(expr, {"__builtins__": {}}, {"doc": doc, "bool": bool})


class TestSimpleLeaf(unittest.TestCase):
	"""(a) Basit tek koşul: base_price gt 1000."""

	def test_gt_expression(self):
		builder = {"match": "all", "conditions": [{"field": "base_price", "op": "gt", "value": 1000}]}
		expr = compile_condition(builder)
		self.assertEqual(expr, "(doc.get('base_price') > 1000)")

	def test_gt_evaluates_true(self):
		expr = compile_condition(
			{"match": "all", "conditions": [{"field": "base_price", "op": "gt", "value": 1000}]}
		)
		self.assertTrue(_eval(expr, {"base_price": 1500}))
		self.assertFalse(_eval(expr, {"base_price": 500}))

	def test_all_comparison_ops(self):
		cases = {"gt": ">", "lt": "<", "gte": ">=", "lte": "<=", "eq": "==", "neq": "!="}
		for op, sym in cases.items():
			expr = compile_condition(
				{"match": "all", "conditions": [{"field": "base_price", "op": op, "value": 100}]}
			)
			self.assertEqual(expr, f"(doc.get('base_price') {sym} 100)")


class TestMatchAll(unittest.TestCase):
	"""(b) match=all iki koşul -> 'and' + parantez."""

	def test_two_conditions_and(self):
		builder = {
			"match": "all",
			"conditions": [
				{"field": "base_price", "op": "gt", "value": 1000},
				{"field": "brand", "op": "eq", "value": "Petkim"},
			],
		}
		expr = compile_condition(builder)
		self.assertEqual(
			expr,
			"((doc.get('base_price') > 1000) and (doc.get('brand') == 'Petkim'))",
		)

	def test_all_requires_both_true(self):
		expr = compile_condition(
			{
				"match": "all",
				"conditions": [
					{"field": "base_price", "op": "gt", "value": 1000},
					{"field": "brand", "op": "eq", "value": "Petkim"},
				],
			}
		)
		self.assertTrue(_eval(expr, {"base_price": 1500, "brand": "Petkim"}))
		self.assertFalse(_eval(expr, {"base_price": 1500, "brand": "Other"}))
		self.assertFalse(_eval(expr, {"base_price": 500, "brand": "Petkim"}))


class TestMatchAny(unittest.TestCase):
	"""(c) match=any -> 'or'."""

	def test_two_conditions_or(self):
		builder = {
			"match": "any",
			"conditions": [
				{"field": "base_price", "op": "gt", "value": 1000},
				{"field": "brand", "op": "eq", "value": "Petkim"},
			],
		}
		expr = compile_condition(builder)
		self.assertEqual(
			expr,
			"((doc.get('base_price') > 1000) or (doc.get('brand') == 'Petkim'))",
		)

	def test_any_requires_one_true(self):
		expr = compile_condition(
			{
				"match": "any",
				"conditions": [
					{"field": "base_price", "op": "gt", "value": 1000},
					{"field": "brand", "op": "eq", "value": "Petkim"},
				],
			}
		)
		self.assertTrue(_eval(expr, {"base_price": 500, "brand": "Petkim"}))
		self.assertTrue(_eval(expr, {"base_price": 1500, "brand": "Other"}))
		self.assertFalse(_eval(expr, {"base_price": 500, "brand": "Other"}))


class TestStringQuoting(unittest.TestCase):
	"""(d) string value güvenli quote — injection denemesi literal kalır."""

	def test_plain_string_quoted(self):
		expr = compile_condition(
			{"match": "all", "conditions": [{"field": "brand", "op": "eq", "value": "Petkim"}]}
		)
		self.assertEqual(expr, "(doc.get('brand') == 'Petkim')")

	def test_injection_value_is_safely_serialized(self):
		# repr() ile kaçışlandığı için tırnak kapatıp kod enjekte edilemez.
		evil = "x') or __import__('os').system('rm -rf /') or doc.get('y"
		expr = compile_condition(
			{"match": "all", "conditions": [{"field": "brand", "op": "eq", "value": evil}]}
		)
		# Tek bir == karşılaştırması olmalı; ek 'or' / '__import__' kod olarak girmemeli.
		self.assertEqual(expr.count("=="), 1)
		self.assertNotIn("__import__(", expr.replace(repr(evil), ""))
		# Eval edilince yalnızca string eşitliği döner, kod çalışmaz.
		self.assertFalse(_eval(expr, {"brand": "Petkim"}))

	def test_string_with_quote_char(self):
		expr = compile_condition(
			{"match": "all", "conditions": [{"field": "brand", "op": "eq", "value": "O'Brien"}]}
		)
		# repr kaçışı doğru olmalı — eval round-trip eşitliği korunur.
		self.assertTrue(_eval(expr, {"brand": "O'Brien"}))


class TestFieldWhitelist(unittest.TestCase):
	"""(e) whitelist DIŞI field -> CompileError (güvenlik)."""

	def test_unknown_field_rejected(self):
		builder = {
			"match": "all",
			"conditions": [{"field": "admin_secret_flag", "op": "eq", "value": 1}],
		}
		with self.assertRaises(CompileError):
			compile_condition(builder)

	def test_empty_field_rejected(self):
		with self.assertRaises(CompileError):
			compile_condition({"match": "all", "conditions": [{"field": "", "op": "eq", "value": 1}]})

	def test_dunder_field_rejected(self):
		# __class__ gibi attribute sızdırma denemesi whitelist dışı kalır.
		with self.assertRaises(CompileError):
			compile_condition(
				{"match": "all", "conditions": [{"field": "__class__", "op": "eq", "value": 1}]}
			)

	def test_unknown_doctype_rejected(self):
		with self.assertRaises(CompileError):
			compile_condition(
				{"match": "all", "conditions": [{"field": "base_price", "op": "gt", "value": 1}]},
				doctype="GheReklendi",
			)

	def test_unknown_operator_rejected(self):
		with self.assertRaises(CompileError):
			compile_condition(
				{"match": "all", "conditions": [{"field": "base_price", "op": "regex", "value": ".*"}]}
			)


class TestSpecialOperators(unittest.TestCase):
	"""Üyelik / truthy operatörleri (in_list, contains, is_set, is_empty)."""

	def test_in_list(self):
		expr = compile_condition(
			{
				"match": "all",
				"conditions": [{"field": "brand", "op": "in_list", "value": ["Petkim", "Tüpraş"]}],
			}
		)
		self.assertTrue(_eval(expr, {"brand": "Petkim"}))
		self.assertFalse(_eval(expr, {"brand": "Other"}))

	def test_is_set_and_is_empty(self):
		set_expr = compile_condition({"match": "all", "conditions": [{"field": "barcode", "op": "is_set"}]})
		empty_expr = compile_condition(
			{"match": "all", "conditions": [{"field": "barcode", "op": "is_empty"}]}
		)
		self.assertTrue(_eval(set_expr, {"barcode": "123"}))
		self.assertFalse(_eval(set_expr, {"barcode": ""}))
		self.assertTrue(_eval(empty_expr, {"barcode": ""}))


class TestNestedGroups(unittest.TestCase):
	"""İç içe grup: dış all + iç any."""

	def test_nested_group_parenthesized(self):
		builder = {
			"match": "all",
			"conditions": [{"field": "base_price", "op": "gt", "value": 1000}],
			"groups": [
				{
					"match": "any",
					"conditions": [
						{"field": "brand", "op": "eq", "value": "Petkim"},
						{"field": "brand", "op": "eq", "value": "Tüpraş"},
					],
				}
			],
		}
		expr = compile_condition(builder)
		self.assertTrue(_eval(expr, {"base_price": 1500, "brand": "Petkim"}))
		self.assertFalse(_eval(expr, {"base_price": 1500, "brand": "Other"}))
		self.assertFalse(_eval(expr, {"base_price": 500, "brand": "Petkim"}))


class TestDescribeCondition(unittest.TestCase):
	"""(f) describe_condition düz Türkçe cümle üretir."""

	def test_simple_sentence(self):
		sentence = describe_condition(
			{"match": "all", "conditions": [{"field": "base_price", "op": "gt", "value": 1000}]}
		)
		self.assertIn("base_price", sentence)
		self.assertIn("büyüktür", sentence)
		self.assertIn("1000", sentence)

	def test_all_uses_ve(self):
		sentence = describe_condition(
			{
				"match": "all",
				"conditions": [
					{"field": "base_price", "op": "gt", "value": 1000},
					{"field": "brand", "op": "eq", "value": "Petkim"},
				],
			}
		)
		self.assertIn(" VE ", sentence)
		self.assertIn("TÜMÜ", sentence)

	def test_any_uses_veya(self):
		sentence = describe_condition(
			{
				"match": "any",
				"conditions": [
					{"field": "base_price", "op": "gt", "value": 1000},
					{"field": "brand", "op": "eq", "value": "Petkim"},
				],
			}
		)
		self.assertIn(" VEYA ", sentence)
		self.assertIn("HERHANGİ", sentence)

	def test_empty_builder_returns_empty(self):
		self.assertEqual(describe_condition({}), "")
		self.assertEqual(describe_condition({"match": "all", "conditions": []}), "")


class TestCompileErrors(unittest.TestCase):
	"""Yapısal hatalar — boş grup, yanlış tip, geçersiz match."""

	def test_non_dict_builder(self):
		with self.assertRaises(CompileError):
			compile_condition("not a dict")

	def test_empty_group_rejected(self):
		with self.assertRaises(CompileError):
			compile_condition({"match": "all", "conditions": []})

	def test_invalid_match_rejected(self):
		with self.assertRaises(CompileError):
			compile_condition(
				{"match": "maybe", "conditions": [{"field": "base_price", "op": "gt", "value": 1}]}
			)

	def test_unsupported_value_type_rejected(self):
		with self.assertRaises(CompileError):
			compile_condition(
				{"match": "all", "conditions": [{"field": "base_price", "op": "eq", "value": {"a": 1}}]}
			)


if __name__ == "__main__":
	unittest.main()

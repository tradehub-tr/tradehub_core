"""
Numeric girdi validator'ları — defansif tip cast'i.

Daha önceki kodda `int(quantity)` veya `float(rating)` gibi cast'ler kullanıcının
gönderdiği `abc` / `NaN` / `Infinity` / boş string için Python'un native ValueError'ını
yukarı bırakıyor → HTTP 500 + stack trace sızıntısı + monitoring kirliliği (HATA 18).

Bu modül `safe_int` ve `safe_float` ile her cast hatasını kullanıcı dostu Türkçe
`frappe.throw(ValidationError)` mesajına çevirir.

Modül `frappe` import eder; runtime dışında (unit test) çağrılırsa import patlamaz
ama `_throw` çağrısı no-op olur (değer döndürmez, exception fırlatır).
"""

import math

import frappe
from frappe import _


def safe_int(value, label="Değer", default=None):
	"""
	Değeri `int`'e çevirir. Başarısız olursa kullanıcı dostu mesajla `frappe.throw`.

	- `value` None ve `default` verilmişse default döner.
	- Bool kabul EDILMEZ (Python `int(True)==1` davranışı yanıltıcı olduğundan).
	- `label` hata mesajına Türkçe alan adı koyar.
	"""
	if value is None or value == "":
		if default is not None:
			return default
		frappe.throw(_("{0} alanı boş bırakılamaz").format(label))
	if isinstance(value, bool):
		frappe.throw(_("{0} geçerli bir sayı olmalıdır").format(label))
	try:
		return int(value)
	except (ValueError, TypeError):
		frappe.throw(_("{0} geçerli bir sayı olmalıdır").format(label))


def safe_float(value, label="Değer", default=None, allow_negative=True):
	"""
	Değeri `float`'a çevirir. NaN ve Infinity reddedilir.

	- `allow_negative=False` ise <0 için throw.
	- Cast/NaN/Inf/None+default-yok → throw.
	"""
	if value is None or value == "":
		if default is not None:
			return default
		frappe.throw(_("{0} alanı boş bırakılamaz").format(label))
	if isinstance(value, bool):
		frappe.throw(_("{0} geçerli bir sayı olmalıdır").format(label))
	try:
		x = float(value)
	except (ValueError, TypeError):
		frappe.throw(_("{0} geçerli bir sayı olmalıdır").format(label))
	if math.isnan(x) or math.isinf(x):
		frappe.throw(_("{0} geçerli bir sayı olmalıdır").format(label))
	if not allow_negative and x < 0:
		frappe.throw(_("{0} negatif olamaz").format(label))
	return x

"""Explicit, versioned field rounding; no ORM, settings lookup or fiscal policy.

The caller supplies the effective precision and method. This is a compatibility
primitive, not a complete totals/tax calculation or evidence of source authority.
Only bounded numeric inputs are accepted; invalid inputs never silently become
zero. NULL follows flt's numeric conversion to 0.0. Source snapshots are untouched.

The five private kernels adapt frappe/utils/data.py from Frappe 15 commit
7b430f5eec8c0537f2f0cde9d30e175ae9068647 and 16 commit
e8d41dd0061a32ee781caefe5d0b0d2bb7c15362. The unchanged shared legacy kernel is
stored once; other algorithm differences are deliberately version-specific.

The MIT License

Copyright (c) 2016-2021 Frappe Technologies Pvt. Ltd. <developers@frappe.io>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

"""

from decimal import MAX_PREC, ROUND_HALF_UP, Decimal, localcontext
import math

from .calculation_rounding import METHODS
from .financial_source_observation import _scalar


class FieldRoundingError(ValueError):
    """Static English diagnostics, without protected amounts/settings."""


def round_field_value(value, *, precision, method, erp_major):
    """Match numeric flt(value, precision, method) in the supported domain.

    This explicit API does not resolve a missing method, parse user strings,
    mutate a document, or claim a rounded XML amount. Precision is None or a
    built-in integer 0..64. Numeric source scalars retain the native bounds;
    finite float getters also allow the 1e64 boundary produced by converting
    a valid 64-digit Decimal. Results preserve upstream type and signed zero.
    """
    try:
        if type(erp_major) is not int or erp_major not in (15, 16):
            raise ValueError
        if precision is not None and (type(precision) is not int or not 0 <= precision <= 64):
            raise ValueError
        if type(method) is not str or method not in METHODS:
            raise ValueError
        if value is not None:
            if type(value) is float:
                if not math.isfinite(value) or abs(value) > 1e64:
                    raise ValueError
            elif type(value) in (int, Decimal):
                _scalar(value)
            else:
                raise ValueError
        if value is None:
            return 0.0
        number = float(value)
        if precision is None:
            return number
        if method == "Banker's Rounding (legacy)":
            result = _legacy(number, precision)
        elif method == "Banker's Rounding":
            result = (_bankers15 if erp_major == 15 else _bankers16)(number, precision)
        else:
            result = (_commercial15 if erp_major == 15 else _commercial16)(number, precision)
        if not math.isfinite(result):
            raise ValueError
        return result
    except Exception:
        invalid = True
    if invalid:
        raise FieldRoundingError("calculation_field_rounding")


def _legacy(num, precision):
    multiplier = 10 ** precision
    num = round(num * multiplier if precision else num, 8)
    floor_num = math.floor(num)
    decimal_part = num - floor_num
    if not precision and decimal_part == 0.5:
        num = floor_num if floor_num % 2 == 0 else floor_num + 1
    elif decimal_part == 0.5:
        num = floor_num + 1
    else:
        num = round(num)
    return num / multiplier if precision else num


def _bankers15(num, precision):
    multiplier = 10 ** precision
    num = round(num * multiplier, 12)
    if num == 0:
        return 0.0
    floor_num = math.floor(num)
    decimal_part = num - floor_num
    epsilon = 2.0 ** (math.log(abs(num), 2) - 52.0)
    if abs(decimal_part - 0.5) < epsilon:
        num = floor_num if floor_num % 2 == 0 else floor_num + 1
    else:
        num = round(num)
    return num / multiplier


def _bankers16(num, precision):
    if num == 0:
        return 0.0
    sign = -1 if num < 0 else 1
    multiplier = 10 ** precision
    num = round(abs(num) * multiplier, 12)
    if num == 0:
        return 0.0
    floor_num = math.floor(num)
    decimal_part = num - floor_num
    epsilon = 2.0 ** (math.log(num, 2) - 52.0)
    if epsilon < 0.5 and abs(decimal_part - 0.5) < epsilon:
        num = floor_num if floor_num % 2 == 0 else floor_num + 1
    else:
        num = round(num)
    return sign * num / multiplier


def _commercial15(num, precision):
    if num == 0:
        return 0.0
    epsilon = 2.0 ** (math.log(abs(num), 2) - 52.0)
    return round(num + math.copysign(epsilon, num), precision)


def _commercial16(num, precision):
    if num == 0:
        return 0.0
    epsilon = math.ulp(abs(num))
    rounding_step = 10.0 ** (-precision)
    if math.isfinite(num) and epsilon >= rounding_step / 4:
        with localcontext() as ctx:
            ctx.prec = MAX_PREC
            ctx.rounding = ROUND_HALF_UP
            return float(Decimal(num).quantize(Decimal(1).scaleb(-precision)))
    return round(num + math.copysign(epsilon, num), precision)

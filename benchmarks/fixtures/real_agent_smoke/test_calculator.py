from calculator import safe_divide


def test_safe_divide_exact_values():
    assert safe_divide(8, 2) == 4


def test_safe_divide_zero_returns_none():
    assert safe_divide(8, 0) is None

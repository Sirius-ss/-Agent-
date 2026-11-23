from datetime import date
import pytest
from ecommerce_service.appliances import warranty

@pytest.mark.parametrize("months,signed,last,first",[
    (12,date(2025,6,15),date(2026,6,14),date(2026,6,15)),
    (24,date(2024,6,15),date(2026,6,14),date(2026,6,15)),
    (12,date(2024,2,29),date(2025,2,27),date(2025,2,28)),
])
def test_anniversary(months,signed,last,first):
    assert warranty(signed,months,last)["status"]=="IN_WARRANTY"
    assert warranty(signed,months,first)["status"]=="EXPIRED"

def test_missing():
    assert warranty(None,12)["notice"]=="签收日期缺失，保修资格待人工核验"

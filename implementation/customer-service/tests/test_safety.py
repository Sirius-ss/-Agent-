import pytest
from atguigu.app.services.scenes import smoke

@pytest.mark.parametrize("query,expected",[("空调 E3 而且正在冒烟",True),("如果正在冒烟怎么办",False),
    ("没有正在冒烟",False),("不是洗衣机，是空调正在冒烟",True)])
def test_smoke(query,expected):
    assert smoke(query)==expected

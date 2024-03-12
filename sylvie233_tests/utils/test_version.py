import django
from django.utils.version import get_main_version



def test_get_main_version():
    print(get_main_version(django.VERSION))
    assert get_main_version((4, 1, 1, "beta", 1)) == "4.1.1", "获取4.1.1版本失败"
    assert get_main_version((4, 1, 0, "beta", 0)) == "4.1", "获取4.1失败"
    assert get_main_version(django.VERSION) == "5.1", "获取5.1版本失败"
    print("django.utils.version.get_main_version() 测试成功！")

def test_get_version():
    print(django.utils.version.get_version())

if __name__ == '__main__':
    test_get_main_version()
    test_get_version()

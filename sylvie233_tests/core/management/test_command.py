import os.path

from django.core.management import find_commands

def test_find_command():
    print({name: "django.core" for name in find_commands(os.path.dirname(__file__))})

def test_print__path__():
    print(__file__)


if __name__ == '__main__':
    # test_print__path__()
    test_find_command()
    pass


import pytest

def test_pytest():
    assert True

@pytest.mark.django_db
def test_db():
    assert True

from aia import __version__


def test_aia_package_imports() -> None:
    assert __version__ == "0.1.14"

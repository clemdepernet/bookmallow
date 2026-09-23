from bookmallow import __version__


def test_version_is_semver():
    assert __version__.count(".") == 2

def test_import_app_package():
    import app
    assert app.__name__ == "app"

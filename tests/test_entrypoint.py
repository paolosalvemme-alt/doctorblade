def test_application_entrypoint_imports() -> None:
    import main

    assert callable(main.main)

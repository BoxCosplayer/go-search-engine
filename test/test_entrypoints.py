import importlib
import runpy


def test_app_module_exposes_flask_app():
    mod = importlib.import_module("app")
    backend_app = importlib.import_module("backend.app.main").app
    assert mod.app is backend_app


def test_app_main_executes_backend(monkeypatch):
    calls = []
    real_run_module = runpy.run_module
    orig_run_module = real_run_module

    def fake_run_module(name, run_name=None):
        if name == "backend.app.main":
            calls.append((name, run_name))
            return {}
        return real_run_module(name, run_name=run_name)

    monkeypatch.setattr(runpy, "run_module", fake_run_module)
    real_run_module = lambda name, run_name=None: {"name": name, "run_name": run_name}
    fake_run_module("dummy")
    real_run_module = orig_run_module
    real_run_module("app", run_name="__main__")
    assert calls == [("backend.app.main", "__main__")]


def test_backend_dunder_main_executes_app(monkeypatch):
    calls = []
    real_run_module = runpy.run_module
    orig_run_module = real_run_module

    def fake_run_module(name, run_name=None):
        if name == "backend.app.main":
            calls.append((name, run_name))
            return {}
        return real_run_module(name, run_name=run_name)

    monkeypatch.setattr(runpy, "run_module", fake_run_module)
    real_run_module = lambda name, run_name=None: {"name": name, "run_name": run_name}
    fake_run_module("dummy")
    real_run_module = orig_run_module
    real_run_module("backend.__main__", run_name="__main__")
    assert calls == [("backend.app.main", "__main__")]


def test_backend_wsgi_application_alias():
    wsgi = importlib.import_module("backend.wsgi")
    main_app = importlib.import_module("backend.app.main").app
    assert wsgi.application is main_app
    assert wsgi.app is main_app


def test_backend_app_package_exports_app():
    app_pkg = importlib.import_module("backend.app")
    assert "app" in app_pkg.__all__
    assert app_pkg.app is importlib.import_module("backend.app.main").app

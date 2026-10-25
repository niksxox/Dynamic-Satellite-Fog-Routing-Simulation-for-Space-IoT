from streamlit.testing.v1 import AppTest


def test_dashboard_overview_starts_without_database_or_runs():
    app = AppTest.from_file("app.py", default_timeout=30).run()
    assert not app.exception
    assert any("Mission overview" in markdown.value for markdown in app.markdown)
    assert any("No simulation has been run" in element.value for element in app.info)


def test_dashboard_lab_executes_real_simulation():
    app = AppTest.from_file("app.py", default_timeout=30).run()
    workspace = next(widget for widget in app.radio if widget.label == "Workspace")
    workspace.set_value("Simulation Lab").run()
    next(button for button in app.button if button.label == "Run simulation").click().run()
    assert not app.exception
    assert any("completed" in element.value for element in app.success)
    assert "dashboard_runs" in app.session_state


def test_dashboard_interactive_pages_handle_real_session_result():
    app = AppTest.from_file("app.py", default_timeout=30).run()
    workspace = next(widget for widget in app.radio if widget.label == "Workspace")
    workspace.set_value("Simulation Lab").run()
    next(button for button in app.button if button.label == "Run simulation").click().run()
    for page in ("Network Explorer", "Failure Replay", "Performance Analytics", "Experiment History"):
        workspace = next(widget for widget in app.radio if widget.label == "Workspace")
        workspace.set_value(page).run()
        assert not app.exception, f"page {page} failed: {app.exception}"

from otai import formatting


def test_render_table_includes_header_and_all_rows():
    rows = [
        {"release": "25.12", "latest": False, "cached": False},
        {"release": "26.06", "latest": True, "cached": False},
    ]
    output = formatting.render_table(rows)

    lines = output.splitlines()
    assert "release" in lines[0]
    assert "latest" in lines[0]
    assert "cached" in lines[0]
    assert any("25.12" in line for line in lines)
    assert any("26.06" in line for line in lines)


def test_render_table_renders_booleans_as_yes_no():
    rows = [{"release": "26.06", "latest": True, "cached": False}]
    output = formatting.render_table(rows)
    assert "yes" in output
    assert "no" in output


def test_render_table_empty_rows_returns_placeholder_text():
    assert formatting.render_table([]) == "(no rows)"

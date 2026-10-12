"""Render style lookup for model pieces (export_models.Styles)."""
import export_models


def test_missing_style_file_falls_back_to_the_default_and_is_reported(extracted):
    # CD3DRenderStyle::SetDefaults stands in when the style can't load; the export lists the path.
    styles = export_models.Styles(extracted)
    c = styles.compile("rs/no_such_style.ltb")
    assert c["name"] == "<default>"
    styles.compile("rs/no_such_style.ltb")
    styles.compile("")
    assert styles.missing == {"rs/no_such_style.ltb"}

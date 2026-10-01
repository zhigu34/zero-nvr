from app.core.coerce import as_text


def test_lenient_text_coercion_preserves_third_party_values() -> None:
    assert as_text(None) is None
    assert as_text("  ") is None
    assert as_text("  camera-1  ") == "camera-1"
    assert as_text(True) == "True"

    class ZeepValue:
        def __str__(self) -> str:
            return "  stream token  "

    assert as_text(ZeepValue()) == "stream token"

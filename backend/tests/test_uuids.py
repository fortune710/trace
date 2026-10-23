from auth.uuids import uuid7


def test_uuid7_generates_a_version_seven_rfc_variant_identifier() -> None:
    identifier = uuid7()

    assert identifier.version == 7
    assert identifier.variant == "specified in RFC 4122"

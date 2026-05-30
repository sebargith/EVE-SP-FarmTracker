from urllib.parse import parse_qs, urlparse

from src.integrations.sso import (
    SsoConfig,
    build_authorization_url,
    character_id_from_claims,
    fake_jwt_for_tests,
    generate_pkce_pair,
    scopes_from_claims,
    decode_unverified_claims,
)
from src.data.database import connect, initialize_database
from src.data.repositories import (
    add_account,
    add_account_group,
    create_sso_auth_state,
    delete_sso_auth_state,
    get_sso_auth_state,
)


def test_pkce_challenge_is_url_safe() -> None:
    verifier, challenge = generate_pkce_pair()

    assert verifier
    assert challenge
    assert "=" not in challenge


def test_authorization_url_contains_expected_scope_and_pkce_fields() -> None:
    config = SsoConfig(
        client_id="client-123",
        callback_url="http://localhost:8766",
        scopes=("esi-skills.read_skills.v1", "esi-skills.read_skillqueue.v1"),
    )

    url = build_authorization_url(
        config,
        state="state-123",
        code_challenge="challenge-123",
    )
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert parsed.netloc == "login.eveonline.com"
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["client-123"]
    assert params["redirect_uri"] == ["http://localhost:8766"]
    assert params["scope"] == ["esi-skills.read_skills.v1 esi-skills.read_skillqueue.v1"]
    assert params["code_challenge"] == ["challenge-123"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["state"] == ["state-123"]


def test_decode_claim_helpers() -> None:
    token = fake_jwt_for_tests(
        {
            "sub": "CHARACTER:EVE:123456",
            "name": "Farm Pilot",
            "scp": ["esi-skills.read_skills.v1"],
        }
    )

    claims = decode_unverified_claims(token)

    assert character_id_from_claims(claims) == 123456
    assert scopes_from_claims(claims) == ("esi-skills.read_skills.v1",)


def test_sso_auth_state_survives_outside_streamlit_session() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    group_id = add_account_group(connection, name="Farm Group")
    account_id = add_account(connection, group_id=group_id, name="Farm Account")

    create_sso_auth_state(
        connection,
        state="state-123",
        account_id=account_id,
        code_verifier="verifier-123",
    )

    row = get_sso_auth_state(connection, state="state-123")

    assert row is not None
    assert row["account_id"] == account_id
    assert row["code_verifier"] == "verifier-123"

    delete_sso_auth_state(connection, state="state-123")
    assert get_sso_auth_state(connection, state="state-123") is None

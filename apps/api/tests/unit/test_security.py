"""Unit tests for password hashing and token generation.

No database or Redis needed — pure functions."""

from app.core.security import generate_token, hash_password, hash_token, verify_password


def test_hash_password_produces_different_hash_each_time() -> None:
    """Argon2id salts each hash, so hashing the same password twice
    must NOT produce identical output — otherwise two users with the
    same password would be trivially detectable from the hash alone."""
    h1 = hash_password("correct horse battery staple")
    h2 = hash_password("correct horse battery staple")
    assert h1 != h2


def test_verify_password_succeeds_for_correct_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_fails_for_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_hash_password_never_returns_the_plaintext() -> None:
    plaintext = "correct horse battery staple"
    hashed = hash_password(plaintext)
    assert plaintext not in hashed


def test_generate_token_is_sufficiently_random_and_unique() -> None:
    tokens = {generate_token() for _ in range(1000)}
    assert len(tokens) == 1000  # no collisions in 1000 draws
    assert all(len(t) >= 32 for t in tokens)


def test_hash_token_is_deterministic_but_not_reversible_in_practice() -> None:
    token = generate_token()
    assert hash_token(token) == hash_token(token)  # same input -> same hash (lookup key)
    assert hash_token(token) != token  # never store/compare the raw token itself

import re

import pytest

import auth as A
import ledger

SECRET = "x" * 40
T0 = 1_000_000.0


class FakeSender:
    def __init__(self):
        self.sent = []

    def send(self, phone, text):
        self.sent.append((phone, text))

    @property
    def code(self):
        return re.search(r"\b(\d{6})\b", self.sent[-1][1]).group(1)


@pytest.fixture
def db():
    conn = ledger.connect(":memory:")
    A.init_schema(conn)
    return conn


PHONE = "+998 90 123 45 67"


# ---------------------------------------------------------------- phone

@pytest.mark.parametrize("raw", ["+998901234567", "998901234567", "90 123 45 67",
                                 "+998 (90) 123-45-67", "901234567"])
def test_phone_formats_normalize(raw):
    assert A.normalize_phone(raw) == "+998901234567"


@pytest.mark.parametrize("raw", ["", "12345", "+79991234567", "+9989012345678", "abc", None])
def test_bad_phones(raw):
    with pytest.raises(A.InvalidPhone):
        A.normalize_phone(raw)


# ------------------------------------------------------------- sms code

def test_login_flow_and_same_user_next_time(db):
    s = FakeSender()
    A.request_code(db, PHONE, SECRET, s, now=T0)
    assert s.sent[0][0] == "+998901234567"
    uid, is_new = A.verify_code(db, "901234567", s.code, SECRET, now=T0 + 10)
    assert is_new is True and len(uid) == 32
    A.request_code(db, PHONE, SECRET, s, now=T0 + 100)
    uid2, is_new2 = A.verify_code(db, PHONE, s.code, SECRET, now=T0 + 110)
    assert (uid2, is_new2) == (uid, False)


def test_code_is_not_stored_in_plain_text(db):
    s = FakeSender()
    A.request_code(db, PHONE, SECRET, s, now=T0)
    row = dict(db.execute("SELECT * FROM otp").fetchone())
    assert s.code not in "".join(str(v) for v in row.values())


def test_code_works_once(db):
    s = FakeSender()
    A.request_code(db, PHONE, SECRET, s, now=T0)
    A.verify_code(db, PHONE, s.code, SECRET, now=T0 + 1)
    with pytest.raises(A.InvalidCode):
        A.verify_code(db, PHONE, s.code, SECRET, now=T0 + 2)


def test_code_expires(db):
    s = FakeSender()
    A.request_code(db, PHONE, SECRET, s, now=T0)
    with pytest.raises(A.InvalidCode):
        A.verify_code(db, PHONE, s.code, SECRET, now=T0 + A.CODE_TTL + 1)


def test_wrong_code_then_right_code_ok(db):
    s = FakeSender()
    A.request_code(db, PHONE, SECRET, s, now=T0)
    wrong = "000000" if s.code != "000000" else "111111"
    with pytest.raises(A.InvalidCode):
        A.verify_code(db, PHONE, wrong, SECRET, now=T0 + 1)
    A.verify_code(db, PHONE, s.code, SECRET, now=T0 + 2)


def test_five_wrong_attempts_burn_the_code(db):
    s = FakeSender()
    A.request_code(db, PHONE, SECRET, s, now=T0)
    wrong = "000000" if s.code != "000000" else "111111"
    for _ in range(A.MAX_ATTEMPTS):
        with pytest.raises(A.InvalidCode):
            A.verify_code(db, PHONE, wrong, SECRET, now=T0 + 1)
    with pytest.raises(A.InvalidCode):  # even the correct code is dead now
        A.verify_code(db, PHONE, s.code, SECRET, now=T0 + 2)


def test_new_code_replaces_old_one(db):
    s = FakeSender()
    A.request_code(db, PHONE, SECRET, s, now=T0)
    old = s.code
    A.request_code(db, PHONE, SECRET, s, now=T0 + 61)
    new = s.code
    if old != new:  # (1 in a million they are equal)
        with pytest.raises(A.InvalidCode):
            A.verify_code(db, PHONE, old, SECRET, now=T0 + 62)
    A.verify_code(db, PHONE, new, SECRET, now=T0 + 63)


def test_verify_without_request(db):
    with pytest.raises(A.InvalidCode):
        A.verify_code(db, PHONE, "123456", SECRET, now=T0)


def test_resend_cooldown(db):
    s = FakeSender()
    A.request_code(db, PHONE, SECRET, s, now=T0)
    with pytest.raises(A.RateLimited) as e:
        A.request_code(db, PHONE, SECRET, s, now=T0 + 10)
    assert 0 < e.value.retry_after <= A.RESEND_AFTER
    assert len(s.sent) == 1  # no second SMS was paid for
    A.request_code(db, PHONE, SECRET, s, now=T0 + 61)
    assert len(s.sent) == 2


def test_hourly_cap(db):
    s = FakeSender()
    for i in range(A.MAX_SENDS_PER_HOUR):
        A.request_code(db, PHONE, SECRET, s, now=T0 + 61 * i)
    with pytest.raises(A.RateLimited):
        A.request_code(db, PHONE, SECRET, s, now=T0 + 61 * A.MAX_SENDS_PER_HOUR)
    A.request_code(db, PHONE, SECRET, s, now=T0 + 3700)  # an hour later it works again
    # another phone is not affected
    A.request_code(db, "+998 91 000 00 00", SECRET, s, now=T0 + 400)


def test_different_phones_get_different_users(db):
    s = FakeSender()
    ids = []
    for ph in ("+998901111111", "+998902222222"):
        A.request_code(db, ph, SECRET, s, now=T0)
        ids.append(A.verify_code(db, ph, s.code, SECRET, now=T0 + 1)[0])
    assert ids[0] != ids[1]


# --------------------------------------------------------------- tokens

def test_token_roundtrip():
    t = A.create_token("user1", SECRET, now=T0)
    assert A.verify_token(t, SECRET, now=T0 + 10) == "user1"


def test_token_expires():
    t = A.create_token("user1", SECRET, now=T0, ttl=100)
    assert A.verify_token(t, SECRET, now=T0 + 99) == "user1"
    with pytest.raises(A.InvalidToken):
        A.verify_token(t, SECRET, now=T0 + 100)


def test_token_wrong_secret_and_tampering():
    t = A.create_token("user1", SECRET, now=T0)
    with pytest.raises(A.InvalidToken):
        A.verify_token(t, "y" * 40, now=T0)
    h, p, s = t.split(".")
    forged = A._b64(b'{"sub":"admin","iat":1,"exp":99999999999}')
    with pytest.raises(A.InvalidToken):
        A.verify_token(f"{h}.{forged}.{s}", SECRET, now=T0)


def test_token_alg_none_rejected():
    h = A._b64(b'{"alg":"none","typ":"JWT"}')
    p = A._b64(b'{"sub":"admin","exp":99999999999}')
    with pytest.raises(A.InvalidToken):
        A.verify_token(f"{h}.{p}.", SECRET, now=T0)


@pytest.mark.parametrize("bad", ["", "abc", "a.b.c", "....", "x" * 500])
def test_garbage_tokens(bad):
    with pytest.raises(A.InvalidToken):
        A.verify_token(bad, SECRET, now=T0)


def test_secret_required(monkeypatch):
    monkeypatch.delenv("SWAP_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        A.get_secret()
    monkeypatch.setenv("SWAP_SECRET", "short")
    with pytest.raises(RuntimeError):
        A.get_secret()
    monkeypatch.setenv("SWAP_SECRET", SECRET)
    assert A.get_secret() == SECRET

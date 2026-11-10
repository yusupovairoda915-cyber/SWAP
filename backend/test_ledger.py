import pytest

import ledger as L


@pytest.fixture
def db():
    return L.connect(":memory:")


def test_welcome_bonus_given_once(db):
    L.ensure_wallet(db, "ali")
    L.ensure_wallet(db, "ali")
    assert L.get_wallet(db, "ali") == {"user_id": "ali", "available": L.WELCOME_BONUS, "held": 0}
    assert len(L.get_history(db, "ali")) == 1


def test_booking_holds_credits(db):
    bid = L.book_session(db, "ali", "vali", 2)
    w = L.get_wallet(db, "ali")
    assert w["available"] == L.WELCOME_BONUS - 2
    assert w["held"] == 2
    assert L.get_wallet(db, "vali")["available"] == L.WELCOME_BONUS  # not paid yet
    assert bid > 0


def test_cannot_overspend(db):
    with pytest.raises(L.InsufficientCredits):
        L.book_session(db, "ali", "vali", L.WELCOME_BONUS + 1)
    assert L.get_wallet(db, "ali")["available"] == L.WELCOME_BONUS  # nothing changed


def test_complete_pays_teacher(db):
    bid = L.book_session(db, "ali", "vali", 2)
    L.complete_booking(db, bid, "ali")
    assert L.get_wallet(db, "vali")["available"] == L.WELCOME_BONUS + 2
    assert L.get_wallet(db, "ali")["held"] == 0


def test_cancel_refunds_learner(db):
    bid = L.book_session(db, "ali", "vali", 2)
    L.cancel_booking(db, bid, "vali")  # teacher may cancel too
    assert L.get_wallet(db, "ali") == {"user_id": "ali", "available": L.WELCOME_BONUS, "held": 0}
    assert L.get_wallet(db, "vali")["available"] == L.WELCOME_BONUS


def test_no_double_finish(db):
    bid = L.book_session(db, "ali", "vali", 1)
    L.complete_booking(db, bid, "ali")
    with pytest.raises(L.InvalidBookingState):
        L.complete_booking(db, bid, "ali")
    with pytest.raises(L.InvalidBookingState):
        L.cancel_booking(db, bid, "ali")
    assert L.get_wallet(db, "vali")["available"] == L.WELCOME_BONUS + 1  # paid once


def test_only_learner_confirms(db):
    bid = L.book_session(db, "ali", "vali", 1)
    with pytest.raises(L.NotAllowed):
        L.complete_booking(db, bid, "vali")  # teacher can't pay himself
    with pytest.raises(L.NotAllowed):
        L.cancel_booking(db, bid, "stranger")


def test_cannot_book_self(db):
    with pytest.raises(L.NotAllowed):
        L.book_session(db, "ali", "ali", 1)


def test_unknown_booking(db):
    with pytest.raises(L.BookingNotFound):
        L.complete_booking(db, 999, "ali")


def test_credits_are_conserved(db):
    """Money never appears or disappears: balances + held == all welcome bonuses."""
    b1 = L.book_session(db, "ali", "vali", 2)
    b2 = L.book_session(db, "vali", "gulya", 1)
    b3 = L.book_session(db, "gulya", "ali", 3)
    L.complete_booking(db, b1, "ali")
    L.cancel_booking(db, b2, "gulya")
    users = ["ali", "vali", "gulya"]
    total = sum(L.get_wallet(db, u)["available"] + L.get_wallet(db, u)["held"] for u in users)
    assert total == len(users) * L.WELCOME_BONUS
    # and the ledger agrees with the wallets
    for u in users:
        ledger_sum = sum(r["amount"] for r in L.get_history(db, u, limit=1000))
        assert ledger_sum == L.get_wallet(db, u)["available"]
    assert b3 > 0


def test_booking_keeps_skill_and_is_listed_for_both_sides(db):
    bid = L.book_session(db, "ali", "vali", 2, "python")
    for me in ("ali", "vali"):
        rows = L.list_bookings(db, me)
        assert [(r["id"], r["skill"], r["credits"], r["status"]) for r in rows] == [(bid, "python", 2, "held")]
    assert L.list_bookings(db, "stranger") == []
    L.complete_booking(db, bid, "ali")
    assert L.list_bookings(db, "vali")[0]["status"] == "completed"

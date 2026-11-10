import pytest

import ledger
import profiles as P
import swaps as S


@pytest.fixture
def db():
    conn = ledger.connect(":memory:")
    P.init_schema(conn)
    S.init_schema(conn)
    for uid, name in (("ali", "Али"), ("vali", "Вали"), ("gulya", "Гуля")):
        P.save_profile(conn, uid, name, "Ташкент")
    P.add_skill(conn, "ali", "python", "teach", 2)
    P.add_skill(conn, "ali", "english", "learn")
    P.add_skill(conn, "vali", "english", "teach", 3)
    P.add_skill(conn, "vali", "python", "learn")
    return conn


def test_full_swap_flow_no_credits_touched(db):
    sid = S.propose_swap(db, "ali", "vali", "Python", "english")
    S.accept_swap(db, sid, "vali")
    assert S.confirm_swap(db, sid, "ali") == "accepted"  # waiting for vali
    assert S.confirm_swap(db, sid, "vali") == "completed"
    assert S.list_swaps(db, "ali")[0]["status"] == "completed"
    # credits are not involved at all: no wallets were even created
    assert db.execute("SELECT COUNT(*) AS c FROM ledger").fetchone()["c"] == 0


def test_swap_must_be_truly_mutual(db):
    with pytest.raises(S.SwapNotAllowed):   # ali does not teach guitar
        S.propose_swap(db, "ali", "vali", "guitar", "english")
    with pytest.raises(S.SwapNotAllowed):   # vali does not teach python
        S.propose_swap(db, "ali", "vali", "python", "python")
    with pytest.raises(S.SwapNotAllowed):   # gulya has no matching skills
        S.propose_swap(db, "ali", "gulya", "python", "english")
    with pytest.raises(S.SwapNotAllowed):
        S.propose_swap(db, "ali", "ali", "python", "english")


def test_only_invited_person_accepts(db):
    sid = S.propose_swap(db, "ali", "vali", "python", "english")
    with pytest.raises(S.SwapNotAllowed):
        S.accept_swap(db, sid, "ali")
    with pytest.raises(S.SwapNotAllowed):
        S.accept_swap(db, sid, "gulya")
    S.accept_swap(db, sid, "vali")
    with pytest.raises(S.SwapInvalidState):
        S.accept_swap(db, sid, "vali")


def test_cannot_confirm_before_accept_or_twice_complete(db):
    sid = S.propose_swap(db, "ali", "vali", "python", "english")
    with pytest.raises(S.SwapInvalidState):
        S.confirm_swap(db, sid, "ali")
    S.accept_swap(db, sid, "vali")
    S.confirm_swap(db, sid, "ali")
    S.confirm_swap(db, sid, "vali")
    with pytest.raises(S.SwapInvalidState):
        S.confirm_swap(db, sid, "vali")
    with pytest.raises(S.SwapInvalidState):
        S.cancel_swap(db, sid, "ali")


def test_cancel_and_decline(db):
    sid = S.propose_swap(db, "ali", "vali", "python", "english")
    S.cancel_swap(db, sid, "vali")  # decline
    assert S.list_swaps(db, "vali")[0]["status"] == "cancelled"
    with pytest.raises(S.SwapNotAllowed):
        S.cancel_swap(db, sid, "gulya")
    with pytest.raises(S.SwapInvalidState):
        S.accept_swap(db, sid, "vali")


def test_no_duplicate_active_swap_but_can_repeat_after_cancel(db):
    sid = S.propose_swap(db, "ali", "vali", "python", "english")
    with pytest.raises(S.SwapInvalidState):
        S.propose_swap(db, "ali", "vali", "python", "english")
    with pytest.raises(S.SwapInvalidState):  # the mirror proposal is the same swap
        S.propose_swap(db, "vali", "ali", "english", "python")
    S.cancel_swap(db, sid, "ali")
    assert S.propose_swap(db, "ali", "vali", "python", "english") != sid


def test_unknown_swap(db):
    with pytest.raises(S.SwapNotFound):
        S.accept_swap(db, 999, "vali")


def test_list_includes_names_for_both_sides(db):
    S.propose_swap(db, "ali", "vali", "python", "english")
    for me in ("ali", "vali"):
        row = S.list_swaps(db, me)[0]
        assert (row["name_a"], row["name_b"]) == ("Али", "Вали")
    assert S.list_swaps(db, "gulya") == []

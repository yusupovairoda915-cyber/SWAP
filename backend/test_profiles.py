import pytest

import ledger
import profiles as P


@pytest.fixture
def db():
    conn = ledger.connect(":memory:")
    P.init_schema(conn)
    P.save_profile(conn, "ali", "Али", "Ташкент")
    P.save_profile(conn, "vali", "Вали", "Самарканд")
    P.save_profile(conn, "gulya", "Гуля", "ташкент")
    return conn


def test_profile_roundtrip_and_update(db):
    p = P.get_profile(db, "ali")
    assert (p["name"], p["city"], p["teach"], p["learn"]) == ("Али", "Ташкент", [], [])
    P.save_profile(db, "ali", "Али К.", "Бухара", "Люблю Python")
    p = P.get_profile(db, "ali")
    assert (p["name"], p["city"], p["bio"]) == ("Али К.", "Бухара", "Люблю Python")


def test_profile_validation(db):
    with pytest.raises(ValueError):
        P.save_profile(db, "x", "   ")
    with pytest.raises(P.ProfileNotFound):
        P.get_profile(db, "nobody")


def test_skill_requires_profile(db):
    with pytest.raises(P.ProfileNotFound):
        P.add_skill(db, "nobody", "python", "teach", 2)


def test_skill_names_are_normalized(db):
    P.add_skill(db, "ali", "  Python ", "teach", 2)
    P.add_skill(db, "vali", "PYTHON", "teach", 3)
    assert [t["user_id"] for t in P.find_teachers(db, "python")] == ["ali", "vali"]


def test_teach_needs_valid_price_learn_has_none(db):
    for bad in (None, 0, -1, 101):
        with pytest.raises(ValueError):
            P.add_skill(db, "ali", "python", "teach", bad)
    with pytest.raises(ValueError):
        P.add_skill(db, "ali", "python", "other", 1)
    P.add_skill(db, "ali", "english", "learn", 5)  # price ignored
    assert P.get_profile(db, "ali")["learn"] == ["english"]


def test_adding_again_updates_price_not_duplicates(db):
    P.add_skill(db, "ali", "python", "teach", 2)
    P.add_skill(db, "ali", "python", "teach", 4)
    assert P.get_profile(db, "ali")["teach"] == [{"skill": "python", "price": 4}]


def test_search_cheapest_first_and_city_filter(db):
    P.add_skill(db, "ali", "python", "teach", 3)
    P.add_skill(db, "vali", "python", "teach", 1)
    P.add_skill(db, "gulya", "python", "teach", 2)
    assert [t["user_id"] for t in P.find_teachers(db, "python")] == ["vali", "gulya", "ali"]
    # city is case-insensitive: "Ташкент" and "ташкент" are the same city
    assert [t["user_id"] for t in P.find_teachers(db, "python", "ТАШКЕНТ")] == ["gulya", "ali"]
    assert P.find_teachers(db, "python", "Нукус") == []
    assert P.find_teachers(db, "guitar") == []


def test_learners_are_not_in_teacher_search(db):
    P.add_skill(db, "ali", "python", "learn")
    assert P.find_teachers(db, "python") == []


def test_remove_skill(db):
    P.add_skill(db, "ali", "python", "teach", 2)
    assert P.remove_skill(db, "ali", "Python", "teach") is True
    assert P.remove_skill(db, "ali", "python", "teach") is False
    assert P.find_teachers(db, "python") == []


def test_skill_limit(db):
    for i in range(P.MAX_SKILLS_PER_USER):
        P.add_skill(db, "ali", f"skill{i}", "teach", 1)
    with pytest.raises(P.ProfileError):
        P.add_skill(db, "ali", "one-too-many", "teach", 1)
    P.add_skill(db, "ali", "skill0", "teach", 5)  # updating an existing one still works


def test_suggest_prefix_is_literal(db):
    P.add_skill(db, "ali", "python", "teach", 1)
    P.add_skill(db, "vali", "python", "teach", 1)
    P.add_skill(db, "gulya", "pytorch", "teach", 1)
    P.add_skill(db, "gulya", "photoshop", "teach", 1)
    assert P.suggest_skills(db, "py") == ["python", "pytorch"]  # most popular first
    assert P.suggest_skills(db, "%") == []  # wildcard characters are not special
    assert P.suggest_skills(db, "  ") == []


def test_matches_for_my_learn_list(db):
    P.add_skill(db, "ali", "english", "learn")
    P.add_skill(db, "ali", "python", "teach", 2)  # my own teach skill must not match me
    P.add_skill(db, "vali", "english", "teach", 3)
    P.add_skill(db, "gulya", "english", "teach", 1)
    m = P.find_matches(db, "ali")
    assert [(x["user_id"], x["skill"]) for x in m] == [("gulya", "english"), ("vali", "english")]
    assert P.find_matches(db, "vali") == []


def _swap_db(db):
    # ali: teaches python, wants english + guitar
    P.add_skill(db, "ali", "python", "teach", 2)
    P.add_skill(db, "ali", "english", "learn")
    P.add_skill(db, "ali", "guitar", "learn")
    # vali: teaches english, wants python      -> mutual swap with ali
    P.add_skill(db, "vali", "english", "teach", 3)
    P.add_skill(db, "vali", "python", "learn")
    # gulya: teaches guitar + english, wants nothing ali teaches -> one-sided (ali pays her)
    P.add_skill(db, "gulya", "guitar", "teach", 1)
    P.add_skill(db, "gulya", "english", "teach", 1)
    # dilya: wants python only -> one-sided the other way (she pays ali)
    P.save_profile(db, "dilya", "Диля", "Ташкент")
    P.add_skill(db, "dilya", "python", "learn")


def test_swap_matches_mutual_first(db):
    _swap_db(db)
    m = P.find_swap_matches(db, "ali")
    assert [x["user_id"] for x in m] == ["vali", "gulya", "dilya"]
    assert [x["mutual"] for x in m] == [True, False, False]


def test_swap_match_directions(db):
    _swap_db(db)
    by = {x["user_id"]: x for x in P.find_swap_matches(db, "ali")}
    assert by["vali"]["they_teach"] == [{"skill": "english", "price": 3}]
    assert by["vali"]["i_teach"] == ["python"]
    assert [s["skill"] for s in by["gulya"]["they_teach"]] == ["english", "guitar"]
    assert by["gulya"]["i_teach"] == []
    assert by["dilya"]["they_teach"] == [] and by["dilya"]["i_teach"] == ["python"]


def test_swap_matches_symmetry_and_no_self(db):
    _swap_db(db)
    assert "ali" not in [x["user_id"] for x in P.find_swap_matches(db, "ali")]
    back = P.find_swap_matches(db, "vali")
    assert [x["user_id"] for x in back] == ["ali"] and back[0]["mutual"] is True


def test_swap_matches_empty(db):
    assert P.find_swap_matches(db, "ali") == []
    P.add_skill(db, "ali", "python", "teach", 2)  # nobody wants it
    assert P.find_swap_matches(db, "ali") == []


def test_price_lookup_and_names(db):
    P.add_skill(db, "ali", "python", "teach", 4)
    P.add_skill(db, "ali", "english", "learn")
    assert P.get_price(db, "ali", " PYTHON ") == 4
    assert P.get_price(db, "ali", "english") is None   # only wants to learn it
    assert P.get_price(db, "vali", "python") is None
    assert P.get_names(db, ["ali", "vali", "nobody", "ali"]) == {"ali": "Али", "vali": "Вали"}
    assert P.get_names(db, []) == {}

import pytest

from agents.categories import DEFAULT_PERSONALITIES
from agents.execution.review_focus import (
    GENERIC_FOCUS,
    REVIEW_FOCUS,
    coverage_instructions,
)
from db.types import ReviewCategory


@pytest.mark.parametrize("category", list(ReviewCategory))
def test_every_review_category_has_a_specific_focus(category: ReviewCategory) -> None:
    focus = REVIEW_FOCUS[category]

    assert focus.mandate
    assert focus.surfaces
    assert focus.searches
    assert focus.absence_checks
    assert category.value in coverage_instructions(category.value) or focus.mandate in (
        coverage_instructions(category.value)
    )


def test_legal_instructions_require_searching_for_absent_policies() -> None:
    instructions = coverage_instructions("legal")

    assert "privacy policy and terms of service" in instructions
    assert "search_code" in instructions
    assert "confirmed absence as a finding" in instructions
    assert "Do not report generic code security bugs" in instructions


def test_categories_get_different_instructions() -> None:
    texts = {
        category: coverage_instructions(category.value) for category in ReviewCategory
    }

    assert len(set(texts.values())) == len(ReviewCategory)


@pytest.mark.parametrize("category", ["", "custom", "LEGAL "])
def test_unknown_categories_fall_back_to_the_generic_pass(category: str) -> None:
    instructions = coverage_instructions(category)

    assert GENERIC_FOCUS.mandate in instructions
    assert "search_code" not in instructions


@pytest.mark.parametrize("category", list(ReviewCategory))
def test_default_personalities_describe_reporting_style_not_scope(
    category: ReviewCategory,
) -> None:
    personality = DEFAULT_PERSONALITIES[category]

    for scoping_phrase in ("Leave ", "Stay out of", "Skip ", "Do not report"):
        assert scoping_phrase not in personality

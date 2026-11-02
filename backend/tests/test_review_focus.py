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


RESEARCH_REQUIRED_CATEGORIES = (
    ReviewCategory.LEGAL,
    ReviewCategory.ACCESSIBILITY,
    ReviewCategory.SECURITY,
)


@pytest.mark.parametrize("category", list(ReviewCategory))
def test_web_research_is_required_only_for_legal_accessibility_and_security(
    category: ReviewCategory,
) -> None:
    instructions = coverage_instructions(category.value)

    if category in RESEARCH_REQUIRED_CATEGORIES:
        assert REVIEW_FOCUS[category].research
        assert "Web research is required for this role" in instructions
        assert "call web_search at least once for every finding" in instructions
    else:
        assert not REVIEW_FOCUS[category].research
        assert "Web research is required" not in instructions


@pytest.mark.parametrize("category", RESEARCH_REQUIRED_CATEGORIES)
def test_required_research_is_grounded_and_cannot_invent_sources(
    category: ReviewCategory,
) -> None:
    instructions = coverage_instructions(category.value)

    assert "never invent a source, citation, or URL" in instructions
    assert "result URL in the finding's evidence" in instructions
    assert "retry once with a shorter query" in instructions
    assert "If you report no findings, no search is required" in instructions
    for topic in REVIEW_FOCUS[category].research:
        assert topic in instructions


def test_required_research_tells_the_model_how_to_avoid_rejected_queries() -> None:
    instructions = coverage_instructions("security")

    for keyword in ("select", "insert", "import", "function", "class"):
        assert keyword in instructions
    assert "plain English" in instructions


@pytest.mark.parametrize("category", RESEARCH_REQUIRED_CATEGORIES)
def test_research_topics_are_generic_enough_for_the_query_filter(
    category: ReviewCategory,
) -> None:
    from agents.execution.tools import _is_public_research_query

    for topic in REVIEW_FOCUS[category].research:
        assert _is_public_research_query(topic), topic


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

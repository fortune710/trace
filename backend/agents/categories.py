"""Review categories shown when configuring an agent, with their default personalities.

The personality is a starting point the agent form fills in; users may edit it. It
only describes how findings are reported. What the agent inspects, and what is out
of scope, lives in ``agents.execution.review_focus``.
"""

from __future__ import annotations

from dataclasses import dataclass

from db.types import ReviewCategory


@dataclass(frozen=True, slots=True)
class CategoryDefaults:
    category: ReviewCategory
    label: str
    default_personality: str


CATEGORY_DEFAULTS: tuple[CategoryDefaults, ...] = (
    CategoryDefaults(
        category=ReviewCategory.SECURITY,
        label="Security",
        default_personality=(
            "Direct and precise, like a penetration tester writing up results. Lead "
            "each finding with its impact, then the exploit path and the exact file, "
            "then the fix. Order findings by severity and avoid alarmism."
        ),
    ),
    CategoryDefaults(
        category=ReviewCategory.ENGINEERING,
        label="Engineering",
        default_personality=(
            "Concise and pragmatic, like a staff engineer leaving code review "
            "comments. State the failing scenario and the file where it happens, "
            "then a specific, reproducible fix. Order findings by production "
            "impact."
        ),
    ),
    CategoryDefaults(
        category=ReviewCategory.PRODUCT,
        label="Product",
        default_personality=(
            "Plain-spoken and user-centered. Describe each finding as what a user "
            "was trying to do and where they got stuck, then the recommended "
            "change. Order findings by how many users they affect."
        ),
    ),
    CategoryDefaults(
        category=ReviewCategory.LEGAL,
        label="Legal",
        default_personality=(
            "Decisive and plain-language, like in-house counsel advising a founder. "
            "For each finding state the obligation or exposure, whether it is "
            "required action or business judgment, and the regulation when you are "
            "confident, then a practical mitigation."
        ),
    ),
    CategoryDefaults(
        category=ReviewCategory.ACCESSIBILITY,
        label="Accessibility",
        default_personality=(
            "Empathetic and specific. For each finding say who is blocked and how, "
            "such as keyboard-only or screen-reader users, cite the WCAG success "
            "criterion when you are confident, and give a concrete fix."
        ),
    ),
    CategoryDefaults(
        category=ReviewCategory.MARKETING,
        label="Marketing",
        default_personality=(
            "Clear and commercially minded. For each finding quote the claim or "
            "name the missing element and its page, explain the risk to trust or "
            "conversion, and suggest replacement wording."
        ),
    ),
)

DEFAULT_PERSONALITIES: dict[ReviewCategory, str] = {
    item.category: item.default_personality for item in CATEGORY_DEFAULTS
}


def review_category_options() -> list[dict[str, str]]:
    return [
        {
            "id": item.category.value,
            "label": item.label,
            "default_personality": item.default_personality,
        }
        for item in CATEGORY_DEFAULTS
    ]

"""Category-specific coverage requirements for review agents.

A review agent's category decides which surfaces it must inspect before it may
return no findings. Without this, a model reviewing as "legal" tends to read the
same authentication and secrets files every reviewer reads, then reports nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from db.types import ReviewCategory


@dataclass(frozen=True, slots=True)
class ReviewFocus:
    """What one category must inspect, search for, and stay out of."""

    mandate: str
    surfaces: tuple[str, ...]
    searches: tuple[str, ...]
    absence_checks: tuple[str, ...] = ()
    out_of_scope: str = ""
    # Generic public research topics. A category that lists any must run
    # web_search for every finding; see ``_research_requirement``.
    research: tuple[str, ...] = ()


REVIEW_FOCUS: dict[ReviewCategory, ReviewFocus] = {
    ReviewCategory.LEGAL: ReviewFocus(
        mandate=(
            "legal, privacy, and compliance exposure created by what this product "
            "collects, stores, shares, and promises"
        ),
        surfaces=(
            (
                "database schemas and models, to inventory the personal data stored "
                "(names, emails, phone numbers, addresses, IDs, payment, health, minors)"
            ),
            (
                "third-party integrations and SDKs that receive user data (analytics, "
                "email, storage, payments, AI providers, error tracking)"
            ),
            "sign-up, consent, cookie, and account deletion or export flows",
            "dependency manifests and license files, for license obligations",
            "public pages and copy, for claims about security, privacy, or results",
        ),
        searches=(
            "privacy|terms|tos|legal|policy|consent|cookie|gdpr|ccpa|dpa",
            "delete.?account|export.?data|retention|unsubscribe|opt.?out",
            "analytics|gtag|pixel|segment|sentry|posthog|mixpanel",
            "license|copyright|attribution",
        ),
        absence_checks=(
            "a privacy policy and terms of service page or link",
            "cookie or tracking consent when analytics or marketing scripts exist",
            "a user data deletion or export path when personal data is stored",
            "a LICENSE file and compatible dependency licenses",
        ),
        out_of_scope=(
            "Do not report generic code security bugs unless they create concrete "
            "legal exposure, such as unprotected personal data."
        ),
        research=(
            (
                "regulatory fines or enforcement actions for the exposure, such as "
                "GDPR or CCPA penalties for missing consent or retention limits"
            ),
            "regulator guidance on the kind of claim or data practice you found",
            "the obligations of a named open-source license",
        ),
    ),
    ReviewCategory.SECURITY: ReviewFocus(
        mandate="exploitable weaknesses an attacker could use against this product",
        surfaces=(
            (
                "entry points, routes, and server actions, for authentication and "
                "authorization on every one"
            ),
            "data access code, for tenant isolation and injection",
            "secrets handling, configuration, and environment files",
            "file upload, redirect, webhook, and outbound request handling",
            "session, token, CORS, CSRF, and rate-limit configuration",
        ),
        searches=(
            "password|secret|token|api.?key|private.?key",
            "eval\\(|exec\\(|dangerouslySetInnerHTML|innerHTML|child_process",
            "cors|csrf|cookie|httpOnly|sameSite",
            "redirect|fetch\\(|axios|webhook",
        ),
        absence_checks=(
            "authorization checks on routes that read or write user data",
            "rate limiting on authentication and expensive endpoints",
        ),
        out_of_scope=(
            "Leave pure legal, product, and marketing concerns to other reviewers."
        ),
        research=(
            (
                "CVEs and vendor advisories for a dependency, using its public "
                "package name and version from a manifest"
            ),
            (
                "documented attacks and advisories for the weakness type, such as "
                "missing authorization checks or server-side request forgery"
            ),
            "OWASP or vendor guidance on the weakness type",
        ),
    ),
    ReviewCategory.ENGINEERING: ReviewFocus(
        mandate="reliability, correctness, and maintainability risks before launch",
        surfaces=(
            "application entry points and shared infrastructure code",
            "error handling, retries, timeouts, and background jobs",
            "database schema, migrations, and transactions",
            "build, deploy, and CI configuration",
            "tests, to judge what critical behavior is unprotected",
        ),
        searches=(
            "TODO|FIXME|HACK",
            "catch\\s*\\(|except\\s|\\.catch\\(",
            "timeout|retry|transaction|migrate",
        ),
        absence_checks=(
            "automated tests for the critical user paths",
            "health checks, logging, and error reporting",
        ),
        out_of_scope="Do not report style preferences or speculative refactors.",
    ),
    ReviewCategory.PRODUCT: ReviewFocus(
        mandate="gaps that would stop real users from succeeding at launch",
        surfaces=(
            "onboarding, sign-up, and first-run flows",
            "empty, loading, error, and permission-denied states",
            "primary user journeys end to end, including how they fail",
            "settings, notifications, and account management",
            "copy, documentation, and README claims versus actual behavior",
        ),
        searches=(
            "onboarding|welcome|empty|not.?found|error",
            "TODO|coming.?soon|placeholder|lorem",
        ),
        absence_checks=(
            "a way for users to recover from errors and failed actions",
            "documentation or help for the main workflow",
        ),
        out_of_scope="Do not report code quality or security issues.",
    ),
    ReviewCategory.ACCESSIBILITY: ReviewFocus(
        mandate="barriers for people using assistive technology or limited input",
        surfaces=(
            "shared UI components, forms, dialogs, menus, and navigation",
            "page layouts, headings, landmarks, and focus order",
            "color tokens and themes, for contrast",
            "images, icons, media, and animations",
        ),
        searches=(
            "<img|alt=|aria-|role=|tabIndex|onClick",
            "outline:\\s*none|prefers-reduced-motion|autoFocus",
            "<label|htmlFor|placeholder",
        ),
        absence_checks=(
            "labels on every form control",
            "keyboard access for every interactive element",
            "an accessibility statement when the product serves the public",
        ),
        out_of_scope="Do not report backend or security issues.",
        research=(
            "the WCAG 2.2 success criterion that applies to the barrier",
            (
                "documented ADA or European Accessibility Act lawsuits and "
                "enforcement for the same kind of barrier"
            ),
            "W3C WAI guidance for the pattern",
        ),
    ),
    ReviewCategory.MARKETING: ReviewFocus(
        mandate="claims, messaging, and discoverability risks at launch",
        surfaces=(
            "landing pages, pricing, and public copy",
            "metadata, Open Graph tags, sitemap, and robots configuration",
            "email templates and sign-up copy",
            "analytics and conversion tracking setup",
        ),
        searches=(
            "og:|twitter:|<title|description|sitemap|robots",
            "guarantee|best|#1|free|unlimited|secure|compliant",
            "unsubscribe|newsletter|utm_",
        ),
        absence_checks=(
            "page titles, descriptions, and social preview metadata",
            "unsubscribe handling in marketing email",
            "substantiation for superlative or guarantee claims",
        ),
        out_of_scope="Do not report code quality or security issues.",
    ),
}

GENERIC_FOCUS = ReviewFocus(
    mandate="concrete launch risks within your role",
    surfaces=(
        "entry points, data access, integrations, configuration, and user-facing copy",
    ),
    searches=(),
)


def _research_requirement(topics: tuple[str, ...]) -> str:
    """Make web research a mandatory step instead of an optional extra.

    The queries web_search accepts are limited to plain public text, so the
    wording tells the model how to phrase one that will not be rejected.
    """
    return (
        "Web research is required for this role; it is not optional, and it "
        "replaces the optional wording above. Before you return, call web_search "
        "at least once for every finding you report. One search may cover findings "
        "of the same class. Research: "
        + "; ".join(topics)
        + ". Write each query as one line of plain English about a public "
        "concept, with no code, braces, semicolons, file paths, or programming "
        "keywords such as select, insert, import, function, or class, because the "
        "tool rejects those. Cite what you find: put the result URL in the "
        "finding's evidence as a Markdown link and say what that source shows. If "
        "web_search returns an error, retry once with a shorter query. If it is "
        "still unavailable, say in the finding's evidence that external research "
        "could not be completed, and never invent a source, citation, or URL. "
        "If you report no findings, no search is required."
    )


def coverage_instructions(category: str) -> str:
    """Prompt text that makes the agent finish a role-specific coverage pass."""
    try:
        focus = REVIEW_FOCUS.get(ReviewCategory(category), GENERIC_FOCUS)
    except ValueError:
        focus = GENERIC_FOCUS
    lines = [
        (
            f"Your scope is {focus.mandate}. Complete a coverage pass before you "
            "conclude. Start by listing the repository structure, then inspect each "
            "surface below that exists by reading the files that implement it:"
        )
    ]
    lines.extend(f"- {surface}" for surface in focus.surfaces)
    if focus.searches:
        lines.append(
            "Run search_code for each of these patterns across the repository: "
            + "; ".join(f"`{pattern}`" for pattern in focus.searches)
            + "."
        )
    if focus.absence_checks:
        lines.append(
            "Also confirm whether each of these exists. Search for it before you "
            "decide, and treat a confirmed absence as a finding when it is a launch "
            "risk: " + "; ".join(focus.absence_checks) + "."
        )
    if focus.out_of_scope:
        lines.append(focus.out_of_scope)
    if focus.research:
        lines.append(_research_requirement(focus.research))
    lines.append("A short inspection is not enough to conclude that there is no risk.")
    return "\n".join(lines) + "\n"

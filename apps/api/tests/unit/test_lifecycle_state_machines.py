"""Unit tests for Project/Scraper lifecycle state machines — pure
logic, no database needed."""

from app.models.project import PROJECT_STATUS_TRANSITIONS, ProjectStatus
from app.models.scraper import SCRAPER_STATUS_TRANSITIONS, ScraperStatus
from app.services.project_service import InvalidStatusTransition, apply_status_transition
from app.services.scraper_service import apply_status_transition as apply_scraper_transition


class _FakeProject:
    def __init__(self, status: str) -> None:
        self.status = status


class _FakeScraper:
    def __init__(self, status: str) -> None:
        self.status = status


def test_project_draft_can_activate_or_archive() -> None:
    assert PROJECT_STATUS_TRANSITIONS[ProjectStatus.DRAFT] == {
        ProjectStatus.ACTIVE,
        ProjectStatus.ARCHIVED,
    }


def test_project_archived_is_terminal() -> None:
    assert PROJECT_STATUS_TRANSITIONS[ProjectStatus.ARCHIVED] == set()


def test_project_draft_cannot_go_to_paused_directly() -> None:
    assert ProjectStatus.PAUSED not in PROJECT_STATUS_TRANSITIONS[ProjectStatus.DRAFT]


def test_apply_status_transition_succeeds_for_valid_transition() -> None:
    project = _FakeProject(ProjectStatus.DRAFT.value)
    apply_status_transition(project, ProjectStatus.ACTIVE.value)  # type: ignore[arg-type]
    assert project.status == ProjectStatus.ACTIVE.value


def test_apply_status_transition_rejects_invalid_transition() -> None:
    project = _FakeProject(ProjectStatus.ARCHIVED.value)
    try:
        apply_status_transition(project, ProjectStatus.ACTIVE.value)  # type: ignore[arg-type]
        raise AssertionError("expected InvalidStatusTransition")
    except InvalidStatusTransition:
        pass
    assert project.status == ProjectStatus.ARCHIVED.value  # unchanged


def test_scraper_has_no_paused_state() -> None:
    """Regression guard for the deliberate scope decision: Scraper's
    state machine is simpler than Project's — no PAUSED."""
    all_targets: set[str] = set()
    for targets in SCRAPER_STATUS_TRANSITIONS.values():
        all_targets |= targets
    assert "PAUSED" not in all_targets
    assert "PAUSED" not in SCRAPER_STATUS_TRANSITIONS


def test_scraper_draft_can_activate_or_archive() -> None:
    assert SCRAPER_STATUS_TRANSITIONS[ScraperStatus.DRAFT] == {
        ScraperStatus.ACTIVE,
        ScraperStatus.ARCHIVED,
    }


def test_scraper_active_disabled_roundtrip() -> None:
    scraper = _FakeScraper(ScraperStatus.ACTIVE.value)
    apply_scraper_transition(scraper, ScraperStatus.DISABLED.value)  # type: ignore[arg-type]
    assert scraper.status == ScraperStatus.DISABLED.value
    apply_scraper_transition(scraper, ScraperStatus.ACTIVE.value)  # type: ignore[arg-type]
    assert scraper.status == ScraperStatus.ACTIVE.value

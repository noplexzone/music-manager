from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.models.workflow import AcquisitionState, ImportWorkflowState
from app.services.staging import StagingPathError, build_staging_release_path
from app.services.workflow_state import transition_acquisition, transition_import


def test_import_workflow_allows_only_forward_reviewable_transitions() -> None:
    assert (
        transition_import(ImportWorkflowState.discovered, ImportWorkflowState.staged)
        == ImportWorkflowState.staged
    )
    assert (
        transition_import(ImportWorkflowState.staged, ImportWorkflowState.matching)
        == ImportWorkflowState.matching
    )
    assert (
        transition_import(ImportWorkflowState.matching, ImportWorkflowState.needs_review)
        == ImportWorkflowState.needs_review
    )
    assert (
        transition_import(ImportWorkflowState.needs_review, ImportWorkflowState.ready)
        == ImportWorkflowState.ready
    )
    assert (
        transition_import(ImportWorkflowState.ready, ImportWorkflowState.importing)
        == ImportWorkflowState.importing
    )
    assert (
        transition_import(ImportWorkflowState.importing, ImportWorkflowState.imported)
        == ImportWorkflowState.imported
    )
    assert (
        transition_import(ImportWorkflowState.importing, ImportWorkflowState.rolled_back)
        == ImportWorkflowState.rolled_back
    )

    with pytest.raises(ValueError, match="invalid import workflow transition"):
        transition_import(ImportWorkflowState.imported, ImportWorkflowState.importing)


def test_acquisition_workflow_terminal_states_do_not_restart() -> None:
    assert (
        transition_acquisition(AcquisitionState.queued, AcquisitionState.searching)
        == AcquisitionState.searching
    )
    assert (
        transition_acquisition(AcquisitionState.searching, AcquisitionState.acquiring)
        == AcquisitionState.acquiring
    )
    assert (
        transition_acquisition(AcquisitionState.acquiring, AcquisitionState.downloaded)
        == AcquisitionState.downloaded
    )

    with pytest.raises(ValueError, match="invalid acquisition transition"):
        transition_acquisition(AcquisitionState.failed, AcquisitionState.queued)


def test_staging_path_is_contained_under_configured_root(tmp_path: Path) -> None:
    settings = Settings(
        secret_key="test-secret",
        staging_root=tmp_path / "staging",
        library_root=tmp_path / "library",
    )

    path = build_staging_release_path(settings, source="slskd", release_id=42)

    assert path == (tmp_path / "staging" / "slskd" / "release-42").resolve()


def test_staging_path_rejects_escaping_source_segments(tmp_path: Path) -> None:
    settings = Settings(secret_key="test-secret", staging_root=tmp_path / "staging")

    with pytest.raises(StagingPathError):
        build_staging_release_path(settings, source="../escape", release_id=1)

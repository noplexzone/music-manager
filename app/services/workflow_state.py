from __future__ import annotations

from app.models.workflow import AcquisitionState, ImportWorkflowState

_ACQUISITION_TRANSITIONS: dict[AcquisitionState, set[AcquisitionState]] = {
    AcquisitionState.queued: {
        AcquisitionState.searching,
        AcquisitionState.cancelled,
        AcquisitionState.failed,
    },
    AcquisitionState.searching: {
        AcquisitionState.acquiring,
        AcquisitionState.failed,
        AcquisitionState.cancelled,
    },
    AcquisitionState.acquiring: {
        AcquisitionState.downloaded,
        AcquisitionState.failed,
        AcquisitionState.cancelled,
    },
    AcquisitionState.downloaded: set(),
    AcquisitionState.failed: set(),
    AcquisitionState.cancelled: set(),
}

_IMPORT_TRANSITIONS: dict[ImportWorkflowState, set[ImportWorkflowState]] = {
    ImportWorkflowState.discovered: {ImportWorkflowState.staged, ImportWorkflowState.failed},
    ImportWorkflowState.staged: {ImportWorkflowState.matching, ImportWorkflowState.failed},
    ImportWorkflowState.matching: {
        ImportWorkflowState.needs_review,
        ImportWorkflowState.ready,
        ImportWorkflowState.failed,
    },
    ImportWorkflowState.needs_review: {ImportWorkflowState.ready, ImportWorkflowState.failed},
    ImportWorkflowState.ready: {ImportWorkflowState.importing, ImportWorkflowState.failed},
    ImportWorkflowState.importing: {
        ImportWorkflowState.imported,
        ImportWorkflowState.failed,
        ImportWorkflowState.rolled_back,
    },
    ImportWorkflowState.imported: set(),
    ImportWorkflowState.failed: {ImportWorkflowState.needs_review},
    ImportWorkflowState.rolled_back: {ImportWorkflowState.needs_review},
}


def transition_acquisition(
    current: AcquisitionState, target: AcquisitionState
) -> AcquisitionState:
    if current == target:
        return current
    if target not in _ACQUISITION_TRANSITIONS[current]:
        raise ValueError(f"invalid acquisition transition: {current} -> {target}")
    return target


def transition_import(
    current: ImportWorkflowState, target: ImportWorkflowState
) -> ImportWorkflowState:
    if current == target:
        return current
    if target not in _IMPORT_TRANSITIONS[current]:
        raise ValueError(f"invalid import workflow transition: {current} -> {target}")
    return target

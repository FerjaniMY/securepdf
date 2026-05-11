"""Per-document state held in the GUI — pure data, no Qt imports.

Why a dedicated state class
---------------------------
The GUI needs to track several things per opened PDF that the headless pipeline
doesn't:

  - Extracted pages and detections from the pipeline
  - The user's per-detection decision (Accepted / Rejected / Pending), which is
    not present in the headless flow (everything is accepted by default there)
  - Output paths the user has chosen
  - A current-page cursor for the viewer

Putting this in a Qt widget would couple business logic to widget lifecycles
(e.g. closing a window would lose state). Putting it in a separate dataclass
makes it test-without-Qt, snapshot/restore-friendly, and lets the worker
populate it from a background thread without thread-safety surgery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterator

from securepdf.detection.models import Detection
from securepdf.pdf.models import PageContent


class Decision(str, Enum):
    """User's verdict on a single detection.

    Default is ACCEPTED — surface "everything will be redacted unless you uncheck
    it" rather than "nothing will be redacted unless you check it". That matches
    user intent (they ran detection to find things to redact) and is the safer
    default (over-redaction beats leakage).
    """

    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass
class DocumentSession:
    """All state for one opened PDF in the GUI.

    Lifecycle:
      1. `DocumentSession(path)` — bare session, no pages/detections yet.
      2. Worker populates `pages` then `detections`, setting `processed=True`.
      3. User reviews; each Detection's row in `decisions` flips between
         ACCEPTED and REJECTED.
      4. "Save outputs" reads `accepted_detections()` and runs redaction.
    """

    path: Path
    pages: list[PageContent] = field(default_factory=list)
    detections: list[Detection] = field(default_factory=list)
    decisions: dict[int, Decision] = field(default_factory=dict)
    current_page: int = 0
    processed: bool = False
    output_pdf: Path | None = None
    output_text: Path | None = None

    # -----------------------------------------------------------------
    # Lifecycle transitions
    # -----------------------------------------------------------------

    def set_pages(self, pages: list[PageContent]) -> None:
        """Called by the worker after extraction completes."""
        self.pages = pages
        # Clamp current_page in case the new doc has fewer pages.
        if self.current_page >= len(pages):
            self.current_page = max(0, len(pages) - 1)

    def set_detections(self, detections: list[Detection]) -> None:
        """Called by the worker after detection completes.

        All detections default to ACCEPTED. The user demotes individual ones
        through the review panel.
        """
        self.detections = detections
        self.decisions = {i: Decision.ACCEPTED for i in range(len(detections))}
        self.processed = True

    # -----------------------------------------------------------------
    # User actions
    # -----------------------------------------------------------------

    def set_decision(self, index: int, decision: Decision) -> None:
        if not 0 <= index < len(self.detections):
            raise IndexError(f"detection index {index} out of range [0, {len(self.detections)})")
        self.decisions[index] = decision

    def accept_all(self) -> None:
        self.decisions = {i: Decision.ACCEPTED for i in range(len(self.detections))}

    def reject_all(self) -> None:
        self.decisions = {i: Decision.REJECTED for i in range(len(self.detections))}

    # -----------------------------------------------------------------
    # Queries
    # -----------------------------------------------------------------

    def decision_for(self, index: int) -> Decision:
        return self.decisions.get(index, Decision.ACCEPTED)

    def accepted_detections(self) -> list[Detection]:
        """The subset that should actually be redacted, in original detection order."""
        return [
            d for i, d in enumerate(self.detections)
            if self.decisions.get(i, Decision.ACCEPTED) == Decision.ACCEPTED
        ]

    def detections_on_page(self, page_idx: int) -> Iterator[tuple[int, Detection]]:
        """Yield (index, detection) for detections on a given page.

        Index is the global detection index so callers can map back to `decisions`.
        """
        for i, d in enumerate(self.detections):
            if d.page == page_idx:
                yield i, d

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def detection_count(self) -> int:
        return len(self.detections)

    @property
    def accepted_count(self) -> int:
        return sum(1 for d in self.decisions.values() if d == Decision.ACCEPTED)

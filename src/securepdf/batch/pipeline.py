"""Batch processing orchestrator.

Given an input directory of PDFs, run extract → detect → redact on each file
and write outputs into a parallel directory tree. Failed files are recorded
with their error and the run continues.

Output layout
-------------
    input_dir/
        report1.pdf
        sub/report2.pdf
    output_dir/
        report1.redacted.pdf
        report1.anonymized.txt
        sub/report2.redacted.pdf
        sub/report2.anonymized.txt
        manifest.json

The relative subdirectory structure is preserved so users can drop a whole
project folder in without flattening it.

Resume behavior
---------------
On rerun, files whose expected outputs already exist are skipped. This makes
the workflow safe to Ctrl-C and resume: only un-processed files run again.
The skip check looks at both the redacted PDF and the anonymized text (when
the mode requests both). Pass `force=True` to reprocess regardless.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Literal

from securepdf.detection.custom_entities import CustomEntityProfile, load_profile

log = logging.getLogger(__name__)

Mode = Literal["pdf", "text", "both"]


@dataclass
class FileResult:
    """One file's outcome — recorded in the manifest."""

    input_path: str
    output_pdf: str | None = None
    output_text: str | None = None
    detection_count: int = 0
    skipped: bool = False  # outputs already existed
    error: str | None = None
    elapsed_seconds: float = 0.0


@dataclass
class BatchResult:
    """Full-batch summary."""

    input_dir: str
    output_dir: str
    started_at: str  # ISO-8601
    ended_at: str
    total: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    files: list[FileResult] = field(default_factory=list)


def _output_paths(input_pdf: Path, input_root: Path, output_root: Path, mode: Mode) -> tuple[Path | None, Path | None]:
    """Compute (output_pdf_path, output_text_path) — None for modes we skip.

    Defensive: verifies the computed paths land inside `output_root` after
    resolution. `Path.relative_to()` already prevents most escapes upstream,
    but this guard catches future code changes where a refactor might
    accidentally introduce a write outside the intended tree.
    """
    rel = input_pdf.relative_to(input_root)
    base = output_root / rel
    out_pdf = base.with_suffix(".redacted.pdf") if mode in ("pdf", "both") else None
    out_txt = base.with_suffix(".anonymized.txt") if mode in ("text", "both") else None
    # Belt-and-braces: each computed path must stay inside output_root.
    resolved_root = output_root.resolve()
    for p in (out_pdf, out_txt):
        if p is None:
            continue
        try:
            p.resolve().relative_to(resolved_root)
        except ValueError as e:
            raise ValueError(
                f"computed output path escapes output_root: {p} (root={resolved_root})"
            ) from e
    return out_pdf, out_txt


def _process_one(
    pdf: Path,
    input_root: Path,
    output_root: Path,
    profile: CustomEntityProfile | None,
    mode: Mode,
    use_stage2: bool,
    spacy_model: str,
    force: bool,
) -> FileResult:
    """Run the full pipeline on one file. Wrapped in a top-level try/except so
    one bad file doesn't kill the whole batch."""
    started = time.monotonic()
    out_pdf, out_txt = _output_paths(pdf, input_root, output_root, mode)
    result = FileResult(
        input_path=str(pdf),
        output_pdf=str(out_pdf) if out_pdf else None,
        output_text=str(out_txt) if out_txt else None,
    )

    # Skip if outputs already exist (resume-on-rerun).
    if not force:
        expected = [p for p in (out_pdf, out_txt) if p]
        if expected and all(p.exists() for p in expected):
            result.skipped = True
            result.elapsed_seconds = time.monotonic() - started
            return result

    try:
        # Imports are local to keep module-load cheap when tests don't exercise
        # the heavy spaCy / Presidio stacks.
        from securepdf.detection import detect
        from securepdf.pdf.pipeline import extract
        from securepdf.redaction.pipeline import redact

        pages = extract(pdf)
        detections = detect(
            pages,
            profile=profile,
            spacy_model=spacy_model,
            use_stage2=use_stage2,
        )
        rresult = redact(
            pdf,
            detections,
            pages=pages,
            output_pdf=out_pdf,
            output_text=out_txt,
            mode=mode,
        )
        result.detection_count = len(detections)
        result.output_pdf = str(rresult.pdf_path) if rresult.pdf_path else None
        result.output_text = str(rresult.text_path) if rresult.text_path else None
    except Exception as e:  # noqa: BLE001 — record per-file failure, continue batch
        log.exception("Batch: failed on %s", pdf)
        result.error = f"{type(e).__name__}: {e}"
    result.elapsed_seconds = time.monotonic() - started
    return result


def run_batch(
    input_dir: Path | str,
    output_dir: Path | str,
    *,
    profile_path: Path | str | None = None,
    mode: Mode = "both",
    use_stage2: bool = True,
    spacy_model: str = "en_core_web_sm",
    workers: int = 1,
    force: bool = False,
    on_progress: Callable[[FileResult], None] | None = None,
) -> BatchResult:
    """Walk `input_dir` for *.pdf files and process each.

    Parameters
    ----------
    workers:
        Concurrent file processing. The Presidio analyzer is constructed per
        thread, so 1 is fast for small batches; bump up only for hundreds of
        documents on a multi-core machine.
    force:
        Reprocess files whose outputs already exist. Default is to skip them
        (resume-on-rerun).
    on_progress:
        Called with each `FileResult` as it completes — for CLI progress bars.

    Returns a `BatchResult` summary; also written to `<output_dir>/manifest.json`.
    """
    input_root = Path(input_dir).resolve()
    output_root = Path(output_dir).resolve()
    if not input_root.is_dir():
        raise NotADirectoryError(input_root)
    output_root.mkdir(parents=True, exist_ok=True)

    profile: CustomEntityProfile | None = None
    if profile_path:
        profile = load_profile(profile_path)

    # Exclude paths inside `output_root` — without this, when output_dir is nested
    # inside input_dir (a perfectly normal layout), rglob picks up the previously
    # generated .redacted.pdf files and reprocesses them on the next run.
    resolved_output = output_root.resolve()

    def _is_inside_output(p: Path) -> bool:
        try:
            p.resolve().relative_to(resolved_output)
            return True
        except ValueError:
            return False

    pdfs = sorted(p for p in input_root.rglob("*.pdf") if not _is_inside_output(p))
    log.info("Batch: found %d PDFs under %s", len(pdfs), input_root)

    started_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started_mono = time.monotonic()
    file_results: list[FileResult] = []

    def _work(pdf: Path) -> FileResult:
        # Create the file's parent dir in the output tree before processing
        # so PyMuPDF's save() doesn't have to.
        rel = pdf.relative_to(input_root)
        (output_root / rel.parent).mkdir(parents=True, exist_ok=True)
        return _process_one(
            pdf, input_root, output_root, profile, mode, use_stage2, spacy_model, force
        )

    if workers > 1 and len(pdfs) > 1:
        # ThreadPool is fine here: the heavy work is in C (PyMuPDF, spaCy) and
        # releases the GIL. ProcessPool would have to re-init the spaCy model
        # per worker, which dwarfs any parallelism gain on a small batch.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_work, p): p for p in pdfs}
            for fut in as_completed(futures):
                result = fut.result()
                file_results.append(result)
                if on_progress:
                    on_progress(result)
    else:
        for pdf in pdfs:
            result = _work(pdf)
            file_results.append(result)
            if on_progress:
                on_progress(result)

    ended_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summary = BatchResult(
        input_dir=str(input_root),
        output_dir=str(output_root),
        started_at=started_iso,
        ended_at=ended_iso,
        total=len(file_results),
        succeeded=sum(1 for r in file_results if r.error is None and not r.skipped),
        skipped=sum(1 for r in file_results if r.skipped),
        failed=sum(1 for r in file_results if r.error is not None),
        files=file_results,
    )

    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(asdict(summary), indent=2), encoding="utf-8")
    log.info(
        "Batch: %d files (%d succeeded, %d skipped, %d failed) in %.1fs",
        summary.total,
        summary.succeeded,
        summary.skipped,
        summary.failed,
        time.monotonic() - started_mono,
    )
    return summary


def _cli(argv: list[str] | None = None) -> int:
    """`securepdf-batch` command."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="securepdf-batch",
        description="Process every PDF in a folder through SecurePDF's pipeline.",
    )
    parser.add_argument("input_dir", type=Path, help="Folder containing PDFs (searched recursively)")
    parser.add_argument("output_dir", type=Path, help="Where to write outputs + manifest.json")
    parser.add_argument("--profile", type=Path, help="YAML custom entity profile")
    parser.add_argument(
        "--mode",
        choices=["pdf", "text", "both"],
        default="both",
        help="Which outputs to produce per file",
    )
    parser.add_argument("--no-stage2", action="store_true", help="Skip Gemma contextual pass")
    parser.add_argument(
        "--spacy-model",
        default="en_core_web_sm",
        help="spaCy model (en_core_web_sm or en_core_web_lg)",
    )
    parser.add_argument("--workers", type=int, default=1, help="Concurrent files (default 1)")
    parser.add_argument("--force", action="store_true", help="Reprocess files even if outputs exist")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    def _on_progress(r: FileResult) -> None:
        status = "✗" if r.error else "⏭" if r.skipped else "✓"
        print(
            f"{status} {Path(r.input_path).name:40s} "
            f"({r.detection_count:3d} det)  {r.elapsed_seconds:5.1f}s"
            + (f"  {r.error}" if r.error else "")
        )

    summary = run_batch(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        profile_path=args.profile,
        mode=args.mode,
        use_stage2=not args.no_stage2,
        spacy_model=args.spacy_model,
        workers=args.workers,
        force=args.force,
        on_progress=_on_progress,
    )

    print(
        f"\nBatch complete: {summary.succeeded}/{summary.total} succeeded, "
        f"{summary.skipped} skipped, {summary.failed} failed"
    )
    print(f"Manifest: {Path(summary.output_dir) / 'manifest.json'}")
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(_cli())

"""Batch processing — run the SecurePDF pipeline over a folder of PDFs.

For users with thousands of documents to clean: drop them all into a directory,
point `securepdf-batch` at it, walk away. The module handles resume-on-rerun
(skips files whose outputs already exist), continues on per-file errors, and
writes a JSON manifest summarizing the run.
"""

from securepdf.batch.pipeline import BatchResult, FileResult, run_batch

__all__ = ["BatchResult", "FileResult", "run_batch"]

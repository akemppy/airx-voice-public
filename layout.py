"""layout.py - the few job-folder rules AirX Voice needs, carried inside the app.

A copy of what `Cowork Files\\Claude\\job_layout.py` defines (the one definition of the estimating tree),
because an installed app can't depend on that folder being on the PC. tests/run_phrases.py checks these
still match job_layout.py whenever that file is here.
"""
import os
import re

JOB_RE = re.compile(r"^\d{2} \d{2} .+")               # a live bid folder: "MM DD <Name>"
MASTER = "MASTER ESTIMATING FOLDER"
BID_SHEET_GLOB = "*BID Sheet*.xls*"
TAKEOFF_PDF_GLOB = "_takeoff*.pdf"
ROOT_FILES = (BID_SHEET_GLOB, TAKEOFF_PDF_GLOB, "AirX*Proposal*.docx", "AirX*Proposal*.pdf",
              "_DRAFT_AirX*Proposal*", "Basis of Design*", "BOD.docx", "BOD.pdf")


def estimating_root(configured=""):
    """<AirX LLC>/Operations - Documents/01 - Estimating as synced on this PC, never the 'OneDrive - AirX LLC' decoy."""
    cands = [configured, os.path.join(os.path.expanduser("~"), "AirX LLC", "Operations - Documents", "01 - Estimating")]
    for est in cands:
        if est and "OneDrive - AirX LLC" not in est and os.path.isdir(os.path.join(est, MASTER)):
            return est
    return ""

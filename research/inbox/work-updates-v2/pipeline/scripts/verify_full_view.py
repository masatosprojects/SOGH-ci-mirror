"""Run from repository root or pipeline root without changing Claude's code."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from admissions_pipeline.full_view import main

if __name__=='__main__':main()

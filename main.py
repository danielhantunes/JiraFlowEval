"""
Entry point for JiraFlowEval.
Run:  python main.py
  or: python main.py evaluate --file input/repos.xlsx
"""
import sys

from evaluator.cli import app

if __name__ == "__main__":
    # If no args, default to evaluate with input/repos.xlsx
    if len(sys.argv) == 1:
        sys.argv.extend(["evaluate", "--file", "input/repos.xlsx"])
    app()

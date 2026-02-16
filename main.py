"""
Entry point for JiraFlowEval.
Run:  python main.py
  or: python main.py --file input/repos.xlsx --output repos_evaluated.xlsx
  or: python main.py evaluate --file input/repos.xlsx
"""
from evaluator.cli import app

if __name__ == "__main__":
    app()

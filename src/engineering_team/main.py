#!/usr/bin/env python
import argparse
import os
from pathlib import Path

from engineering_team.crew import EngineeringTeam


def run() -> None:
    parser = argparse.ArgumentParser(description="Run the EngineeringTeam code-generation workflow.")
    parser.add_argument("requirements", nargs="?", help="Software requirements for the team.")
    args = parser.parse_args()
    requirements = args.requirements or os.getenv("ENGINEERING_TEAM_REQUIREMENTS")
    if not requirements or not requirements.strip():
        parser.error("provide requirements or set ENGINEERING_TEAM_REQUIREMENTS")

    output_dir = Path(__file__).resolve().parents[2] / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    crew = EngineeringTeam().crew()
    output_paths = (
        output_dir / "design.md",
        output_dir / "main.py",
        output_dir / "app.py",
        output_dir / "test_main.py",
    )
    for task, output_path in zip(crew.tasks, output_paths):
        task.output_file = str(output_path)

    crew.kickoff(
        inputs={
            "requirements": requirements.strip(),
            "module_name": "main.py",
            "class_name": "GeneratedProject",
        }
    )


if __name__ == "__main__":
    run()

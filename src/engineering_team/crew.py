import os

from crewai import Agent, Crew, Process, Task
from crewai import LLM
from crewai.project import CrewBase, agent, crew, task


MODEL_TIMEOUT_SECONDS = 90
AGENT_TIMEOUT_SECONDS = 120


def configured_llm() -> LLM:
    return LLM(
        model=os.getenv("ENGINEERING_TEAM_MODEL", "groq/llama-3.3-70b-versatile"),
        timeout=MODEL_TIMEOUT_SECONDS,
        max_tokens=4096,
    )



@CrewBase
class EngineeringTeam:
    """EngineeringTeam crew"""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def engineering_lead(self) -> Agent:
        return Agent(
            config=self.agents_config["engineering_lead"],
            llm=configured_llm(),
            verbose=False,
            max_execution_time=AGENT_TIMEOUT_SECONDS,
            max_iter=3,
            max_retry_limit=1,
        )

    @agent
    def backend_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config["backend_engineer"],
            llm=configured_llm(),
            verbose=False,
            allow_code_execution=False,
            max_execution_time=AGENT_TIMEOUT_SECONDS,
            max_iter=3,
            max_retry_limit=1,
        )

    @agent
    def frontend_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config["frontend_engineer"],
            llm=configured_llm(),
            verbose=False,
            max_execution_time=AGENT_TIMEOUT_SECONDS,
            max_iter=3,
            max_retry_limit=1,
        )

    @agent
    def test_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config["test_engineer"],
            llm=configured_llm(),
            verbose=False,
            allow_code_execution=False,
            max_execution_time=AGENT_TIMEOUT_SECONDS,
            max_iter=3,
            max_retry_limit=1,
        )

    @task
    def design_task(self) -> Task:
        return Task(config=self.tasks_config["design_task"])

    @task
    def code_task(self) -> Task:
        return Task(config=self.tasks_config["code_task"])

    @task
    def frontend_task(self) -> Task:
        return Task(config=self.tasks_config["frontend_task"])

    @task
    def test_task(self) -> Task:
        return Task(config=self.tasks_config["test_task"])

    @crew
    def crew(self, task_callback=None) -> Crew:
        """Create the sequential engineering team."""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
            task_callback=task_callback,
        )
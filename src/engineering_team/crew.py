import os

from crewai import Agent, Crew, Process, Task
from crewai import LLM
from crewai.project import CrewBase, agent, crew, task

from engineering_team.provider import DEFAULT_MODEL, GROQ_API_BASE, normalize_groq_api_key


MODEL_TIMEOUT_SECONDS = 90
AGENT_TIMEOUT_SECONDS = 120


def configured_llm(
    *,
    max_tokens: int = 4096,
    timeout: int = MODEL_TIMEOUT_SECONDS,
) -> LLM:
    model = os.getenv("ENGINEERING_TEAM_MODEL", DEFAULT_MODEL).strip()
    options: dict[str, str] = {}
    if model.startswith("groq/"):
        api_key = normalize_groq_api_key(os.getenv("GROQ_API_KEY", ""))
        if api_key:
            os.environ["GROQ_API_KEY"] = api_key
            options = {"api_key": api_key, "base_url": GROQ_API_BASE}
    return LLM(
        model=model,
        timeout=timeout,
        max_tokens=max_tokens,
        **options,
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
import pytest


pytestmark = pytest.mark.core


@pytest.mark.parametrize(
    "case_module",
    [
        "tests.backend._cases.agents.case_agent_harness",
        "tests.backend._cases.agents.case_agent_runner",
    ],
    ids=["harness", "background-runner"],
)
def test_agent_runtime(case_module: str, run_isolated_case) -> None:
    run_isolated_case(case_module)

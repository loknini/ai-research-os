import pytest


pytestmark = pytest.mark.core


def test_agent_teams(run_isolated_case) -> None:
    run_isolated_case("tests.backend._cases.agents.case_agent_teams")

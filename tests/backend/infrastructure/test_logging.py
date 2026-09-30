import pytest


pytestmark = [pytest.mark.fast, pytest.mark.core]


def test_logging_system(run_isolated_case) -> None:
    run_isolated_case("tests.backend._cases.infrastructure.case_logging")

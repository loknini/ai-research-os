import pytest


@pytest.mark.parametrize(
    "case_module",
    [
        pytest.param(
            "tests.backend._cases.infrastructure.case_migrations",
            marks=pytest.mark.core,
            id="schema-migrations",
        ),
        pytest.param(
            "tests.backend._cases.infrastructure.case_init_race",
            id="multi-process-init",
        ),
        pytest.param(
            "tests.backend._cases.infrastructure.case_correctness",
            id="correctness-regressions",
        ),
    ],
)
def test_database_and_correctness(case_module: str, run_isolated_case) -> None:
    run_isolated_case(case_module)

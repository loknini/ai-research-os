import pytest


pytestmark = pytest.mark.core


def test_rag_job_queue(run_isolated_case) -> None:
    run_isolated_case("tests.backend._cases.rag.case_rag_queue")

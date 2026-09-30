import pytest


pytestmark = pytest.mark.core


def test_vector_store(run_isolated_case) -> None:
    run_isolated_case("tests.backend._cases.rag.case_vec")

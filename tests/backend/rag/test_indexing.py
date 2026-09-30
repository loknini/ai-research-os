import pytest


@pytest.mark.parametrize(
    "case_module",
    [
        pytest.param(
            "tests.backend._cases.rag.case_rag_v21",
            marks=pytest.mark.core,
            id="generation-and-security",
        ),
        pytest.param("tests.backend._cases.rag.case_rag", id="full-indexing"),
    ],
)
def test_rag_indexing(case_module: str, run_isolated_case) -> None:
    run_isolated_case(case_module)

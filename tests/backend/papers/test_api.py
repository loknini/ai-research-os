import pytest


@pytest.mark.parametrize(
    "case_module",
    [
        pytest.param(
            "tests.backend._cases.papers.case_papers_fetch",
            marks=pytest.mark.core,
            id="fetch-contract",
        ),
        pytest.param(
            "tests.backend._cases.papers.case_paper_pdf_stream",
            marks=pytest.mark.core,
            id="pdf-stream",
        ),
        pytest.param(
            "tests.backend._cases.papers.case_pdf_viewer_render",
            id="viewer-source-contract",
        ),
        pytest.param(
            "tests.backend._cases.papers.case_pdf_worker_dev",
            id="pdf-worker",
        ),
    ],
)
def test_paper_api_and_pdf(case_module: str, run_isolated_case) -> None:
    run_isolated_case(case_module)

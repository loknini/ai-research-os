import pytest


pytestmark = [pytest.mark.fast, pytest.mark.core]


def test_conversation_contracts(run_isolated_case) -> None:
    run_isolated_case("tests.backend._cases.chat.case_chat_conversations")

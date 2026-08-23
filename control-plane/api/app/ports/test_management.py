"""Port: where generated test cases are written.

Demo adapter: local JSON file. Future: Jira/Zephyr, TestRail.
"""

from typing import ClassVar, Protocol

from pydantic import BaseModel


class TestCaseRecord(BaseModel):
    __test__: ClassVar[bool] = False  # not a pytest test class

    id: str
    run_id: str
    story_ref: str
    gherkin_text: str


class TestManagement(Protocol):
    async def create_test_case(self, run_id: str, tc: TestCaseRecord) -> TestCaseRecord: ...

    async def list_test_cases(self, run_id: str) -> list[TestCaseRecord]: ...

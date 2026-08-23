import json
from pathlib import Path

import anyio

from app.ports.test_management import TestCaseRecord

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
TEST_CASES_FILE = DATA_DIR / "test_cases.json"


class JsonFileTestManagement:
    """Demo-default TestManagement adapter: append/read a local JSON file."""

    async def create_test_case(self, run_id: str, tc: TestCaseRecord) -> TestCaseRecord:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        records = await self._read_all()
        records.append(tc.model_dump())
        await self._write_all(records)
        return tc

    async def list_test_cases(self, run_id: str) -> list[TestCaseRecord]:
        records = await self._read_all()
        return [TestCaseRecord(**r) for r in records if r["run_id"] == run_id]

    async def _read_all(self) -> list[dict]:
        if not TEST_CASES_FILE.exists():
            return []
        content = await anyio.Path(TEST_CASES_FILE).read_text()
        return json.loads(content) if content.strip() else []

    async def _write_all(self, records: list[dict]) -> None:
        await anyio.Path(TEST_CASES_FILE).write_text(json.dumps(records, indent=2))

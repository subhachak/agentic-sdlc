import csv
import io

from app.ports.requirements_source import RequirementsDoc, RequirementsInput


class PlainTextCSVRequirementsSource:
    """Demo-default RequirementsSource adapter: accepts freeform text or a
    CSV upload, no external system involved.
    """

    async def fetch(self, raw: RequirementsInput) -> RequirementsDoc:
        if raw.file_bytes is not None and (raw.filename or "").lower().endswith(".csv"):
            text = raw.file_bytes.decode("utf-8", errors="replace")
            rows = list(csv.reader(io.StringIO(text)))
            item_count = max(len(rows) - 1, 0) if rows else 0  # exclude header row
            return RequirementsDoc(text=text, source_type="csv", item_count=item_count)

        text = raw.text or ""
        return RequirementsDoc(text=text, source_type="text", item_count=1 if text.strip() else 0)

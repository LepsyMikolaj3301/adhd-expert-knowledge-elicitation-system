import time
from pathlib import Path

from docling.document_converter import DocumentConverter

data_raw_path = Path("/workspace/data/raw")
data_parsed_path = data_raw_path / "pdf_parsed"
data_parsed_path.mkdir(parents=True, exist_ok=True)

converter = DocumentConverter()

for pdf_path in sorted(data_raw_path.glob("*.pdf")):
    start = time.perf_counter()
    result = converter.convert(pdf_path)
    elapsed = time.perf_counter() - start
    doc = result.document

    doc.save_as_json(str(data_parsed_path / f"{pdf_path.stem}.docling.json"))
    markdown = doc.export_to_markdown()
    (data_parsed_path / f"{pdf_path.stem}.md").write_text(markdown)

    print(
        f"{pdf_path.name}: {len(doc.pages)} pages, {len(doc.texts)} text items, "
        f"{len(doc.tables)} tables, {len(doc.pictures)} pictures, "
        f"{len(markdown)} md chars, {elapsed:.1f}s, status={result.status.value}"
    )

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.extractors.office import validate_office_zip
from backend.types import ExtractionResult

GROUP_CANDIDATES = ("cliente", "departamento", "proveedor", "proyecto", "categoria", "tipo")


def extract_csv(path: Path) -> ExtractionResult:
    raw = path.read_bytes()
    encoding = "utf-8"
    sample = ""
    for candidate in ("utf-8", "latin-1", "cp1252"):
        try:
            sample = raw[:2048].decode(candidate)
            encoding = candidate
            break
        except UnicodeDecodeError:
            continue
    separator = ";" if sample.count(";") > sample.count(",") else ","
    dataframe = pd.read_csv(path, sep=separator, encoding=encoding, on_bad_lines="skip")
    return dataframe_to_result(path, dataframe, encoding=encoding, separator=separator)


def extract_xlsx(path: Path) -> ExtractionResult:
    validate_office_zip(path)
    sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
    frames: list[pd.DataFrame] = []
    for sheet_name, frame in sheets.items():
        frame = frame.copy()
        frame["__sheet__"] = sheet_name
        frames.append(frame)
    dataframe = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return dataframe_to_result(path, dataframe, sheet_names=list(sheets.keys()))


def dataframe_to_result(
    path: Path,
    dataframe: pd.DataFrame,
    *,
    encoding: str | None = None,
    separator: str | None = None,
    sheet_names: list[str] | None = None,
) -> ExtractionResult:
    dataframe = dataframe.copy()
    dataframe.columns = [str(column).strip() for column in dataframe.columns]
    rows = dataframe.fillna("").to_dict(orient="records")
    table_rows: list[dict[str, str]] = []
    lines: list[str] = []
    row_spans: list[tuple[int, int]] = []

    intro = f"Tabular document {path.name}. Rows: {len(rows)}. Columns: {', '.join(dataframe.columns)}."
    lines.append(intro)
    current_offset = len(intro) + 1

    for index, row in enumerate(rows):
        record = {str(key): str(value).strip() for key, value in row.items() if str(value).strip()}
        table_rows.append(record)
        parts = [f"{column}: {value}" for column, value in record.items()]
        line = f"Row {index}. " + " | ".join(parts)
        lines.append(line)
        row_spans.append((current_offset, current_offset + len(line)))
        current_offset += len(line) + 1

    group_key = None
    lowercase_columns = {column.lower(): column for column in dataframe.columns}
    for candidate in GROUP_CANDIDATES:
        if candidate in lowercase_columns:
            group_key = lowercase_columns[candidate]
            break

    metadata = {
        "encoding": encoding,
        "separator": separator,
        "sheet_names": sheet_names or [],
        "row_count": len(table_rows),
        "column_count": len(dataframe.columns),
    }
    return ExtractionResult(
        path=path,
        text="\n".join(lines),
        metadata=metadata,
        table_rows=table_rows,
        row_spans=row_spans,
        table_group_key=group_key,
    )

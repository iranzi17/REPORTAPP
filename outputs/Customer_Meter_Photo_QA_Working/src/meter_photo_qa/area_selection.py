"""District-qualified selectors and SQL filters for Rwanda administrative boundaries.

The one-district plain sector/cell interface remains backwards compatible.
A multi-district selection requires qualified sector/cell tokens of the form
'District :: Sector' and 'District :: Sector :: Cell' to prevent ambiguous
names from silently selecting the wrong locations.
"""
from __future__ import annotations

from collections.abc import Sequence

SEPARATOR = " :: "


def selected_districts(value: str | Sequence[str] | None) -> list[str]:
    if not value:
        return []
    source = value.split(";") if isinstance(value, str) else value
    districts = []
    used = set()
    for item in source:
        name = str(item or "").strip().strip("\"'")
        if name and name.casefold() not in used:
            districts.append(name)
            used.add(name.casefold())
    return districts


def _sql(value: str) -> str:
    return "'" + value.upper().replace("'", "''") + "'"


def _tokens(values: Sequence[str] | None) -> list[str]:
    return [str(value).strip().strip("\"'") for value in (values or []) if str(value).strip()]


def district_filters(
    district: str | Sequence[str] | None,
    sectors: Sequence[str] | None = None,
    cells: Sequence[str] | None = None,
) -> str | None:
    """Return safe SQL covering exactly the requested district-qualified areas."""
    districts = selected_districts(district)
    sector_values, cell_values = _tokens(sectors), _tokens(cells)
    if not districts:
        if sector_values or cell_values:
            raise ValueError("Choose one or more districts before choosing sectors or cells.")
        return None
    if cell_values and not sector_values:
        raise ValueError("Choose sector(s) before choosing cells.")
    lookup = {name.casefold(): name for name in districts}
    multi = len(districts) > 1

    qualified_sectors = set()
    for value in sector_values:
        parts = [part.strip() for part in value.split(SEPARATOR)]
        if multi and len(parts) != 2:
            raise ValueError("When selecting multiple districts, sectors must be 'District :: Sector'.")
        if len(parts) == 1 and not multi:
            parts = [districts[0], parts[0]]
        if len(parts) != 2 or not all(parts) or parts[0].casefold() not in lookup:
            raise ValueError(f"Sector selection is outside the selected districts: {value}")
        qualified_sectors.add((lookup[parts[0].casefold()], parts[1]))

    qualified_cells = set()
    for value in cell_values:
        parts = [part.strip() for part in value.split(SEPARATOR)]
        if multi and len(parts) != 3:
            raise ValueError("When selecting multiple districts, cells must be 'District :: Sector :: Cell'.")
        if len(parts) == 1 and not multi:
            # The old single-district picker has plain cell names.
            # A cell name may occur in more than one selected sector; use
            # OR across each selected sector rather than a cross-product.
            candidates = [pair for pair in qualified_sectors]
            if not candidates:
                raise ValueError("Choose a sector before choosing cells.")
            for candidate in candidates:
                qualified_cells.add((*candidate, parts[0]))
            continue
        if len(parts) == 3 and all(parts) and parts[0].casefold() in lookup:
            district_name = lookup[parts[0].casefold()]
            if (district_name, parts[1]) not in qualified_sectors:
                raise ValueError(f"Cell is outside the selected sectors: {value}")
            qualified_cells.add((district_name, parts[1], parts[2]))
        else:
            raise ValueError(f"Invalid selected cell: {value}")

    if qualified_cells:
        clauses = [
            "(UPPER(district) = " + _sql(d) +
            " AND UPPER(sector) = " + _sql(s) +
            " AND UPPER(cell) = " + _sql(c) + ")"
            for d, s, c in sorted(qualified_cells)
        ]
    elif qualified_sectors:
        clauses = [
            "(UPPER(district) = " + _sql(d) +
            " AND UPPER(sector) = " + _sql(s) + ")"
            for d, s in sorted(qualified_sectors)
        ]
    else:
        clauses = ["UPPER(district) IN (" + ", ".join(_sql(d) for d in districts) + ")"]
    return "(" + " OR ".join(clauses) + ")"

"""Small shared helpers: bbox validation, date parsing, logging flags."""

from __future__ import annotations

from datetime import date, datetime


def log(msg: str) -> None:
    """Short status flag so users know the code is running."""
    print(f"[wfi2mask] {msg}")


def warn(msg: str) -> None:
    print(f"[wfi2mask] AVISO: {msg}")


def validate_bbox(bbox) -> list:
    """Validate a [min_lon, min_lat, max_lon, max_lat] bounding box."""
    if bbox is None:
        raise ValueError(
            "bbox é obrigatório. Formato: [lon_min, lat_min, lon_max, lat_max], "
            "ex.: [-46.65, -23.85, -46.45, -23.65]"
        )
    bbox = list(map(float, bbox))
    if len(bbox) != 4:
        raise ValueError("bbox deve ter 4 valores: [lon_min, lat_min, lon_max, lat_max]")
    lon_min, lat_min, lon_max, lat_max = bbox
    if not (-180 <= lon_min < lon_max <= 180):
        raise ValueError(f"Longitudes inválidas no bbox: {lon_min}, {lon_max}")
    if not (-90 <= lat_min < lat_max <= 90):
        raise ValueError(f"Latitudes inválidas no bbox: {lat_min}, {lat_max}")
    return bbox


def parse_dates(date_arg) -> tuple[date, date]:
    """Parse the ``date`` argument of :func:`wfi2mask.get_toa`.

    Accepts:
      * "2024-08-01"                       -> single day
      * "2024-08-01, 2024-09-30"           -> range (comma separated)
      * ("2024-08-01", "2024-09-30")       -> tuple/list of strings
      * (date(2024, 8, 1), date(2024, 9, 30))
    """
    if date_arg is None:
        raise ValueError(
            'date é obrigatório. Use "AAAA-MM-DD" ou "AAAA-MM-DD, AAAA-MM-DD".'
        )

    def _one(d):
        if isinstance(d, date) and not isinstance(d, datetime):
            return d
        if isinstance(d, datetime):
            return d.date()
        return datetime.strptime(str(d).strip(), "%Y-%m-%d").date()

    if isinstance(date_arg, str):
        parts = [p for p in date_arg.replace(";", ",").split(",") if p.strip()]
    elif isinstance(date_arg, (list, tuple)):
        parts = list(date_arg)
    else:
        parts = [date_arg]

    if len(parts) == 1:
        d = _one(parts[0])
        return d, d
    if len(parts) == 2:
        d0, d1 = _one(parts[0]), _one(parts[1])
        if d1 < d0:
            d0, d1 = d1, d0
        return d0, d1
    raise ValueError(f"date deve conter 1 ou 2 datas, recebido: {date_arg!r}")

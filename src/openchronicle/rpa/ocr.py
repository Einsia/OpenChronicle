"""OCR observer abstraction with optional PaddleOCR support."""

from __future__ import annotations

from typing import Any


class OCRObserver:
    """Base OCR interface used by providers and workflow verification."""

    def recognize(
        self, image_path: str, region: list[int] | None = None
    ) -> list[dict[str, Any]]:
        raise NotImplementedError


class EmptyOCRObserver(OCRObserver):
    """No-op OCR implementation used when no local OCR backend is configured."""

    def recognize(
        self, image_path: str, region: list[int] | None = None
    ) -> list[dict[str, Any]]:
        del image_path, region
        return []


class PaddleOCRObserver(OCRObserver):
    """Lazy PaddleOCR adapter.

    PaddleOCR initialization can be expensive and may load local model files, so
    the object is created only on the first recognition call.
    """

    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs
        self._engine: Any | None = None
        self.last_error = ""

    def _load(self) -> Any | None:
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR  # type: ignore[import-not-found]

            self._engine = PaddleOCR(**self._kwargs)
        except Exception as exc:  # noqa: BLE001 - optional dependency failures should not crash RPA
            self.last_error = str(exc)
            return None
        return self._engine

    def recognize(
        self, image_path: str, region: list[int] | None = None
    ) -> list[dict[str, Any]]:
        engine = self._load()
        if engine is None:
            return []
        target = image_path
        try:
            result = engine.ocr(target, cls=False)
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            return []
        return _normalize_paddle_result(result, region=region)


def _normalize_paddle_result(
    result: Any, *, region: list[int] | None = None
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not result:
        return rows
    offset_x = region[0] if region else 0
    offset_y = region[1] if region else 0
    pages = result if isinstance(result, list) else [result]
    for page in pages:
        if not page:
            continue
        for item in page:
            try:
                points = item[0]
                text, confidence = item[1]
                xs = [int(p[0]) + offset_x for p in points]
                ys = [int(p[1]) + offset_y for p in points]
            except (TypeError, ValueError, IndexError):
                continue
            rows.append(
                {
                    "text": str(text),
                    "box": [min(xs), min(ys), max(xs), max(ys)],
                    "confidence": float(confidence),
                }
            )
    return rows


def create_ocr_observer(*, prefer_paddle: bool = True) -> OCRObserver:
    if not prefer_paddle:
        return EmptyOCRObserver()
    return PaddleOCRObserver(use_angle_cls=False, lang="ch")

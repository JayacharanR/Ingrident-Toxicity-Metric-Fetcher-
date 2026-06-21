"""
OCR text extraction using PaddleOCR.

Wraps PaddleOCR to extract raw text from preprocessed food label images,
with confidence filtering and line-ordering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from src.config import OCR_LANGUAGE, OCR_MIN_CONFIDENCE
from src.ocr.preprocessor import preprocess

logger = logging.getLogger(__name__)


@dataclass
class TextBox:
    """A single detected text region from OCR."""
    text: str
    confidence: float
    # Bounding-box coordinates [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
    bbox: list[list[float]] = field(default_factory=list)

    @property
    def y_center(self) -> float:
        """Vertical center of the bounding box (for sorting top→bottom)."""
        if not self.bbox:
            return 0.0
        return sum(pt[1] for pt in self.bbox) / len(self.bbox)

    @property
    def x_center(self) -> float:
        """Horizontal center of the bounding box (for sorting left→right)."""
        if not self.bbox:
            return 0.0
        return sum(pt[0] for pt in self.bbox) / len(self.bbox)


class TextExtractor:
    """Extract text from food label images using PaddleOCR.

    Usage:
        extractor = TextExtractor()
        text = extractor.extract("path/to/label.jpg")
    """

    def __init__(
        self,
        language: str = OCR_LANGUAGE,
        min_confidence: float = OCR_MIN_CONFIDENCE,
    ) -> None:
        self.language = language
        self.min_confidence = min_confidence
        self._ocr = None  # Lazy init to avoid slow import at startup

    def _get_ocr(self):
        """Lazily initialise PaddleOCR (first call downloads models ~100 MB)."""
        if self._ocr is None:
            import os
            os.environ["FLAGS_use_mkldnn"] = "0"
            os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(
                lang=self.language,
                enable_mkldnn=False,
            )
        return self._ocr

    def detect(
        self,
        image: NDArray[np.uint8] | str | Path,
    ) -> list[TextBox]:
        """Run OCR on an image and return individual text boxes.

        Args:
            image: Either a preprocessed NumPy image or a file path.

        Returns:
            List of TextBox objects sorted top-to-bottom, left-to-right.
        """
        ocr = self._get_ocr()

        # PaddleOCR v3 has its own doc preprocessing pipeline, so pass
        # file paths directly. Only use our preprocessor for raw arrays.
        if isinstance(image, (str, Path)):
            ocr_input = str(image)
        else:
            ocr_input = image

        results = list(ocr.predict(ocr_input))

        boxes: list[TextBox] = []
        if not results:
            logger.warning("PaddleOCR returned no results")
            return boxes

        # PaddleOCR v3 returns OCRResult objects with rec_texts, rec_scores, dt_polys
        for ocr_result in results:
            texts = ocr_result.get("rec_texts", [])
            scores = ocr_result.get("rec_scores", [])
            polys = ocr_result.get("dt_polys", [])

            for i, text in enumerate(texts):
                confidence = scores[i] if i < len(scores) else 0.0
                if confidence >= self.min_confidence:
                    # Convert numpy polygon to list of [x, y] pairs
                    bbox = []
                    if i < len(polys):
                        poly = polys[i]
                        bbox = [[float(pt[0]), float(pt[1])] for pt in poly]

                    boxes.append(TextBox(
                        text=text.strip(),
                        confidence=float(confidence),
                        bbox=bbox,
                    ))

        # Sort by vertical position, then horizontal (reading order)
        boxes.sort(key=lambda b: (b.y_center, b.x_center))
        return boxes

    def extract(
        self,
        image: NDArray[np.uint8] | str | Path,
    ) -> str:
        """Extract all text from an image as a single string.

        Args:
            image: Preprocessed image array or path to an image file.

        Returns:
            Concatenated text from all detected boxes, joined by newlines.
        """
        boxes = self.detect(image)
        return "\n".join(box.text for box in boxes)

    def extract_with_confidence(
        self,
        image: NDArray[np.uint8] | str | Path,
    ) -> tuple[str, float]:
        """Extract text and return the average OCR confidence.

        Returns:
            Tuple of (full_text, average_confidence).
        """
        boxes = self.detect(image)
        if not boxes:
            return "", 0.0

        full_text = "\n".join(box.text for box in boxes)
        avg_conf = sum(b.confidence for b in boxes) / len(boxes)
        return full_text, round(avg_conf, 3)

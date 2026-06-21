"""
Image preprocessing for food label OCR.

Applies a sequence of transformations to make ingredient text easier to
extract: resize, grayscale, contrast enhancement, adaptive thresholding,
and optional deskewing.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray


def load_image(image_path: str | Path) -> NDArray[np.uint8]:
    """Load an image from disk.

    Args:
        image_path: Absolute or relative path to the image file.

    Returns:
        The image as a BGR NumPy array.

    Raises:
        FileNotFoundError: If the image file does not exist.
        ValueError: If OpenCV cannot decode the file.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"Could not decode image: {path}")

    return img


def resize_image(
    image: NDArray[np.uint8],
    max_width: int = 1920,
    max_height: int = 1080,
) -> NDArray[np.uint8]:
    """Resize an image to fit within max dimensions while keeping aspect ratio.

    Args:
        image: Input BGR image.
        max_width: Maximum allowed width in pixels.
        max_height: Maximum allowed height in pixels.

    Returns:
        Resized image (or the original if already small enough).
    """
    h, w = image.shape[:2]
    if w <= max_width and h <= max_height:
        return image

    scale = min(max_width / w, max_height / h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)


def to_grayscale(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Convert a BGR image to grayscale."""
    if len(image.shape) == 2:
        return image  # Already grayscale
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def enhance_contrast(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Apply CLAHE (Contrast Limited Adaptive Histogram Equalization).

    This dramatically improves OCR accuracy on low-contrast labels or images
    taken in poor lighting.
    """
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(image)


def denoise(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Remove noise while preserving edges using a bilateral filter."""
    return cv2.bilateralFilter(image, d=9, sigmaColor=75, sigmaSpace=75)


def adaptive_threshold(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Apply adaptive Gaussian thresholding for binarization.

    This works well on labels with uneven lighting or shadows.
    """
    return cv2.adaptiveThreshold(
        image,
        maxValue=255,
        adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        thresholdType=cv2.THRESH_BINARY,
        blockSize=11,
        C=2,
    )


def deskew(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Correct slight rotation/skew in the image.

    Uses the minimum area rectangle of detected contours to estimate
    the skew angle and rotate the image to straighten text lines.
    """
    coords = np.column_stack(np.where(image > 0))
    if coords.shape[0] < 5:
        return image  # Not enough points to estimate skew

    angle = cv2.minAreaRect(coords)[-1]

    # cv2.minAreaRect returns angles in [-90, 0); normalise to [-45, 45]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    if abs(angle) < 0.5:
        return image  # Negligible skew

    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        image,
        rotation_matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def sharpen(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Apply a light sharpening kernel to crispen text edges."""
    kernel = np.array(
        [[0, -1, 0],
         [-1,  5, -1],
         [0, -1, 0]],
        dtype=np.float32,
    )
    return cv2.filter2D(image, -1, kernel)


def preprocess(
    image_path: str | Path,
    *,
    apply_threshold: bool = False,
    apply_deskew: bool = True,
) -> NDArray[np.uint8]:
    """Run the full preprocessing pipeline on a food label image.

    The pipeline order is:
      load → resize → grayscale → denoise → contrast → sharpen
      → (optional) deskew → (optional) adaptive threshold

    Args:
        image_path: Path to the input image.
        apply_threshold: Whether to binarize the image.  Leave *False* for
            PaddleOCR (which prefers grayscale), set *True* for Tesseract.
        apply_deskew: Whether to correct rotation.

    Returns:
        Preprocessed image ready for OCR.
    """
    img = load_image(image_path)
    img = resize_image(img)
    gray = to_grayscale(img)
    gray = denoise(gray)
    gray = enhance_contrast(gray)
    gray = sharpen(gray)

    if apply_deskew:
        gray = deskew(gray)

    if apply_threshold:
        gray = adaptive_threshold(gray)

    return gray

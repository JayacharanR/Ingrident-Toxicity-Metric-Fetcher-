"""
Unit tests for the OCR preprocessing module.
"""

from pathlib import Path
import pytest
import numpy as np
import cv2

from src.ocr.preprocessor import (
    load_image,
    resize_image,
    to_grayscale,
    enhance_contrast,
    denoise,
    adaptive_threshold,
    sharpen,
)


def test_load_image_not_found():
    """Test that load_image raises FileNotFoundError for a missing path."""
    with pytest.raises(FileNotFoundError):
        load_image("non_existent_file.jpg")


def test_load_image_invalid(tmp_path):
    """Test that load_image raises ValueError for an invalid/un-decodable file."""
    bad_file = tmp_path / "corrupted.jpg"
    bad_file.write_text("not an image")
    with pytest.raises(ValueError):
        load_image(bad_file)


def test_to_grayscale():
    """Test that to_grayscale converts BGR to 2D array."""
    # Create random BGR image
    bgr_img = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
    gray = to_grayscale(bgr_img)
    assert len(gray.shape) == 2
    assert gray.shape == (100, 100)

    # If already grayscale, should return as-is
    gray2 = to_grayscale(gray)
    assert gray2.shape == (100, 100)


def test_resize_image():
    """Test image resizing maintaining aspect ratio."""
    # Big image 2000 x 1000
    big_img = np.random.randint(0, 256, (1000, 2000, 3), dtype=np.uint8)
    resized = resize_image(big_img, max_width=1000, max_height=500)
    assert resized.shape[1] == 1000  # width scaled to max
    assert resized.shape[0] == 500   # height scaled accordingly

    # Small image should remain unchanged
    small_img = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
    resized_small = resize_image(small_img, max_width=500, max_height=500)
    assert resized_small.shape == (100, 100, 3)


def test_preprocessor_pipeline_functions():
    """Test that all basic image manipulation helper functions run without crashing."""
    gray_img = np.random.randint(0, 256, (100, 100), dtype=np.uint8)

    enhanced = enhance_contrast(gray_img)
    assert enhanced.shape == (100, 100)

    denoised = denoise(gray_img)
    assert denoised.shape == (100, 100)

    thresholded = adaptive_threshold(gray_img)
    assert thresholded.shape == (100, 100)

    sharpened = sharpen(gray_img)
    assert sharpened.shape == (100, 100)

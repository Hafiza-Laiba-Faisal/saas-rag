"""Preprocessing package for the OCR service.

Exports the :class:`ImagePreprocessor` class which applies an in-memory
OpenCV preprocessing pipeline to image arrays before OCR inference.
"""

from preprocessing.preprocessor import ImagePreprocessor

__all__ = ["ImagePreprocessor"]

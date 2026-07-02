"""
OCR Reader Module

Text extraction from screenshots using pytesseract and easyocr.
"""

import os
import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from loguru import logger


@dataclass
class OCRTextBlock:
    """A block of text found by OCR."""
    text: str
    bbox: Tuple[int, int, int, int]  # x, y, width, height
    confidence: float


class OCRReader:
    """OCR text extraction from images."""
    
    def __init__(self, use_easyocr: bool = False):
        self.use_easyocr = use_easyocr
        self._easyocr_reader = None
        
        if use_easyocr:
            try:
                import easyocr
                self._easyocr_reader = easyocr.Reader(['en'])
                logger.info("EasyOCR initialized")
            except ImportError:
                logger.warning("easyocr not installed, falling back to pytesseract")
                self.use_easyocr = False
    
    def read_image(self, image_path: str) -> List[OCRTextBlock]:
        """Read all text blocks from an image."""
        if self.use_easyocr and self._easyocr_reader:
            return self._read_easyocr(image_path)
        return self._read_pytesseract(image_path)
    
    def read_text(self, image_path: str) -> str:
        """Read plain text from an image."""
        blocks = self.read_image(image_path)
        return "\n".join([b.text for b in blocks])
    
    def find_text(self, image_path: str, pattern: str) -> List[OCRTextBlock]:
        """Find text matching a regex pattern."""
        blocks = self.read_image(image_path)
        regex = re.compile(pattern, re.IGNORECASE)
        matches = []
        for block in blocks:
            if regex.search(block.text):
                matches.append(block)
        return matches
    
    def extract_numbers(self, image_path: str) -> List[float]:
        """Extract all numbers from an image."""
        text = self.read_text(image_path)
        numbers = []
        for match in re.finditer(r'[\d,]+\.?\d*', text):
            try:
                num_str = match.group().replace(',', '')
                numbers.append(float(num_str))
            except ValueError:
                continue
        return numbers
    
    def extract_price(self, image_path: str) -> Optional[float]:
        """Extract a price value (number with $ or near currency indicators)."""
        text = self.read_text(image_path)
        # Look for $X.XX patterns
        match = re.search(r'\$?([\d,]+\.\d{2})', text)
        if match:
            try:
                return float(match.group(1).replace(',', ''))
            except ValueError:
                pass
        return None
    
    def extract_pnl(self, image_path: str) -> Optional[Dict[str, float]]:
        """Extract P&L values from a screenshot."""
        text = self.read_text(image_path)
        result = {}
        
        # Look for patterns like "P&L: +$123.45" or "Unrealized P/L: -50.00"
        pnl_patterns = [
            r'(?:P&L|P/L|Profit/Loss)\s*[:\-]?\s*\+?\$?([\d,]+\.?\d*)',
            r'(?:Unrealized|Realized)\s*(?:P&L|P/L)\s*[:\-]?\s*\+?\$?([\d,]+\.?\d*)',
            r'(?:Daily|Total)\s*(?:P&L|P/L)\s*[:\-]?\s*\+?\$?([\d,]+\.?\d*)',
        ]
        
        for pattern in pnl_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1).replace(',', ''))
                    result['pnl'] = value
                    break
                except ValueError:
                    continue
        
        return result if result else None
    
    def _read_pytesseract(self, image_path: str) -> List[OCRTextBlock]:
        """Read using pytesseract with bounding boxes."""
        try:
            from PIL import Image
            import pytesseract
            
            image = Image.open(image_path)
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            
            blocks = []
            n_boxes = len(data['text'])
            for i in range(n_boxes):
                text = data['text'][i].strip()
                if not text:
                    continue
                
                conf = int(data['conf'][i])
                if conf < 30:  # Skip low confidence
                    continue
                
                x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                blocks.append(OCRTextBlock(
                    text=text,
                    bbox=(x, y, w, h),
                    confidence=conf / 100.0
                ))
            
            return blocks
        except Exception as e:
            logger.error(f"Pytesseract OCR failed: {e}")
            return []
    
    def _read_easyocr(self, image_path: str) -> List[OCRTextBlock]:
        """Read using EasyOCR."""
        try:
            results = self._easyocr_reader.readtext(image_path)
            blocks = []
            for (bbox, text, conf) in results:
                x_coords = [p[0] for p in bbox]
                y_coords = [p[1] for p in bbox]
                x, y = int(min(x_coords)), int(min(y_coords))
                w = int(max(x_coords) - x)
                h = int(max(y_coords) - y)
                blocks.append(OCRTextBlock(
                    text=text,
                    bbox=(x, y, w, h),
                    confidence=conf
                ))
            return blocks
        except Exception as e:
            logger.error(f"EasyOCR failed: {e}")
            return []

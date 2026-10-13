import io
import logging
from typing import Any, Optional, Tuple
from PIL import Image

logger = logging.getLogger(__name__)

class OCRProcessor:
    '''Base class for OCR processing.'''
    
    def __init__(self):
        '''Initialize the OCR processor.'''
        pass
    
    def extract_text(self, image_data: bytes) -> tuple[Optional[str], float]:
        '''
        Extract text from image data.
        
        Args:
            image_data: Raw image bytes
            
        Returns:
            Tuple of (extracted_text, confidence_score)
            Returns (None, 0.0) if no text could be extracted
        '''
        raise NotImplementedError("Subclasses must implement extract_text method")
    
    def is_available(self) -> bool:
        '''Check if the OCR engine is available and properly configured.'''
        return True

class TesseractOCR(OCRProcessor):
    '''OCR processor using Tesseract via pytesseract.'''
    
    def __init__(self):
        '''Initialize the Tesseract OCR processor.'''
        super().__init__()
        try:
            import pytesseract
            self.pytesseract = pytesseract
            self._available = True
        except ImportError:
            self._available = False
            logger.warning("pytesseract not available. Install with: pip install pytesseract")
    
    def is_available(self) -> bool:
        '''Check if Tesseract is available.'''
        return self._available
    
    def extract_text(self, image_data: bytes) -> tuple[Optional[str], float]:
        '''Extract text using Tesseract OCR.'''
        if not self.is_available():
            return None, 0.0
            
        try:
            # Convert bytes to PIL Image
            image = Image.open(io.BytesIO(image_data))
            
            # Configure Tesseract for digits and common meter number characters
            custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
            
            # Get detailed output including confidence
            data = self.pytesseract.image_to_data(
                image, 
                config=custom_config,
                output_type=self.pytesseract.Output.DICT
            )
            
            # Extract text and calculate average confidence
            text_parts = []
            confidences = []
            
            for i in range(len(data['text'])):
                text = data['text'][i].strip()
                conf = data['conf'][i]
                if text and conf > 0:  # Filter out empty text and negative confidence
                    text_parts.append(text)
                    confidences.append(conf)
            
            if not text_parts:
                return None, 0.0
                
            full_text = ''.join(text_parts)  # Concatenate without spaces for meter numbers
            avg_confidence = sum(confidences) / len(confidences) / 100.0  # Convert to 0-1 scale
            
            return full_text, avg_confidence
            
        except Exception as e:
            logger.error(f"Error in Tesseract OCR: {e}")
            return None, 0.0

class EasyOCRProcessor(OCRProcessor):
    '''OCR processor using EasyOCR.'''
    
    def __init__(self):
        '''Initialize the EasyOCR processor.'''
        super().__init__()
        try:
            import easyocr
            self.reader = easyocr.Reader(['en'])  # English only for now
            self._available = True
        except ImportError:
            self._available = False
            logger.warning("EasyOCR not available. Install with: pip install easyocr")
    
    def is_available(self) -> bool:
        '''Check if EasyOCR is available.'''
        return self._available
    
    def extract_text(self, image_data: bytes) -> tuple[Optional[str], float]:
        '''Extract text using EasyOCR.'''
        if not self.is_available():
            return None, 0.0
            
        try:
            # Convert bytes to numpy array for EasyOCR
            import numpy as np
            from PIL import Image
            
            image = Image.open(io.BytesIO(image_data))
            img_array = np.array(image)
            
            # Extract text
            results = self.reader.readtext(img_array)
            
            if not results:
                return None, 0.0
                
            # Combine all detected text and calculate average confidence
            text_parts = []
            confidences = []
            
            for (bbox, text, confidence) in results:
                if text.strip():
                    text_parts.append(text.strip())
                    confidences.append(confidence)
            
            if not text_parts:
                return None, 0.0
                
            full_text = ''.join(text_parts)  # Concatenate without spaces
            avg_confidence = sum(confidences) / len(confidences)
            
            return full_text, avg_confidence
            
        except Exception as e:
            logger.error(f"Error in EasyOCR: {e}")
            return None, 0.0

def get_ocr_processor(preferred_engine: str = "tesseract") -> OCRProcessor:
    '''
    Get an OCR processor instance based on availability and preference.
    
    Args:
        preferred_engine: Preferred OCR engine ("tesseract" or "easyocr")
        
    Returns:
        OCRProcessor instance
    '''
    if preferred_engine.lower() == "tesseract":
        processor = TesseractOCR()
        if processor.is_available():
            return processor
        # Fall back to EasyOCR if Tesseract not available
    
    # Try EasyOCR as fallback or primary
    processor = EasyOCRProcessor()
    if processor.is_available():
        return processor
        
    # If neither is available, raise an error
    raise RuntimeError(
        "No OCR engine available. Please install either pytesseract or easyocr "
        "(and Tesseract OCR software for pytesseract)."
    )

import sys
import os
import re
import json
import time
import fitz  # PyMuPDF
import numpy as np
import google.generativeai as genai
import logging

# ==========================
# Global Variables and Parameters
# ==========================

# API Keys
API_KEYS = {
    'Andrew': ''
}

# Prompt for AI
PROMPT = "Trascrivi. Converti eventuali notazioni matematiche in LaTeX."

# Color Map
COLOR_MAP = {
    'red': np.array([255, 0, 0]),
    'green': np.array([0, 255, 0]),
    'blue': np.array([0, 0, 255]),
    'yellow': np.array([255, 255, 0]),
    'cyan': np.array([0, 255, 255]),
    'magenta': np.array([255, 0, 255]),
    # Add more colors as needed
}

# Tolerance
COLOR_TOLERANCE = 110

# Space Tolerance
SPACE_TOLERANCE = 100  # Number of consecutive non-target color lines to end a region

# Margin
MARGIN = 20  # pixels

# Temporary Directory
TEMP_DIR = "temp"

# API Rate Limits
REQUESTS_PER_MINUTE = 2
DELAY_AFTER_REQUESTS = REQUESTS_PER_MINUTE
DELAY_DURATION = 60  # seconds

# Retry Parameters
MAX_RETRIES = 2
RETRY_DELAY = 15  # seconds

# Logging Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ==========================
# Function Definitions
# ==========================

def check_color_in_pdf(pdf_path, target_color='green', tolerance=COLOR_TOLERANCE):
    if target_color.lower() not in COLOR_MAP:
        raise ValueError(f"Color '{target_color}' is not defined in the color map.")
    target_rgb = COLOR_MAP[target_color.lower()]

    # Open the PDF file
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.error(f"Error opening PDF file: {e}")
        raise

    pages_with_color = []
    for page_number in range(len(doc)):
        page = doc[page_number]
        # Render the page to a pixmap (image)
        pix = page.get_pixmap(colorspace=fitz.csRGB)
        # Convert the pixmap to a NumPy array
        img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)

        # Calculate the difference from the target color
        diff = np.abs(img_data - target_rgb)
        # Create a mask where all differences are within the tolerance
        mask = np.all(diff <= tolerance, axis=2)

        if np.any(mask):
            pages_with_color.append(page_number)  # Page indices start from 0
            logger.info(f"Page {page_number + 1} contains the target color '{target_color}'.")
        else:
            logger.info(f"Page {page_number + 1} does NOT contain the target color '{target_color}'.")

    doc.close()
    return pages_with_color


def process_page_for_color(page, img_data, mask, margin, page_number, temp_dir, color, tolerance=COLOR_TOLERANCE, space_tolerance=SPACE_TOLERANCE, img_prefix="page"):
    """
    Processes a single page to find and crop color regions based on space_tolerance.
    """
    height, width, _ = img_data.shape
    current_y = 0
    region_count = 1  # To keep track of multiple regions in the same page

    while current_y < height:
        # Find the next y_min where target color pixel is found
        green_rows = np.where(np.any(mask, axis=1))[0]
        remaining_rows = green_rows[green_rows >= current_y]
        if len(remaining_rows) == 0:
            break
        y_min = remaining_rows.min()

        # Initialize y_max to y_min
        y_max = y_min
        gap = 0

        # Iterate from y_min to find y_max based on space_tolerance
        for y in range(y_min + 1, height):
            if mask[y].any():
                y_max = y
                gap = 0
            else:
                gap += 1
                if gap >= space_tolerance:
                    break

        # Apply margin
        y_min_margin = max(y_min - margin, 0)
        y_max_margin = min(y_max + margin, height)

        # Define the rectangle to crop
        rect = fitz.Rect(0, y_min_margin, page.rect.width, y_max_margin)
        try:
            cropped_pix = page.get_pixmap(clip=rect, colorspace=fitz.csRGB)
        except Exception as e:
            logger.error(f"Error cropping page {page_number + 1}, region {region_count}: {e}")
            current_y = y_max + gap + 1
            region_count += 1
            continue

        # Save the cropped image with clear naming
        output_filename = os.path.join(temp_dir, f"{img_prefix}_{page_number+1}_region_{region_count}.jpg")
        try:
            cropped_pix.save(output_filename)
            logger.info(f"Saved cropped image to {output_filename}")
        except Exception as e:
            logger.error(f"Error saving cropped image for page {page_number + 1}, region {region_count}: {e}")

        # Update for next iteration
        current_y = y_max + gap + 1
        region_count += 1


def upload_and_generate_content(model, sample_file, prompt):
    """
    Uploads a file and generates content using the model with retry logic.
    """
    retries = 0
    while retries <= MAX_RETRIES:
        try:
            uploaded_file = genai.upload_file(path=sample_file, display_name=os.path.basename(sample_file))
            response = model.generate_content([prompt, uploaded_file])
            return response.text
        except genai.errors.InternalServerError as e:
            if retries < MAX_RETRIES:
                logger.warning(f"Internal Server Error when processing {sample_file}. Retrying in {RETRY_DELAY} seconds...")
                retries += 1
                time.sleep(RETRY_DELAY)
            else:
                logger.error(f"Failed to process {sample_file} after {MAX_RETRIES + 1} attempts.")
                raise
        except Exception as e:
            logger.error(f"Error processing {sample_file}: {e}")
            raise


def main():
    response = {
        'status': 'success',
        'message': '',
        'transcriptions': [],
        'errors': []
    }

    try:
        # Read input data from stdin
        input_data = sys.stdin.read()
        data = json.loads(input_data) if input_data else {}

        # Get pdf_path from input data
        pdf_path = data.get('pdf_path')
        if not pdf_path:
            raise ValueError("PDF path is missing in input data.")

        # Get color from input data
        color = data.get('color')
        if not color:
            raise ValueError("Color preference is missing in input data.")

        # Ensure the temporary directory exists
        if not os.path.exists(TEMP_DIR):
            os.makedirs(TEMP_DIR)

        # Check if PDF file exists
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        # Configure Google GenAI
        genai_api_key = API_KEYS.get('Andrew')
        if not genai_api_key:
            raise ValueError("Google GenAI API key not set.")

        genai.configure(api_key=genai_api_key)
        model = genai.GenerativeModel(model_name="gemini-1.5-pro")

        # Identify pages with the target color
        pages_with_color = check_color_in_pdf(pdf_path, target_color=color, tolerance=COLOR_TOLERANCE)

        if not pages_with_color:
            # No pages with the target color found
            response['message'] = f"No pages with color '{color}' found in the PDF."
            print(json.dumps(response))
            sys.exit(0)

        # Open the PDF document
        try:
            pdf_document = fitz.open(pdf_path)
        except Exception as e:
            raise RuntimeError(f"Error opening PDF document: {e}")

        # Process each page that contains the target color
        for page_number in pages_with_color:
            logger.info(f"Processing page {page_number + 1}...")
            try:
                page = pdf_document.load_page(page_number)
                pix = page.get_pixmap(colorspace=fitz.csRGB)
                img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
            except Exception as e:
                error_message = f"Error loading page {page_number + 1}: {e}"
                logger.error(error_message)
                response['errors'].append(error_message)
                continue

            # Calculate the difference from the target color
            diff = np.abs(img_data - COLOR_MAP[color.lower()])
            mask = np.all(diff <= COLOR_TOLERANCE, axis=2)

            if np.any(mask):
                # Process the page for the target color
                try:
                    process_page_for_color(
                        page=page,
                        img_data=img_data,
                        mask=mask,
                        margin=MARGIN,
                        page_number=page_number,
                        temp_dir=TEMP_DIR,
                        color=color,
                        tolerance=COLOR_TOLERANCE,
                        space_tolerance=SPACE_TOLERANCE,
                        img_prefix="page"
                    )
                except Exception as e:
                    error_message = f"Error processing color regions on page {page_number + 1}: {e}"
                    logger.error(error_message)
                    response['errors'].append(error_message)
                    continue
            else:
                logger.info(f"No target color '{color}' found on page {page_number + 1} during processing.")

        pdf_document.close()

        # Initialize counters and variables for API rate limiting
        transcriptions = []
        errors = []
        request_count = 0
        total_images = len(os.listdir(TEMP_DIR))
        processed_images = 0

        # Iterate over each image in the temporary directory
        for entry in os.listdir(TEMP_DIR):
            full_path = os.path.join(TEMP_DIR, entry)

            # Check if it's a file
            if os.path.isfile(full_path):
                processed_images += 1
                logger.info(f"Processing image: {full_path}")

                try:
                    transcription = upload_and_generate_content(model, full_path, PROMPT)
                    # Process transcription: replace LaTeX math delimiters with eq()
                    result = re.sub(r'\$(.*?)\$', r'eq(\1)', transcription)
                    transcriptions.append(result)
                except Exception as e:
                    error_message = f"Error processing image '{entry}': {e}"
                    logger.warning(error_message)
                    response['errors'].append(error_message)
                    continue

                # Increment the request count
                request_count += 1

                # After processing REQUESTS_PER_MINUTE images, check if more images remain
                if request_count >= DELAY_AFTER_REQUESTS and processed_images < total_images:
                    logger.info(f"Processed {request_count} images. Waiting for {DELAY_DURATION} seconds to comply with API rate limits.")
                    time.sleep(DELAY_DURATION)
                    request_count = 0  # Reset the request count

        # Clean up the temporary directory by deleting all files and removing the directory
        try:
            for entry in os.listdir(TEMP_DIR):
                full_path = os.path.join(TEMP_DIR, entry)
                if os.path.isfile(full_path):
                    os.remove(full_path)
            os.rmdir(TEMP_DIR)
            logger.info(f"Cleaned up temporary directory '{TEMP_DIR}'.")
        except Exception as e:
            logger.error(f"Error cleaning up temporary directory '{TEMP_DIR}': {e}")
            # Not critical, continue

        # Populate the response with transcriptions and errors
        response['message'] = f"Processed pages with color '{color}'."
        response['transcriptions'] = transcriptions
        response['errors'].extend(errors)

    except Exception as e:
        # Handle any unexpected exceptions and return as error in response
        logger.error(f"An error occurred: {e}")
        response['status'] = 'error'
        response['message'] = str(e)

    finally:
        # Ensure temporary directory is cleaned up in case of errors
        if os.path.exists(TEMP_DIR):
            try:
                for entry in os.listdir(TEMP_DIR):
                    full_path = os.path.join(TEMP_DIR, entry)
                    if os.path.isfile(full_path):
                        os.remove(full_path)
                os.rmdir(TEMP_DIR)
                logger.info(f"Cleaned up temporary directory '{TEMP_DIR}' in finally block.")
            except Exception as e:
                logger.error(f"Error cleaning up temporary directory '{TEMP_DIR}' in finally block: {e}")

    # Output the response as JSON
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
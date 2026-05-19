#!/usr/bin/env python3

import sys
import os
import re
import json
import time
import fitz  # PyMuPDF
import numpy as np
import google.generativeai as genai

api_keys = {'Andrew': 'GOOGLE API KEY'}

# Define RGB values for common colors
color_map = {
    'red': np.array([255, 0, 0]),
    'green': np.array([0, 255, 0]),
    'blue': np.array([0, 0, 255]),
    'yellow': np.array([255, 255, 0]),
    'cyan': np.array([0, 255, 255]),
    'magenta': np.array([255, 0, 255]),
    'black': np.array([0, 0, 0]),
    'white': np.array([255, 255, 255]),
    # Add more colors as needed
}

def check_color_in_pdf(pdf_path, target_color='green', tolerance=110):
    if target_color.lower() not in color_map:
        raise ValueError(f"Color '{target_color}' is not defined in the color map.")
    target_rgb = color_map[target_color.lower()]

    # Open the PDF file
    doc = fitz.open(pdf_path)
    pages_with_color = []
    for page_number in range(len(doc)):
        page = doc[page_number]
        # Render the page to a pixmap (image)
        pix = page.get_pixmap(colorspace=fitz.csRGB)
        # Convert the pixmap to a NumPy array
        img_data = np.frombuffer(pix.samples, dtype=np.uint8)
        img_data = img_data.reshape(pix.height, pix.width, 3)

        # Calculate the difference from the target color
        diff = np.abs(img_data - target_rgb)
        # Create a mask where all differences are within the tolerance
        mask = np.all(diff <= tolerance, axis=2)

        if np.any(mask):
            pages_with_color.append(page_number)  # Page indices start from 0
    doc.close()
    return pages_with_color

def main():
    try:
        # # Read input data from stdin
        # input_data = sys.stdin.read()
        # data = json.loads(input_data) if input_data else {}

        # # Get pdf_path from input data
        # pdf_path = data.get('pdf_path')
        pdf_path = 'successioni\\Successioni1_4.pdf'
        if not pdf_path:
            raise ValueError("PDF path is missing in input data.")

        # # Get color from input data
        # color = data.get('color')
        color = 'green'
        if not color:
            raise ValueError("Color preference is missing in input data.")

        # Check if PDF file exists
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        # Configure Google GenAI API
        genai_api_key = api_keys['Andrew']
        if not genai_api_key:
            raise ValueError("Google GenAI API key not set.")

        genai.configure(api_key=genai_api_key)

        prompt = "Trascrivi. Converti eventuali notazioni matematiche in LaTeX."

        # Choose a Gemini model.
        model = genai.GenerativeModel(model_name="gemini-1.5-pro")

        # Identify pages with the target color using the restored function
        pages_with_color = check_color_in_pdf(pdf_path, target_color=color, tolerance=110)

        if not pages_with_color:
            # No pages with the target color found
            response = {
                'status': 'success',
                'message': f"No pages with color '{color}' found in the PDF.",
                'transcriptions': []
            }
            print(json.dumps(response))
            sys.exit(0)

        # Temporary directory to store images
        temp_dir = "temp"
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)

        pdf_document = fitz.open(pdf_path)

        transcriptions = []
        errors = []
        delay_after_requests = 2  # Number of requests after which to delay
        delay_duration = 60  # Delay duration in seconds (1 minute)
        request_count = 0

        # Define the margin in pixels
        margin = 20  # Adjust this value as needed

        for index, page_number in enumerate(pages_with_color):
            page = pdf_document.load_page(page_number)
            pix = page.get_pixmap(colorspace=fitz.csRGB)
            img_data = np.frombuffer(pix.samples, dtype=np.uint8)
            img_data = img_data.reshape(pix.height, pix.width, 3)

            # Calculate the difference from the target color
            diff = np.abs(img_data - color_map[color.lower()])
            # Create a mask where all differences are within the tolerance
            mask = np.all(diff <= 110, axis=2)

            if np.any(mask):
                # Find the coordinates where the mask is True
                coords = np.column_stack(np.where(mask))
                y_min, x_min = coords.min(axis=0)
                y_max, x_max = coords.max(axis=0)

                # Apply margin
                y_min = max(y_min - margin, 0)
                x_min = max(x_min - margin, 0)
                y_max = min(y_max + margin, img_data.shape[0])
                x_max = min(x_max + margin, img_data.shape[1])

                rect = fitz.Rect(x_min, y_min, x_max, y_max)
                # Generate a pixmap of the cropped area
                cropped_pix = page.get_pixmap(clip=rect, colorspace=fitz.csRGB)
                # Save the cropped image
                output_filename = os.path.join(temp_dir, f"page_{page_number + 1}_crop.jpg")
                cropped_pix.save(output_filename)

                input('Look at the images')  # Uncomment to pause and check images

                image_number = page_number + 1
                image_path = output_filename

                # Process this cropped image with GenAI
                sample_file = genai.upload_file(path=image_path, display_name=f"Image {image_number}")
                try:
                    response = model.generate_content([prompt, sample_file])
                    output = response.text
                    # Process transcription
                    result = re.sub(r'\$(.*?)\$', r'eq(\1)', output)
                    transcriptions.append(result)
                except Exception as e:
                    # Handle exceptions from model.generate_content()
                    error_message = f"Error processing image {image_number}: {str(e)}"
                    print(f"Warning: {error_message}")  # Log the warning
                    errors.append(error_message)
                    continue  # Skip to the next image

                # Clean up the cropped image file if desired
                # os.remove(output_filename)

                # Increment the request count
                request_count += 1

                # After processing two images, insert a delay
                if request_count == delay_after_requests:
                    print(f"Processed {request_count} images. Waiting for {delay_duration} seconds to comply with API rate limits.")
                    time.sleep(delay_duration)
                    request_count = 0  # Reset the request count
            else:
                print(f"No regions with color '{color}' found on page {page_number + 1}.")

        pdf_document.close()

        # Clean up: Remove temp directory if empty
        if os.path.exists(temp_dir) and not os.listdir(temp_dir):
            os.rmdir(temp_dir)

        # Output success message
        response = {
            'status': 'success',
            'message': 'Processing completed with some errors.' if errors else 'All went well',
            'transcriptions': transcriptions,
            'errors': errors
        }
        print(json.dumps(response))
        sys.exit(0)

    except Exception as e:
        # Handle all exceptions and output error report
        error_response = {
            'status': 'error',
            'message': str(e),
            'location': 'script3.py',
            'troubleshoot': 'An error occurred during processing. Please check the error message and try again.'
        }
        print(json.dumps(error_response))
        sys.exit(1)

if __name__ == '__main__':
    main()


#FUNZIONA DA DIO MA SOLO SE SI HANNO PAGINE CHE HANNO UNA SOLA PARTE DI TESTO VERDE
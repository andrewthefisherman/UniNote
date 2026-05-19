#!/usr/bin/env python3

import sys
import json
from notion_processor import NotionProcessor, NotionProcessorError

def main():
    try:
        # Parse input data from command-line arguments or stdin
        if len(sys.argv) > 1:
            input_data = sys.argv[1]
        else:
            input_data = sys.stdin.read()

        # Assume input_data is a JSON string containing necessary information
        data = json.loads(input_data)

        metadata_to_process = data.get('metadata')
        content_to_process = data.get('content')
        title = data.get('title')
        emoji = data.get('emoji')

        # Initialize NotionProcessor with your API keys and database ID
        processor = NotionProcessor(
            notion_api_key='your_notion_api_key',
            database_id='your_database_id',
            cohere_api_key='your_cohere_api_key'
        )

        # Process the input
        processor.process_input(metadata_to_process, content_to_process, title, emoji)

        # If successful, output a JSON success message
        response = {'status': 'success', 'message': 'Page created successfully.'}
        print(json.dumps(response))
        sys.exit(0)

    except NotionProcessorError as e:
        # Output the error information in JSON format
        error_response = {
            'status': 'error',
            'message': e.message,
            'location': e.location,
            'troubleshoot': e.troubleshoot
        }
        print(json.dumps(error_response))
        sys.exit(1)

    except Exception as e:
        # Handle unexpected exceptions
        error_response = {
            'status': 'error',
            'message': str(e),
            'location': 'script2.py',
            'troubleshoot': 'An unexpected error occurred.'
        }
        print(json.dumps(error_response))
        sys.exit(1)

if __name__ == '__main__':
    main()

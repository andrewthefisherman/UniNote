import sys, os, shutil
import time
import requests
import re
import json
import datetime
import copy
import Levenshtein
import logging
import inspect
from functools import wraps
from typing import Any, Dict, Optional, Tuple, List, Callable
import difflib
import urllib.parse
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('C:/Users/andrf/Desktop/Programming/Web Apps and Projects/Output_Debug/notion_processor.log', mode='w', encoding='utf-8')
    ]
)
logger = logging.getLogger('NotionProcessor')

# Custom exception classes
class NotionProcessorError(Exception):
    """Base class for exceptions in NotionProcessor."""
    def __init__(self, message: str, location: Optional[str] = None, troubleshoot: Optional[str] = None, status_code: int = 500):
        super().__init__(message)
        self.location = location
        self.troubleshoot = troubleshoot
        self.status_code = status_code
        logger.error(f"{self.__class__.__name__}: {message} | Location: {location} | Troubleshoot: {troubleshoot}")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the error to a dictionary."""
        return {
            'error': {
                'type': self.__class__.__name__,
                'message': str(self),
                'location': self.location,
                'troubleshoot': self.troubleshoot
            }
        }

class InputError(NotionProcessorError):
    def __init__(self, message: str, location: Optional[str] = None, troubleshoot: Optional[str] = None):
        super().__init__(message, location, troubleshoot, status_code=400)

class ConnectionError(NotionProcessorError):
    def __init__(self, message: str, location: Optional[str] = None, troubleshoot: Optional[str] = None):
        super().__init__(message, location, troubleshoot, status_code=503)

class APIError(NotionProcessorError):
    def __init__(self, message: str, location: Optional[str] = None, troubleshoot: Optional[str] = None, status_code: int = 502):
        super().__init__(message, location, troubleshoot, status_code=status_code)

class SyntaxError(NotionProcessorError):
    def __init__(self, message: str, location: Optional[str] = None, troubleshoot: Optional[str] = None):
        super().__init__(message, location, troubleshoot, status_code=422)


def default(func):
    """
    **DECORATOR:** 
    Standalone decorator to set default for either `database_id` or `page_id`
    if they are explicitly set as `None` in the method call.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Get the function's signature
        sig = inspect.signature(func)
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()

        # Access arguments as a dictionary
        arguments = bound_args.arguments
        instance = arguments.get('self')

        # Set default for `database_id` if it's None
        if 'database_id' in arguments and arguments['database_id'] is None:
            arguments['database_id'] = instance.default_database_id

        # Set default for `page_id` if it's None
        if 'page_id' in arguments and arguments['page_id'] is None:
            arguments['page_id'] = instance.default_page_id

        if 'block_id' in arguments and arguments['block_id'] is None:
            arguments['block_id'] = instance.default_page_id

        # Extract 'kwargs' from arguments
        func_kwargs = arguments.pop('kwargs', {})

        # Call the original function with the modified arguments
        return func(**arguments, **func_kwargs)

    return wrapper

class NotionBase:
    def __init__(
        self,
        notion_api_key: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None
    ):
        """
        Initialize the NotionBase class.

        :param notion_api_key: Optional Notion API key.
        :param username: Optional username to retrieve the API key if not provided.
        :param password: Optional password to retrieve the API key if not provided.
        """
        self.cache = {'notion_requests': [], 'cohere_requests': [], 'queries': []}
        self.notion_api_key = None

        if notion_api_key:
            self.notion_api_key = notion_api_key
            logger.info("Using provided Notion API key.")
        elif username and password:
            logger.info("No API key provided. Attempting to retrieve API key using username and password.")
            # Placeholder for the logic to retrieve the API key using username and password
            # TODO: Implement API key retrieval logic here
            raise NotImplementedError("API key retrieval using username and password is not implemented yet.")
        else:
            logger.warning("No API key or username/password provided. Some methods may not function without an API key.")
            # It's acceptable to proceed without an API key for methods that don't require it.

        # Test the API key if it has been set
        if self.notion_api_key:
            try:
                # Test the API key by making a simple request to the Notion API
                url = 'https://api.notion.com/v1/users/me'
                response, status_code = self.notion(url, 'get')
                if status_code == 200:
                    logger.info("API key is valid. Successfully authenticated with Notion API.")
                else:
                    raise APIError(
                        f"Invalid API key. Received status code {status_code} when testing API key.",
                        location='__init__',
                        troubleshoot='Check your Notion API key.'
                    )
            except NotionProcessorError as e:
                # Log and re-raise any NotionProcessorError exceptions
                logger.error(f"Error during API key validation: {str(e)}")
                raise
            except Exception as e:
                # Catch any other unexpected exceptions
                logger.error(f"Unexpected error during API key validation: {str(e)}")
                raise APIError(
                    f"An unexpected error occurred: {str(e)}",
                    location='__init__',
                    troubleshoot='Check your network connection and API key.'
                )
            
    
    
    def id(self, **kwargs) -> str:
        """
        Extracts the Notion ID from a provided database, page, or block link,
        verifies it via a minimal GET request, and returns the ID.

        Accepts exactly one of 'database_link', 'page_link', or 'block_link'.

        :param kwargs: One of 'database_link', 'page_link', or 'block_link'.
        :return: The extracted and verified Notion ID.
        """
        # Define valid link types and their corresponding API endpoints
        LINK_TYPES = {
            'database_link': {
                'type': 'database',
                'endpoint_template': 'https://api.notion.com/v1/databases/{id}',
            },
            'page_link': {
                'type': 'page',
                'endpoint_template': 'https://api.notion.com/v1/pages/{id}',
            },
            'block_link': {
                'type': 'block',
                'endpoint_template': 'https://api.notion.com/v1/blocks/{id}',
            },
        }

        # Filter provided links and ensure exactly one is provided
        provided_links = [(key, value) for key, value in kwargs.items() if key in LINK_TYPES and value]
        if len(provided_links) != 1:
            raise InputError(
                'Exactly one of database_link, page_link, or block_link must be provided.',
                location='id',
                troubleshoot='Provide a single Notion database, page, or block link.'
            )

        link_key, link = provided_links[0]
        link_info = LINK_TYPES[link_key]
        link_type = link_info['type']
        endpoint_template = link_info['endpoint_template']

        # Extract ID from the link
        link_clean = link.split('?')[0]  # Remove query parameters
        parts = re.split(r'[-/]', link_clean)
        parts = parts[::-1]  # Reverse to start checking from the end
        notion_id = None
        for part in parts:
            part_clean = re.sub(r'\W+', '', part)
            if re.match(r'^[0-9a-fA-F]{32}$', part_clean):
                notion_id = part_clean
                break

        if not notion_id:
            raise InputError(
                'Invalid Notion link provided. Unable to extract ID.',
                location='id',
                troubleshoot='Provide a valid Notion database, page, or block link.'
            )

        logger.info(f"Extracted {link_type.capitalize()} ID: {notion_id}")

        # Verify the ID with a minimal GET request
        url = endpoint_template.format(id=notion_id)
        response, status_code = self.notion(url, 'get')
        if status_code == 200:
            logger.info(f"Verified {link_type.capitalize()} ID: {notion_id}")
        else:
            raise APIError(
                f'Error {status_code}: Unable to access {link_type} with ID {notion_id}',
                location='id',
                troubleshoot='Check your link and permissions.',
                status_code=status_code
            )

        return notion_id
    
    def endpoint(self, endpoint_type: str, database_id=None, page_id=None, block_id=None, **kwargs) -> str:
        """
        Returns the Notion API endpoint URL based on the endpoint_type and provided IDs.
        Handles potential spelling mistakes in the endpoint_type by matching to valid endpoints.

        :param endpoint_type: The type of the endpoint to resolve.
        :param database_id: The database ID if required by the endpoint.
        :param page_id: The page ID if required by the endpoint.
        :param kwargs: Other IDs required for the endpoint.
        :return: The resolved endpoint URL.

        **Endpoints:**
        > 'blocks_children'\n
        > 'block'\n
        > 'pages'\n
        > 'page'\n
        > 'page_properties'\n
        > 'databases'\n
        > 'database_query'\n
        > 'database'\n
        > 'users'\n
        > 'user'\n
        > 'users_me'\n
        > 'comments'\n
        > 'search'
        """

        endpoint_type = endpoint_type.lower().strip()

        ENDPOINTS = {
            'blocks_children': {
                'url_template': 'https://api.notion.com/v1/blocks/{block_id}/children',
                'required_ids': ['block_id'],
            },
            'block': {
                'url_template': 'https://api.notion.com/v1/blocks/{block_id}',
                'required_ids': ['block_id'],
            },
            'pages': {
                'url_template': 'https://api.notion.com/v1/pages',
                'required_ids': [],
            },
            'page': {
                'url_template': 'https://api.notion.com/v1/pages/{page_id}',
                'required_ids': ['page_id'],
            },
            'page_properties': {
                'url_template': 'https://api.notion.com/v1/pages/{page_id}/properties/{property_id}',
                'required_ids': ['page_id', 'property_id'],
            },
            'databases': {
                'url_template': 'https://api.notion.com/v1/databases',
                'required_ids': [],
            },
            'database_query': {
                'url_template': 'https://api.notion.com/v1/databases/{database_id}/query',
                'required_ids': ['database_id'],
            },
            'database': {
                'url_template': 'https://api.notion.com/v1/databases/{database_id}',
                'required_ids': ['database_id'],
            },
            'users': {
                'url_template': 'https://api.notion.com/v1/users',
                'required_ids': [],
            },
            'user': {
                'url_template': 'https://api.notion.com/v1/users/{user_id}',
                'required_ids': ['user_id'],
            },
            'users_me': {
                'url_template': 'https://api.notion.com/v1/users/me',
                'required_ids': [],
            },
            'comments': {
                'url_template': 'https://api.notion.com/v1/comments',
                'required_ids': [],
            },
            'search': {
                'url_template': 'https://api.notion.com/v1/search',
                'required_ids': [],
            },
        }

        # List of valid endpoint types
        valid_endpoint_types = list(ENDPOINTS.keys())

        # Use the match function to handle potential spelling mistakes
        matched_endpoint_type = self.match(endpoint_type, valid_endpoint_types)

        if not matched_endpoint_type:
            raise InputError(
                f'Invalid endpoint type: {endpoint_type}',
                location='endpoint',
                troubleshoot='Provide a valid endpoint type.'
            )

        endpoint_info = ENDPOINTS[matched_endpoint_type]
        url_template = endpoint_info['url_template']
        required_ids = endpoint_info['required_ids']

        # Collect all provided IDs
        provided_ids = {}
        if database_id is not None:
            provided_ids['database_id'] = database_id
        if page_id is not None:
            provided_ids['page_id'] = page_id
        if block_id is not None:
            provided_ids['block_id'] = block_id
        provided_ids.update(kwargs)

        # Check for missing IDs
        missing_ids = [id_name for id_name in required_ids if id_name not in provided_ids]
        if missing_ids:
            raise InputError(
                f'Missing required IDs: {", ".join(missing_ids)}',
                location='endpoint',
                troubleshoot=f'Provide the required IDs: {", ".join(required_ids)}.'
            )

        # Check for extra IDs
        extra_ids = [id_name for id_name in provided_ids if id_name not in required_ids]
        if extra_ids:
            raise InputError(
                f'Extra IDs provided: {", ".join(extra_ids)}',
                location='endpoint',
                troubleshoot=f'Only provide the required IDs: {", ".join(required_ids)}.'
            )

        # Replace placeholders in URL template with actual IDs
        try:
            url = url_template.format(**provided_ids)
        except KeyError as e:
            raise InputError(
                f'Missing required ID: {e.args[0]}',
                location='endpoint',
                troubleshoot=f'Provide the required IDs: {", ".join(required_ids)}.'
            )

        return url

    def validate(self, url: str) -> Tuple[str, bool, int]:
        try:
            # Parse the URL
            parsed = urlparse(url)
            absolute_url = url

            # Resolve partial URL to absolute URL
            if not parsed.scheme:
                scheme = 'https'
                domain = parsed.netloc if parsed.netloc else parsed.path
                path = parsed.path if parsed.netloc else ''

                # Append '.com' if TLD is missing
                if not re.search(r'\.[a-z]{2,}$', domain, re.IGNORECASE):
                    domain += '.com'
                    logging.info(f"No TLD detected. Appended '.com' to domain: {domain}")

                absolute_url = f"{scheme}://{domain}{path}"
                logging.info(f"No scheme detected. Formatted to absolute URL: {absolute_url}")
            else:
                logging.info(f"Scheme detected. Using absolute URL as is: {absolute_url}")

            # Define the schemes to try: first HTTPS, then HTTP if HTTPS fails due to SSL error
            schemes_to_try = ['https', 'http']
            for scheme in schemes_to_try:
                # Update the URL with the current scheme
                parsed = urlparse(absolute_url)
                if parsed.scheme != scheme:
                    absolute_url = parsed._replace(scheme=scheme).geturl()
                    logging.info(f"Trying scheme: {scheme}. Updated URL: {absolute_url}")

                # Validate the URL with minimal GET request
                max_retries = 3
                retry_delay = 3  # seconds

                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ' +
                                'AppleWebKit/537.36 (KHTML, like Gecko) ' +
                                'Chrome/58.0.3029.110 Safari/537.3'
                }

                for attempt in range(1, max_retries + 1):
                    try:
                        response = requests.get(absolute_url, headers=headers, timeout=5, allow_redirects=True)

                        if response.status_code == 200:
                            logging.info(f"Website validation for {absolute_url}: Valid (Status {response.status_code})")
                            return (absolute_url, True, response.status_code)
                        elif 300 <= response.status_code < 400:
                            # Handle redirects
                            redirected_url = response.url
                            if redirected_url != absolute_url:
                                logging.info(f"Website validation for {absolute_url}: Redirected to {redirected_url}")
                                absolute_url = redirected_url
                                # Update scheme based on redirected URL
                                parsed = urlparse(redirected_url)
                                scheme = parsed.scheme if parsed.scheme else 'https'
                                absolute_url = parsed.geturl()
                                continue  # Validate the new redirected URL
                            else:
                                logging.warning(f"Website validation for {absolute_url}: Redirected to the same URL.")
                                return (absolute_url, True, response.status_code)
                        elif response.status_code == 403:
                            # Treat 403 as valid but access restricted
                            logging.warning(f"Access forbidden when validating URL '{absolute_url}'. HTTP Status: {response.status_code}")
                            return (absolute_url, True, response.status_code)
                        else:
                            logging.warning(f"Failed to validate URL '{absolute_url}'. HTTP Status: {response.status_code}")
                            return (absolute_url, False, response.status_code)

                    except requests.exceptions.SSLError as ssl_err:
                        logging.error(f"SSL error encountered for URL '{absolute_url}': {ssl_err}")
                        if scheme == 'https':
                            logging.info(f"Attempting to retry with 'http' scheme.")
                            # Break out of retry loop to try the next scheme (http)
                            break
                        else:
                            # If already using http, don't retry further
                            logging.error(f"SSL error with 'http' scheme is unexpected. Aborting.")
                            return (absolute_url, False, 495)  # 495: SSL Certificate Error (non-standard)
                    
                    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                        logging.error(f"Attempt {attempt} - Connection error during website validation for {absolute_url}: {e}")
                        if attempt < max_retries:
                            logging.info(f"Retrying in {retry_delay} seconds...")
                            time.sleep(retry_delay)
                            continue  # Retry the request
                        else:
                            logging.error(f"Website validation failed for {absolute_url} after {max_retries} attempts.")
                            return (absolute_url, False, 408)  # Code for Request Timeout

                    except requests.exceptions.RequestException as e:
                        logging.error(f"Request exception during website validation for {absolute_url}: {e}")
                        return (absolute_url, False, 500)

            # If all schemes have been tried and failed
            logging.error(f"All schemes tried. Failed to validate URL: {absolute_url}")
            return (absolute_url, False, 500)

        except Exception as e:
            logging.error(f"Unexpected error in validate: {e}")
            return (url, False, 500)

    def match(
            self, 
            input_word: str, 
            word_list: list, 
            deprioritized_words: str = None, 
            penalty: int = 7, 
            force_match: bool = False
            ):
        
        input_word_lower = input_word.lower()
        deprioritized_words = set(deprioritized_words) if deprioritized_words else set()

        # Step 1: Exact match (case-sensitive)
        if input_word in word_list:
            return input_word

        # Step 2: Case-insensitive exact matches
        case_insensitive_matches = [word for word in word_list if word.lower() == input_word_lower]
        if case_insensitive_matches:
            # Prefer the word with capitalization closest to input_word
            matches = []
            for word in case_insensitive_matches:
                cap_diff = sum(c1 != c2 for c1, c2 in zip(input_word, word))
                matches.append((cap_diff, word))
            matches.sort()
            return matches[0][1]

        # Step 3: Fuzzy matching
        word_length = len(input_word)
        if word_length < 4:
            threshold = 1
        elif 4 <= word_length <= 8:
            threshold = 2
        else:
            threshold = max(2, word_length // 3)

        matches = []
        for word in word_list:
            word_lower = word.lower()
            distance = Levenshtein.distance(input_word_lower, word_lower)
            # Apply penalty if the word is deprioritized
            if word in deprioritized_words:
                distance += penalty

            # Compute capitalization difference
            cap_diff = sum(c1.isupper() != c2.isupper() for c1, c2 in zip(input_word, word))
            cap_diff += abs(len(input_word) - len(word))  # Add difference in length to cap_diff

            matches.append((distance, cap_diff, -len(word), word))

        # Try to find matches within the threshold
        threshold_matches = [m for m in matches if m[0] <= threshold]
        if threshold_matches:
            threshold_matches.sort()
            return threshold_matches[0][3]
        elif force_match:
            # If force_match is True, return the best possible match
            matches.sort()
            return matches[0][3]
        else:
            return None

    def notion(
        self,
        url: str,
        method: str,
        body: Optional[Dict] = None,
        bypass_cache: bool = False
    ) -> Tuple[Dict, int]:
        # Create a unique cache key based on the request
        cache_key = {
            'url': url,
            'method': method.upper(),
            'body': body or {}
        }

        # Check if the request is cached, unless bypass_cache is True
        if not bypass_cache:
            for cached_request in self.cache['notion_requests']:
                if (cached_request['url'] == cache_key['url'] and
                    cached_request['method'] == cache_key['method'] and
                    cached_request['body'] == cache_key['body']):
                    logger.info(f"Returning cached response for {method.upper()} request to {url}")
                    return cached_request['response'], cached_request['status_code']

        headers = {
            'Authorization': f'Bearer {self.notion_api_key}',
            'Notion-Version': '2022-06-28'
        }
        if method.lower() in ["post", "patch"]:
            headers['Content-Type'] = "application/json"
        elif method.lower() not in ['get']:
            raise APIError(
                f'HTTP method {method} is not supported.',
                location='Notion Request',
                troubleshoot='Use GET, POST, or PATCH methods.'
            )

        max_retries = 3
        retry_delay = 3  # seconds

        for attempt in range(1, max_retries + 1):
            try:
                request_func = getattr(requests, method.lower())
                response = request_func(url=url, headers=headers, json=body, timeout=10)

                if response.status_code in [200, 201]:
                    logger.info(f"Notion {method.upper()} request to {url} succeeded with status {response.status_code}.")

                    # Cache the successful response
                    self.cache['notion_requests'].append({
                        'url': url,
                        'method': method.upper(),
                        'body': body or {},
                        'response': response.json(),
                        'status_code': response.status_code
                    })

                    return response.json(), response.status_code
                else:
                    logger.warning(f"Notion {method.upper()} request to {url} failed with status {response.status_code}: {response.text}")
                    raise APIError(
                        f'Error {response.status_code}: {response.text}',
                        location='Notion API',
                        troubleshoot='Check your request and API key.',
                        status_code=response.status_code
                    )
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                logger.error(f"Attempt {attempt} - Connection error during Notion {method.upper()} request to {url}: {str(e)}")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue  # Retry the request
                else:
                    raise ConnectionError(
                        'Connection Error with Notion API',
                        location='Notion API',
                        troubleshoot='Check your internet connection.'
                    ) from e
            except requests.exceptions.RequestException as e:
                logger.error(f"Request exception during Notion {method.upper()} request to {url}: {str(e)}")
                raise APIError(
                    f'Request exception: {str(e)}',
                    location='Notion API',
                    troubleshoot='Check your request and network connection.'
                ) from e

    def cohere(self, prompt: str, chat_history: Optional[list] = None) -> Tuple[str, int]:
        # Before making any API call or processing API keys, check the cache
        if 'cohere_requests' not in self.cache:
            self.cache['cohere_requests'] = []

        # Check if the request is already in the cache
        for cached_entry in self.cache['cohere_requests']:
            if cached_entry['prompt'] == prompt and cached_entry['chat_history'] == chat_history:
                output = cached_entry['output']
                status_code = cached_entry['status_code']
                logger.info("Cache hit for the given prompt and chat history.")
                return output, status_code

        logger.info("No cache entry found. Proceeding to process the request.")

        json_file_path = 'cohere_api_keys.json'
        if not os.path.exists(json_file_path):
            default_api_key_data = {
                "api_keys": [
                    {
                        "api_key": "hJKCY9GBu8gpqmUIXpuRR00EU2aciPMrRVAPiCBD",  # Replace with your actual hardcoded API key
                        "requests_last_minute": [],
                        "monthly_requests": 0,
                        "last_request_time": "",
                        "last_reset_month": ""
                    }
                ]
            }
            with open(json_file_path, 'w') as f:
                json.dump(default_api_key_data, f, indent=4)
            logger.info(f"API keys JSON file created at {json_file_path} with a default API key.")

        # Load API keys data
        with open(json_file_path, 'r') as f:
            api_keys_data = json.load(f)

        current_time = datetime.datetime.now(datetime.timezone.utc)
        available_api_keys = []

        # Process each API key to check for availability
        for api_key_entry in api_keys_data.get('api_keys', []):
            api_key = api_key_entry.get('api_key')
            requests_last_minute = api_key_entry.get('requests_last_minute', [])
            monthly_requests = api_key_entry.get('monthly_requests', 0)
            last_reset_month = api_key_entry.get('last_reset_month')

            # Remove timestamps older than 60 seconds from requests_last_minute
            updated_requests_last_minute = []
            for timestamp_str in requests_last_minute:
                try:
                    timestamp = datetime.datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                    if (current_time - timestamp).total_seconds() <= 60:
                        updated_requests_last_minute.append(timestamp_str)
                except ValueError:
                    logger.warning(f"Invalid timestamp format in JSON: {timestamp_str}")
            api_key_entry['requests_last_minute'] = updated_requests_last_minute

            # Check RPM limit
            rpm_available = len(updated_requests_last_minute) < 10

            # Check monthly limit
            current_month = current_time.strftime('%Y-%m')
            if last_reset_month != current_month:
                # Reset monthly_requests
                api_key_entry['monthly_requests'] = 0
                api_key_entry['last_reset_month'] = current_month
                monthly_requests = 0
            else:
                monthly_requests = api_key_entry.get('monthly_requests', 0)

            monthly_available = monthly_requests < 1000

            if rpm_available and monthly_available:
                available_api_keys.append(api_key_entry)

        if not available_api_keys:
            # Check if all API keys have exceeded the monthly limit
            all_monthly_limited = all(
                api_key_entry.get('monthly_requests', 0) >= 1000 for api_key_entry in api_keys_data.get('api_keys', [])
            )
            if all_monthly_limited:
                logger.error("Monthly limit reached for all API keys.")
                raise APIError(
                    'Monthly limit reached for all Cohere API keys.',
                    location='Cohere API',
                    troubleshoot='Please add more API keys or wait until the next month.',
                    status_code=429
                )
            else:
                # All API keys have exceeded RPM limit, wait a minute and retry
                logger.info("All API keys have exceeded RPM limit. Waiting a minute.")
                time.sleep(60)
                # After waiting, call the function again
                return self.cohere(prompt, chat_history)

        # Select the API key with the earliest last_request_time
        def get_last_request_time(api_key_entry):
            last_request_time_str = api_key_entry.get('last_request_time')
            if last_request_time_str:
                try:
                    return datetime.datetime.strptime(last_request_time_str, '%Y-%m-%dT%H:%M:%SZ')
                except ValueError:
                    logger.warning(f"Invalid last_request_time format: {last_request_time_str}")
                    return datetime.datetime.min
            else:
                return datetime.datetime.min

        available_api_keys.sort(key=get_last_request_time)
        selected_api_key_entry = available_api_keys[0]
        api_key = selected_api_key_entry['api_key']

        # Prepare the chat history
        formatted_chat_history = []
        if chat_history:
            for message in chat_history:
                if 'chatbot' in message:
                    strip = re.sub(r'chatbot\s*:\s*', '', message)
                    chat_message = {'role': 'assistant', 'content': strip}
                    formatted_chat_history.append(chat_message)
                elif 'user' in message:
                    strip = re.sub(r'user\s*:\s*', '', message)
                    chat_message = {'role': 'user', 'content': strip}
                    formatted_chat_history.append(chat_message)
                elif 'system' in message:
                    strip = re.sub(r'system\s*:\s*', '', message)
                    chat_message = {'role': 'system', 'content': strip}
                    formatted_chat_history.append(chat_message)
                else:
                    logger.warning(f"Invalid chat history message encountered: {message}")

        # Append the current prompt as the last user message
        messages = formatted_chat_history
        messages.append({'role': 'user', 'content': prompt})

        # Make the API call using requests with retry logic
        MAX_RETRIES = 3
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                headers = {
                    'accept': 'application/json',
                    'content-type': 'application/json',
                    'Authorization': f'Bearer {api_key}',
                }

                data = {
                    "model": "command-r-plus-08-2024",
                    "messages": messages,
                }

                response = requests.post('https://api.cohere.com/v2/chat', headers=headers, json=data)
                status_code = response.status_code

                if status_code == 200:
                    response_json = response.json()
                    # Parse the assistant's reply from the response
                    if (response_json.get('message', {}).get('role', '') == 'assistant' and
                        response_json.get('message', {}).get('content', [])[0].get('text', '')):
                        output = response_json.get('message', {}).get('content', [])[0].get('text', '').strip()
                    else:
                        logger.error("Unexpected response format from Cohere API.")
                        raise APIError(
                            'Unexpected response format from Cohere API.',
                            location='Cohere API',
                            troubleshoot='Check Cohere API documentation for response structure.',
                            status_code=500
                        )

                    logger.info(f"Cohere API request succeeded with status {status_code}.")

                    # Update the usage stats
                    current_timestamp_str = current_time.strftime('%Y-%m-%dT%H:%M:%SZ')
                    selected_api_key_entry['requests_last_minute'].append(current_timestamp_str)
                    selected_api_key_entry['monthly_requests'] += 1
                    selected_api_key_entry['last_request_time'] = current_timestamp_str

                    # Write back to the JSON file
                    with open(json_file_path, 'w') as f:
                        json.dump(api_keys_data, f, indent=4)

                    # Cache the successful response
                    self.cache['cohere_requests'].append({
                        'prompt': prompt,
                        'chat_history': chat_history,
                        'output': output,
                        'status_code': status_code
                    })

                    return output, status_code

                else:
                    logger.error(f"Cohere API returned status code {status_code}: {response.text}")
                    # Retry on server errors (5xx)
                    if 500 <= status_code < 600 and attempt < MAX_RETRIES:
                        logger.warning(f"Server error on attempt {attempt}/{MAX_RETRIES}. Retrying in 3 seconds.")
                        time.sleep(3)
                        continue
                    else:
                        raise APIError(
                            f'Cohere API error: {response.text}',
                            location='Cohere API',
                            troubleshoot='Check your request parameters and API key.',
                            status_code=status_code
                        )

            except requests.exceptions.RequestException as e:
                # Handle connection-related errors
                if attempt < MAX_RETRIES:
                    logger.warning(f"Connection error on attempt {attempt}/{MAX_RETRIES}: {str(e)}. Retrying in 3 seconds.")
                    time.sleep(3)
                    continue
                else:
                    logger.error(f"Connection error after {MAX_RETRIES} attempts: {str(e)}")
                    raise APIError(
                        f'Connection error after {MAX_RETRIES} attempts: {str(e)}',
                        location='Cohere API',
                        troubleshoot='Check your network connection.',
                        status_code=503
                    )

            except Exception as e:
                logger.error(f"Unexpected error during Cohere API request: {str(e)}")
                raise APIError(
                    f'Unexpected error: {str(e)}',
                    location='Cohere API',
                    troubleshoot='Check your request and network connection.',
                    status_code=500
                )

    def cohere_merged(self, prompt: str, chat_history: Optional[list] = None) -> Tuple[str, int]:
        # Before making any API call or processing API keys, check the cache
        if 'cohere_requests' not in self.cache:
            self.cache['cohere_requests'] = []

        # Check if the request is already in the cache
        for cached_entry in self.cache['cohere_requests']:
            if cached_entry['prompt'] == prompt and cached_entry['chat_history'] == chat_history:
                output = cached_entry['output']
                status_code = cached_entry['status_code']
                logger.info("Cache hit for the given prompt and chat history.")
                return output, status_code

        logger.info("No cache entry found. Proceeding to process the request.")

        json_file_path = 'cohere_api_keys.json'
        if not os.path.exists(json_file_path):
            default_api_key_data = {
                "api_keys": [
                    {
                        "api_key": "hJKCY9GBu8gpqmUIXpuRR00EU2aciPMrRVAPiCBD",  # Replace with your actual hardcoded API key
                        "requests_last_minute": [],
                        "monthly_requests": 0,
                        "last_request_time": "",
                        "last_reset_month": ""
                    }
                ]
            }
            with open(json_file_path, 'w') as f:
                json.dump(default_api_key_data, f, indent=4)
            logger.info(f"API keys JSON file created at {json_file_path} with a default API key.")

        # Load API keys data
        with open(json_file_path, 'r') as f:
            api_keys_data = json.load(f)

        current_time = datetime.datetime.now(datetime.timezone.utc)
        available_api_keys = []
        all_requests_last_minute = []  # Collect all requests from all API keys

        # Process each API key to check for availability
        for api_key_entry in api_keys_data.get('api_keys', []):
            api_key = api_key_entry.get('api_key')
            requests_last_minute = api_key_entry.get('requests_last_minute', [])
            monthly_requests = api_key_entry.get('monthly_requests', 0)
            last_reset_month = api_key_entry.get('last_reset_month')

            # Remove timestamps older than 60 seconds from requests_last_minute
            updated_requests_last_minute = []
            for timestamp_str in requests_last_minute:
                try:
                    timestamp = datetime.datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                    if (current_time - timestamp).total_seconds() <= 60:
                        updated_requests_last_minute.append(timestamp_str)
                except ValueError:
                    logger.warning(f"Invalid timestamp format in JSON: {timestamp_str}")
            api_key_entry['requests_last_minute'] = updated_requests_last_minute

            # Collect all requests into the global list
            all_requests_last_minute.extend(updated_requests_last_minute)

            # Check monthly limit
            current_month = current_time.strftime('%Y-%m')
            if last_reset_month != current_month:
                # Reset monthly_requests
                api_key_entry['monthly_requests'] = 0
                api_key_entry['last_reset_month'] = current_month
                monthly_requests = 0
            else:
                monthly_requests = api_key_entry.get('monthly_requests', 0)

            monthly_available = monthly_requests < 1000

            if monthly_available:
                available_api_keys.append(api_key_entry)

        # Now, check the global RPM limit
        total_requests_last_minute = len(all_requests_last_minute)
        rpm_available = total_requests_last_minute < 10

        if not rpm_available:
            # Wait a minute and retry
            logger.info("Global RPM limit reached (10 requests per minute). Waiting for 60 seconds.")
            time.sleep(60)
            # After waiting, call the function again
            return self.cohere(prompt, chat_history)

        if not available_api_keys:
            # Check if all API keys have exceeded the monthly limit
            all_monthly_limited = all(
                api_key_entry.get('monthly_requests', 0) >= 1000 for api_key_entry in api_keys_data.get('api_keys', [])
            )
            if all_monthly_limited:
                logger.error("Monthly limit reached for all API keys.")
                raise APIError(
                    'Monthly limit reached for all Cohere API keys.',
                    location='Cohere API',
                    troubleshoot='Please add more API keys or wait until the next month.',
                    status_code=429
                )
            else:
                # All API keys have exceeded RPM limit, wait a minute and retry
                logger.info("All API keys have exceeded RPM limit. Waiting a minute.")
                time.sleep(60)
                # After waiting, call the function again
                return self.cohere(prompt, chat_history)

        # Select the API key with the earliest last_request_time
        def get_last_request_time(api_key_entry):
            last_request_time_str = api_key_entry.get('last_request_time')
            if last_request_time_str:
                try:
                    return datetime.datetime.strptime(last_request_time_str, '%Y-%m-%dT%H:%M:%SZ')
                except ValueError:
                    logger.warning(f"Invalid last_request_time format: {last_request_time_str}")
                    return datetime.datetime.min
            else:
                return datetime.datetime.min

        available_api_keys.sort(key=get_last_request_time)
        selected_api_key_entry = available_api_keys[0]
        api_key = selected_api_key_entry['api_key']

        # Prepare the chat history
        formatted_chat_history = []
        if chat_history:
            for message in chat_history:
                if 'chatbot' in message:
                    strip = re.sub(r'chatbot\s*:\s*', '', message)
                    chat_message = {'role': 'assistant', 'content': strip}
                    formatted_chat_history.append(chat_message)
                elif 'user' in message:
                    strip = re.sub(r'user\s*:\s*', '', message)
                    chat_message = {'role': 'user', 'content': strip}
                    formatted_chat_history.append(chat_message)
                elif 'system' in message:
                    strip = re.sub(r'system\s*:\s*', '', message)
                    chat_message = {'role': 'system', 'content': strip}
                    formatted_chat_history.append(chat_message)
                else:
                    logger.warning(f"Invalid chat history message encountered: {message}")

        # Append the current prompt as the last user message
        messages = formatted_chat_history
        messages.append({'role': 'user', 'content': prompt})

        # Make the API call using requests with retry logic
        MAX_RETRIES = 3
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                headers = {
                    'accept': 'application/json',
                    'content-type': 'application/json',
                    'Authorization': f'Bearer {api_key}',
                }

                data = {
                    "model": "command-r-plus-08-2024",
                    "messages": messages,
                }

                response = requests.post('https://api.cohere.com/v2/chat', headers=headers, json=data)
                status_code = response.status_code

                if status_code == 200:
                    response_json = response.json()
                    # Parse the assistant's reply from the response
                    if (response_json.get('message', {}).get('role', '') == 'assistant' and
                        response_json.get('message', {}).get('content', [])[0].get('text', '')):
                        output = response_json.get('message', {}).get('content', [])[0].get('text', '').strip()
                    else:
                        logger.error("Unexpected response format from Cohere API.")
                        raise APIError(
                            'Unexpected response format from Cohere API.',
                            location='Cohere API',
                            troubleshoot='Check Cohere API documentation for response structure.',
                            status_code=500
                        )

                    logger.info(f"Cohere API request succeeded with status {status_code}.")

                    # Update the usage stats
                    current_timestamp_str = current_time.strftime('%Y-%m-%dT%H:%M:%SZ')
                    selected_api_key_entry['requests_last_minute'].append(current_timestamp_str)
                    selected_api_key_entry['monthly_requests'] += 1
                    selected_api_key_entry['last_request_time'] = current_timestamp_str

                    # Write back to the JSON file
                    with open(json_file_path, 'w') as f:
                        json.dump(api_keys_data, f, indent=4)

                    # Cache the successful response
                    self.cache['cohere_requests'].append({
                        'prompt': prompt,
                        'chat_history': chat_history,
                        'output': output,
                        'status_code': status_code
                    })

                    return output, status_code

                else:
                    logger.error(f"Cohere API returned status code {status_code}: {response.text}")
                    # Retry on server errors (5xx)
                    if 500 <= status_code < 600 and attempt < MAX_RETRIES:
                        logger.warning(f"Server error on attempt {attempt}/{MAX_RETRIES}. Retrying in 3 seconds.")
                        time.sleep(3)
                        continue
                    else:
                        raise APIError(
                            f'Cohere API error: {response.text}',
                            location='Cohere API',
                            troubleshoot='Check your request parameters and API key.',
                            status_code=status_code
                        )

            except requests.exceptions.RequestException as e:
                # Handle connection-related errors
                if attempt < MAX_RETRIES:
                    logger.warning(f"Connection error on attempt {attempt}/{MAX_RETRIES}: {str(e)}. Retrying in 3 seconds.")
                    time.sleep(3)
                    continue
                else:
                    logger.error(f"Connection error after {MAX_RETRIES} attempts: {str(e)}")
                    raise APIError(
                        f'Connection error after {MAX_RETRIES} attempts: {str(e)}',
                        location='Cohere API',
                        troubleshoot='Check your network connection.',
                        status_code=503
                    )

            except Exception as e:
                logger.error(f"Unexpected error during Cohere API request: {str(e)}")
                raise APIError(
                    f'Unexpected error: {str(e)}',
                    location='Cohere API',
                    troubleshoot='Check your request and network connection.',
                    status_code=500
                )
            
    def cohere_restricted(self, prompt: str, chat_history: Optional[list] = None) -> Tuple[str, int]:
        # Before making any API call or processing API keys, check the cache
        if 'cohere_requests' not in self.cache:
            self.cache['cohere_requests'] = []

        # Check if the request is already in the cache
        for cached_entry in self.cache['cohere_requests']:
            if cached_entry['prompt'] == prompt and cached_entry['chat_history'] == chat_history:
                output = cached_entry['output']
                status_code = cached_entry['status_code']
                logger.info("Cache hit for the given prompt and chat history.")
                return output, status_code

        logger.info("No cache entry found. Proceeding to process the request.")

        json_file_path = 'cohere_api_keys.json'
        if not os.path.exists(json_file_path):
            default_api_key_data = {
                "api_keys": [
                    {
                        "api_key": "YOUR_DEFAULT_API_KEY",  # Replace with your actual default API key
                        "requests_last_minute": [],
                        "monthly_requests": 0,
                        "last_request_time": "",
                        "last_reset_month": ""
                    }
                ]
            }
            with open(json_file_path, 'w') as f:
                json.dump(default_api_key_data, f, indent=4)
            logger.info(f"API keys JSON file created at {json_file_path} with a default API key.")

        # Load API keys data
        with open(json_file_path, 'r') as f:
            api_keys_data = json.load(f)

        current_time = datetime.datetime.now(datetime.timezone.utc)
        available_api_keys = []
        all_requests_last_minute = []  # Collect all requests from all API keys

        # Process each API key to check for availability
        for api_key_entry in api_keys_data.get('api_keys', []):
            api_key = api_key_entry.get('api_key')
            requests_last_minute = api_key_entry.get('requests_last_minute', [])
            monthly_requests = api_key_entry.get('monthly_requests', 0)
            last_reset_month = api_key_entry.get('last_reset_month')

            # Remove timestamps older than 60 seconds from requests_last_minute
            updated_requests_last_minute = []
            for timestamp_str in requests_last_minute:
                try:
                    timestamp = datetime.datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                    if (current_time - timestamp).total_seconds() <= 60:
                        updated_requests_last_minute.append(timestamp_str)
                except ValueError:
                    logger.warning(f"Invalid timestamp format in JSON: {timestamp_str}")
            api_key_entry['requests_last_minute'] = updated_requests_last_minute

            # Collect all requests into the global list
            all_requests_last_minute.extend(updated_requests_last_minute)

            # Check monthly limit
            current_month = current_time.strftime('%Y-%m')
            if last_reset_month != current_month:
                # Reset monthly_requests
                api_key_entry['monthly_requests'] = 0
                api_key_entry['last_reset_month'] = current_month
                monthly_requests = 0
            else:
                monthly_requests = api_key_entry.get('monthly_requests', 0)

            monthly_available = monthly_requests < 1000

            if monthly_available:
                available_api_keys.append(api_key_entry)

        # Now, check the global RPM limit
        total_requests_last_minute = len(all_requests_last_minute)
        rpm_available = total_requests_last_minute < 10

        if not rpm_available:
            # Wait a minute and retry
            logger.info("Global RPM limit reached (10 requests per minute). Waiting for 60 seconds.")
            time.sleep(60)
            # After waiting, call the function again
            return self.cohere(prompt, chat_history)

        if not available_api_keys:
            # All API keys have exceeded the monthly limit
            logger.error("Monthly limit reached for all API keys.")
            raise APIError(
                'Monthly limit reached for all Cohere API keys.',
                location='Cohere API',
                troubleshoot='Please add more API keys or wait until the next month.',
                status_code=429
            )

        # Select the API key with the earliest last_request_time
        def get_last_request_time(api_key_entry):
            last_request_time_str = api_key_entry.get('last_request_time')
            if last_request_time_str:
                try:
                    return datetime.datetime.strptime(last_request_time_str, '%Y-%m-%dT%H:%M:%SZ')
                except ValueError:
                    logger.warning(f"Invalid last_request_time format: {last_request_time_str}")
                    return datetime.datetime.min
            else:
                return datetime.datetime.min

        available_api_keys.sort(key=get_last_request_time)
        selected_api_key_entry = available_api_keys[0]
        api_key = selected_api_key_entry['api_key']

        # Prepare the chat history
        formatted_chat_history = []
        if chat_history:
            for message in chat_history:
                if 'chatbot' in message:
                    strip = re.sub(r'chatbot\s*:\s*', '', message)
                    chat_message = {'role': 'assistant', 'content': strip}
                    formatted_chat_history.append(chat_message)
                elif 'user' in message:
                    strip = re.sub(r'user\s*:\s*', '', message)
                    chat_message = {'role': 'user', 'content': strip}
                    formatted_chat_history.append(chat_message)
                elif 'system' in message:
                    strip = re.sub(r'system\s*:\s*', '', message)
                    chat_message = {'role': 'system', 'content': strip}
                    formatted_chat_history.append(chat_message)
                else:
                    logger.warning(f"Invalid chat history message encountered: {message}")

        # Append the current prompt as the last user message
        messages = formatted_chat_history
        messages.append({'role': 'user', 'content': prompt})

        # Make the API call using requests with retry logic
        MAX_RETRIES = 3
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                headers = {
                    'accept': 'application/json',
                    'content-type': 'application/json',
                    'Authorization': f'Bearer {api_key}',
                }

                data = {
                    "model": "command-r-plus-08-2024",
                    "messages": messages,
                }

                response = requests.post('https://api.cohere.com/v1/chat', headers=headers, json=data)
                status_code = response.status_code

                if status_code == 200:
                    response_json = response.json()
                    # Parse the assistant's reply from the response
                    output = response_json.get('text', '').strip()
                    if output:
                        logger.info(f"Cohere API request succeeded with status {status_code}.")

                        # Update the usage stats
                        current_timestamp_str = current_time.strftime('%Y-%m-%dT%H:%M:%SZ')
                        selected_api_key_entry['requests_last_minute'].append(current_timestamp_str)
                        selected_api_key_entry['monthly_requests'] += 1
                        selected_api_key_entry['last_request_time'] = current_timestamp_str

                        # Write back to the JSON file
                        with open(json_file_path, 'w') as f:
                            json.dump(api_keys_data, f, indent=4)

                        # Cache the successful response
                        self.cache['cohere_requests'].append({
                            'prompt': prompt,
                            'chat_history': chat_history,
                            'output': output,
                            'status_code': status_code
                        })

                        return output, status_code
                    else:
                        logger.error("Unexpected response format from Cohere API.")
                        raise APIError(
                            'Unexpected response format from Cohere API.',
                            location='Cohere API',
                            troubleshoot='Check Cohere API documentation for response structure.',
                            status_code=500
                        )
                else:
                    logger.error(f"Cohere API returned status code {status_code}: {response.text}")
                    # Retry on server errors (5xx)
                    if 500 <= status_code < 600 and attempt < MAX_RETRIES:
                        logger.warning(f"Server error on attempt {attempt}/{MAX_RETRIES}. Retrying in 3 seconds.")
                        time.sleep(3)
                        continue
                    else:
                        raise APIError(
                            f'Cohere API error: {response.text}',
                            location='Cohere API',
                            troubleshoot='Check your request parameters and API key.',
                            status_code=status_code
                        )

            except requests.exceptions.RequestException as e:
                # Handle connection-related errors
                if attempt < MAX_RETRIES:
                    logger.warning(f"Connection error on attempt {attempt}/{MAX_RETRIES}: {str(e)}. Retrying in 3 seconds.")
                    time.sleep(3)
                    continue
                else:
                    logger.error(f"Connection error after {MAX_RETRIES} attempts: {str(e)}")
                    raise APIError(
                        f'Connection error after {MAX_RETRIES} attempts: {str(e)}',
                        location='Cohere API',
                        troubleshoot='Check your network connection.',
                        status_code=503
                    )

            except Exception as e:
                logger.error(f"Unexpected error during Cohere API request: {str(e)}")
                raise APIError(
                    f'Unexpected error: {str(e)}',
                    location='Cohere API',
                    troubleshoot='Check your request and network connection.',
                    status_code=500
                )

    def context(
        self,
        keyword: str,
        input_string: str,
        window: int = 100,
        strip: Optional[str] = None,
        wrap: Optional[str] = None
        ) -> Optional[str]:
        
        try:
            if not keyword:
                logging.warning("Empty keyword provided.")
                return None

            # Step 1: Strip unwanted characters if 'strip' is provided
            if strip:
                try:
                    stripped_input = re.sub(strip, '', input_string)
                    logging.info(f"Applied stripping with pattern: {strip}")
                except re.error as regex_err:
                    logging.error(f"Invalid regex pattern for strip: {strip}. Error: {regex_err}")
                    return None
            else:
                stripped_input = input_string

            # Step 2: Attempt case-sensitive search for the keyword
            match = re.search(re.escape(keyword), stripped_input)
            search_case_sensitive = True

            if not match:
                # Step 3: Attempt case-insensitive search if case-sensitive search fails
                match = re.search(re.escape(keyword), stripped_input, re.IGNORECASE)
                search_case_sensitive = False

            if not match:
                logging.warning(f"Keyword '{keyword}' not found in the input string.")
                return None

            # Extract the actual keyword as it appears in the text
            found_keyword = match.group()

            start_index, end_index = match.start(), match.end()

            # Step 4: Calculate window boundaries (exactly 'window' characters on each side)
            window_start = max(start_index - window, 0)
            window_end = min(end_index + window, len(stripped_input))

            # Extract the surrounding context from the stripped input string
            context = stripped_input[window_start:window_end]

            # Step 5: Wrap the keyword if 'wrap' is provided
            if wrap:
                # Ensure the wrap string contains a '{keyword}' placeholder (case-insensitive)
                if not re.search(r'\{keyword\}', wrap, re.IGNORECASE):
                    logging.error("The 'wrap' string must contain a '{keyword}' placeholder (case-insensitive).")
                    return None

                # Replace the '{keyword}' placeholder in wrap with the actual found keyword
                wrapped_keyword = re.sub(r'\{keyword\}', found_keyword, wrap, flags=re.IGNORECASE)

                # Find the position of the keyword within the context
                keyword_pattern = re.escape(found_keyword)
                keyword_match_in_context = re.search(keyword_pattern, context)

                if not keyword_match_in_context:
                    logging.error("Keyword not found in the extracted window after stripping.")
                    return None

                kw_start_context, kw_end_context = keyword_match_in_context.start(), keyword_match_in_context.end()

                # Replace the keyword with the wrapped keyword in the context
                context = (
                    context[:kw_start_context] +
                    wrapped_keyword +
                    context[kw_end_context:]
                )

                logging.info(f"Wrapped keyword with: {wrap}")

            # Step 6: Add ellipses if the context is a snippet
            if window_start > 0:
                context = "..." + context
            if window_end < len(stripped_input):
                context += "..."

            return context

        except Exception as e:
            logging.error(f"An unexpected error occurred in get_context: {e}")
            return None
    
    def search(self, query: str, database_id: Optional[str] = None, page_id: Optional[str] = None,
           ignore_ids: Optional[List[str]] = None, ignore_notion_links: bool = False) -> Optional[Dict[str, str]]:
        """
        Searches for content matching the query across the workspace, within a specified database, or within a specific page.

        :param query: The search query string.
        :param database_id: (Optional) The ID of the Notion database to search within.
        :param page_id: (Optional) The ID of the page to restrict the search to.
        :param ignore_ids: (Optional) A list of Page IDs and Block IDs to ignore in the search.
        :param ignore_notion_links: (Optional) If True, ignores content blocks that contain Notion workspace links.
        :return: A dictionary with 'page_id', 'block_id', and 'title' of the best match, or None if no match is found.
        """
        # Initialize ignore_ids if not provided
        if ignore_ids is None:
            ignore_ids = []

        # Create a cache directory if it doesn't exist
        cache_dir = os.path.join(os.getcwd(), 'notion_content_cache')
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        
        # Define cache file paths
        if database_id:
            cache_file = os.path.join(cache_dir, f'{database_id}_content.json')
        else:
            cache_file = os.path.join(cache_dir, 'workspace_content.json')

        # Load cache if it exists
        if os.path.exists(cache_file):
            with open(cache_file, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    logger.error(f"Cache file {cache_file} is corrupted. Resetting cache.")
                    data = []
        else:
            data = []

        # Fetch pages and update cache if necessary
        pages = []
        if page_id:
            # Fetch the specific page
            url = self.endpoint('pages', page_id=page_id)
            response, status_code = self.notion(url, 'get')
            if status_code == 200:
                pages = [response]
            else:
                logger.error(f"Failed to fetch page with id {page_id}")
                return None
        elif database_id:
            # Fetch all pages from the database
            url = self.endpoint('database query', database_id=database_id)
            has_more = True
            start_cursor = None
            while has_more:
                body = {'page_size': 100}
                if start_cursor:
                    body['start_cursor'] = start_cursor
                response, status_code = self.notion(url, 'post', body=body)
                if status_code != 200:
                    logger.error(f"Failed to fetch pages from database {database_id} at cursor {start_cursor}")
                    break
                results = response.get('results', [])
                pages.extend(results)
                has_more = response.get('has_more', False)
                start_cursor = response.get('next_cursor', None)
        else:
            # Fetch all pages in the workspace
            url = self.endpoint('search')
            has_more = True
            start_cursor = None
            while has_more:
                body = {
                    'page_size': 100,
                    'query': '',
                    'filter': {'value': 'page', 'property': 'object'}
                }
                if start_cursor:
                    body['start_cursor'] = start_cursor
                response, status_code = self.notion(url, 'post', body=body)
                if status_code != 200:
                    logger.error(f"Failed to fetch workspace pages at cursor {start_cursor}")
                    break
                results = response.get('results', [])
                pages.extend(results)
                has_more = response.get('has_more', False)
                start_cursor = response.get('next_cursor', None)

        # Prepare a lookup for cached pages
        cached_pages = {item['id']: item for item in data}

        # Gather all page titles
        page_titles = {}
        for page in pages:
            page_id_ = page['id']
            properties = page.get('properties', {})
            title_prop = None
            for prop in properties.values():
                if prop.get('type') == 'title':
                    title_prop = prop
                    break
            if title_prop:
                title_items = title_prop.get('title', [])
                title_text = ''.join([t.get('plain_text', '') for t in title_items])
                page_titles[page_id_] = title_text

        # Check if query includes a page title
        query_pieces = [piece.strip() for piece in re.split(r'[;,]', query)]

        if not page_id:
            matched_page_id = None
            remaining_query_pieces = []
            for piece in query_pieces:
                matched_title = self.match(piece, list(page_titles.values()))
                if matched_title:
                    # Find the page_id corresponding to the matched title
                    for pid, title in page_titles.items():
                        if title == matched_title:
                            matched_page_id = pid
                            break
                else:
                    remaining_query_pieces.append(piece)

            # Update query and restrict search if page_id is found
            if matched_page_id and remaining_query_pieces:
                query = ' '.join(remaining_query_pieces)
                pages = [page for page in pages if page['id'] == matched_page_id]
            else:
                # Use the original query if no page title is matched
                query = ' '.join(query_pieces)
        else:
            # page_id is given, restrict pages to that page
            pages = [page for page in pages if page['id'] == page_id]
            query = ' '.join(query_pieces)

        # Update pages data if necessary
        for page in pages:
            page_id_ = page.get('id')
            page_properties = page.get('properties', {})
            # Get the title
            title_text = page_titles.get(page_id_, '')

            # Get last edited time
            last_edited_time = page.get('last_edited_time')

            # Check if page content is already cached and up-to-date
            cache_entry = cached_pages.get(page_id_)
            if cache_entry and cache_entry.get('last_edited_time') == last_edited_time:
                continue  # Content is up-to-date
            else:
                # Fetch page content (blocks) recursively
                def fetch_blocks(block_id):
                    """
                    Fetches all blocks recursively starting from the given block_id.
                    Automatically skips footnote sections based on their specific structure.
                    :param block_id: The ID of the block to start fetching from.
                    :return: A list of block information.
                    """
                    blocks = []
                    has_more = True
                    start_cursor = None
                    in_footnote = False  # Flag to indicate if we are inside a footnote section

                    while has_more:
                        url = self.endpoint('blocks_children', block_id=block_id)
                        params = {'start_cursor': start_cursor} if start_cursor else {}
                        response, status_code = self.notion(url, 'get', body=params)
                        if status_code != 200:
                            logger.error(f"Failed to fetch blocks for block_id {block_id}")
                            break
                        results = response.get('results', [])

                        i = 0
                        while i < len(results):
                            block = results[i]
                            block_id_ = block.get('id')
                            block_type = block.get('type')

                            # Detect the start of a footnote section
                            if block_type == 'heading_1':
                                rich_text_array = block.get('heading_1', {}).get('rich_text', [])
                                heading_text = ''.join([t.get('plain_text', '') for t in rich_text_array]).strip()
                                footnote_headings = ["Wiki Footnote", "Link Footnote", "Reference Links", "Reference Footnote"]
                                if heading_text in footnote_headings:
                                    # Possible footnote section detected
                                    # Check the next block to confirm footnote structure
                                    if i + 1 < len(results):
                                        next_block = results[i + 1]
                                        if next_block.get('type') == 'quote':
                                            # Get the quote text
                                            quote_text_array = next_block.get('quote', {}).get('rich_text', [])
                                            quote_text = ''.join([t.get('plain_text', '') for t in quote_text_array]).strip()
                                            footnote_quotes = ["Page Sources", "Page Links", "Internal References", "Non-Wikipedia Links"]
                                            if quote_text in footnote_quotes:
                                                # Confirmed footnote section
                                                in_footnote = True
                                                # Skip the heading and quote blocks
                                                i += 2  # Move past the heading and quote blocks
                                                continue
                            # If currently in footnote, check if we have exited
                            if in_footnote:
                                # Check if current block is a heading_1 that is not a footnote heading
                                if block_type == 'heading_1':
                                    rich_text_array = block.get('heading_1', {}).get('rich_text', [])
                                    heading_text = ''.join([t.get('plain_text', '') for t in rich_text_array]).strip()
                                    footnote_headings = ["Wiki Footnote", "Link Footnote", "Reference Links", "Reference Footnote"]
                                    if heading_text not in footnote_headings:
                                        # Exited footnote section
                                        in_footnote = False
                                        # Re-evaluate this block now that we're out of footnote
                                        continue
                                    else:
                                        # Still in footnote
                                        i += 1
                                        continue
                                else:
                                    # Skip this block since we're in a footnote
                                    i += 1
                                    continue

                            # Process the block as usual
                            block_info = {
                                'id': block_id_,
                                'type': block_type,
                                'has_children': block.get('has_children', False),
                                'content': '',  # Initialize as empty string
                                'children': []  # For nested blocks
                            }

                            # Process the content based on block type (existing logic)
                            if block_type in [
                                'paragraph', 'heading_1', 'heading_2', 'heading_3',
                                'bulleted_list_item', 'numbered_list_item', 'to_do',
                                'toggle', 'quote', 'callout', 'code', 'equation'
                            ]:
                                content = ''
                                if block_type == 'equation':
                                    equation = block.get('equation', {}).get('expression', '')
                                    content = equation
                                elif block_type == 'code':
                                    code_texts = block.get('code', {}).get('rich_text', [])
                                    for text in code_texts:
                                        plain_text = text.get('plain_text', '')
                                        href = text.get('href', None)
                                        if href and 'notion.so' in href.lower():
                                            content += f"{plain_text} {{{href}}}"
                                        else:
                                            content += plain_text
                                else:
                                    rich_text_array = block.get(block_type, {}).get('rich_text', [])
                                    for text in rich_text_array:
                                        plain_text = text.get('plain_text', '')
                                        href = text.get('href', None)
                                        if href and 'notion.so' in href.lower():
                                            content += f"{{{plain_text}:{href}}}"
                                        else:
                                            content += plain_text
                                block_info['content'] = content
                            else:
                                # For block types without rich_text, leave content empty or handle as needed
                                block_info['content'] = ''

                            # If the block has children, fetch them recursively
                            if block.get('has_children', False):
                                child_blocks = fetch_blocks(block_id_)
                                block_info['children'] = child_blocks

                            blocks.append(block_info)
                            i += 1  # Move to the next block

                        has_more = response.get('has_more', False)
                        start_cursor = response.get('next_cursor', None)

                    return blocks

                # Fetch the blocks starting from the page id
                blocks = fetch_blocks(page_id_)

                # Update or add the cache entry
                data_entry = {
                    'id': page_id_,
                    'title': title_text,
                    'last_edited_time': last_edited_time,
                    'blocks': blocks
                }
                # Update the cached_pages lookup
                cached_pages[page_id_] = data_entry

        # Update the data list with the updated cached_pages
        data = list(cached_pages.values())

        # Save data to cache
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Failed to write cache to {cache_file}: {e}")

        # Step 1: Narrow down potential matches using keyword search
        potential_matches = []
        query_lower = query.lower()

        # Extract keywords using simple splitting for short queries
        if len(query.split()) <= 3:
            # For short queries, use the query terms directly as keywords
            keywords = query_lower.split()
        else:
            # For longer queries, you can use a more sophisticated method
            # For example, you could use NLP techniques to extract keywords
            # For simplicity, we'll split on spaces and remove common stopwords
            stopwords = {'the', 'and', 'or', 'in', 'on', 'at', 'a', 'an', 'of', 'for', 'with', 'to', 'from'}
            keywords = [word for word in query_lower.split() if word not in stopwords]

        num_keywords = len(keywords)

        # Define count_keyword_matches inside search
        def count_keyword_matches(keywords: List[str], content: str) -> int:
            content_words = set(re.findall(r'\w+', content.lower()))
            return sum(1 for kw in keywords if kw in content_words)

        # Define calculate_relevance_score inside search
        def calculate_relevance_score(matches_count, num_keywords, block_priority):
            keyword_match_ratio = matches_count / num_keywords if num_keywords > 0 else 0
            score = keyword_match_ratio
            if block_priority == 1:
                score += 0.5  # Boost score for headings
            return score

        for item in data:
            page_id_ = item['id']
            title_text = item['title']
            
            # Skip if page_id_ is in ignore_ids
            if page_id_ in ignore_ids:
                continue

            # Search in page title
            if query_lower in title_text.lower():
                potential_matches.append({
                    'page_id': page_id_,
                    'block_id': None,
                    'content': title_text,
                    'title': title_text,
                    'priority': 0,  # Highest priority for page titles
                    'score': 1.5  # Max score with boost
                })
                continue  # Skip to next item

            # Search in blocks
            for block in item['blocks']:
                def search_block(block, keywords, num_keywords):
                    block_id_ = block.get('id')
                    content = block.get('content', '')
                    
                    if not content:
                        return

                    # Skip if block_id_ is in ignore_ids
                    if block_id_ in ignore_ids:
                        return

                    # If ignore_notion_links is True and content contains a Notion link, skip
                    if ignore_notion_links:
                        content = re.sub(r'\{(.*?)\:(https?:\/\/(?:www\.)?notion\.so\/\S{32}#\S{32})\}', '', content, flags=re.IGNORECASE)

                    content_lower = content.lower()
                    block_type = block.get('type', '')
                    
                    # Determine priority based on block type
                    block_priority = 1 if block_type in ['heading_1', 'heading_2', 'heading_3'] else 2

                    # Exact phrase match
                    if query_lower in content_lower:
                        potential_matches.append({
                            'page_id': page_id_,
                            'block_id': block['id'],
                            'content': content,
                            'title': content if block_priority == 1 else '',
                            'priority': 0,  # Highest priority
                            'score': 1.0 + (0.5 if block_priority == 1 else 0)
                        })
                    else:
                        # Keyword-based matching
                        matches_count = count_keyword_matches(keywords, content)
                        if num_keywords >= 4:
                            if matches_count >= num_keywords - 1:
                                score = calculate_relevance_score(matches_count, num_keywords, block_priority)
                                potential_matches.append({
                                    'page_id': page_id_,
                                    'block_id': block['id'],
                                    'content': content,
                                    'title': content if block_priority == 1 else '',
                                    'priority': block_priority,
                                    'score': score
                                })
                        elif num_keywords == 3:
                            if matches_count == 3:
                                score = calculate_relevance_score(matches_count, num_keywords, block_priority)
                                potential_matches.append({
                                    'page_id': page_id_,
                                    'block_id': block['id'],
                                    'content': content,
                                    'title': content if block_priority == 1 else '',
                                    'priority': block_priority,
                                    'score': score
                                })
                        elif num_keywords == 2:
                            if matches_count == 2:
                                score = calculate_relevance_score(matches_count, num_keywords, block_priority)
                                potential_matches.append({
                                    'page_id': page_id_,
                                    'block_id': block['id'],
                                    'content': content,
                                    'title': content if block_priority == 1 else '',
                                    'priority': block_priority,
                                    'score': score
                                })
                        elif num_keywords == 1:
                            if matches_count == 1:
                                score = calculate_relevance_score(matches_count, num_keywords, block_priority)
                                potential_matches.append({
                                    'page_id': page_id_,
                                    'block_id': block['id'],
                                    'content': content,
                                    'title': content if block_priority == 1 else '',
                                    'priority': block_priority,
                                    'score': score
                                })
                        # No Levenshtein distance matching for queries with fewer than 4 keywords
                        elif num_keywords >= 4 and matches_count == 0:
                            # Use Levenshtein distance if no matches found and query is sufficiently long
                            distance = Levenshtein.distance(query_lower, content_lower)
                            normalized_distance = distance / max(len(query_lower), len(content_lower))
                            if normalized_distance <= 0.2:  # Adjust threshold as needed
                                potential_matches.append({
                                    'page_id': page_id_,
                                    'block_id': block['id'],
                                    'content': content,
                                    'title': content if block_priority == 1 else '',
                                    'priority': block_priority,
                                    'score': 0.5  # Lower score for Levenshtein matches
                                })
                        else:
                            # Do nothing if no matches and query is short
                            pass

                    # Recursively search in children
                    for child in block.get('children', []):
                        search_block(child, keywords, num_keywords)

                search_block(block, keywords, num_keywords)

        # If no potential matches found, return None
        if not potential_matches:
            return None

        # Step 2: Sort potential matches by score in descending order
        potential_matches.sort(key=lambda x: (-x['score'], x['priority']))

        # Limit to max 10 potential matches
        potential_matches = potential_matches[:10]

        # Prepare data for Cohere
        cohere_inputs = []
        for idx, match in enumerate(potential_matches):
            content_snippet = match['content']
            cohere_inputs.append(f"Option {idx+1}:\n{content_snippet}\n")

        # Prepare the prompt for Cohere
        cohere_prompt = f"You are to select the best matching content for the following query:\n\nQuery: {query}\n\nOptions:\n"
        cohere_prompt += "\n".join(cohere_inputs)
        cohere_prompt += "\nPlease provide the number of the option that best matches the query."

        chat_history = ['user: You are to select the best matching content for the following query:\n\nQuery: V4\n\nOptions:\nOption 1:\nTest V4 n.4.3.4\n\nOption 2:\nTest V4 n.4.2.5\n\nOption 3:\nTest V4 n.4.3.2\n\nOption 4:\nTest V4 n.4.3.0\n\nOption 5:\nV4\n\nOption 6:\nTest V4 n.4.3.5\n\nOption 7:\nTest V4 n.4.3.6\n\nOption 8:\nTest V4 n.4.3.4\n\nOption 9:\nTest V4 n.4.3.3\n\nOption 10:\nTest V4 n.4.3.3\n\nPlease provide strictly only the number of the option that best matches the query.', 'chatbot: 4']

        # Call Cohere to get the best match
        output, status_code = self.cohere(cohere_prompt, chat_history=chat_history)
        if status_code == 200:
            # Extract the selected option number
            match_number = int(output)
            if match_number:
                selected_index = match_number - 1
                if 0 <= selected_index < len(potential_matches):
                    best_match = potential_matches[selected_index]
                else:
                    best_match = potential_matches[0]  # Default to first option
            else:
                best_match = potential_matches[0]  # Default to first option if parsing fails
        else:
            logger.error("Failed to select best match using Cohere.")
            best_match = potential_matches[0]  # Default to first option

        # Step 3: Extract the title if not already available
        if not best_match.get('title'):
            # Refined prompt to include both query and content for better title extraction
            extract_prompt = (
                f"Given the following query and content, extract or infer the most appropriate title. "
                f"If the content does not contain an explicit title, generate a suitable title that best represents the main idea based on both the query and the content, using only words from them. Return only the title.\n\n"
                f"Query: \"{query}\"\n\n"
                f"Content:\n\"{best_match['content']}\""
            )
            title_output, status_code = self.cohere(extract_prompt)
            if status_code == 200:
                extracted_title = title_output.strip()
                best_match['title'] = extracted_title
            else:
                # If Cohere fails, use the first sentence as a fallback
                best_match['title'] = best_match['content'].split('.')[0]

        # Step 4: Return the page_id, block_id, and title of the best match
        result = {
            'page_id': best_match['page_id'],
            'block_id': best_match['block_id'],
            'title': best_match['title']
        }

        return result

    @default
    def query(self, query: str, database_id: Optional[str] = None) -> List[Dict]:
        if database_id: pass
        else: raise InputError(
            'Missing Database ID',
            location='query',
            troubleshoot='Neither Class nor Method database ID was given. Provide one.'
        )

        # Check if query is cached
        cache_entry = next((item for item in self.cache['queries'] if item['database_id'] == database_id and item['query'] == query), None)
        if cache_entry:
            return cache_entry['results']

        # If not cached, proceed
        matches = []

        # Step 1: Retrieve database schema
        url = self.endpoint('database', database_id=database_id)
        db_response, status_code = self.notion(url, 'get')

        properties = db_response.get('properties', {})

        # First, attempt case-sensitive search
        found_case_sensitive = False

        # Helper function to perform search on properties
        def search_properties(properties, query, case_sensitive):
            matches = []
            for prop_name, prop_info in properties.items():
                prop_id = prop_info.get('id', '')
                prop_type = prop_info.get('type', '')
                prop_name_match = prop_name if case_sensitive else prop_name.lower()
                query_match = query if case_sensitive else query.lower()

                # Check if property name matches
                if query_match in (prop_name_match if case_sensitive else prop_name_match.lower()):
                    matches.append({
                        'match_type': 'property_name',
                        'name': prop_name,
                        'property_type': prop_type,
                        'id': prop_id,
                        'type': 'property'
                    })

                # Check if property type matches exactly
                prop_type_match = prop_type if case_sensitive else prop_type.lower()
                if query_match == prop_type_match:
                    matches.append({
                        'match_type': 'property_type',
                        'name': prop_name,
                        'id': prop_id,
                        'type': 'property'
                    })

                # If property is 'select' or 'multi_select', get options
                if prop_type in ['select', 'multi_select']:
                    options = prop_info.get(prop_type, {}).get('options', [])
                    for option in options:
                        option_name = option.get('name', '')
                        option_id = option.get('id', '')
                        option_name_match = option_name if case_sensitive else option_name.lower()
                        if query_match in option_name_match:
                            matches.append({
                                'match_type': 'option_name',
                                'name': option_name,
                                'id': option_id,
                                'property_name': prop_name,
                                'property_id': prop_id,
                                'property_type': prop_type,
                                'type': 'option'
                            })
            return matches

        # First attempt: case-sensitive search
        matches = search_properties(properties, query, case_sensitive=True)
        if matches:
            found_case_sensitive = True

        # Helper function to search pages
        def search_pages(query, case_sensitive):
            matches = []
            has_more = True
            next_cursor = None
            url = self.endpoint('database query', database_id=database_id)
            while has_more:
                body = {}
                if next_cursor:
                    body['start_cursor'] = next_cursor
                response, status_code = self.notion(url, 'post', body=body)
                results = response.get('results', [])
                for page in results:
                    page_id = page.get('id')
                    properties = page.get('properties', {})
                    # Get the title
                    for prop_name, prop_info in properties.items():
                        prop_type = prop_info.get('type', '')
                        if prop_type == 'title':
                            title_items = prop_info.get('title', [])
                            title_text = ''.join([item.get('plain_text', '') for item in title_items])
                            if case_sensitive:
                                if query in title_text:
                                    matches.append({
                                        'type': 'page',
                                        'id': page_id,
                                        'name': title_text,
                                        'match_type': 'title'
                                    })
                            else:
                                if query.lower() in title_text.lower():
                                    matches.append({
                                        'type': 'page',
                                        'id': page_id,
                                        'name': title_text,
                                        'match_type': 'title'
                                    })
                            break  # Assuming only one title property
                has_more = response.get('has_more', False)
                next_cursor = response.get('next_cursor', None)
            return matches

        # Search pages with case-sensitive matching
        page_matches = search_pages(query, case_sensitive=True)
        if page_matches:
            found_case_sensitive = True
        matches.extend(page_matches)

        if not found_case_sensitive:
            # No case-sensitive matches found, try case-insensitive search
            matches = search_properties(properties, query, case_sensitive=False)
            page_matches = search_pages(query, case_sensitive=False)
            matches.extend(page_matches)

        # Cache the results
        self.cache['queries'].append({
            'database_id': database_id,
            'query': query,
            'results': matches
        })

        return matches

    def wikipedia(self, title: str) -> Optional[Tuple[str, str]]:
        try:
            # Attempt to detect the language of the query using AI (Cohere)
            chat_history = [
                'user: Teorema di Weierstrass',
                'chatbot: it',
                'user: Astronomy',
                'chatbot: en'
            ]
            response, status_code = self.cohere(
                f'"{title}".\n\nWhich language is this? Respond strictly only with two-letter format of the language ("it", "en", "es", "de", etc.). If you aren\'t able to deduce a language, default to "en".',
                chat_history=chat_history
            )
            if status_code == 200:
                response = response.strip()
                if len(response) == 2 and response.isalpha():
                    language = response.lower()
                else:
                    language = 'en'
            else:
                language = 'en'
        except Exception as e:
            logger.error(f"Error detecting language: {e}")
            language = 'en'

        api_url = f'https://{language}.wikipedia.org/w/api.php'

        def correct_spelling_ai(search_title: str) -> str:
            """
            Uses Cohere AI to correct spelling mistakes in the input title.

            Parameters:
                search_title (str): The title to correct.

            Returns:
                str: The corrected title.
            """
            try:
                chat_history = ['user: SDiffrazione elettromagnetica', 'chatbot: Diffrazione Elettromagnetica', 'user: Sqdra di calci italiana', 'chatbot: Squadra di calcio italiana']
                prompt = f"Correct the spelling of this sentence in the this language ({language}):\n\"{search_title}\".\nOutput the corrected sentence."
                corrected_text, status_code = self.cohere(prompt, chat_history=chat_history)
                corrected_text = corrected_text.strip()
                if corrected_text and corrected_text.lower() != search_title.lower():
                    logger.info(f"Spell correction (AI): '{search_title}' corrected to '{corrected_text}'")
                    return corrected_text
                else:
                    return search_title
            except Exception as e:
                logger.error(f"Error using Cohere for spell correction: {e}")
                return search_title
            
        def perform_search(search_title: str) -> Optional[Tuple[str, str]]:
            search_params = {
                'action': 'query',
                'list': 'search',
                'srsearch': search_title,
                'format': 'json',
                'srlimit': 10,  # Increased limit to get more results
                'srwhat': 'text',
                'srprop': '',
            }
            try:
                search_response = requests.get(api_url, params=search_params, timeout=10)
                search_response.raise_for_status()
                search_data = search_response.json()
                search_results = search_data.get('query', {}).get('search', [])
                if search_results:
                    # Collect titles
                    titles = [result.get('title', '') for result in search_results]
                    # Use AI (Cohere) to find the best match
                    try:
                        # Prepare the prompt
                        prompt = f'Given the following Wikipedia search results for "{search_title}":\n'
                        for idx, t in enumerate(titles, 1):
                            prompt += f'{idx}. {t}\n'
                        prompt += f'Which one is the most relevant to the query "{search_title}"? Respond with the number only.'
                        # Call Cohere
                        ai_response, status_code = self.cohere(prompt)
                        if status_code == 200:
                            ai_response = ai_response.strip()
                            if ai_response.isdigit() and 1 <= int(ai_response) <= len(titles):
                                best_title = titles[int(ai_response) - 1]
                            else:
                                # If the AI response is invalid, default to the first title
                                best_title = titles[0]
                    except Exception as e:
                        logger.error(f"Error using Cohere to select best match: {e}")
                        best_title = titles[0]
                    # Get the page URL
                    encoded_title = urllib.parse.quote(best_title.replace(' ', '_'))
                    url = f'https://{language}.wikipedia.org/wiki/{encoded_title}'
                    return best_title, url
                return None
            except requests.RequestException as e:
                logger.error(f"Network error during search: {e}")
                return None

        params = {
            'action': 'query',
            'format': 'json',
            'titles': title,
            'redirects': 1,
            'prop': 'info|pageprops|categories',
            'inprop': 'url',
            'ppprop': 'disambiguation',
            'cllimit': 'max',
        }

        try:
            # Try to get the exact page
            response = requests.get(api_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            pages = data.get('query', {}).get('pages', {})
            page = next(iter(pages.values()))
            if 'missing' in page:
                # Page does not exist, perform search
                result = perform_search(title)
                if result:
                    return result
                else:
                    result = perform_search(correct_spelling_ai(title))
                    if result:
                        return result
                    else:
                        return None
            else:
                # Page exists
                is_disambiguation = False
                pageprops = page.get('pageprops', {})
                if 'disambiguation' in pageprops:
                    is_disambiguation = True
                else:
                    categories = page.get('categories', [])
                    for category in categories:
                        cat_title = category.get('title', '').lower()
                        if 'disambiguation pages' in cat_title:
                            is_disambiguation = True
                            break
                page_title = page.get('title', '')
                page_url = page.get('fullurl', '')
                if not page_url:
                    # Construct the URL if not provided
                    encoded_title = urllib.parse.quote(page_title.replace(' ', '_'))
                    page_url = f'https://{language}.wikipedia.org/wiki/{encoded_title}'
                if not is_disambiguation:
                    return page_title, page_url
                else:
                    # Page is a disambiguation page, perform search
                    result = perform_search(title)
                    if result:
                        return result
                    else:
                        result = perform_search(correct_spelling_ai(title))
                        if result:
                            return result
                        else:
                            return None
                        
        except requests.RequestException as e:
            logger.error(f"Network error while accessing Wikipedia API: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in wikipedia function: {e}")
            return None



class NotionDraft(NotionBase):
    def __init__(
        self, 
        notion_api_key: Optional[str] = None, 
        username: Optional[str] = None, 
        password: Optional[str] = None,
        database_link: Optional[str] = None,
        page_link: Optional[str] = None
    ):
        """
        Initialize the NotionDraft class.

        :param notion_api_key: Optional Notion API key.
        :param username: Optional username to retrieve API key if not provided.
        :param password: Optional password to retrieve API key if not provided.
        :param database_link: Optional Notion database link to set as default.
        :param page_link: Optional Notion page link to set as default.
        """
        # Initialize the parent NotionBase class
        super().__init__(notion_api_key=notion_api_key, username=username, password=password)

        # Initialize default IDs
        self.default_database_id: Optional[str] = None
        self.default_page_id: Optional[str] = None

        # Process default_database_link if provided
        if database_link:
            try:
                logger.info("Processing default_database_link.")
                database_id = self.id(database_link=database_link)
                # The id() method already verifies the ID, so no need to make another request
                self.default_database_id = database_id
                logger.info(f"Default database ID set: {database_id}")
            except NotionProcessorError as e:
                logger.error(f"Error setting default_database_id: {str(e)}")
                raise

        # Process default_page_link if provided
        if page_link:
            try:
                logger.info("Processing default_page_link.")
                page_id = self.id(page_link=page_link)
                # The id() method already verifies the ID, so no need to make another request
                self.default_page_id = page_id
                logger.info(f"Default page ID set: {page_id}")
            except NotionProcessorError as e:
                logger.error(f"Error setting default_page_id: {str(e)}")
                raise
    
    #Input: <metadata> value from input string; Output: Empty Body Page JSON to post.
    @default
    def metadata(self, input=None, database_id=None, title: Optional[str] = None, emoji: Optional[str] = None):
        """
        Processes the input to construct metadata for Notion API requests.
        Includes error handling and logging.
        """
        try:
            # Strip <meta> tags if present
            if input is not None:
                if "<meta>" in input or "</meta>" in input:
                    meta_content = re.search(r'<meta>(.*?)</meta>', input)
                    input = meta_content.group(1)
            else:
                input = ''
            headers = {}
            properties = {}
            today = datetime.datetime.now().date()

            if input:
                MARKEGEX = {
                    r"<title>\2</title>": ['tit', 'title', 'name', 'titolo', 'nome'],
                    r"<relation>\2</relation>": ['parent', r'parent\s*item', 'pit', 'pitem', r'pagina\s*padre'],
                    r"<date>\2</date>": ['date', 'dat', 'data', 'giorno', 'orario', 'time', 'day'],
                    r"<checkbox>\2</checkbox>": ['checkbox', 'check', 'chk'],
                    r"<multi_select>\2</multi_select>": ['msl', 'multi-select', 'msel', 'multisel', r'multi\s*select', 'multi_select', 'mselect', 'multisl'],
                    r"<select>\2</select>": ['sel', 'select', 'sl'],
                    r"<icon>\2</icon>": ['ico', 'icon', 'emoji', 'emoticon', 'icona'],
                    r"<undefined>\1</undefined>": None
                }

                for key, value in MARKEGEX.items():
                    if value:
                        keyword_pattern = r'(' + '|'.join(re.escape(kw) for kw in value) + r')'
                        pattern = keyword_pattern + r'\s*\(\s*([^)]+?)\s*\)[\s,;]*'
                        replacement = rf'{key}'
                    else:
                        pattern = r'>?\s*\w*?\s*\(\s*([^)]+?)\s*\)[\s,;]*<?'
                        replacement = rf'>{key}<'
                    input = re.sub(pattern, replacement, input)

                input_list = list({x for x in re.split(r'</\w+>', input) if x})
                for data in input_list:
                    pattern = r'<(\w+)>\s*(?:([^:]+)\s*:)?\s*([^,\n]+(?:,\s*[^,\n]+)*)'
                    match = re.match(pattern, data)
                    if not match:
                        logger.warning(f"Data does not match the pattern: {data}")
                        continue
                    header = {
                        'type': match.group(1) and match.group(1).strip(),
                        'property name': match.group(2) and match.group(2).strip(),
                        'value': [value.strip() for value in match.group(3).strip().split(',')]
                    }
                    logger.debug(f"Parsed header: {header}")

                    if header['type'] == 'undefined':
                        search = [header['property name']] if header['property name'] else header['value'] if header['value'] else None
                        logger.debug(f"Search terms: {search}")
                        if search:
                            if len(search) == 1:
                                results = self.query(search[0])
                                logger.debug(f"Query results for {search[0]}: {results}")
                                if results and len(results) == 1:
                                    type_ = results[0]['property_type']
                                    data = f'<{type_}>{header["property name"]}:{header["value"]}' if header['property name'] else f'<{type_}>{", ".join(header["value"])}'
                                    logger.debug(f"New data appended to input_list: {data}")
                                    input_list.append(data)
                                    continue
                                else:
                                    logger.error(f"Couldn't find a unique property matching the criteria: {search[0]}")
                                    raise InputError(
                                        f"Couldn't find a unique property matching the criteria: {search[0]}",
                                        location='metadata',
                                        troubleshoot='Please provide a valid property name.'
                                    )
                            elif len(search) > 1:
                                found = False
                                for value in search:
                                    results = self.query(value)
                                    logger.debug(f"Query results for {value}: {results}")
                                    if results and len(results) == 1:
                                        type_ = results[0]['property_type']
                                        data = f'<{type_}>{", ".join(header["value"])}'
                                        found = True
                                        input_list.append(data)
                                        break
                                if found:
                                    continue
                                else:
                                    logger.error("Couldn't find any property matching the criteria.")
                                    raise InputError(
                                        "Couldn't find any property matching the criteria.",
                                        location='metadata',
                                        troubleshoot='Please provide valid property names.'
                                    )
                        else:
                            logger.error("No value was given for undefined tag.")
                            raise InputError(
                                "No value was given for undefined tag.",
                                location='metadata',
                                troubleshoot='Please provide a value for the undefined tag.'
                            )

                    if header['type'] != 'icon' and not self.query(header['type']):
                        logger.error(f'No properties for property type: "{header["type"]}"')
                        raise InputError(
                            f'No properties for property type: "{header["type"]}"',
                            location='metadata',
                            troubleshoot='Please provide a valid property type.'
                        )

                    if header['type'] not in ['multi_select', 'date'] and len(header['value']) > 1:
                        logger.error(f'"{header["type"]}" property does not admit more than one option')
                        raise InputError(
                            f'"{header["type"]}" property does not admit more than one option',
                            location='metadata',
                            troubleshoot='Please provide only one value for this property.'
                        )

                    if header['type'] == 'title':
                        if not title:
                            title = header['value'][0] if header['value'] else 'Untitled'
                            logger.debug(f"Title set to: {title}")

                    elif header['type'] == 'icon':
                        if not emoji:
                            emoji = header['value'][0] if header['value'] else None
                            logger.debug(f"Emoji set to: {emoji}")

                    elif header['type'] == 'relation':
                        results = self.query('relation')
                        if not results:
                            logger.error("No relation properties found.")
                            raise InputError(
                                "No relation properties found.",
                                location='metadata',
                                troubleshoot='Please ensure relation properties are defined.'
                            )
                        string = ', '.join(result['name'] for result in results)
                        chat_history = [
                            'system: You are given a list of names and you choose that one that suits best as a "parent" property name. You strictly answer only with the chosen name',
                            'user: Parent Item, Sub Item', 'chatbot: Sub Item',
                            'user: Parent, Sub', 'chatbot: Parent'
                        ]
                        response, status_code = self.cohere(string, chat_history)
                        if status_code == 200:
                            chosen_name = response.strip()
                            for result in results:
                                if result['name'] == chosen_name:
                                    query_results = self.query(header['value'][0])
                                    if query_results:
                                        parent_id = query_results[0].get('id') if query_results[0].get('type') == 'page' else None
                                        properties[result['name']] = {
                                            'relation': [
                                                {
                                                    'id': parent_id
                                                }
                                            ]
                                        }
                                        logger.debug(f"Relation property set: {properties[result['name']]}")
                                    else:
                                        logger.warning("Couldn't find and set Parent Item Property")
                                    break
                            else:
                                logger.error(f"Chosen relation property '{chosen_name}' not found in results.")
                                raise InputError(
                                    f"Chosen relation property '{chosen_name}' not found.",
                                    location='metadata',
                                    troubleshoot='Please ensure the chosen property exists.'
                                )
                        else:
                            logger.error("Failed to get response from cohere for relation property.")
                            raise ConnectionError(
                                "Failed to get response from cohere for relation property.",
                                location='metadata',
                                troubleshoot='Please check the cohere service.'
                            )

                    elif header['type'] == 'checkbox':
                        # Error handling for 'checkbox' type
                        if not header['property name']:
                            results = self.query('checkbox')
                            if not results:
                                logger.error("No checkbox properties found.")
                                raise InputError(
                                    "No checkbox properties found.",
                                    location='metadata',
                                    troubleshoot='Please ensure checkbox properties are defined.'
                                )
                            if len(results) == 1:
                                property_name = results[0]['name']
                            else:
                                logger.error("Multiple checkbox properties found without specifying a property name.")
                                raise InputError(
                                    "Multiple checkbox properties found.",
                                    location='metadata',
                                    troubleshoot='Please specify a property name for the checkbox.'
                                )
                        else:
                            property_name = header['property name']

                        true_synonyms = {'yes', 'ok', 'sì', 'sure', 'true', 'vero', 'completato', 'completed'}
                        false_synonyms = {'no', 'not yet', 'non ancora', 'falso', 'false', 'to do', 'incomplete'}

                        checkbox_input = header['value'][0].lower().strip()
                        if checkbox_input in true_synonyms:
                            checkbox_value = True
                        elif checkbox_input in false_synonyms:
                            checkbox_value = False
                        else:
                            logger.error(f"Invalid value for checkbox: {checkbox_input}")
                            raise InputError(
                                f"Invalid value for checkbox: {checkbox_input}",
                                location='metadata',
                                troubleshoot='Please provide a valid value for the checkbox.'
                            )

                        properties[property_name] = {
                            'checkbox': checkbox_value
                        }
                        logger.debug(f"Checkbox property set: {properties[property_name]}")

                    elif header['type'] == 'date':
                        if not header['property name']:
                            results = self.query('date')
                            if not results:
                                logger.error("No date properties found.")
                                raise InputError(
                                    "No date properties found.",
                                    location='metadata',
                                    troubleshoot='Please ensure date properties are defined in the database.'
                                )
                            if len(results) == 1:
                                property_name = results[0]['name']
                            else:
                                logger.error("Multiple date properties found without specifying a property name.")
                                raise InputError(
                                    "Multiple date properties found without specifying a property name.",
                                    location='metadata',
                                    troubleshoot='Please specify the date property name.'
                                )
                        else:
                            property_name = header['property name']

                        start = None
                        end = None

                        if len(header['value']) == 1:
                            try:
                                next_saturday = (today + datetime.timedelta((5 - today.weekday()) % 7)).isoformat()  # Saturday is weekday 5
                                next_wednesday = (today + datetime.timedelta((2 - today.weekday()) % 7)).isoformat()  # Wednesday is weekday 2
                                next_tuesday = (today + datetime.timedelta((1 - today.weekday()) % 7)).isoformat()  # Tuesday is weekday 1
                                tomorrow = (today + datetime.timedelta(days=1)).isoformat()
                                if today.day <= 12:
                                    twelfth_of_month = today.replace(day=12).isoformat()
                                else:
                                    next_month = (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=12)
                                    twelfth_of_month = next_month.isoformat()

                                if today.day <= 17:
                                    seventeenth_of_month = today.replace(day=17).isoformat()
                                else:
                                    next_month = (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=17)
                                    seventeenth_of_month = next_month.isoformat()

                                today_iso = today.isoformat()

                                system_message = f'''You are a date parser and formatter.
                    Your task is to recognize in a sentence which part indicates the start of something and which part indicates the end of it. You separate these parts with a "$" separator. The complete format should thus be: "{{start bit}}${{end bit}}". If one of them is missing, you omit the part, but the separator must still be included. You strictly output only the formatted string in this way. Be careful with time ranges where PM or AM are not specified in any form and choose the most reasonable.
                    Additionally, format input dates into ISO 8601. If the input is a sole two-digit number, treat it as the day of the month.
                    If no time is specified, do not add time, only include the date. If time is included, format it using the template (THH:MM) and add the +02:00 timezone offset. For relative time terms, refer to "{today_iso}". If no start is given, default to "{today_iso}". If end time is given but no start time is given, default to midnight. Output must strictly be the formatted string. If the sentence doesn't mention dates or doesn't make sense, respond "null".'''

                                chat_history = [
                                    f'system: {system_message}',
                                    'user: per il prossimo mercoledì', f'chatbot: {next_wednesday}$',
                                    'user: entro sabato alle sette', f'chatbot: {next_saturday}T07:00+02:00$',
                                    'user: dalle 8 alle 12', f'chatbot: {today_iso}T08:00+02:00${today_iso}T12:00+02:00',
                                    'user: martedì alle 17', f'chatbot: {next_tuesday}T17:00+02:00$',
                                    'user: fino al 17', f'chatbot: {today_iso}${seventeenth_of_month}',
                                    'user: 12', f'chatbot: {twelfth_of_month}',
                                    'user: da oggi alle 8 fino a domani alle 11', f'chatbot: {today_iso}T08:00+02:00${tomorrow}T11:00+02:00',
                                    'user: fino alle 9 di domani sera', f'chatbot: {today_iso}T00:00+02:00${tomorrow}T21:00+02:00',
                                    'user: fino a domani alle 2', f'chatbot: {today_iso}T00:00+02:00${tomorrow}T14:00+02:00',
                                    'user: domani alle 4', f'chatbot: {tomorrow}T16:00+02:00$',
                                    'user: history art museum', 'chatbot: null'
                                ]

                                # Ensure header['value'] is a string
                                user_input = header['value'][0]

                                response, status_code = self.cohere(user_input, chat_history=chat_history)
                                if status_code != 200:
                                    logger.error("Failed to get response from cohere for date parsing.")
                                    raise ConnectionError(
                                        "Failed to get response from cohere for date parsing.",
                                        location='metadata',
                                        troubleshoot='Please check the cohere service.'
                                    )

                                response = response.strip()
                                logger.debug(f"Date parsing response: {response}")

                                if response.lower() != 'null':
                                    start_str, end_str = response.split('$')
                                    start = start_str.strip() if start_str else today_iso
                                    end = end_str.strip() if end_str else None
                                else:
                                    logger.error("Date parsing returned 'null'. Input may not contain valid date information.")
                                    raise InputError(
                                        "Date parsing failed. Input may not contain valid date information.",
                                        location='metadata',
                                        troubleshoot='Please provide a valid date or date range.'
                                    )

                            except ValueError as e:
                                logger.exception("Error while parsing dates.")
                                raise InputError(
                                    f"Error while parsing dates: {str(e)}",
                                    location='metadata',
                                    troubleshoot='Ensure the date format is correct.'
                                )
                            except Exception as e:
                                logger.exception("An unexpected error occurred while processing the date.")
                                raise NotionProcessorError(
                                    f"An unexpected error occurred while processing the date: {str(e)}",
                                    location='metadata',
                                    troubleshoot='An unexpected error occurred.'
                                )

                        elif len(header['value']) == 2:
                            # Assume the values are start and end dates
                            start = header['value'][0].strip()
                            end = header['value'][1].strip()
                        else:
                            logger.error("Invalid number of values provided for date.")
                            raise InputError(
                                "Invalid number of values provided for date.",
                                location='metadata',
                                troubleshoot='Please provide one or two date values.'
                            )

                        if start:
                            properties[property_name] = {
                                'date': {
                                    'start': start,
                                    'end': end
                                }
                            }
                            logger.debug(f"Date property set: {properties[property_name]}")
                        else:
                            logger.error("Start date is missing after processing.")
                            raise InputError(
                                "Start date is missing after processing.",
                                location='metadata',
                                troubleshoot='Please ensure a valid start date is provided.'
                            )

                    elif header['type'] == 'select':
                        # Error handling for 'select' type
                        if not header['property name']:
                            results = self.query('select')
                            if not results:
                                logger.error("No select properties found.")
                                raise InputError(
                                    "No select properties found.",
                                    location='metadata',
                                    troubleshoot='Please ensure select properties are defined.'
                                )
                            if len(results) == 1:
                                property_name = results[0]['name']
                            else:
                                logger.error("Multiple select properties found without specifying a property name.")
                                raise InputError(
                                    "Multiple select properties found.",
                                    location='metadata',
                                    troubleshoot='Please specify a property name for the select.'
                                )
                        else:
                            property_name = header['property name']

                        properties[property_name] = {
                            'select': {
                                'name': header['value'][0]
                            }
                        }
                        logger.debug(f"Select property set: {properties[property_name]}")

                    elif header['type'] == 'multi_select':
                        # Error handling for 'multi_select' type
                        if not header['property name']:
                            results = self.query('multi_select')
                            if not results:
                                logger.error("No multi_select properties found.")
                                raise InputError(
                                    "No multi_select properties found.",
                                    location='metadata',
                                    troubleshoot='Please ensure multi_select properties are defined.'
                                )
                            if len(results) == 1:
                                property_name = results[0]['name']
                            else:
                                logger.error("Multiple multi_select properties found without specifying a property name.")
                                raise InputError(
                                    "Multiple multi_select properties found.",
                                    location='metadata',
                                    troubleshoot='Please specify a property name for the multi_select.'
                                )
                        else:
                            property_name = header['property name']

                        options = []
                        for option in header['value']:
                            option = option.strip()
                            if option:
                                options.append({'name': option})
                            else:
                                logger.warning(f"Ignoring empty option in multi_select: {option}")

                        if not options:
                            logger.error("No valid options provided for multi_select.")
                            raise InputError(
                                "No valid options provided for multi_select.",
                                location='metadata',
                                troubleshoot='Please provide valid options.'
                            )

                        properties[property_name] = {
                            'multi_select': options
                        }
                        logger.debug(f"Multi-select property set: {properties[property_name]}")

                    else:
                        logger.error(f"Unknown property type: {header['type']}")
                        raise InputError(
                            f"Unknown property type: {header['type']}",
                            location='metadata',
                            troubleshoot='Please provide a valid property type.'
                        )

                # After processing all data in input_list
                if title:
                    title_property = self.query('title')
                    if not title_property:
                        logger.error("Title property not found.")
                        raise InputError(
                            "Title property not found.",
                            location='metadata',
                            troubleshoot='Please ensure a title property is defined.'
                        )
                    title_property_name = title_property[0]['name']
                    properties[title_property_name] = {
                        'title': [
                            {
                                'text': {
                                    'content': title
                                }
                            }
                        ]
                    }
                    logger.debug(f"Title property set: {properties[title_property_name]}")
                else:
                    # Handle case where title is still None
                    title_property = self.query('title')
                    if not title_property:
                        logger.error("Title property not found.")
                        raise InputError(
                            "Title property not found.",
                            location='metadata',
                            troubleshoot='Please ensure a title property is defined.'
                        )
                    title_property_name = title_property[0]['name']
                    properties[title_property_name] = {
                        'title': [
                            {
                                'text': {
                                    'content': 'Untitled ' + str(today)
                                }
                            }
                        ]
                    }
                    logger.debug(f"Title property set to default: {properties[title_property_name]}")

                if emoji:
                    chat_history = [
                        'system: You are an emoji resolver. From a sentence, word or multiple words you resolve to one and only one emoji and respond strictly with that. Watch out for spelling mistakes',
                        'user: flag hole', 'chatbot: ⛳', 'user: baby', 'chatbot: 👶'
                    ]
                    response, status_code = self.cohere(emoji, chat_history=chat_history)
                    if status_code == 200:
                        headers['icon'] = {
                            'emoji': response.strip()
                        }
                        logger.debug(f"Icon set: {headers['icon']}")
                    else:
                        logger.error("Failed to get emoji from cohere.")
                        raise ConnectionError(
                            "Failed to get emoji from cohere.",
                            location='metadata',
                            troubleshoot='Please check the cohere service.'
                        )

                headers['parent'] = {
                    'database_id': database_id
                }

                headers['properties'] = properties

                headers['children'] = []

            else:
                # Handle case where input is empty
                if not title:
                    title = 'Untitled ' + str(today)
                title_property = self.query('title')
                if not title_property:
                    logger.error("Title property not found.")
                    raise InputError(
                        "Title property not found.",
                        location='metadata',
                        troubleshoot='Please ensure a title property is defined.'
                    )
                title_property_name = title_property[0]['name']
                properties[title_property_name] = {
                    'title': [
                        {
                            'text': {
                                'content': title
                            }
                        }
                    ]
                }
                logger.debug(f"Title property set: {properties[title_property_name]}")

                if emoji:
                    chat_history = [
                        'system: You are an emoji resolver. From a sentence, word or multiple words you resolve to one and only one emoji and respond strictly with that. Watch out for spelling mistakes',
                        'user: flag hole', 'chatbot: ⛳', 'user: baby', 'chatbot: 👶'
                    ]
                    response, status_code = self.cohere(emoji, chat_history=chat_history)
                    if status_code == 200:
                        headers['icon'] = {
                            'emoji': response.strip()
                        }
                        logger.debug(f"Icon set: {headers['icon']}")
                    else:
                        logger.error("Failed to get emoji from cohere.")
                        raise ConnectionError(
                            "Failed to get emoji from cohere.",
                            location='metadata',
                            troubleshoot='Please check the cohere service.'
                        )

                headers['parent'] = {
                    'database_id': database_id
                }

                headers['properties'] = properties

                headers['children'] = []

            return json.dumps(headers, indent=4)

        except NotionProcessorError as e:
            # Reraise custom exceptions
            raise e
        except Exception as e:
            # Catch any unexpected exceptions and log them
            logger.exception("An unexpected error occurred in metadata method.")
            raise NotionProcessorError(
                message=str(e),
                location='metadata',
                troubleshoot='An unexpected error occurred.'
            )

    #Input: marked input string; Output: Body Children JSON
    def body(self, input):
        """
        Processes the input text and converts it into Notion blocks, handling both
        block-level and inline elements, including nested lists. Adds error handling
        for unrecognized markers and invalid inputs.
        """

        # Split the input text into blocks based on block markers
        blocks = [x.strip() for x in re.split(r'<\/(?!i)\w{3}>', input) if x]

        children = []
        list_stack = []

        block_type_mapping = {
            'hd1': 'heading_1',
            'hd2': 'heading_2',
            'hd3': 'heading_3',
            'pgr': 'paragraph',
            'cod': 'code',
            'blq': 'equation',
        }

        def process_inlines(input: str) -> List[Dict[str, Any]]:
            """
            Processes inline elements within the content and returns a list of rich text elements.
            """
            rich_text = []
            for inline in [x for x in re.split(r'<\/i\w{2}>', input) if x]:
                print(inline)
                marker = (re.match(r'<(i\w{2})>', inline)).group(1)
                content = re.sub(r'<i\w{2}>', '', inline)
                if marker == 'ipg':
                    rich_text.append({
                        'type': 'text',
                        'text': {
                            'content': content
                        }
                    })
                elif marker == 'icd':
                    rich_text.append({
                        'type': 'text',
                        'text': {
                            'content': content
                        },
                        'annotations': {
                            'code': True
                        }
                    })
                elif marker == 'ieq':
                    rich_text.append({
                        'type': 'equation',
                        'equation': {
                            'expression': content
                        }
                    })
                else:
                    # Should not reach here due to regex, but added for safety
                    raise SyntaxError(f'Unrecognized inline marker "{marker}"')
                
            return rich_text

        for object in blocks:
            marker = (re.match(r'<((?!i)\w{3})>', object)).group(1)
            content = re.sub(r'<(?!i)\w{3}>', '', object)
            if marker in block_type_mapping:
                block_type = block_type_mapping[marker]
                level = None
            elif marker.startswith('bl'):
                block_type = 'bulleted_list_item'
                try:
                    level = int(marker[2:])
                except ValueError:
                    raise SyntaxError(f'Invalid bulleted list level in "{marker}"')
            elif marker.startswith('nr'):
                block_type = 'numbered_list_item'
                try:
                    level = int(marker[2:])
                except ValueError:
                    raise SyntaxError(f'Invalid numbered list level in "{marker}"')
            else:
                raise SyntaxError(
                    f'Unrecognized block marker "{marker}" in "{marker}". '
                    'Check your block formatting.'
                )

            # Process the content based on block type
            if block_type == 'equation':
                # Block equations cannot contain inlines
                block = {
                    'object': 'block',
                    'type': block_type,
                    block_type: {
                        'expression': content.strip()
                    }
                }
            elif block_type == 'code':
                inlines = process_inlines(content)
                block = {
                    'object': 'block',
                    'type': block_type,
                    block_type: {
                        'rich_text': inlines,
                        'language': 'python'  # Or specify appropriate language
                    }
                }
            else:
                # Process the inlines in the content
                inlines = process_inlines(content)
                block = {
                    'object': 'block',
                    'type': block_type,
                    block_type: {
                        'rich_text': inlines
                    }
                }

            # Handle nesting for list items
            if block_type in ['bulleted_list_item', 'numbered_list_item']:
                if level is None:
                    raise SyntaxError(f'List item level not specified in "{marker}"')
                # Adjust the list_stack according to the level
                while len(list_stack) >= level:
                    list_stack.pop()
                if level > 1 and list_stack:
                    # Add block as a child to the last item in the stack
                    parent = list_stack[-1]
                    parent_type = parent['type']
                    if 'children' not in parent[parent_type]:
                        parent[parent_type]['children'] = []
                    parent[parent_type]['children'].append(block)
                else:
                    # Level 1 item, add to children
                    children.append(block)
                list_stack.append(block)
            else:
                # For non-list items, reset the list_stack
                list_stack = []
                children.append(block)

        return json.dumps(children, indent=4)

    #Input: Body Children JSON; Ouput: No return, appends blocks to page
    @default
    def append(self, body, page_id=None):
        all_blocks = []

        def traverse(blocks_list):
            while isinstance(blocks_list, str):
                blocks_list = json.loads(blocks_list)
            for block in blocks_list:
                if block.get("object") == "block":
                    all_blocks.append(block)
                    children = block.get("children", [])
                    if isinstance(children, list):
                        traverse(children)

        try:
            traverse(body)
        except (ValueError, TypeError) as e:
            raise Exception(f"Error parsing body JSON: {e}")

        responses = []
        json_chunks = []
        for i in range(0, len(all_blocks), 100):
            chunk = {'children': all_blocks[i:i + 100]}
            try:
                response, status_code = self.notion(self.endpoint('blocks_children', block_id=page_id), 'patch', chunk)
                if status_code != 200:
                    raise Exception(f"Failed to append block chunk with status code: {status_code}")
                responses.append(response)
            except Exception as e:
                raise Exception(f"Error appending block chunk: {e}")

        return responses

    # Input: Empty Body Page JSON; Output: No return, posts the page with properties
    def post(self, metadata):
        try:
            response, status_code = self.notion(self.endpoint('pages'), 'post', body=json.loads(metadata))
            if status_code != 200:
                raise Exception(f"Failed to post page with status code: {status_code}")
            return response, status_code
        except (ValueError, TypeError) as e:
            raise Exception(f"Error parsing metadata JSON: {e}")
        except Exception as e:
            raise Exception(f"Error posting page: {e}")

    # Input: Marked Transcription; Output: Syncs all methods to create a page
    def create(self, input, database_id=None, title=None, emoji=None):
        #try:
        if "<meta>" in input or "</meta>" in input:
            meta_content = (re.search(r'<meta>(.*?)</meta>', input)).group(1)
        else:
            meta_content = None

        response, status_code = self.post(self.metadata(meta_content, database_id=database_id, title=title, emoji=emoji))
        page_id = response.get('id', '')
        if status_code == 200:
            body_content = re.sub(r'<meta>.*?</meta>', '', input)
            responses = self.append(self.body(body_content), page_id=page_id)
            if status_code == 200:
                responses.insert(0, response)
                return responses
        else:
            raise Exception(f"Failed to create page with status code: {status_code}")

        # except AttributeError:
        #     raise Exception("Error extracting metadata: Could not find <meta> tags")
        # except Exception as e:
        #     raise Exception(f"Error in create method: {e}")

class NotionLink(NotionDraft):
    def __init__(
        self, 
        notion_api_key: str | None = None, 
        username: str | None = None, 
        password: str | None = None, 
        database_link: str | None = None, 
        page_link: str | None = None
        ):

        super().__init__(notion_api_key, username, password, database_link, page_link)
        self.wiki_count = 0
        self.wiki_pairs = {}
        self.url_count = 0
        self.url_pairs = {}
        self.ref_count = 0
        self.ref_pairs = {}
        self.int_count = 0
        self.int_pairs = {}


    def process_blocks(self, page_id: str, function):
        """
        Traverses all blocks in a Notion page, applies a regex to rich_text items,
        and updates blocks where matches are found in batches of 100.

        :param page_id: The ID of the Notion page to process.
        """
        update_batch_size = 100
        updates_to_send = []

        def collect_updates(block: Dict):
            """
            Checks a single block for regex matches and prepares it for updating.

            :param block: A single Notion block.
            """
            block_type = block.get('type')
            block_id = block.get('id')

            # Skip equation blocks entirely
            if block_type == 'equation':
                logger.debug(f"Skipping equation block ID: {block_id}")
                return

            # Access the rich_text array based on block type
            block_content = block.get(block_type, {})
            rich_text = block_content.get('rich_text', [])

            updated_rich_text = function(rich_text, block_id)
            if updated_rich_text:
                # Prepare the PATCH body based on block type
                patch_body = {
                    block_type: {
                        "rich_text": updated_rich_text
                    }
                }
                updates_to_send.append((block_id, patch_body))
                logger.debug(f"Queued update for block ID: {block_id}")

        def send_updates_batch(updates: List[Tuple[str, Dict]]):
            """
            Sends a batch of updates to Notion.

            :param updates: A list of tuples containing block_id and PATCH body.
            """
            for block_id, patch_body in updates:
                block_url = self.endpoint('block', block_id=block_id)
                try:
                    response, status_code = self.notion(block_url, 'patch', body=patch_body, bypass_cache=True)
                    if status_code in [200, 201]:
                        logger.info(f"Successfully updated block ID: {block_id}")
                    else:
                        logger.error(f"Failed to update block ID: {block_id} with status code: {status_code}")
                except Exception as e:
                    logger.error(f"Error updating block ID: {block_id}: {e}")

        def traverse_and_collect(blocks: List[Dict]):
            """
            Traverses a list of blocks, processes them, and collects updates.

            :param blocks: A list of Notion blocks.
            """
            for block in blocks:
                collect_updates(block)

                # If the block has children, enqueue them for traversal
                if block.get('has_children'):
                    children_url = self.endpoint('blocks_children', block_id=block.get('id'))
                    has_more = True
                    start_cursor = None

                    while has_more:
                        params = {'start_cursor': start_cursor} if start_cursor else None

                        try:
                            response, status_code = self.notion(children_url, 'get', body=params, bypass_cache=True)
                            if status_code == 200:
                                child_blocks = response.get('results', [])
                                traverse_and_collect(child_blocks)  # Recursive traversal
                                has_more = response.get('has_more', False)
                                start_cursor = response.get('next_cursor')
                            else:
                                logger.error(f"Failed to fetch children for block ID: {block.get('id')} with status code: {status_code}")
                                break
                        except Exception as e:
                            logger.error(f"Error fetching children for block ID: {block.get('id')}]: {e}")
                            break

        # Initial fetch of blocks from the page
        url = self.endpoint('blocks_children', block_id=page_id)
        has_more = True
        start_cursor = None

        while has_more:
            params = {'start_cursor': start_cursor} if start_cursor else None

            try:
                response, status_code = self.notion(url, 'get', body=params, bypass_cache=True)
                if status_code == 200:
                    blocks = response.get('results', [])
                    traverse_and_collect(blocks)

                    # After processing the batch, send updates if any
                    while len(updates_to_send) >= update_batch_size:
                        batch_to_send = updates_to_send[:update_batch_size]
                        send_updates_batch(batch_to_send)
                        updates_to_send = updates_to_send[update_batch_size:]
                        logger.debug(f"Sent a batch of {update_batch_size} updates.")

                    has_more = response.get('has_more', False)
                    start_cursor = response.get('next_cursor')
                else:
                    logger.error(f"Failed to fetch blocks from page ID: {page_id} with status code: {status_code}")
                    break
            except Exception as e:
                logger.error(f"Error fetching blocks from page ID: {page_id}: {e}")
                break

        # Send any remaining updates after the loop
        if updates_to_send:
            send_updates_batch(updates_to_send)
            logger.debug(f"Sent the final batch of {len(updates_to_send)} updates.")

    @default
    def wiki_update(self, page_id = None, wiki_footnote = False):

        def wiki_rich_text(rich_text: List[Dict], block_id: str) -> Optional[List[Dict]]:
            """
            Processes the rich_text array of a block, applies regex matches, and
            returns the updated rich_text if modifications are made.

            :param rich_text: The rich_text array from a Notion block.
            :return: Updated rich_text array or None if no changes.
            """

            wiki_synonyms = ['wik', 'wiki', 'wikipedia']
            compiled_regex = re.compile(rf'({"|".join(wiki_synonyms)})\((.*?)\)', re.IGNORECASE)
            updated = False
            new_rich_text = []

            for rt in rich_text:
                if rt.get('type') == 'text':
                    text_content = rt.get('text', {}).get('content', '')
                    matches = list(compiled_regex.finditer(text_content))
                    if matches:
                        logger.info(f"Regex match found in text: '{text_content}'")

                        last_end = 0
                        for match in matches:
                            start, end = match.span()
                            # Text before the match
                            if start > last_end:
                                before_text = text_content[last_end:start]
                                if before_text:
                                    new_rt_before = copy.deepcopy(rt)
                                    new_rt_before['text']['content'] = before_text
                                    new_rt_before['plain_text'] = before_text
                                    new_rich_text.append(new_rt_before)
                                    logger.debug(f"Added before_text: '{before_text}'")

                            # Replacement rt(s) for the match
                            matched_text = match.group(2)  # The content inside parentheses

                            replacement_rt1 = copy.deepcopy(rt)
                            replacement_rt1['text']['content'] = matched_text
                            replacement_rt1['plain_text'] = matched_text
                            wiki_response = self.wikipedia(matched_text) if self.wikipedia(matched_text) else None
                            wiki_url = wiki_response[1]
                            if wiki_url not in self.wiki_pairs.keys():
                                self.wiki_count += 1
                                self.wiki_pairs[wiki_url] = {
                                    'title': wiki_response[0],
                                    'number': str(self.wiki_count),
                                    'occurrences': [block_id]
                                }
                            else:
                                self.wiki_pairs[wiki_url]['occurrences'].append(block_id)

                            if wiki_url:
                                replacement_rt1['annotations']['color'] = 'blue'
                                replacement_rt1['text']['link'] = {'url': wiki_url}
                                replacement_rt1['annotations']['italic'] = True

                                new_rich_text.extend([replacement_rt1])

                            else:
                                replacement_rt1['annotations']['color'] = 'red'
                                replacement_rt1['annotations']['italic'] = True

                                replacement_rt2 = copy.deepcopy(rt)
                                replacement_rt2['text']['content'] = '(link not found)'
                                replacement_rt2['plain_text'] = '(link not found)'
                                replacement_rt2['annotations']['color'] = 'gray'

                                new_rich_text.extend([replacement_rt1, replacement_rt2])

                            updated = True

                            # Update last_end
                            last_end = end

                        # Text after the last match
                        if last_end < len(text_content):
                            after_text = text_content[last_end:]
                            if after_text:
                                new_rt_after = copy.deepcopy(rt)
                                new_rt_after['text']['content'] = after_text
                                new_rt_after['plain_text'] = after_text
                                new_rich_text.append(new_rt_after)
                                logger.debug(f"Added after_text: '{after_text}'")
                    else:
                        new_rich_text.append(rt)
                else:
                    # Keep non-text types (e.g., equation) unchanged
                    new_rich_text.append(rt)

            return new_rich_text if updated else None

        self.process_blocks(page_id=page_id, function=wiki_rich_text)

        if wiki_footnote:
            self.wiki_footnote(page_id=page_id)

    @default
    def wiki_footnote(self, page_id):
        """
        Appends the wiki footnote and sets the necessary anchors even if the links are already created.

        :param page_id: The ID of the Notion page to process.
        """
        self.wiki_pairs = {}
        self.wiki_count = 0

        def collect_existing_wiki_links(rich_text: List[Dict], block_id: str) -> None:
            """
            Collects existing wiki links from the rich_text and populates self.wiki_pairs.

            :param rich_text: The rich_text array from a Notion block.
            :param block_id: The ID of the block being processed.
            """
            for rt in rich_text:
                if rt.get('type') == 'text':
                    link_info = rt.get('text', {}).get('link', {})
                    if link_info:
                        url = link_info.get('url', '')
                        if 'wikipedia.org' in url:
                            text_content = rt.get('text', {}).get('content', '')
                            # Remove any trailing footnote number in parentheses
                            text_content = re.sub(r'\(\d+\)$', '', text_content).strip()
                            normalized_url = urllib.parse.unquote(url)
                            if normalized_url not in self.wiki_pairs:
                                self.wiki_count += 1
                                self.wiki_pairs[normalized_url] = {
                                    'title': text_content,
                                    'number': str(self.wiki_count),
                                    'footnote_block_id': None,
                                    'occurrences': []
                                }
                            self.wiki_pairs[normalized_url]['occurrences'].append({
                                'block_id': block_id,
                                'rich_text': rt
                            })

        # Traverse the blocks to collect existing wiki links
        self.process_blocks(page_id=page_id, function=collect_existing_wiki_links)

        if not self.wiki_pairs:
            logger.info("No existing wiki links found to create a footnote.")
            return

        # Build the footnote content
        quote_children = []
        for wiki_url, value in self.wiki_pairs.items():
            rich_text = []
            wiki_entry = {
                "type": "text",
                "text": {
                    "content": value['title'],
                    "link": {
                        'url': wiki_url
                    }
                },
                "annotations": {
                    "bold": False,
                    "italic": False,
                    "strikethrough": False,
                    "underline": False,
                    "code": False,
                    "color": "blue"
                },
                "plain_text": value['title']
            }
            rich_text.append(wiki_entry)

            starting_bracket = {
                "type": "text",
                "text": {
                    "content": ' ('
                },
                'annotations': {
                    'color': 'gray'
                }
            }
            rich_text.append(starting_bracket)

            for idx, occurrence in enumerate(value['occurrences'], start=1):
                block_link = f'https://www.notion.so/{page_id.replace("-", "")}#{occurrence["block_id"].replace("-", "")}'
                block_anchor = {
                    "type": "text",
                    "text": {
                        "content": f'instance {idx}',
                        "link": {
                            'url': block_link
                        }
                    },
                    "annotations": {
                        "bold": False,
                        "italic": True,
                        "strikethrough": False,
                        "underline": False,
                        "code": False,
                        "color": "gray"
                    },
                    "plain_text": f'instance {idx}'
                }
                rich_text.append(block_anchor)

                if idx != len(value['occurrences']):
                    comma = {
                        'type': 'text',
                        'text': {
                            'content': ', '
                        },
                        'annotations': {
                            'color': 'gray'
                        }
                    }
                    rich_text.append(comma)

            closing_bracket = {
                "type": "text",
                "text": {
                    "content": ')'
                },
                'annotations': {
                    'color': 'gray'
                }
            }
            rich_text.append(closing_bracket)

            block = {
                'object': 'block',
                'type': 'numbered_list_item',
                'numbered_list_item': {
                    'rich_text': rich_text
                }
            }

            quote_children.append(block)

        wikinote_json = [
            {
                'object': 'block',
                'type': 'heading_1',
                'heading_1': {
                    'rich_text': [
                        {
                            'type': 'text',
                            'text': {
                                'content': 'Wiki Footnote'
                            }
                        }
                    ]
                }
            },
            {
                'object': 'block',
                'type': 'quote',
                'quote': {
                    'rich_text': [
                        {
                            'type': 'text',
                            'text': {
                                'content': 'Page Sources'
                            }
                        }
                    ],
                    'children': quote_children
                }
            }
        ]

        # Append the footnote to the page
        responses = self.append(json.dumps(wikinote_json), page_id=page_id)
        results = responses[0].get('results')
        for block in results:
            if block.get('type', '') == 'quote':
                quote_id = block.get('id', '')

        # Retrieve the IDs of the footnote entries
        response, status_code = self.notion(self.endpoint('blocks_children', block_id=quote_id), 'get', bypass_cache=True)
        footnote_blocks = response.get('results', [])

        # Map footnote entries to their block IDs and collect footnote block IDs
        footnote_block_ids = set()
        for footnote_block in footnote_blocks:
            footnote_block_id = footnote_block.get('id', '')
            footnote_block_ids.add(footnote_block_id)
            rich_texts = footnote_block.get('numbered_list_item', {}).get('rich_text', [])
            for rt in rich_texts:
                if rt and rt.get('text', {}).get('link', {}):
                    url = rt.get('text', {}).get('link', {}).get('url', '')
                    normalized_url = urllib.parse.unquote(url)
                    if normalized_url and normalized_url in self.wiki_pairs.keys():
                        # Map the footnote block IDs for anchor linking
                        self.wiki_pairs[normalized_url]['footnote_block_id'] = footnote_block_id

        # Define the function to update links with footnote numbers and anchor links
        def update_links_with_footnotes(rich_text: List[Dict], block_id: str) -> Optional[List[Dict]]:
            """
            Updates rich_text items by appending footnote numbers to wiki links and setting anchor links.

            :param rich_text: The rich_text array from a Notion block.
            :param block_id: The ID of the block being processed.
            :return: Updated rich_text array or None if no changes.
            """
            # Skip footnote blocks
            if block_id in footnote_block_ids:
                return None

            updated = False
            new_rich_text = []

            for rt in rich_text:
                if rt.get('type') == 'text':
                    link_info = rt.get('text', {}).get('link', {})
                    if link_info:
                        url = link_info.get('url', '')
                        if 'wikipedia.org' in url:
                            normalized_url = urllib.parse.unquote(url)
                            if normalized_url in self.wiki_pairs:
                                value = self.wiki_pairs[normalized_url]
                                footnote_number = value['number']
                                footnote_block_id = value['footnote_block_id']

                                # Create new rich_text with footnote number
                                link_text = rt.get('text', {}).get('content', '')
                                # Remove any trailing footnote number in parentheses
                                link_text = re.sub(r'\(\d+\)$', '', link_text).strip()

                                # Create rich_text for link text
                                link_rt = copy.deepcopy(rt)
                                link_rt['text']['content'] = link_text
                                link_rt['plain_text'] = link_text

                                # Create '(' rich text
                                left_paren_rt = copy.deepcopy(rt)
                                left_paren_rt['text']['content'] = '('
                                left_paren_rt['plain_text'] = '('
                                left_paren_rt['text']['link'] = None
                                left_paren_rt['annotations']['bold'] = False
                                left_paren_rt['annotations']['italic'] = False
                                left_paren_rt['annotations']['color'] = 'gray'
                                left_paren_rt['annotations']['underline'] = False

                                # Create '1' rich text with link
                                number_rt = copy.deepcopy(rt)
                                number_rt['text']['content'] = footnote_number
                                number_rt['plain_text'] = footnote_number
                                number_rt['text']['link'] = {
                                    'url': f'https://www.notion.so/{page_id.replace("-", "")}#{footnote_block_id.replace("-", "")}'
                                }
                                # Update annotations for the footnote number
                                number_rt['annotations']['bold'] = False
                                number_rt['annotations']['italic'] = False
                                number_rt['annotations']['color'] = 'gray'
                                number_rt['annotations']['underline'] = False

                                # Create ')' rich text
                                right_paren_rt = copy.deepcopy(rt)
                                right_paren_rt['text']['content'] = ')'
                                right_paren_rt['plain_text'] = ')'
                                right_paren_rt['text']['link'] = None
                                right_paren_rt['annotations']['bold'] = False
                                right_paren_rt['annotations']['italic'] = False
                                right_paren_rt['annotations']['color'] = 'gray'
                                right_paren_rt['annotations']['underline'] = False

                                # Append updated rich_texts
                                new_rich_text.extend([link_rt, left_paren_rt, number_rt, right_paren_rt])
                                updated = True
                            else:
                                new_rich_text.append(rt)
                        else:
                            new_rich_text.append(rt)
                    else:
                        new_rich_text.append(rt)
                else:
                    new_rich_text.append(rt)

            return new_rich_text if updated else None

        # Process the blocks again to update the links with footnote numbers
        self.process_blocks(page_id=page_id, function=update_links_with_footnotes)

    @default
    def url_update(self, page_id = None, url_footnote = False):

        def url_rich_text(rich_text: List[Dict], block_id: str) -> Optional[List[Dict]]:
            """
            Processes the rich_text array of a block, applies regex matches, and
            returns the updated rich_text if modifications are made.

            :param rich_text: The rich_text array from a Notion block.
            :return: Updated rich_text array or None if no changes.
            """

            wiki_synonyms = ['url', 'link']
            compiled_regex = re.compile(rf'({"|".join(wiki_synonyms)})\((.*?)\)', re.IGNORECASE)
            updated = False
            new_rich_text = []

            for rt in rich_text:
                if rt.get('type') == 'text':
                    text_content = rt.get('text', {}).get('content', '')
                    matches = list(compiled_regex.finditer(text_content))
                    if matches:
                        logger.info(f"Regex match found in text: '{text_content}'")

                        last_end = 0
                        for match in matches:
                            start, end = match.span()
                            # Text before the match
                            if start > last_end:
                                before_text = text_content[last_end:start]
                                if before_text:
                                    new_rt_before = copy.deepcopy(rt)
                                    new_rt_before['text']['content'] = before_text
                                    new_rt_before['plain_text'] = before_text
                                    new_rich_text.append(new_rt_before)
                                    logger.debug(f"Added before_text: '{before_text}'")

                            # Replacement rt(s) for the match
                            matched_text = match.group(2)  # The content inside parentheses

                            replacement_rt1 = copy.deepcopy(rt)
                            replacement_rt1['text']['content'] = matched_text
                            replacement_rt1['plain_text'] = matched_text
                            url_response = self.validate(matched_text) if self.validate(matched_text) else None
                            url = url_response[0]
                            if url not in self.url_pairs.keys():
                                self.url_count += 1
                                self.url_pairs[url] = {
                                    'number': str(self.url_count),
                                    'occurrences': [block_id]
                                }
                            else:
                                self.url_pairs[url]['occurrences'].append(block_id)

                            if url:
                                replacement_rt1['annotations']['color'] = 'green'
                                replacement_rt1['text']['link'] = {'url': url}
                                replacement_rt1['annotations']['italic'] = True

                                new_rich_text.extend([replacement_rt1])

                            else:
                                replacement_rt1['annotations']['color'] = 'red'
                                replacement_rt1['annotations']['italic'] = True

                                replacement_rt2 = copy.deepcopy(rt)
                                replacement_rt2['text']['content'] = '(link not found)'
                                replacement_rt2['plain_text'] = '(link not found)'
                                replacement_rt2['annotations']['color'] = 'gray'

                                new_rich_text.extend([replacement_rt1, replacement_rt2])

                            updated = True

                            # Update last_end
                            last_end = end

                        # Text after the last match
                        if last_end < len(text_content):
                            after_text = text_content[last_end:]
                            if after_text:
                                new_rt_after = copy.deepcopy(rt)
                                new_rt_after['text']['content'] = after_text
                                new_rt_after['plain_text'] = after_text
                                new_rich_text.append(new_rt_after)
                                logger.debug(f"Added after_text: '{after_text}'")
                    else:
                        new_rich_text.append(rt)
                else:
                    # Keep non-text types (e.g., equation) unchanged
                    new_rich_text.append(rt)

            return new_rich_text if updated else None

        self.process_blocks(page_id=page_id, function=url_rich_text)

        if url_footnote:
            self.url_footnote(page_id=page_id)

    @default
    def url_footnote(self, page_id):
        """
        Appends a footnote for non-Wikipedia URLs and sets the necessary anchors.

        :param page_id: The ID of the Notion page to process.
        """
        self.url_pairs = {}
        self.url_count = 0

        def collect_existing_non_wiki_links(rich_text: List[Dict], block_id: str) -> None:
            """
            Collects existing non-Wikipedia links from the rich_text and populates self.url_pairs.

            :param rich_text: The rich_text array from a Notion block.
            :param block_id: The ID of the block being processed.
            """
            for rt in rich_text:
                if rt.get('type') == 'text':
                    text = rt.get('text', {})
                    text_content = text.get('content', '')
                    link_info = text.get('link', {})
                    if link_info:
                        url = link_info.get('url', '')
                        if 'wikipedia.org' not in url and not 'notion.so' in url and not re.match(r'\d+|instance\s*\d+', text_content):
                            text_content = rt.get('text', {}).get('content', '')
                            # Remove any trailing footnote number in parentheses
                            text_content = re.sub(r'\(\d+\)$', '', text_content).strip()
                            normalized_url = urllib.parse.unquote(url)
                            if normalized_url not in self.url_pairs:
                                self.url_count += 1
                                self.url_pairs[normalized_url] = {
                                    'title': text_content,
                                    'number': str(self.url_count),
                                    'footnote_block_id': None,
                                    'occurrences': []
                                }
                            self.url_pairs[normalized_url]['occurrences'].append({
                                'block_id': block_id,
                                'rich_text': rt
                            })

        # Traverse the blocks to collect existing non-Wikipedia links
        self.process_blocks(page_id=page_id, function=collect_existing_non_wiki_links)

        if not self.url_pairs:
            logger.info("No existing non-Wikipedia links found to create a footnote.")
            return

        # Build the footnote content
        quote_children = []
        for url, value in self.url_pairs.items():
            rich_text = []
            url_entry = {
                "type": "text",
                "text": {
                    "content": value['title'],
                    "link": {
                        'url': url
                    }
                },
                "annotations": {
                    "bold": False,
                    "italic": False,
                    "strikethrough": False,
                    "underline": False,
                    "code": False,
                    "color": "green"
                },
                "plain_text": value['title']
            }
            rich_text.append(url_entry)

            starting_bracket = {
                "type": "text",
                "text": {
                    "content": ' ('
                },
                'annotations': {
                    'color': 'gray'
                }
            }
            rich_text.append(starting_bracket)

            for idx, occurrence in enumerate(value['occurrences'], start=1):
                block_link = f'https://www.notion.so/{page_id.replace("-", "")}#{occurrence["block_id"].replace("-", "")}'
                block_anchor = {
                    "type": "text",
                    "text": {
                        "content": f'instance {idx}',
                        "link": {
                            'url': block_link
                        }
                    },
                    "annotations": {
                        "bold": False,
                        "italic": True,
                        "strikethrough": False,
                        "underline": False,
                        "code": False,
                        "color": "gray"
                    },
                    "plain_text": f'instance {idx}'
                }
                rich_text.append(block_anchor)

                if idx != len(value['occurrences']):
                    comma = {
                        'type': 'text',
                        'text': {
                            'content': ', '
                        },
                        'annotations': {
                            'color': 'gray'
                        }
                    }
                    rich_text.append(comma)

            closing_bracket = {
                "type": "text",
                "text": {
                    "content": ')'
                },
                'annotations': {
                    'color': 'gray'
                }
            }
            rich_text.append(closing_bracket)

            block = {
                'object': 'block',
                'type': 'numbered_list_item',
                'numbered_list_item': {
                    'rich_text': rich_text
                }
            }

            quote_children.append(block)

        urlnote_json = [
            {
                'object': 'block',
                'type': 'heading_1',
                'heading_1': {
                    'rich_text': [
                        {
                            'type': 'text',
                            'text': {
                                'content': 'Link Footnote'
                            }
                        }
                    ]
                }
            },
            {
                'object': 'block',
                'type': 'quote',
                'quote': {
                    'rich_text': [
                        {
                            'type': 'text',
                            'text': {
                                'content': 'Page Links'
                            }
                        }
                    ],
                    'children': quote_children
                }
            }
        ]

        # Append the footnote to the page
        responses = self.append(json.dumps(urlnote_json), page_id=page_id)
        results = responses[0].get('results')
        for block in results:
            if block.get('type', '') == 'quote':
                quote_id = block.get('id', '')

        # Retrieve the IDs of the footnote entries
        response, status_code = self.notion(self.endpoint('blocks_children', block_id=quote_id), 'get', bypass_cache=True)
        footnote_blocks = response.get('results', [])

        # Map footnote entries to their block IDs and collect footnote block IDs
        footnote_block_ids = set()
        for footnote_block in footnote_blocks:
            footnote_block_id = footnote_block.get('id', '')
            footnote_block_ids.add(footnote_block_id)
            rich_texts = footnote_block.get('numbered_list_item', {}).get('rich_text', [])
            for rt in rich_texts:
                if rt and rt.get('text', {}).get('link', {}):
                    url = rt.get('text', {}).get('link', {}).get('url', '')
                    normalized_url = urllib.parse.unquote(url)
                    if normalized_url and normalized_url in self.url_pairs.keys():
                        # Map the footnote block IDs for anchor linking
                        self.url_pairs[normalized_url]['footnote_block_id'] = footnote_block_id

        # Define the function to update links with footnote numbers and anchor links
        def update_links_with_footnotes(rich_text: List[Dict], block_id: str) -> Optional[List[Dict]]:
            """
            Updates rich_text items by appending footnote numbers to links and setting anchor links.

            :param rich_text: The rich_text array from a Notion block.
            :param block_id: The ID of the block being processed.
            :return: Updated rich_text array or None if no changes.
            """
            # Skip footnote blocks
            if block_id in footnote_block_ids:
                return None

            updated = False
            new_rich_text = []

            for rt in rich_text:
                if rt.get('type') == 'text':
                    link_info = rt.get('text', {}).get('link', {})
                    if link_info:
                        url = link_info.get('url', '')
                        if 'wikipedia.org' not in url:
                            normalized_url = urllib.parse.unquote(url)
                            if normalized_url in self.url_pairs:
                                value = self.url_pairs[normalized_url]
                                footnote_number = value['number']
                                footnote_block_id = value['footnote_block_id']

                                # Create new rich_text with footnote number
                                link_text = rt.get('text', {}).get('content', '')
                                # Remove any trailing footnote number in parentheses
                                link_text = re.sub(r'\(\d+\)$', '', link_text).strip()

                                # Create rich_text for link text
                                link_rt = copy.deepcopy(rt)
                                link_rt['text']['content'] = link_text
                                link_rt['plain_text'] = link_text

                                # Create '(' rich text
                                left_paren_rt = copy.deepcopy(rt)
                                left_paren_rt['text']['content'] = '('
                                left_paren_rt['plain_text'] = '('
                                left_paren_rt['text']['link'] = None
                                left_paren_rt['annotations']['bold'] = False
                                left_paren_rt['annotations']['italic'] = False
                                left_paren_rt['annotations']['color'] = 'gray'
                                left_paren_rt['annotations']['underline'] = False

                                # Create '1' rich text with link
                                number_rt = copy.deepcopy(rt)
                                number_rt['text']['content'] = footnote_number
                                number_rt['plain_text'] = footnote_number
                                number_rt['text']['link'] = {
                                    'url': f'https://www.notion.so/{page_id.replace("-", "")}#{footnote_block_id.replace("-", "")}'
                                }
                                # Update annotations for the footnote number
                                number_rt['annotations']['bold'] = False
                                number_rt['annotations']['italic'] = False
                                number_rt['annotations']['color'] = 'gray'
                                number_rt['annotations']['underline'] = False

                                # Create ')' rich text
                                right_paren_rt = copy.deepcopy(rt)
                                right_paren_rt['text']['content'] = ')'
                                right_paren_rt['plain_text'] = ')'
                                right_paren_rt['text']['link'] = None
                                right_paren_rt['annotations']['bold'] = False
                                right_paren_rt['annotations']['italic'] = False
                                right_paren_rt['annotations']['color'] = 'gray'
                                right_paren_rt['annotations']['underline'] = False

                                # Append updated rich_texts
                                new_rich_text.extend([link_rt, left_paren_rt, number_rt, right_paren_rt])
                                updated = True
                            else:
                                new_rich_text.append(rt)
                        else:
                            new_rich_text.append(rt)
                    else:
                        new_rich_text.append(rt)
                else:
                    new_rich_text.append(rt)

            return new_rich_text if updated else None

        # Process the blocks again to update the links with footnote numbers
        self.process_blocks(page_id=page_id, function=update_links_with_footnotes)

    @default
    def ref_update(self, page_id = None, ref_footnote = False):

        def ref_rich_text(rich_text: List[Dict], block_id: str) -> Optional[List[Dict]]:
            """
            Processes the rich_text array of a block, applies regex matches, and
            returns the updated rich_text if modifications are made.

            :param rich_text: The rich_text array from a Notion block.
            :return: Updated rich_text array or None if no changes.
            """

            synonyms = ['reference', 'refer', 'ref']
            compiled_regex = re.compile(rf'({"|".join(synonyms)})\((.*?)\)', re.IGNORECASE)
            updated = False
            new_rich_text = []

            for rt in rich_text:
                if rt.get('type') == 'text':
                    text_content = rt.get('text', {}).get('content', '')
                    matches = list(compiled_regex.finditer(text_content))
                    if matches:
                        logger.info(f"Regex match found in text: '{text_content}'")

                        last_end = 0
                        for match in matches:
                            start, end = match.span()
                            # Text before the match
                            if start > last_end:
                                before_text = text_content[last_end:start]
                                if before_text:
                                    new_rt_before = copy.deepcopy(rt)
                                    new_rt_before['text']['content'] = before_text
                                    new_rt_before['plain_text'] = before_text
                                    new_rich_text.append(new_rt_before)
                                    logger.debug(f"Added before_text: '{before_text}'")

                            # Replacement rt(s) for the match
                            matched_text = match.group(2)  # The content inside parentheses

                            replacement_rt1 = copy.deepcopy(rt)
                            search = self.search(matched_text, ignore_ids=[block_id], ignore_notion_links=True) if self.search(matched_text, ignore_ids=[block_id], ignore_notion_links=True) else None

                            if search:
                                search_url = f'https://www.notion.so/{search['page_id'].replace("-", "")}#{search["block_id"].replace("-", "")}'
                                search_title = search['title']
                                if search_url not in self.ref_pairs.keys():
                                    self.ref_count += 1
                                    self.ref_pairs[search_url] = {
                                        'title': search_title,
                                        'number': str(self.ref_count),
                                        'occurrences': [block_id]
                                    }
                                else:
                                    self.ref_pairs[search_url]['occurrences'].append(block_id)

                                replacement_rt1['text']['content'] = search_title
                                replacement_rt1['plain_text'] = search_title
                                replacement_rt1['annotations']['color'] = 'orange'
                                replacement_rt1['text']['link'] = {'url': search_url}
                                replacement_rt1['annotations']['italic'] = True

                                new_rich_text.extend([replacement_rt1])

                            else:
                                replacement_rt1['text']['content'] = matched_text
                                replacement_rt1['plain_text'] = matched_text
                                replacement_rt1['annotations']['color'] = 'red'
                                replacement_rt1['annotations']['italic'] = True

                                replacement_rt2 = copy.deepcopy(rt)
                                replacement_rt2['text']['content'] = '(link not found)'
                                replacement_rt2['plain_text'] = '(link not found)'
                                replacement_rt2['annotations']['color'] = 'gray'

                                new_rich_text.extend([replacement_rt1, replacement_rt2])

                            updated = True

                            # Update last_end
                            last_end = end

                        # Text after the last match
                        if last_end < len(text_content):
                            after_text = text_content[last_end:]
                            if after_text:
                                new_rt_after = copy.deepcopy(rt)
                                new_rt_after['text']['content'] = after_text
                                new_rt_after['plain_text'] = after_text
                                new_rich_text.append(new_rt_after)
                                logger.debug(f"Added after_text: '{after_text}'")
                    else:
                        new_rich_text.append(rt)
                else:
                    # Keep non-text types (e.g., equation) unchanged
                    new_rich_text.append(rt)

            return new_rich_text if updated else None

        self.process_blocks(page_id=page_id, function=ref_rich_text)

        if ref_footnote:
            self.ref_footnote(page_id=page_id)

    @default
    def int_update(self, page_id):

        def int_rich_text(rich_text: List[Dict], block_id: str) -> Optional[List[Dict]]:
            """
            Processes the rich_text array of a block, applies regex matches, and
            returns the updated rich_text if modifications are made.

            :param rich_text: The rich_text array from a Notion block.
            :return: Updated rich_text array or None if no changes.
            """

            results = self.query('')
            pages = [result for result in results if result['type'] == 'page' and result['match_type'] == 'title']
            compiled_regex = re.compile(rf'({"|".join(page['name'] for page in pages)})', re.IGNORECASE)
            updated = False
            new_rich_text = []

            for rt in rich_text:
                if rt.get('type') == 'text':
                    text = rt.get('text', {})
                    text_content = text.get('content', '')
                    link = text.get('link', {})
                    if link and link.get('url', ''):
                        continue
                    matches = list(compiled_regex.finditer(text_content))
                    if matches:
                        logger.info(f"Regex match found in text: '{text_content}'")

                        last_end = 0
                        for match in matches:
                            start, end = match.span()
                            # Text before the match
                            if start > last_end:
                                before_text = text_content[last_end:start]
                                if before_text:
                                    new_rt_before = copy.deepcopy(rt)
                                    new_rt_before['text']['content'] = before_text
                                    new_rt_before['plain_text'] = before_text
                                    new_rich_text.append(new_rt_before)
                                    logger.debug(f"Added before_text: '{before_text}'")

                            matched_text = match.group(1)
                            matched_page = [page for page in pages if page['name'].lower() == matched_text.lower()][0]

                            replacement_rt1 = copy.deepcopy(rt)
                            
                            page_url = f'https://www.notion.so/{matched_page['id'].replace("-", "")}'
                            page_title = matched_page['name']
                            if page_url not in self.ref_pairs.keys():
                                self.int_count += 1
                                self.int_pairs[page_url] = {
                                    'title': page_title,
                                    'number': str(self.ref_count),
                                    'occurrences': [block_id]
                                }
                            else:
                                self.ref_pairs[page_url]['occurrences'].append(block_id)

                            replacement_rt1['text']['content'] = page_title
                            replacement_rt1['plain_text'] = page_title
                            replacement_rt1['annotations']['color'] = 'orange'
                            replacement_rt1['text']['link'] = {'url': page_url}
                            replacement_rt1['annotations']['italic'] = True

                            new_rich_text.extend([replacement_rt1])


                            updated = True

                            # Update last_end
                            last_end = end

                        # Text after the last match
                        if last_end < len(text_content):
                            after_text = text_content[last_end:]
                            if after_text:
                                new_rt_after = copy.deepcopy(rt)
                                new_rt_after['text']['content'] = after_text
                                new_rt_after['plain_text'] = after_text
                                new_rich_text.append(new_rt_after)
                                logger.debug(f"Added after_text: '{after_text}'")
                    else:
                        new_rich_text.append(rt)
                else:
                    # Keep non-text types (e.g., equation) unchanged
                    new_rich_text.append(rt)

            return new_rich_text if updated else None

        self.process_blocks(page_id=page_id, function=int_rich_text)
    
    @default
    def ref_footnote(self, page_id):
        """
        Appends a footnote for internal references and sets the necessary anchors.

        :param page_id: The ID of the Notion page to process.
        """
        self.ref_pairs = {}
        self.ref_count = 0

        def collect_internal_refs(rich_text: List[Dict], block_id: str) -> None:
            """
            Collects internal references from the rich_text and populates self.ref_pairs.

            :param rich_text: The rich_text array from a Notion block.
            :param block_id: The ID of the block being processed.
            """
            for rt in rich_text:
                if rt.get('type') == 'text':
                    text = rt.get('text', {})
                    text_content = text.get('content', '')
                    link_info = text.get('link', {})
                    if link_info:
                        url = link_info.get('url', '')
                        if 'notion.so' in url and not re.match(r'\d+|instance\s*\d+', text_content):
                            text_content = rt.get('text', {}).get('content', '')
                            # Remove any trailing footnote number in parentheses
                            text_content = re.sub(r'\(\d+\)$', '', text_content).strip()
                            normalized_url = url  # For Notion links, no need to unquote
                            if normalized_url not in self.ref_pairs:
                                self.ref_count += 1
                                self.ref_pairs[normalized_url] = {
                                    'title': text_content,
                                    'number': str(self.ref_count),
                                    'footnote_block_id': None,
                                    'occurrences': []
                                }
                            self.ref_pairs[normalized_url]['occurrences'].append({
                                'block_id': block_id,
                                'rich_text': rt
                            })

        # Traverse the blocks to collect internal references
        self.process_blocks(page_id=page_id, function=collect_internal_refs)

        if not self.ref_pairs:
            logger.info("No internal references found to create a footnote.")
            return

        # Build the footnote content
        quote_children = []
        for ref_url, value in self.ref_pairs.items():
            rich_text = []
            ref_entry = {
                "type": "text",
                "text": {
                    "content": value['title'],
                    "link": {
                        'url': ref_url
                    }
                },
                "annotations": {
                    "bold": False,
                    "italic": False,
                    "strikethrough": False,
                    "underline": False,
                    "code": False,
                    "color": "orange"
                },
                "plain_text": value['title']
            }
            rich_text.append(ref_entry)

            starting_bracket = {
                "type": "text",
                "text": {
                    "content": ' ('
                },
                'annotations': {
                    'color': 'gray'
                }
            }
            rich_text.append(starting_bracket)

            for idx, occurrence in enumerate(value['occurrences'], start=1):
                block_link = f'https://www.notion.so/{page_id.replace("-", "")}#{occurrence["block_id"].replace("-", "")}'
                block_anchor = {
                    "type": "text",
                    "text": {
                        "content": f'instance {idx}',
                        "link": {
                            'url': block_link
                        }
                    },
                    "annotations": {
                        "bold": False,
                        "italic": True,
                        "strikethrough": False,
                        "underline": False,
                        "code": False,
                        "color": "gray"
                    },
                    "plain_text": f'instance {idx}'
                }
                rich_text.append(block_anchor)

                if idx != len(value['occurrences']):
                    comma = {
                        'type': 'text',
                        'text': {
                            'content': ', '
                        },
                        'annotations': {
                            'color': 'gray'
                        }
                    }
                    rich_text.append(comma)

            closing_bracket = {
                "type": "text",
                "text": {
                    "content": ')'
                },
                'annotations': {
                    'color': 'gray'
                }
            }
            rich_text.append(closing_bracket)

            block = {
                'object': 'block',
                'type': 'numbered_list_item',
                'numbered_list_item': {
                    'rich_text': rich_text
                }
            }

            quote_children.append(block)

        refnote_json = [
            {
                'object': 'block',
                'type': 'heading_1',
                'heading_1': {
                    'rich_text': [
                        {
                            'type': 'text',
                            'text': {
                                'content': 'Reference Links'
                            }
                        }
                    ]
                }
            },
            {
                'object': 'block',
                'type': 'quote',
                'quote': {
                    'rich_text': [
                        {
                            'type': 'text',
                            'text': {
                                'content': 'Internal References'
                            }
                        }
                    ],
                    'children': quote_children
                }
            }
        ]

        # Append the footnote to the page
        responses = self.append(json.dumps(refnote_json), page_id=page_id)
        results = responses[0].get('results')
        for block in results:
            if block.get('type', '') == 'quote':
                quote_id = block.get('id', '')

        # Retrieve the IDs of the footnote entries
        response, status_code = self.notion(self.endpoint('blocks_children', block_id=quote_id), 'get', bypass_cache=True)
        footnote_blocks = response.get('results', [])

        # Map footnote entries to their block IDs and collect footnote block IDs
        footnote_block_ids = set()
        for footnote_block in footnote_blocks:
            footnote_block_id = footnote_block.get('id', '')
            footnote_block_ids.add(footnote_block_id)
            rich_texts = footnote_block.get('numbered_list_item', {}).get('rich_text', [])
            for rt in rich_texts:
                if rt and rt.get('text', {}).get('link', {}):
                    url = rt.get('text', {}).get('link', {}).get('url', '')
                    if url and url in self.ref_pairs.keys():
                        # Map the footnote block IDs for anchor linking
                        self.ref_pairs[url]['footnote_block_id'] = footnote_block_id

        # Define the function to update references with footnote numbers and anchor links
        def update_refs_with_footnotes(rich_text: List[Dict], block_id: str) -> Optional[List[Dict]]:
            """
            Updates rich_text items by appending footnote numbers to references and setting anchor links.

            :param rich_text: The rich_text array from a Notion block.
            :param block_id: The ID of the block being processed.
            :return: Updated rich_text array or None if no changes.
            """
            # Skip footnote blocks
            if block_id in footnote_block_ids:
                return None

            updated = False
            new_rich_text = []

            for rt in rich_text:
                if rt.get('type') == 'text':
                    link_info = rt.get('text', {}).get('link', {})
                    if link_info:
                        url = link_info.get('url', '')
                        if 'notion.so' in url and url in self.ref_pairs:
                            value = self.ref_pairs[url]
                            footnote_number = value['number']
                            footnote_block_id = value['footnote_block_id']

                            # Create new rich_text with footnote number
                            link_text = rt.get('text', {}).get('content', '')
                            # Remove any trailing footnote number in parentheses
                            link_text = re.sub(r'\(\d+\)$', '', link_text).strip()

                            # Create rich_text for link text
                            link_rt = copy.deepcopy(rt)
                            link_rt['text']['content'] = link_text
                            link_rt['plain_text'] = link_text

                            # Create '(' rich text
                            left_paren_rt = copy.deepcopy(rt)
                            left_paren_rt['text']['content'] = '('
                            left_paren_rt['plain_text'] = '('
                            left_paren_rt['text']['link'] = None
                            left_paren_rt['annotations']['bold'] = False
                            left_paren_rt['annotations']['italic'] = False
                            left_paren_rt['annotations']['color'] = 'gray'
                            left_paren_rt['annotations']['underline'] = False

                            # Create footnote number rich text with link
                            number_rt = copy.deepcopy(rt)
                            number_rt['text']['content'] = footnote_number
                            number_rt['plain_text'] = footnote_number
                            number_rt['text']['link'] = {
                                'url': f'https://www.notion.so/{page_id.replace("-", "")}#{footnote_block_id.replace("-", "")}'
                            }
                            # Update annotations for the footnote number
                            number_rt['annotations']['bold'] = False
                            number_rt['annotations']['italic'] = False
                            number_rt['annotations']['color'] = 'gray'
                            number_rt['annotations']['underline'] = False

                            # Create ')' rich text
                            right_paren_rt = copy.deepcopy(rt)
                            right_paren_rt['text']['content'] = ')'
                            right_paren_rt['plain_text'] = ')'
                            right_paren_rt['text']['link'] = None
                            right_paren_rt['annotations']['bold'] = False
                            right_paren_rt['annotations']['italic'] = False
                            right_paren_rt['annotations']['color'] = 'gray'
                            right_paren_rt['annotations']['underline'] = False

                            # Append updated rich_texts
                            new_rich_text.extend([link_rt, left_paren_rt, number_rt, right_paren_rt])
                            updated = True
                        else:
                            new_rich_text.append(rt)
                    else:
                        new_rich_text.append(rt)
                else:
                    new_rich_text.append(rt)

            return new_rich_text if updated else None

        # Process the blocks again to update the references with footnote numbers
        self.process_blocks(page_id=page_id, function=update_refs_with_footnotes)

    @default
    def update_all(self, page_id, footnotes = False):
        self.wiki_update(page_id=page_id)
        self.url_update(page_id=page_id)
        self.ref_update(page_id=page_id)
        self.int_update(page_id=page_id)

        if footnotes:
            self.wiki_footnote(page_id=page_id)
            self.url_footnote(page_id=page_id)
            self.ref_footnote(page_id=page_id)
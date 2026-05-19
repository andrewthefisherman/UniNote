import sys, os
import time
import requests
import re
import json
import datetime
import Levenshtein
import logging
from typing import Any, Dict, Optional, Tuple, List
import urllib.parse
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('notion_processor.log', encoding='utf-8')
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

class NotionProcessor:
    def __init__(self, notion_api_key: str, database_id: str, cohere_api_key: str):
        if not notion_api_key:
            raise InputError(
                "Notion API key is required.",
                location="Initialization",
                troubleshoot="Provide a valid Notion API key."
            )
        if not database_id:
            raise InputError(
                "Database ID is required.",
                location="Initialization",
                troubleshoot="Provide a valid Notion Database ID."
            )
        if not cohere_api_key:
            raise InputError(
                "Cohere API key is required.",
                location="Initialization",
                troubleshoot="Provide a valid Cohere API key."
            )
        
        self.notion_api_key = notion_api_key
        self.database_id = database_id
        self.cohere_api_key = cohere_api_key
        self.superscript_mapping = {'⁰': '0', '¹': '1', '²': '2', '³': '3', '⁴': '4', '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9',
                            '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹'}
        self.wiki_count = 1
        self.wiki_footnote_pairs = {}  # Change from list to dict
        self.cohere_request_count = 0
        self.cohere_start_time = datetime.datetime.now()
        self.cohere_end_time = datetime.datetime.now()

        # Calculate the elapsed time in seconds
        

        logger.info("NotionProcessor initialized successfully.")

    def notion_request(self, url: str, method: str, body: Optional[Dict] = None) -> Tuple[Dict, int]:
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
                if method.lower() in ["post", "patch"]:
                    request_func = getattr(requests, method.lower())
                    response = request_func(url=url, headers=headers, json=body, timeout=10)
                elif method.lower() == 'get':
                    response = requests.get(url=url, headers=headers, timeout=10)

                if response.status_code in [200, 201]:
                    logger.info(f"Notion {method.upper()} request to {url} succeeded with status {response.status_code}.")
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

    def cohere_request(self, prompt: str, chat_history: Optional[list] = None) -> Tuple[str, int]:
        '''Chat History must be sumbitted as a lists of strings. Each string is a message with the subject specified at the beginning: ["chatbot: {chatbot message}, user: {user message}...]'''
        if not self.cohere_api_key:
            raise APIError(
                'Cohere API key is missing.',
                location='Cohere API',
                troubleshoot='Provide a valid Cohere API key.',
                status_code=500
            )

        url = "https://api.cohere.ai/chat"
        formatted_chat_history = []
        if chat_history:
            for message in chat_history:
                if 'chatbot' in message:
                    strip = re.sub(r'chatbot\s*:\s*', '', message)
                    chat_message = {'role': 'chatbot', 'message':strip}
                    formatted_chat_history.append(chat_message)
                elif 'user' in message:
                    strip = re.sub(r'user\s*:\s*', '', message)
                    chat_message = {'role': 'user', 'message':strip}
                    formatted_chat_history.append(chat_message)
                elif 'system' in message:
                    strip = re.sub(r'system\s*:\s*', '', message)
                    chat_message = {'role': 'system', 'message':strip}
                    formatted_chat_history.append(chat_message)
                else:
                    logger.warning(f"Invalid chat history message encountered: {message}")

            if formatted_chat_history:
                body = {'chat_history': formatted_chat_history, 'message': prompt}

            else: body = {'message': prompt}

        else: body = {'message': prompt}

        headers = {'Authorization': f'Bearer {self.cohere_api_key}', 'Content-Type': 'application/json'}

        max_retries = 3
        retry_delay = 3  # seconds
        
        self.cohere_end_time = datetime.datetime.now()
        elapsed_time = (self.cohere_end_time - self.cohere_start_time).total_seconds()
        if self.cohere_request_count > 9 and elapsed_time < 60:
            logger.info("Exceeded 10 Cohere RPMs. Waiting a minute")
            time.sleep(60)
            self.cohere_request_count = 0
            self.cohere_start_time = datetime.datetime.now()

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(url=url, headers=headers, json=body, timeout=10)

                if response.status_code == 200:
                    output = response.json()['text'].strip()
                    logger.info(f"Cohere API request succeeded with status {response.status_code}.")
                    self.cohere_request_count += 1
                    return output, response.status_code
                else:
                    logger.warning(f"Cohere API request failed with status {response.status_code}: {response.text}")
                    raise APIError(
                        f'Error {response.status_code}: {response.text}',
                        location='Cohere API',
                        troubleshoot='Check your request and API key.',
                        status_code=response.status_code
                    )
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                logger.error(f"Attempt {attempt} - Connection error during Cohere API request: {str(e)}")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue  # Retry the request
                else:
                    raise ConnectionError(
                        'Connection Error with Cohere API',
                        location='Cohere API',
                        troubleshoot='Check your internet connection.'
                    ) from e
            except requests.exceptions.RequestException as e:
                logger.error(f"Request exception during Cohere API request: {str(e)}")
                raise APIError(
                    f'Request exception: {str(e)}',
                    location='Cohere API',
                    troubleshoot='Check your request and network connection.'
                ) from e

    def is_website_valid(self, url: str) -> bool:
        max_retries = 3
        retry_delay = 3  # seconds

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.get(url, timeout=5)
                valid = response.status_code == 200
                logger.info(f"Website validation for {url}: {'Valid' if valid else 'Invalid'} (Status {response.status_code})")
                return valid
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                logger.error(f"Attempt {attempt} - Connection error during website validation for {url}: {str(e)}")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue  # Retry the request
                else:
                    logger.warning(f"Failed to validate website '{url}' after {max_retries} attempts.")
                    return False
            except requests.exceptions.RequestException as e:
                logger.error(f"Request exception during website validation for {url}: {str(e)}")
                return False

    def check_wikipedia_page(self, title: str, language: str = 'en') -> Optional[Any]:
        """
        Check if a Wikipedia page exists for the given title in the specified language.
        If not, search for a similar page considering spelling mistakes or missing words.
        Handles disambiguation pages by performing a search to find the most relevant page.

        Parameters:
            title (str): The title of the Wikipedia page to search for.
            language (str): The language code for Wikipedia (e.g., 'en', 'es'). Default is 'en'.

        Returns:
            str or None:
                - If a page is found, returns the absolute URL as a string.
                - If no page is found, returns None.
        """
        api_url = f'https://{language}.wikipedia.org/w/api.php'

        # First, try to get the page with the given title
        params = {
            'action': 'query',
            'format': 'json',
            'titles': title,
            'redirects': 1,
            'prop': 'pageprops|categories',
            'ppprop': 'disambiguation',
            'cllimit': 'max',
        }

        try:
            response = requests.get(api_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            pages = data.get('query', {}).get('pages', {})

            page = next(iter(pages.values()))
            if 'missing' in page:
                # Page does not exist, proceed to search
                pass
            else:
                # Page exists
                is_disambiguation = False
                # Check if 'disambiguation' is in pageprops
                pageprops = page.get('pageprops', {})
                if 'disambiguation' in pageprops:
                    is_disambiguation = True
                else:
                    # Check if categories include 'Disambiguation pages'
                    categories = page.get('categories', [])
                    for category in categories:
                        cat_title = category.get('title', '').lower()
                        if 'disambiguation pages' in cat_title:
                            is_disambiguation = True
                            break

                page_title = page.get('title', '')
                encoded_title = urllib.parse.quote(page_title.replace(' ', '_'))
                url = f'https://{language}.wikipedia.org/wiki/{encoded_title}'

                if not is_disambiguation:
                    return page_title, url
                else:
                    # It's a disambiguation page; perform a search to find the most relevant page
                    params_search = {
                        'action': 'query',
                        'list': 'search',
                        'srsearch': f'intitle:{title}',
                        'format': 'json',
                        'srlimit': 1
                    }

                    search_response = requests.get(api_url, params=params_search, timeout=10)
                    search_response.raise_for_status()
                    search_data = search_response.json()

                    search_results = search_data.get('query', {}).get('search', [])
                    if search_results:
                        top_result = search_results[0]
                        top_title = top_result.get('title', '')
                        # Return the URL of the top search result
                        encoded_top_title = urllib.parse.quote(top_title.replace(' ', '_'))
                        top_url = f'https://{language}.wikipedia.org/wiki/{encoded_top_title}'
                        return top_title, top_url

                    # No suitable page found
                    return None, None

            # If page does not exist, perform a search
            params_search = {
                'action': 'query',
                'list': 'search',
                'srsearch': f'intitle:{title}',
                'format': 'json',
                'srlimit': 1
            }

            search_response = requests.get(api_url, params=params_search, timeout=10)
            search_response.raise_for_status()
            search_data = search_response.json()

            search_results = search_data.get('query', {}).get('search', [])
            if search_results:
                top_result = search_results[0]
                top_title = top_result.get('title', '')
                # Return the URL of the top search result
                encoded_top_title = urllib.parse.quote(top_title.replace(' ', '_'))
                top_url = f'https://{language}.wikipedia.org/wiki/{encoded_top_title}'
                return top_title, top_url

            # No suitable page found
            return None, None

        except requests.RequestException as e:
            logger.error(f"Network error while accessing Wikipedia API: {e}")
            raise NotionProcessorError(
                message="Failed to connect to Wikipedia API.",
                location="check_wikipedia_page",
                troubleshoot="Ensure your network connection is stable and Wikipedia API is accessible.",
                status_code=503
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error in check_wikipedia_page: {e}")
            raise NotionProcessorError(
                message="An unexpected error occurred in check_wikipedia_page.",
                location="check_wikipedia_page",
                troubleshoot="Check the input parameters and try again.",
                status_code=500
            ) from e

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
                        return absolute_url, True, response.status_code
                    elif 300 <= response.status_code < 400:
                        # Handle redirects
                        redirected_url = response.url
                        if redirected_url != absolute_url:
                            logging.info(f"Website validation for {absolute_url}: Redirected to {redirected_url}")
                            absolute_url = redirected_url
                            continue  # Validate the new redirected URL
                        else:
                            logging.warning(f"Website validation for {absolute_url}: Redirected to the same URL.")
                            return absolute_url, True, response.status_code
                    elif response.status_code == 403:
                        # Treat 403 as valid but access restricted
                        logging.warning(f"Access forbidden when validating URL '{absolute_url}'. HTTP Status: {response.status_code}")
                        return absolute_url, True, response.status_code
                    else:
                        logging.warning(f"Failed to validate URL '{absolute_url}'. HTTP Status: {response.status_code}")
                        return absolute_url, False, response.status_code
                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                    logging.error(f"Attempt {attempt} - Connection error during website validation for {absolute_url}: {e}")
                    if attempt < max_retries:
                        logging.info(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        continue  # Retry the request
                    else:
                        logging.error(f"Website validation failed for {absolute_url} after {max_retries} attempts.")
                        return absolute_url, False, 408 #Code for Request Timeout
                except requests.exceptions.RequestException as e:
                    logging.error(f"Request exception during website validation for {absolute_url}: {e}")
                    return absolute_url, False, 500

        except Exception as e:
            logging.error(f"Unexpected error in resolve_link: {e}")
            return url, False, 500

    def normalize_word(self, word: str, valid_words: set) -> str:
        """
        Removes consecutive duplicate letters from the input word only if the normalized word exists in valid_words.
        
        :param word: The word to normalize.
        :param valid_words: A set of valid words to check against after normalization.
        :return: The normalized word if it exists in valid_words; otherwise, the original word.
        """
        word_lower = word.lower()
        if word_lower in valid_words:
            return word_lower  # Word is already valid; no normalization needed
        
        # Remove consecutive duplicates
        normalized = re.sub(r'(.)\1+', r'\1', word_lower)
        if normalized in valid_words:
            return normalized
        
        # If normalization does not result in a valid word, return the original
        return word_lower

    def spellmargin(self, input_word: str, word_list, deprioritized_words=None, penalty=7, strict_distance=3):
        """
        Finds the best match for the input_word from the word_list based on Levenshtein distance.
        The function prioritizes exact matches, followed by case-insensitive matches, and then
        fuzzy matches within a dynamic threshold.
        Additionally, it deprioritizes matches that are in the deprioritized_words list
        unless their Levenshtein distance is <= strict_distance.

        :param input_word: The word to match.
        :param word_list: A list of candidate words.
        :param deprioritized_words: A set of words to deprioritize.
        :param penalty: The penalty to add to the score of deprioritized words.
        :param strict_distance: The maximum Levenshtein distance to not apply the penalty.
        :return: The best matching word from word_list or None if no match is found within the threshold.
        """
        input_word_lower = input_word.lower()
        deprioritized_words = set(deprioritized_words) if deprioritized_words else set()

        # Step 1: Exact match (case-sensitive)
        exact_matches = [word for word in word_list if word == input_word]
        if exact_matches:
            return exact_matches[0]

        # Step 2: Case-insensitive exact matches
        case_insensitive_matches = [word for word in word_list if word.lower() == input_word_lower]
        if case_insensitive_matches:
            # Prefer capitalized words
            capitalized_matches = [word for word in case_insensitive_matches if word.istitle()]
            if capitalized_matches:
                return capitalized_matches[0]
            else:
                return case_insensitive_matches[0]

        # Step 3: Fuzzy matching within dynamic threshold
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
            if distance <= threshold:
                # If the word is deprioritized and distance > strict_distance, skip it
                if word in deprioritized_words and distance > strict_distance:
                    continue

                # Assign score based on capitalization
                if word == input_word:
                    score = 0  # Exact match
                elif word.istitle():
                    score = 1  # Capitalized
                elif word.isupper():
                    score = 2  # All uppercase
                elif word.islower():
                    score = 3  # All lowercase
                else:
                    score = 4  # Other mixed cases

                # Apply penalty if the word is deprioritized
                deprioritized_flag = 1 if word in deprioritized_words else 0
                if word in deprioritized_words:
                    if distance > strict_distance:
                        score += penalty
                    else:
                        # If distance <= strict_distance, do not apply penalty
                        pass

                matches.append((deprioritized_flag, distance, score, -len(word), word))

        if not matches:
            return None

        # Enhanced Sorting: Sort by deprioritized_flag, distance, score, then longer word length
        matches.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

        best_match = matches[0][4]
        return best_match

    def string_window_cut(self, text, keyword, window=10, wrap=None):
        # Split the input string and the keyword into words
        words = text.split()
        keyword_words = keyword.split()
        kw_length = len(keyword_words)
        
        keyword_index = None
        # Iterate through the words to find the keyword sequence
        for i in range(len(words) - kw_length + 1):
            # Check if the sequence matches the keyword words
            if words[i:i + kw_length] == keyword_words:
                keyword_index = i
                break

        if keyword_index is None:
            # If not found, try splitting the text differently
            words = text.split('$')
            for i in range(len(words) - kw_length + 1):
                if words[i:i + kw_length] == keyword_words:
                    keyword_index = i
                    break

            if keyword_index is None:
                # Keyword not found
                logger.warning(f"Keyword '{keyword}' not found in text during window cut.")
                return None

        # If wrapping is requested
        if wrap:
            try:
                wrap_list = wrap.lower().split('keyword')
                # Reconstruct the new keyword with wrapping
                new_keyword = wrap_list[0] + keyword + wrap_list[1]
                # Replace the keyword in the words list
                words[keyword_index:keyword_index + kw_length] = [new_keyword]
            except Exception as e:
                logger.error(f"Error in wrapping keyword: {e}")
                pass

        # Calculate the start and end indices for slicing
        start = max(keyword_index - window, 0)
        end = min(keyword_index + kw_length + window, len(words))

        # Extract the surrounding words
        surrounding_words = words[start:end]

        # Join the words back into a string and return
        return '...' + ' '.join(surrounding_words) + '...'

    def check_against_database(self, property_type, item, property_name=None):
        """
        Check the database for the closest match based on the property type and item.
        Optionally, specify the property_name to narrow down the search if multiple matches exist.
        
        Args:
            property_type (str): The type of the property (e.g., title, multi_select, select).
            item (str): The item to search for.
            property_name (str, optional): The specific property name to limit the search to. Defaults to None.
            
        Returns:
            str: The ID of the page where the match was found, or None if no match is found.
        """
        
        # Get the list of properties of the requested type from the type_lists dictionary
        property_keys = self.type_lists.get(property_type, [])

        # Initialize an empty list to collect all possible options (e.g., titles, tags, dates)
        possible_options = []

        # Iterate over all pages in the database
        for page in self.database_query.get('results', []):
            for prop_key in property_keys:
                # If property_name is specified, only consider that property key
                if property_name and prop_key != property_name:
                    continue

                property_data = page['properties'].get(prop_key, None)

                if not property_data:
                    continue

                # Handle different property types (e.g., title, multi-select, select, date)
                if property_type == 'title':
                    # Titles: Extract the title's text content
                    title_property = property_data.get('title', [])
                    if title_property:
                        possible_options.append((title_property[0]['text']['content'], page['id'], prop_key))

                elif property_type == 'multi_select':
                    # Multi-select: Extract all the tags in the multi-select field
                    multi_select_options = self.properties_dict.get(prop_key).get('multi_select', []).get('options')
                    for option in multi_select_options:
                        if (option['name'], option['id'], prop_key) not in possible_options:
                            possible_options.append((option['name'], option['id'], prop_key))

                elif property_type == 'select':
                    # Select: Extract the selected option(s)
                    select_options = self.properties_dict.get(prop_key).get('select', []).get('options')
                    for option in select_options:
                        if (option['name'], option['id'], prop_key) not in possible_options:
                            possible_options.append((option['name'], option['id'], prop_key))

        # Normalize the list of possible options to lowercase for case-insensitive comparison
        option_list = [option[0].lower() for option in possible_options]

        # Use the spellmargin function to find the closest match
        best_match = self.spellmargin(item.lower(), option_list)

        if best_match:
            # Filter matches for the specified property, if applicable
            matches = [option for option in possible_options if option[0].lower() == best_match]

            if len(matches) > 1 and not property_name:
                option_list = [option[0] for option in possible_options]
                best_match = self.spellmargin(item, option_list)
                if best_match:
                     matches = [option for option in possible_options if option[0] == best_match]
                else:
                    # If multiple matches exist and property_name is not specified, raise an error
                    raise ValueError(f"Multiple matches found for '{item}' in different properties. Please specify the property_name.")

            # Return the ID of the match (if property_name is specified, only that property is considered)
            for option, id, prop_key in matches:
                if not property_name or prop_key == property_name:
                    return prop_key, id

        # If no match is found, return None
        return None, None

    def notion_api_headers(self, metadata_to_process: Optional[str], title: Optional[str] = None, emoji: Optional[str] = None) -> Dict[str, Any]:
        
        try:
            logger.debug(f"Retrieving database properties for database ID: {self.database_id}")
            response, status_code = self.notion_request(f'https://api.notion.com/v1/databases/{self.database_id}', 'get')
            if response is None:
                raise APIError(
                    'Failed to retrieve database properties.',
                    location='Notion API',
                    troubleshoot='Check your database ID and API key.'
                )
            # Query the database to retrieve all pages
            self.database_query, status_code = self.notion_request(f'https://api.notion.com/v1/databases/{self.database_id}/query', 'post', None)
            self.properties_dict = response.get('properties')
            all_property_names = list(self.properties_dict.keys())
            # Counts how many times there is a specific "type"
            self.type_lists = {t: [key for key in all_property_names if self.properties_dict[key]['type'] == t]
                        for t in {self.properties_dict[key]['type'] for key in all_property_names}}
            property_types = {key: value['type'] for key, value in self.properties_dict.items()}
            property_markers = {
                'title': '<tit>', 'relation': '<pit>', 'date': '<dat>',
                'checkbox': '<chk>', 'select': '<sel>', 'multi_select': '<msl>'
            }

            property_options = {
                key: {option['name']: option['id'] for option in self.properties_dict[key][self.properties_dict[key]['type']]['options']}
                for key in self.properties_dict
                if self.properties_dict[key]['type'] in ['select', 'multi_select']
            }
            

            headers = {}
            properties = {}
            if metadata_to_process:
                # Start parsing headers
                input_headers = metadata_to_process.replace("\n", "")
                matching = r"\s*\(\s*([^)]+)\s*\)\s*"
                patterns = [
                    r"(title|tit|name)\s*\(\s*([^)]+?)\s*\)",                                   # Titles
                    r"(parentitem|parent\s+Item|pit|pitem|parent)\s*\(\s*([^)]+?)\s*\)",        # Parents
                    r"(date|dat|data)\s*\(\s*([^)]+?)\s*\)",                                    # Dates
                    r"(checkbox|check|chk)\s*\(\s*([^)]+?)\s*\)",                               # Checkboxes
                    r"(multiselect|multi-select|msel|multisel|mselect)\s*\(\s*([^)]+?)\s*\)",   # Multiselects
                    r"(select|sel)\s*\(\s*([^)]+?)\s*\)",                                       # Selects
                    r"(ico|icon|emoji|emoticon)\s*\(\s*([^)]+?)\s*\)",                          # Icons
                    r"\s*\(\s*([^)]+?)\s*\)"
                ]
                replacements = [
                    r"<tit>\2",
                    r"<pit>\2",
                    r"<dat>\2",
                    r"<chk>\2",
                    r"<msl>\2",
                    r"<sel>\2",
                    r"<ico>\2",
                    r"<und>\1"
                ]
                try:
                    formatted_headers_list = []
                    headers_split = re.split(r'(?<=\))[\s,;]+', input_headers)
                    for header in headers_split:
                        original_header = header.strip()
                        header = original_header.lower()
                        if not header:
                            continue
                        matched = False  # Flag to check if any pattern matches
        
                        for pattern, replacement in zip(patterns, replacements):
                            if re.search(pattern, header):
                                formatted_header = re.sub(pattern, replacement, header).strip()
                                formatted_header_original = re.sub(pattern, replacement, original_header).strip()
                                formatted_headers_list.append((formatted_header, formatted_header_original))
                                matched = True  # Set flag to True if a match is found
                                break  # Stop checking more patterns once a match is found
                        
                        # If no match was found for the current header, raise a SyntaxError
                        if not matched:
                            raise SyntaxError(
                                f'Unrecognized header format: "{header}"',
                                location='Headers and metadata processor',
                                troubleshoot='Check the syntax of your metadata.'
                            )
                except SyntaxError as e:
                    logger.exception("Syntax error while parsing headers.")
                    raise e
                except Exception as e:
                    logger.exception("Unexpected error while parsing headers.")
                    raise APIError(
                        f'Unexpected error: {str(e)}',
                        location='Headers and metadata processor',
                        troubleshoot='Check the syntax of your metadata.'
                    ) from e

                for header, header_original in formatted_headers_list:
                    if header.startswith('<chk>') and not self.type_lists.get('checkbox'):
                        raise SyntaxError(
                            'No Checkbox Property Found',
                            location='Headers and metadata processor',
                            troubleshoot='Add a checkbox property to your database or correct your metadata.'
                        )
                    if header.startswith('<dat>') and not self.type_lists.get('date'):
                        raise SyntaxError(
                            'No Date Property Found',
                            location='Headers and metadata processor',
                            troubleshoot='Add a date property to your database or correct your metadata.'
                        )
                    if header.startswith('<sel>') and not self.type_lists.get('select'):
                        raise SyntaxError(
                            'No Select Property Found',
                            location='Headers and metadata processor',
                            troubleshoot='Add a select property to your database or correct your metadata.'
                        )
                    if header.startswith('<msl>') and not self.type_lists.get('multi_select'):
                        raise SyntaxError(
                            'No Multi-Select Property Found',
                            location='Headers and metadata processor',
                            troubleshoot='Add a multi-select property to your database or correct your metadata.'
                        )

                    if not header.startswith(('<msl>', '<sel>')) and ',' in header:
                        generic_marker = re.search(r'<\w+>', header)
                        raise SyntaxError(
                            f'Only one argument allowed for {generic_marker.group()} elements',
                            location='Headers and metadata processor',
                            troubleshoot='Correct your metadata syntax.'
                        )

                    stripped_header = re.sub(r'<\w+>', '', header)
                    stripped_header_original = re.sub(r'<\w+>', '', header_original)
                    if ':' in stripped_header:
                        property_name, option_name = stripped_header.split(":", 1)
                        original_property_name, original_option_name = stripped_header_original.split(":", 1)
                        property_name = self.spellmargin(property_name.strip(), all_property_names)
                        if not property_name:
                            raise SyntaxError(
                                f'Property Name not found for {header}',
                                location='Headers and metadata processor',
                                troubleshoot=f'Wrong property in {header}'
                            )
                        original_option_name = original_option_name.strip()
                        option_name = option_name.strip()
                    else:
                        property_name = None
                        original_option_name = stripped_header_original.strip()
                        option_name = stripped_header.strip()

                    if header.startswith('<und>'):
                        if ':' in header:
                            marker = property_markers[property_types[property_name]]
                            header = marker
                        else:
                            raise SyntaxError(
                                f'Missing Property Name for value "{option_name}"',
                                location='Headers and metadata processor',
                                troubleshoot='Specify the property name.'
                            )

                    # Start marker and property parsing
                    if header.startswith('<tit>'):
                        if not title:
                            title = original_option_name
                            logger.debug(f"Title set to: {title}")

                    elif header.startswith('<pit>'):
                        if self.type_lists.get('relation'):
                            if 'Parent item' in self.properties_dict:
                                parent_property = 'Parent item'
                            else:
                                chosen_parent_name = self.cohere_request(f'Which of these two names "{self.type_lists.get('relation')}" do you think represents a parental item relation? Strictly output only the chosen name with no changes.').strip()
                                parent_property = chosen_parent_name

                            title_property_name, parent_id = self.check_against_database('title', option_name)
                            if parent_id:
                                properties[parent_property] = {
                                    'relation': [
                                        {
                                            'id': parent_id
                                        }
                                    ]
                                }
                                logger.debug(f"Parent relation set with ID: {parent_id}")
                            else:
                                raise APIError(
                                    f'Parent Item "{option_name}" not found.',
                                    location='Notion API',
                                    troubleshoot='Ensure the parent item exists in your database.'
                                )
                        else:
                            raise SyntaxError(
                                'No Relation Property "Parent Item" set in the database.',
                                location='Headers and metadata processor',
                                troubleshoot='Add a relation property named "Parent Item" to your database.'
                            )

                    elif header.startswith('<ico>'):
                        if not emoji:
                            emoji = option_name
                            logger.debug(f"Emoji set to: {emoji}")

                    elif header.startswith('<chk>'):
                        if len(self.type_lists.get('checkbox')) == 1:
                            property_name = self.type_lists.get('checkbox')[0]

                        if property_name:
                            checkbox_answers = {'yes': True, 'no': False, 'true': True, 'false': False}
                            checkbox_value = checkbox_answers.get(option_name.lower())
                            if checkbox_value is not None:
                                properties[property_name] = {
                                    'checkbox': checkbox_value
                                }
                                logger.debug(f"Checkbox '{property_name}' set to {checkbox_value}")
                            else:
                                raise SyntaxError(
                                    'Checkbox value is invalid',
                                    location='Headers and metadata processor',
                                    troubleshoot='Use "yes", "no", "true", or "false" for checkbox values.'
                                )
                        else:
                            raise SyntaxError(
                                'No Property name specified for Checkbox Property',
                                location='Headers and metadata processor',
                                troubleshoot='Specify the property name for the checkbox.'
                            )

                    elif header.startswith('<dat>'):
                        if len(self.type_lists.get('date')) == 1:
                            property_name = self.type_lists.get('date')[0]
                        
                        if property_name:
                            start, end = self.parse_dates(option_name)
                            if not start and not end:
                                continue
                            properties[property_name] = {
                                'date': {
                                    'start': start,
                                    'end': end
                                }
                            }
                            logger.debug(f"Date '{property_name}' set with start: {start}, end: {end}")
                        else:
                            raise SyntaxError(
                                'Date Property Name not specified',
                                location='Headers and metadata processor',
                                troubleshoot='Specify the property name for the date.'
                            )

                    elif header.startswith('<sel>'):
                        properties = self.handle_select_property(properties, property_name, original_option_name, self.type_lists, property_options)

                    elif header.startswith('<msl>'):
                        properties = self.handle_multi_select_property(properties, property_name, original_option_name, self.type_lists, property_options)

            headers['parent'] = {
                'database_id': self.database_id
            }
            
            if title:
                properties[self.type_lists['title'][0]] = {'title': [
                    {
                        'text': {
                            'content': title
                        }
                    }
                ]}
                logger.debug(f"Title property set to: {title}")
            else:
                properties[self.type_lists['title'][0]] = {'title': [
                    {
                        'text': {
                            'content': 'Untitled ' + self.today
                        }
                    }
                ]}
                logger.debug("Default title property set.")
                logger.info('Default title was set')

            if emoji:
                actual_emoji = self.emoji_resolver(emoji)
                if actual_emoji:
                    headers['icon'] = {
                        'emoji': actual_emoji
                    }
                    logger.debug(f"Icon set to emoji: {actual_emoji}")
                else:
                    logger.info('No emoji was set')
            else:
                logger.info('No emoji was set')


            if properties:
                headers['properties'] = properties
            logger.info("Headers processed successfully.")
            return headers

        except NotionProcessorError as e:
            logger.exception("Error processing Notion API headers.")
            raise e
        except Exception as e:
            logger.exception("Unexpected error in notion_api_headers.")
            raise APIError(
                f'Unexpected error: {str(e)}',
                location='Notion API Headers Processor',
                troubleshoot='Check the metadata format and try again.'
            ) from e

    def emoji_resolver(self, emoji):
        # List of deprioritized flags
            deprioritized_flags = ["flag Ascension Island", "flag Andorra", "flag Afghanistan", "flag Antigua & Barbuda", "flag Anguilla", "flag Albania", "flag Armenia", "flag Angola", "flag Antarctica", "flag Argentina", "flag American Samoa", "flag Austria", "flag Aruba", "flag Åland Islands", "flag Azerbaijan", "flag Bosnia & Herzegovina", "flag Barbados", "flag Bangladesh", "flag Belgium", "flag Burkina Faso", "flag Bulgaria", "flag Bahrain", "flag Burundi", "flag Benin", "flag St. Barthélemy", "flag Bermuda", "flag Brunei", "flag Bolivia", "flag Caribbean Netherlands", "flag Bahamas", "flag Bhutan", "flag Bouvet Island", "flag Botswana", "flag Belarus", "flag Belize", "flag Cocos (Keeling) Islands", "flag Congo - Kinshasa", "flag Central African Republic", "flag Congo - Brazzaville", "flag Switzerland", "flag Côte d’Ivoire", "flag Cook Islands", "flag Chile", "flag Cameroon", "flag China", "flag Colombia", "flag Clipperton Island", "flag Costa Rica", "flag Cuba", "flag Cape Verde", "flag Curaçao", "flag Christmas Island", "flag Cyprus", "flag Czechia", "flag Diego Garcia", "flag Djibouti", "flag Denmark", "flag Dominica", "flag Dominican Republic", "flag Algeria", "flag Ceuta & Melilla", "flag Ecuador", "flag Estonia", "flag Egypt", "flag Western Sahara", "flag Eritrea", "flag Spain", "flag Ethiopia", "flag Finland", "flag Fiji", "flag Falkland Islands", "flag Micronesia", "flag Faroe Islands", "flag Gabon", "flag Grenada", "flag Georgia", "flag French Guiana", "flag Guernsey", "flag Ghana", "flag Gibraltar", "flag Greenland", "flag Gambia", "flag Guinea", "flag Guadeloupe", "flag Equatorial Guinea", "flag Greece", "flag South Georgia & South Sandwich Islands", "flag Guatemala", "flag Guam", "flag Guinea-Bissau", "flag Guyana", "flag Hong Kong SAR China", "flag Heard & McDonald Islands", "flag Honduras", "flag Croatia", "flag Haiti", "flag Hungary", "flag Canary Islands", "flag Indonesia", "flag Ireland", "flag Israel", "flag Isle of Man", "flag British Indian Ocean Territory", "flag Iraq", "flag Iran", "flag Iceland", "flag Jersey", "flag Jamaica", "flag Jordan", "flag Japan", "flag Kenya", "flag Kyrgyzstan", "flag Cambodia", "flag Kiribati", "flag Comoros", "flag St. Kitts & Nevis", "flag North Korea", "flag South Korea", "flag Kuwait", "flag Cayman Islands", "flag Kazakhstan", "flag Laos", "flag Lebanon", "flag St. Lucia", "flag Liechtenstein", "flag Sri Lanka", "flag Liberia", "flag Lesotho", "flag Lithuania", "flag Luxembourg", "flag Latvia", "flag Libya", "flag Morocco", "flag Monaco", "flag Moldova", "flag Montenegro", "flag St. Martin", "flag Madagascar", "flag Marshall Islands", "flag North Macedonia", "flag Mali", "flag Myanmar (Burma)", "flag Mongolia", "flag Macao SAR China", "flag Northern Mariana Islands", "flag Martinique", "flag Mauritania", "flag Montserrat", "flag Malta", "flag Mauritius", "flag Maldives", "flag Malawi", "flag Malaysia", "flag Mozambique", "flag Namibia", "flag New Caledonia", "flag Niger", "flag Norfolk Island", "flag Nigeria", "flag Nicaragua", "flag Netherlands", "flag Norway", "flag Nepal", "flag Nauru", "flag Niue", "flag Oman", "flag Panama", "flag Peru", "flag French Polynesia", "flag Papua New Guinea", "flag Philippines", "flag Pakistan", "flag Poland", "flag St. Pierre & Miquelon", "flag Pitcairn Islands", "flag Puerto Rico", "flag Palestinian Territories", "flag Portugal", "flag Palau", "flag Paraguay", "flag Qatar", "flag Réunion", "flag Romania", "flag Serbia", "flag Rwanda", "flag Saudi Arabia", "flag Solomon Islands", "flag Seychelles", "flag Sudan", "flag Sweden", "flag Singapore", "flag St. Helena", "flag Slovenia", "flag Svalbard & Jan Mayen", "flag Slovakia", "flag Sierra Leone", "flag San Marino", "flag Senegal", "flag Somalia", "flag Suriname", "flag South Sudan", "flag São Tomé & Príncipe", "flag El Salvador", "flag Sint Maarten", "flag Syria", "flag Eswatini", "flag Tristan da Cunha", "flag Turks & Caicos Islands", "flag Chad", "flag French Southern Territories", "flag Togo", "flag Thailand", "flag Tajikistan", "flag Tokelau", "flag Timor-Leste", "flag Turkmenistan", "flag Tunisia", "flag Tonga", "flag Türkiye", "flag Trinidad & Tobago", "flag Tuvalu", "flag Taiwan", "flag Tanzania", "flag Ukraine", "flag Uganda", "flag U.S. Outlying Islands", "flag United Nations", "flag Uruguay", "flag Uzbekistan", "flag Vatican City", "flag St. Vincent & Grenadines", "flag Venezuela", "flag British Virgin Islands", "flag U.S. Virgin Islands", "flag Vietnam", "flag Vanuatu", "flag Wallis & Futuna", "flag Samoa", "flag Kosovo", "flag Yemen", "flag Mayotte", "flag South Africa", "flag Zambia", "flag Zimbabwe", "flag England", "flag Scotland", "flag Wales"]

            if any(x.isalpha() for x in emoji):
                try:
                    with open('emoji.json', 'r', encoding='utf-8') as file:
                        emoji_list = json.load(file)

                    emoji = emoji.strip()
                    actual_emoji = None
                    all_emoji_names = list(emoji_list.keys())
                    all_emoji_words = list({item.lower() for name in all_emoji_names for item in name.split(' ')})

                    # Prepare a set of valid words for normalization
                    valid_words = set(all_emoji_words)

                    # Check if the input is multi-word
                    if ' ' in emoji:
                        # Split into individual words
                        words = emoji.split()

                        # Normalize each word individually
                        normalized_words = [self.normalize_word(word, valid_words) for word in words]
                        normalized_input = ' '.join(normalized_words)
                    else:
                        # Single-word input; normalize directly
                        normalized_input = self.normalize_word(emoji, valid_words)

                    actual_emoji = None
                    # Attempt to match using original input first
                    matched_word = self.spellmargin(emoji, all_emoji_words)
                    if matched_word and matched_word.lower() == emoji.lower():
                        # Find all emoji names that exactly match the matched word
                        exact_name_matches = [name for name in all_emoji_names if name.lower() == matched_word.lower()]
                        if exact_name_matches:
                            actual_emoji = emoji_list.get(exact_name_matches[0], {}).get('emoji', None)
                        else:
                            # If no exact name match, find all names containing the word
                            possible_emojis = [name for name in all_emoji_names if matched_word.lower() in name.lower()]
                            if len(possible_emojis) == 1:
                                actual_emoji = emoji_list.get(possible_emojis[0], {}).get('emoji', None)
                            elif len(possible_emojis) > 1:
                                # Prefer exact match over partial matches
                                for name in possible_emojis:
                                    if name.lower() == matched_word.lower():
                                        actual_emoji = emoji_list.get(name, {}).get('emoji', None)
                                        break

                                # If no exact match
                                if not actual_emoji:
                                    logger.debug(f"Too many match possibilities found, no emoji was set.")
                    else:
                        # If no match with original input, attempt to match with normalized input
                        matched_word = self.spellmargin(normalized_input, all_emoji_words)
                        if matched_word and matched_word.lower() == normalized_input.lower():
                            # Find all emoji names that exactly match the matched word
                            exact_name_matches = [name for name in all_emoji_names if name.lower() == matched_word.lower()]
                            if exact_name_matches:
                                actual_emoji = emoji_list.get(exact_name_matches[0], {}).get('emoji', None)
                            else:
                                # If no exact name match, find all names containing the word
                                possible_emojis = [name for name in all_emoji_names if matched_word.lower() in name.lower()]
                                if len(possible_emojis) == 1:
                                    actual_emoji = emoji_list.get(possible_emojis[0], {}).get('emoji', None)
                                elif len(possible_emojis) > 1:
                                    # Prefer exact match over partial matches
                                    for name in possible_emojis:
                                        if name.lower() == matched_word.lower():
                                            actual_emoji = emoji_list.get(name, {}).get('emoji', None)
                                            break

                                    # If no exact match
                                    if not actual_emoji:
                                        logger.debug(f"Too many match possibilities found after normalization, no emoji was set.")
                        else:
                            # Step 2: If no exact word match, attempt to match against all_emoji_names with normalized input
                            matched_name = self.spellmargin(normalized_input, all_emoji_names, deprioritized_words=deprioritized_flags)
                            if matched_name:
                                actual_emoji = emoji_list.get(matched_name, {}).get('emoji', None)

                            # Collect possible emojis containing the normalized input
                            possible_emojis = [name for name in all_emoji_names if normalized_input in name.lower()]
                            
                            if len(possible_emojis) == 1:
                                actual_emoji = emoji_list.get(possible_emojis[0], {}).get('emoji', None)
                            elif len(possible_emojis) > 1:
                                # Prefer exact match over partial matches
                                for name in possible_emojis:
                                    if name.lower() == normalized_input.lower():
                                        actual_emoji = emoji_list.get(name, {}).get('emoji', None)
                                        break

                                # If no exact match
                                if not actual_emoji:
                                        logger.debug(f"Too many match possibilities found after normalization, no emoji was set.")

                    if actual_emoji:
                        logger.debug(f"Emoji resolved to: {emoji} -> {actual_emoji}")
                        return actual_emoji
                    else:
                        logger.warning(f"Emoji '{emoji}' not found. No emoji was set.")
                except FileNotFoundError:
                    logger.warning("Emoji JSON file 'emoji.json' not found. Unable to set emoji. Check your working directory.")
                    emoji = None

    def assign_links_to_superscripts(self, page_id: str):
        updated_blocks_ids = []
        # Endpoint to get the blocks of the page
        url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
        blocks, status = self.notion_request(url, 'get')

        if 'results' not in blocks:
            logger.error("No blocks found in the page.")
            raise APIError(
                'No blocks found in the page.',
                location='assign_links_to_superscripts',
                troubleshoot='Ensure the page ID is correct and the page contains blocks.'
            )

        # Build a mapping from superscript numbers to footnote block IDs
        superscript_to_block_id = {}
        for wiki_url, data in self.wiki_footnote_pairs.items():
            superscript_number = data['superscript']
            block_id = data.get('block_id')
            if block_id:
                superscript_to_block_id[superscript_number] = block_id

        # Define the block types that can contain rich_text
        rich_text_block_types = [
            'paragraph',
            'heading_1',
            'heading_2',
            'heading_3',
            'bulleted_list_item',
            'numbered_list_item',
            'quote'
        ]

        # Recursive function to process blocks and their children
        def process_blocks(block_list):
            for block in block_list:
                block_type = block.get('type')
                if block_type in rich_text_block_types:
                    text_content = block[block_type]
                    rich_texts = text_content.get('rich_text', [])
                    superscripts_updated_in_block = 0  # Initialize the counter for each block

                    #################################################################################################
                    #THE PROBLEM IS IN HERE SOMEWHERE. FIGURE OUT HOW IT WORKS. THERE IS SOMETHING THAT ONLY ALLOWS THE RECOGNITION OF THE LAST SUPERSCRIPT OF A LINE
                    new_rich_texts = []
                    for rt in rich_texts:
                        if rt.get("type") != "text":
                            # Add the rich_text without modifications if it's not of type 'text'
                            new_rich_texts.append(rt)
                            continue

                        text_content = rt.get('text').get('content')
                        annotations = rt.get('annotations', {})
                        link = rt.get('text', {}).get('link', None)

                        # Check for superscript characters in the text
                        superscript_regex = re.compile(r'[⁰¹²³⁴⁵⁶⁷⁸⁹]+')
                        new_text_parts = []
                        idx = 0
                        while idx < len(text_content):
                            match = superscript_regex.match(text_content, idx)
    
                            if match:
                                # Get the matched superscript number sequence
                                superscript_number = match.group(0)
                                
                                # Assign the link based on superscript number
                                block_id = superscript_to_block_id.get(superscript_number)
                                if block_id:
                                    link_url = f'https://www.notion.so/{page_id.replace("-", "")}#{block_id.replace("-", "")}'
                                    # Add the superscript number sequence with the link
                                    new_text_parts.append({
                                        "type": "text",
                                        "text": {
                                            "content": superscript_number,
                                            "link": {
                                                "url": link_url
                                            }
                                        },
                                        "annotations": annotations
                                    })
                                    superscripts_updated_in_block += 1

                                else:
                                    # If no link found, add the superscript without link
                                    new_text_parts.append({
                                        "type": "text",
                                        "text": {
                                            "content": superscript_number
                                        },
                                        "annotations": annotations
                                    })
                                idx += len(superscript_number)
                                
                            else:
                                # Collect normal text until the next superscript character
                                start_idx = idx
                                while idx < len(text_content) and text_content[idx] not in self.superscript_mapping.values():
                                    idx += 1
                                normal_text = text_content[start_idx:idx]
                                new_text_parts.append({
                                    "type": "text",
                                    "text": {
                                        "content": normal_text,
                                        "link": rt.get('text', {}).get('link')
                                    },
                                    "annotations": annotations
                                })

                        new_rich_texts.extend(new_text_parts)
                    #☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐☐
                    #THIS IS WHAT IS PREVENTING THE RECOGNITION OF ALL SUPERSCRIPT, FOR SOME REASON, THIS VARIABLE GETS > 0 ONLY FOR THE LAST SUPERSCRIPT OF A LINE
                    if superscripts_updated_in_block > 0:
                        # Prepare the body to update the block
                        update_url = f"https://api.notion.com/v1/blocks/{block['id']}"
                        update_body = {
                            block_type: {
                                "rich_text": new_rich_texts
                            }
                        }
                        # Send the PATCH request to update the block
                        response, status_code = self.notion_request(update_url, 'patch', update_body)
                        if status_code == 200:
                            logger.info(f"Block {block['id']} updated.")
                            print(f'Superscript Number: {superscript_number}')
                            for wiki_url, data in self.wiki_footnote_pairs.items():
                                if data['superscript'] == superscript_number:
                                    if not data.get('first_occurrence_id'):
                                        data['first_occurrence_id'] = block['id']
                        else:
                            logger.error(f"Failed to update block {block['id']}.")
                            raise APIError(
                                f"Failed to update block {block['id']}.",
                                location='assign_links_to_superscripts',
                                troubleshoot='Check the update data and API call.'
                            )
                #####################################################################################################################
                # Recursively process children blocks
                if block.get('has_children'):
                    child_url = f"https://api.notion.com/v1/blocks/{block['id']}/children?page_size=100"
                    child_blocks, status = self.notion_request(child_url, 'get')
                    if 'results' in child_blocks:
                        process_blocks(child_blocks['results'])

        # Start processing from the top-level blocks
        process_blocks(blocks['results'])
        logger.info("Link assignment to superscripts completed.")

    def update_anchor_links(self, parent_block_id: str, page_posted_id: str):
        # Build a mapping from superscript numbers to the first occurrence block ID in the main content
        superscript_to_content_block_id = {}
        for wiki_url, data in self.wiki_footnote_pairs.items():
            superscript_number = data['superscript']
            first_occurrence_block_id = data.get('first_occurrence_block_id')
            if first_occurrence_block_id:
                superscript_to_content_block_id[superscript_number] = first_occurrence_block_id

        print('This is wiki pairs >>>\n')
        print(self.wiki_footnote_pairs)
        print('\n\n')

        print('This is supescript:block_id >>>\n')
        print(superscript_to_content_block_id)
        print('\n\n')

        # Endpoint to get the children of the parent quote block
        url = f"https://api.notion.com/v1/blocks/{parent_block_id}/children"
        response, status = self.notion_request(url, 'get')

        if 'results' not in response:
            logger.error("No blocks found in the parent quote block.")
            raise APIError(
                'No blocks found in the parent quote block.',
                location='update_anchor_links',
                troubleshoot='Ensure the parent block ID is correct and the block contains children.'
            )

        for block in response['results']:
            if block['type'] == 'numbered_list_item':
                numbered_list_item = block['numbered_list_item']
                rich_texts = numbered_list_item['rich_text']
                updated = False

                new_rich_texts = []
                previous_rt = None
                part_before = None
                for rt in rich_texts:
                    if previous_rt:
                        part_before = previous_rt.get('text').get('content')
                    text_content = rt['text']['content']
                    annotations = rt.get('annotations', {})
                    
                    # Find "⚓" in the text content
                    if "⚓" in text_content:
                        try:
                            anchor_link = None
                            for wiki_url, data in self.wiki_footnote_pairs.items():
                                if data.get('title') == part_before.strip():
                                    anchor_link = data.get('first_occurrence_id')

                            if anchor_link:
                                link_url = f'https://www.notion.so/{page_posted_id.replace("-", "")}#{anchor_link.replace("-", "")}'
                                new_rich_texts.append({
                                    'type': 'text',
                                    'text': {
                                        'content': ' '
                                    }
                                })

                                new_rich_texts.append({
                                    "type": "text",
                                    "text": {
                                        "content": "⚓",
                                        "link": {
                                            "url": link_url
                                        }
                                    },
                                    "annotations": annotations
                                })
                                logger.info(f"Assigned link {link_url} to anchor emoji '⚓'.")
                                updated = True
                            else:
                                # If no block ID found, add "⚓" without link
                                new_rich_texts.append({
                                    "type": "text",
                                    "text": {
                                        "content": " (⚓ anchor link error)"
                                    },
                                    "annotations": {
                                        'italic': True,
                                        'color': 'red'
                                    }
                                })
                        except:
                            # If superscript number not found, add "⚓" without link
                            new_rich_texts.append({
                                "type": "text",
                                "text": {
                                    "content": " (⚓ anchor link error)"
                                },
                                "annotations": {
                                    'italic': True,
                                    'color': 'red'
                                }
                            })
                    else:
                        # If there's no "⚓", keep the rich_text as is
                        new_rich_texts.append(rt)
                        previous_rt = rt

                if updated:
                    # Prepare the body for updating the block
                    update_url = f"https://api.notion.com/v1/blocks/{block['id']}"
                    update_body = {
                        "numbered_list_item": {
                            "rich_text": new_rich_texts
                        }
                    }
                    # Send the PATCH request to update the block
                    response, status_code = self.notion_request(update_url, 'patch', update_body)
                    if status_code == 200:
                        logger.info(f"Block {block['id']} updated.")
                    else:
                        logger.error(f"Failed to update block {block['id']}.")
                        raise APIError(
                            f'Failed to update block {block["id"]}.',
                            location='update_anchor_links',
                            troubleshoot='Check the update data and API call.'
                        )

        logger.info("Anchor links assignment completed.")

    def parse_dates(self, option_name: str) -> Tuple[str, Optional[str]]:

        today = datetime.datetime.now().date()
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
        
        today = today.isoformat()

        system_message = f'''You are a date parser and formatter.
Your task is to recognize in a sentence (usually in italian or english but other languages might display) which part indicates the start of something and which part indicates the end of it. You separate these parts with a "$" separator. The complete format should thus be: "{{start bit}}${{end bit}}". If one of them is missing, you omit the part, but the separator must still be included. You strictly output only the formatted string in this way. Be careful with time ranges where PM or AM are not specified in any form and choose the most reasonable.
Additionally, format input dates into ISO 8601. If the input is a sole two-digit number, treat it as the day of the month.
If no time is specified, do not add time, only include the date. If time is included, format it using the template (THH:MM) and add the +02:00 timezone offset. For relative time terms, refer to "{today}". If no start is given, default to "{today}". If end time is given but no start time is given, default to midnight. Output must strictly be the formatted string. If the sentence doesn't mention dates or doesn't make sense, respond "null".'''
        
        chat_history = [f'system: {system_message}', 'user: per il prossimo mercoledì', f'chatbot: {next_wednesday}$', 'user: entro sabato alle sette', f'chatbot: {next_saturday}T07:00+02:00$', 'user: dalle 8 alle 12', f'chatbot: {today}T08:00+02:00${today}T12:00+02:00', 'user: martedì alle 17', f'chatbot: {next_tuesday}T17:00+02:00$', 'user: fino al 17', f'chatbot: {today}${seventeenth_of_month}', 'user: 12', f'chatbot: {twelfth_of_month}', 'user: da oggi alle 8 fino a domani alle 11', f'chatbot: {today}T08:00+02:00${tomorrow}T11:00+02:00', 'user: fino alle 9 di domani sera', f'chatbot: {today}T00:00+02:00${tomorrow}T21:00+02:00','user: fino a domani alle 2', f'chatbot: {today}T00:00+02:00${tomorrow}T14:00+02:00','user: domani alle 4', f'chatbot: {tomorrow}T16:00+02:00$', 'user: history art museum', f'chatbot: null']
        
        try:
            response, _ = self.cohere_request(option_name, chat_history=chat_history)
            if response.lower() != 'null':
                start, end = response.split('$')
                if not start:
                    start = self.today
                if not end:
                    end = None
                logger.debug(f"Parsed dates - Start: {start}, End: {end}")
                return start, end
            elif response.lower() == 'null':
                return None, None
            else:
                raise APIError(
                    'Failed to parse dates using Cohere API.',
                    location='Cohere API',
                    troubleshoot='Check your input and Cohere API key.'
                )
        except NotionProcessorError as e:
            logger.exception("Error parsing dates.")
            raise e
        except Exception as e:
            logger.exception("Unexpected error in parse_dates.")
            raise APIError(
                f'Unexpected error: {str(e)}',
                location='Date Parser',
                troubleshoot='Ensure the date format is correct.'
            ) from e

    def handle_select_property(
        self, 
        properties: Dict[str, Any], 
        property_name: Optional[str], 
        option_name: str, 
        type_lists: Dict[str, List[str]], 
        property_options: Dict[str, Dict[str, str]]
    ) -> Dict[str, Any]:
        try:
            if not property_name:
                if len(self.type_lists.get('select')) == 1:
                    property_name = self.type_lists.get('select')[0]

            if not property_name:
                property_name, option_id = self.check_against_database('select', option_name)
                if option_id:
                    properties[property_name] = {
                        'select': {
                            'id': option_id
                        }
                    }
                    logger.debug(f"Select property '{property_name}' set with ID: {option_id}")
                else:
                    property_name_response, _ = self.cohere_request(
                        f'To which of these property names "{type_lists.get("select", [])}" does the option value "{option_name}" belong? Output only the chosen property value.'
                    )
                    if property_name_response:
                        property_name = property_name_response.strip()
                        properties[property_name] = {
                            'select': {
                                'name': option_name.capitalize()
                            }
                        }
                        logger.debug(f"Select property '{property_name}' set with name: {option_name}")
                    else:
                        raise SyntaxError(
                            'Failed to determine select property name.',
                            location='Cohere API',
                            troubleshoot='Ensure your select properties are correctly named.'
                        )
            else:
                property_name, option_id = self.check_against_database('select', option_name, property_name=property_name)
                if option_id:
                    properties[property_name] = {
                        'select': {
                            'id': option_id
                        }
                    }
                    logger.debug(f"Select property '{property_name}' set with ID: {option_id}")
                else:
                    properties[property_name] = {
                        'select': {
                            'name': option_name.capitalize()
                        }
                    }
                    logger.debug(f"Select property '{property_name}' set with name: {option_name}")
            return properties
        except NotionProcessorError as e:
            logger.exception("Error handling select property.")
            raise e
        except Exception as e:
            logger.exception("Unexpected error in handle_select_property.")
            raise APIError(
                f'Unexpected error: {str(e)}',
                location='Select Property Handler',
                troubleshoot='Ensure the select property and option are valid.'
            ) from e

    def handle_multi_select_property(
        self, 
        properties: Dict[str, Any], 
        property_name: Optional[str], 
        option_name: str, 
        type_lists: Dict[str, List[str]], 
        property_options: Dict[str, Dict[str, str]]
    ) -> Dict[str, Any]:
        try:
            option_dict = []
            if not property_name:
                if len(self.type_lists.get('multi_select')) == 1:
                    property_name = self.type_lists.get('multi_select')[0]
            
            tags_list = [tag.strip() for tag in option_name.split(',')]
            if not property_name:
                for tag in tags_list:
                    property_name, tag_id = self.check_against_database('multi_select', tag)
                    if tag_id and property_name:
                        option_dict.append({'id': tag_id})
                    elif property_name and not tag_id:
                        option_dict.append({'name': tag.capitalize()})
                
                properties[property_name] = {
                    'multi_select': option_dict
                }
                logger.debug(f"Multi-select property '{property_name}' set with options: {tags_list}")

                if not property_name:
                    property_name_response, _ = self.cohere_request(
                        f'To which of these property names "{type_lists.get("multi_select", [])}" do the tags "{option_name}" belong? Output only the chosen property value.'
                    )
                    if property_name_response:
                        property_name = property_name_response.strip()
                        option_dict = [{'name': tag.capitalize()} for tag in tags_list]
                        properties[property_name] = {
                            'multi_select': option_dict
                        }
                        logger.debug(f"Multi-select property '{property_name}' set with names: {tags_list}")
                    else:
                        raise SyntaxError(
                            'Failed to determine multi-select property name.',
                            location='Cohere API',
                            troubleshoot='Ensure your multi-select properties are correctly named.'
                        )
            else:
                for tag in tags_list:
                    property_name, tag_id = self.check_against_database('multi_select', tag, property_name=property_name)
                    if tag_id and property_name:
                        option_dict.append({'id': tag_id})
                    elif property_name and not tag_id:
                        option_dict.append({'name': tag.capitalize()})
                properties[property_name] = {
                    'multi_select': option_dict
                }
                logger.debug(f"Multi-select property '{property_name}' set with options: {tags_list}")
            return properties
        except NotionProcessorError as e:
            logger.exception("Error handling multi-select property.")
            raise e
        except Exception as e:
            logger.exception("Unexpected error in handle_multi_select_property.")
            raise APIError(
                f'Unexpected error: {str(e)}',
                location='Multi-Select Property Handler',
                troubleshoot='Ensure the multi-select property and options are valid.'
            ) from e

    def process_inlines(self, text: str) -> List[Dict[str, Any]]:
        """
        Processa gli elementi inline nel testo e restituisce una lista di rich text per Notion.
        Gli elementi inline includono:
            - <txt>: testo semplice
            - <icd>: codice inline
            - <ieq>: equazione inline (senza custom)
        """
        inline_elements = []
        # Split the text by '£' which is the inline separator
        inlines = text.split('£')
        for inline in inlines:
            if not inline:
                continue
            if inline.startswith('<txt>'):
                content = inline.replace('<txt>', '')
                # Processa eventuali custom nel testo
                inline_elements.extend(self.process_custom(content))
            elif inline.startswith('<icd>'):
                content = inline.replace('<icd>', '')
                # Processa eventuali custom nel codice inline
                try:
                    custom_elements = self.process_custom(content)
                    # Apply 'code' annotation to each element
                    for elem in custom_elements:
                        if 'annotations' not in elem:
                            elem['annotations'] = {}
                        # Merge existing annotations with 'code': True
                        elem['annotations']['code'] = True
                    inline_elements.extend(custom_elements)
                except SyntaxError as e:
                    logger.exception("Syntax error while processing <icd> inline.")
                    raise e
                except Exception as e:
                    logger.exception("Unexpected error while processing <icd> inline.")
                    raise SyntaxError(
                        message=f'Unexpected error processing <icd> inline: {str(e)}',
                        location='process_inlines',
                        troubleshoot='Check the syntax of your <icd> inline.'
                    ) from e
            elif inline.startswith('<ieq>'):
                content = inline.replace('<ieq>', '')
                # Le equazioni inline non possono contenere custom
                if re.search(r'(url|link|wik|wiki|wikipedia)\(', content):
                    raise SyntaxError(
                        message='Custom elements are not allowed inside inline equations.',
                        location='process_inlines',
                        troubleshoot='Remove custom elements from inline equations.'
                    )
                inline_elements.append({
                    'type': 'equation',
                    'equation': {
                        'expression': content
                    }
                })
            else:
                try: 
                    # Process as 'txt'
                    inline_elements.extend(self.process_custom(inline))
                except SyntaxError as e:
                    logger.exception("Syntax error while processing unrecognized inline.")
                    raise e
                except Exception as e:
                    logger.exception("Unexpected error while processing unrecognized inline.")
                    raise SyntaxError(
                        message=f'Unrecognized inline marker in "{inline}"',
                        location='process_inlines',
                        troubleshoot='Check your inline formatting.'
                    ) from e
        return inline_elements

    def process_custom(self, text: str) -> List[Dict[str, Any]]:
        custom_elements = []
        pattern = r'(url|link|wik|wiki|wikipedia)\(([^)]+)\)'
        matches = list(re.finditer(pattern, text))
        last_end = 0
        if not matches:
            custom_elements.append({
                'type': 'text',
                'text': {
                    'content': text
                }
            })
            return custom_elements

        for match in matches:
            start, end = match.span()
            if start > last_end:
                custom_elements.append({
                    'type': 'text',
                    'text': {
                        'content': text[last_end:start]
                    }
                })
            keyword = match.group(1)
            content = match.group(2)
            if keyword in ['wik', 'wiki', 'wikipedia']:
                try:
                    chat_history = ['user: Teorema di Weierstrass', 'chatbot: it', 'user: Astronomy', 'chatbot: en']
                    response, status_code = self.cohere_request(f'\"{content}\".\n\nWhich language is this? Respond strictly only with two-letter format of the language ("it", "en", "es", "de"...). If you aren\'t able to deduct a language, default to \"en\".', chat_history=chat_history)
                    response = response.strip()
                    if len(response) == 2 and response.isalpha():
                        language = response
                    else:
                        language = 'en'
                except:
                    language = 'en'
                wiki_title, wiki_url = self.check_wikipedia_page(content, language=language)
                if wiki_url:
                    # Check if the wiki_url is already in the footnote pairs
                    if wiki_url in self.wiki_footnote_pairs:
                        # Use existing superscript number
                        superscript_number = self.wiki_footnote_pairs[wiki_url]['superscript']
                        # Append the new content variation
                        self.wiki_footnote_pairs[wiki_url]['contents'].append(content)
                    else:
                        # Assign a new superscript number
                        superscript_number = ''.join(self.superscript_mapping[digit] for digit in str(self.wiki_count))
                        # Add to footnote pairs
                        self.wiki_footnote_pairs[wiki_url] = {
                            'title': wiki_title,
                            'superscript': superscript_number,
                            'contents': [content],
                            'block_id': None,  # Will be set later when footnotes are created
                            'first_occurrence_id': None
                        }
                        self.wiki_count += 1

                    # Add the content with link and superscript to custom_elements
                    custom_elements.append({
                        'type': 'text',
                        'text': {
                            'content': content,
                            'link': {
                                'url': wiki_url
                            }
                        },
                        'annotations': {
                            'italic': True,
                            'color': 'blue'
                        }
                    })
                    superscript = {
                        "type": "text",
                        "text": {
                            "content": superscript_number
                        },
                        "annotations": {
                            "color": "blue"
                        }
                    }
                    custom_elements.append(superscript)
                else:
                    custom_elements.append({
                        'type': 'text',
                        'text': {
                            'content': content
                        },
                        'annotations': {
                            'italic': True,
                            'underline': True,
                            'color': 'red'
                        }
                    })
            elif keyword in ['url', 'link']:
                # Process custom link
                full_url = self.resolve_link(content)
                if full_url:
                    custom_elements.append({
                        'type': 'text',
                        'text': {
                            'content': content,
                            'link': {
                                'url': full_url
                            }
                        },
                        'annotations': {
                            'underline': True,
                            'color': 'blue'
                        }
                    })
                else:
                    custom_elements.append({
                        'type': 'text',
                        'text': {
                            'content': content
                        },
                        'annotations': {
                            'color': 'red'
                        }
                    })
            else:
                raise SyntaxError(
                    message=f'Unrecognized custom keyword "{keyword}"',
                    location='process_custom',
                    troubleshoot='Check your custom element syntax.'
                )
            last_end = end
        if last_end < len(text):
            custom_elements.append({
                'type': 'text',
                'text': {
                    'content': text[last_end:]
                }
            })
        return custom_elements

    def notion_api_children(self, content_to_process: List[str]) -> List[Dict[str, Any]]:
        """
        Processes a list of content strings with specific markers and converts them into Notion block structures.
        Handles nested list items based on their indentation level.
        """
        children = []
        list_stack = []

        for element in content_to_process:
            if not element:
                continue
            element = element.strip()

            # Identify the block type and content
            if element.startswith('<hd1>'):
                block_type = 'heading_1'
                content = element.replace('<hd1>', '')
            elif element.startswith('<hd2>'):
                block_type = 'heading_2'
                content = element.replace('<hd2>', '')
            elif element.startswith('<hd3>'):
                block_type = 'heading_3'
                content = element.replace('<hd3>', '')
            elif element.startswith('<pgr>'):
                block_type = 'paragraph'
                content = element.replace('<pgr>', '')
            elif element.startswith('<cod>'):
                block_type = 'code'
                content = element.replace('<cod>', '')
            elif element.startswith('<blq>'):
                block_type = 'equation'
                content = element.replace('<blq>', '')
                # Check for inlines or customs in block equations
                if re.search(r'(url|link|wik|wiki|wikipedia)\(|£', content):
                    raise SyntaxError(
                        message='Inlines or customs are not allowed inside block equations.',
                        location='notion_api_children',
                        troubleshoot='Remove inlines and customs from block equations.'
                    )
            elif element.startswith('<bl'):
                # Bulleted list item
                level = int(element[3])  # e.g., '<bl2>' -> level 2
                block_type = 'bulleted_list_item'
                content = element[element.find('>')+1:]  # Remove the marker '<blN>'
            elif element.startswith('<nr'):
                # Numbered list item
                level = int(element[3])  # e.g., '<nr2>' -> level 2
                block_type = 'numbered_list_item'
                content = element[element.find('>')+1:]  # Remove the marker '<nrN>'
            else:
                # Handle unrecognized block markers
                raise SyntaxError(
                    message=f'Unrecognized block marker in "{element}"',
                    location='notion_api_children',
                    troubleshoot='Check your block formatting.'
                )

            # Process the content
            if block_type == 'equation':
                # Block equations cannot contain inlines or customs
                block = {
                    'object': 'block',
                    'type': block_type,
                    block_type: {
                        'expression': content
                    }
                }
            elif block_type == 'code':
                # Code blocks can contain inlines but not customs
                if re.search(r'(url|link|wik|wiki|wikipedia)\(', content):
                    raise SyntaxError(
                        message='Custom elements are not allowed inside code blocks.',
                        location='notion_api_children',
                        troubleshoot='Remove custom elements from code blocks.'
                    )
                inlines = self.process_inlines('<txt>' + content)
                block = {
                    'object': 'block',
                    'type': block_type,
                    block_type: {
                        'rich_text': inlines,
                        'language': 'python'  # Or specify appropriate language
                    }
                }
            else:
                # Process the inlines and customs in the content
                inlines = self.process_inlines('<txt>' + content)
                block = {
                    'object': 'block',
                    'type': block_type,
                    block_type: {
                        'rich_text': inlines
                    }
                }

            # Handle nesting for list items
            if block_type in ['bulleted_list_item', 'numbered_list_item']:
                # Adjust the list_stack according to the level
                while len(list_stack) >= level:
                    list_stack.pop()
                if level > 1 and list_stack:
                    # Add block as child to the last item in the stack
                    parent = list_stack[-1]
                    if 'children' not in parent[block_type]:
                        parent[block_type]['children'] = []
                    parent[block_type]['children'].append(block)
                else:
                    # Level 1 item, add to children
                    children.append(block)
                list_stack.append(block)
            else:
                # For non-list items, reset the list_stack
                list_stack = []
                children.append(block)

        os.chdir('Web Apps and Projects')
        with open('Output_Debug/output.json', 'w') as file:
            file.write(json.dumps(children, indent=4))
        return children

    def process_and_post(
        self,
        metadata_to_process: Optional[str] = None,
        content_to_process: Optional[str] = None,
        title: Optional[str] = None,
        emoji: Optional[str] = None,
        wiki_footnote: Optional[str] = 'false'
    ) -> Dict[str, Any]:
        custom_title = title if title else None
        custom_emoji = emoji if emoji else None

        try:
            data = self.notion_api_headers(metadata_to_process, title=custom_title, emoji=custom_emoji)

            page_posted_id = None

            if not content_to_process:
                # ... (code remains the same)
                pass
            else:
                input_children = content_to_process.split('$') if content_to_process else []

                # Break the list into batches of 100
                batches = [input_children[i:i + 100] for i in range(0, len(input_children), 100)]
                logger.info(f"Processing {len(batches)} batch(es) of content.")

                if batches:
                    data['children'] = self.notion_api_children(batches[0])
                    page_posted_response, status_code = self.notion_request('https://api.notion.com/v1/pages', 'post', data)
                    if page_posted_response is None or 'id' not in page_posted_response:
                        logger.error("Failed to create page in Notion.")
                        raise APIError(
                            'Failed to create page.',
                            location='Notion API',
                            troubleshoot='Check your data and API key.',
                            status_code=502
                        )
                    page_posted_id = page_posted_response['id']
                    logger.info(f"Page created with ID: {page_posted_id}")

                    # Append remaining batches
                    for idx, batch in enumerate(batches[1:], start=2):
                        append_data = {'children': self.notion_api_children(batch)}
                        append_block_response, status_code = self.notion_request(
                            f'https://api.notion.com/v1/blocks/{page_posted_id}/children', 'patch', append_data
                        )
                        if append_block_response:
                            logger.info(f"Appended batch {idx} to page {page_posted_id}")
                        else:
                            logger.error(f"Failed to append batch {idx} to page {page_posted_id}")
                            raise APIError(
                                'Failed to append batch.',
                                location='Notion API',
                                troubleshoot='Check your data and API key.',
                                status_code=502
                            )

                if wiki_footnote == 'true' and self.wiki_footnote_pairs:
                    sub_children = []
                    # Sort the footnotes by their superscript numbers for consistency
                    sorted_wiki_footnotes = sorted(self.wiki_footnote_pairs.items(), key=lambda x: int(''.join(self.superscript_mapping[char] for char in x[1]['superscript'])))
                    for wiki_url, data in sorted_wiki_footnotes:
                        entry_title = data['title']
                        nrp = {
                            'object': 'block',
                            'type': 'numbered_list_item',
                            'numbered_list_item': {
                                'rich_text': [
                                    {
                                        "type": "text",
                                        "text": {
                                            "content": entry_title,
                                            "link": {
                                                "url": wiki_url
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
                                        "plain_text": entry_title,
                                        "href": wiki_url
                                    },
                                    {
                                        "type": "text",
                                        "text": {
                                            "content": ' ⚓',
                                            "link": None
                                        },
                                        "annotations": {
                                            "bold": False,
                                            "italic": False,
                                            "strikethrough": False,
                                            "underline": False,
                                            "code": False,
                                            "color": "default"
                                        },
                                        "plain_text": ' ⚓',
                                        "href": None
                                    }
                                ]
                            }
                        }
                        sub_children.append(nrp)

                    append_data = {
                        'children': [
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
                                'type': 'quote',
                                'quote': {
                                    'rich_text': [
                                        {
                                            'type': 'text',
                                            'text': {
                                                'content': 'Page Webography'
                                            }
                                        }
                                    ],
                                    'children': sub_children
                                }
                            }
                        ]
                    }

                    append_block_response, status_code = self.notion_request(
                        f'https://api.notion.com/v1/blocks/{page_posted_id}/children', 'patch', append_data
                    )
                    logger.info(f'Wiki Footnote created.')

                    if status_code == 200:
                        quote_id = append_block_response.get('results')[1].get('id')
                        # Get the children of the quote block
                        response, status_code = self.notion_request(f'https://api.notion.com/v1/blocks/{quote_id}/children', 'get')
                        footnote_blocks = response.get('results', [])
                        # Map superscript numbers to footnote block IDs
                        for idx, block in enumerate(footnote_blocks):
                            block_id = block.get('id')
                            wiki_url, data = sorted_wiki_footnotes[idx]
                            # Update the block_id in self.wiki_footnote_pairs
                            self.wiki_footnote_pairs[wiki_url]['block_id'] = block_id

                        # Assign links to superscripts using the updated self.wiki_footnote_pairs
                        # Also, record the first occurrence block IDs for anchor linking
                        self.assign_links_to_superscripts(page_posted_id)

                        # Update anchor links in the footnote entries to point back to the main content
                        self.update_anchor_links(quote_id, page_posted_id)
                    else:
                        logger.error(f"Failed to append footnote blocks. Status code: {status_code}")
                        raise APIError(
                            'Failed to append footnote blocks.',
                            location='process_and_post',
                            troubleshoot='Check the append data and API call.'
                        )

            # Return the page ID or other relevant information
            return {'page_id': page_posted_id}

        except NotionProcessorError as e:
            logger.exception("Error processing input.")
            raise e
        except Exception as e:
            logger.exception("Unexpected error in process_and_post.")
            raise APIError(
                f'Unexpected error: {str(e)}',
                location='process_and_post',
                troubleshoot='An unexpected error occurred.'
            ) from e

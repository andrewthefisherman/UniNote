import sys
import time
import requests
import re
import json
import datetime
import Levenshtein

# Custom exception classes
class NotionProcessorError(Exception):
    """Base class for exceptions in NotionProcessor."""
    def __init__(self, message, location=None, troubleshoot=None):
        super().__init__(message)
        self.location = location
        self.troubleshoot = troubleshoot

class InputError(NotionProcessorError):
    pass

class ConnectionError(NotionProcessorError):
    pass

class APIError(NotionProcessorError):
    pass

class SyntaxError(NotionProcessorError):
    pass

class NotionProcessor:
    def __init__(self, notion_api_key, database_id, cohere_api_key):
        if not notion_api_key:
            raise ValueError("Notion API key is required.")
        if not database_id:
            raise ValueError("Database ID is required.")
        if not cohere_api_key:
            raise ValueError("Cohere API key is required.")
        
        self.notion_api_key = notion_api_key
        self.database_id = database_id
        self.cohere_api_key = cohere_api_key
        self.today = datetime.datetime.now().strftime('%Y-%m-%d')
        self.title = None
        self.emoji = None

    def notion_request(self, url, method, body=None):
        headers = {
            'Authorization': f'Bearer {self.notion_api_key}',
            'Notion-Version': '2022-06-28'
        }
        if method.lower() in ["post", "patch"]:
            headers['Content-Type'] = "application/json"
        elif method.lower() not in ['get']:
            raise APIError(f'HTTP method {method} is not supported.', 'Notion Request', 'Use GET, POST, or PATCH methods.')

        max_retries = 3
        retry_delay = 3  # seconds

        for attempt in range(1, max_retries + 1):
            try:
                if method.lower() in ["post", "patch"]:
                    request_func = getattr(requests, method.lower())
                    response = request_func(url=url, headers=headers, json=body)
                elif method.lower() == 'get':
                    response = requests.get(url=url, headers=headers)

                if response.status_code == 200:
                    return response.json(), response.status_code
                else:
                    raise APIError(f'Error {response.status_code}: {response.text}', 'Notion API', 'Check your request and API key.')
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue  # Retry the request
                else:
                    raise ConnectionError('Connection Error with Notion API', 'Notion API', 'Check your internet connection.') from e
            except requests.exceptions.RequestException as e:
                # Handle other request exceptions
                raise APIError(f'Request exception: {str(e)}', 'Notion API', 'Check your request and network connection.') from e

    def cohere_request(self, prompt):
        if not self.cohere_api_key:
            raise APIError('Cohere API key is missing.', 'Cohere API', 'Provide a valid Cohere API key.')

        url = "https://api.cohere.ai/generate"
        body = {'prompt': prompt, 'model': 'xlarge', 'max_tokens': 50}
        headers = {'Authorization': f'Bearer {self.cohere_api_key}', 'Content-Type': 'application/json'}

        max_retries = 3
        retry_delay = 3  # seconds

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(url=url, headers=headers, json=body)

                if response.status_code == 200:
                    output = response.json()['generations'][0]['text'].strip()
                    return output, response.status_code
                else:
                    raise APIError(f'Error {response.status_code}: {response.text}', 'Cohere API', 'Check your request and API key.')
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue  # Retry the request
                else:
                    raise ConnectionError('Connection Error with Cohere API', 'Cohere API', 'Check your internet connection.') from e
            except requests.exceptions.RequestException as e:
                # Handle other request exceptions
                raise APIError(f'Request exception: {str(e)}', 'Cohere API', 'Check your request and network connection.') from e

    def is_website_valid(self, url):
        max_retries = 3
        retry_delay = 3  # seconds

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.get(url, timeout=5)
                return response.status_code == 200
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue  # Retry the request
                else:
                    return False
            except requests.exceptions.RequestException:
                # For other exceptions, assume the website is invalid
                return False

    def notion_api_headers(self, metadata_to_process):
        def spellmargin(input_word, word_list):
            word_length = len(input_word)
            if word_length < 4:
                threshold = 1
            elif 4 <= word_length <= 8:
                threshold = 3
            else:
                threshold = 4

            best_match = None
            best_distance = float('inf')

            for word in word_list:
                distance = Levenshtein.distance(input_word, word)
                if distance <= threshold and distance < best_distance:
                    best_match = word
                    best_distance = distance

            return best_match

        # GET properties info
        response, status_code = self.notion_request(f'https://api.notion.com/v1/databases/{self.database_id}', 'get')
        if response is None:
            raise APIError('Failed to retrieve database properties.', 'Notion API', 'Check your database ID and API key.')
        properties_dict = response['properties']
        all_property_names = list(properties_dict.keys())
        # Counts how many times there is a specific "type"
        type_lists = {t: [key for key in all_property_names if properties_dict[key]['type'] == t]
                      for t in {properties_dict[key]['type'] for key in all_property_names}}
        property_types = {key: value['type'] for key, value in properties_dict.items()}
        property_markers = {'title': '<tit>', 'relation': '<pit>', 'date': '<dat>', 'checkbox': '<chk>',
                            'select': '<sel>', 'multi_select': '<msl>'}

        property_options = {
            key: {option['name']: option['id'] for option in properties_dict[key][properties_dict[key]['type']]['options']}
            for key in properties_dict
            if properties_dict[key]['type'] in ['select', 'multi_select']
        }

        if not metadata_to_process:
            headers = {
                'parent': {
                    'database_id': self.database_id
                },
                'properties': {}
            }
            headers['properties'][type_lists['title'][0]] = {'title': [
                {
                    'text': {
                        'content': 'Untitled ' + self.today
                    }
                }
            ]}
            return headers

        # Start parsing headers
        input_headers = metadata_to_process.replace("\n", "")
        matching = r"\s*\(\s*([^)]+)\s*\)\s*"
        patterns = [r"(title|tit|name)" + matching, r"(parentitem|parent Item|pit|pitem|parent)" + matching,
                    r"(date|dat|data)" + matching, r"(checkbox|check|chk)" + matching,
                    r"(multiselect|multi-select|msel|multisel|mselect)" + matching, r"(select|sel)" + matching,
                    r'(ico|icon|emoji|emoticon)' + matching, matching]
        replacements = [r"<tit>\2", r"<pit>\2", r"<dat>\2", r"<chk>\2", r"<msl>\2", r"<sel>\2", r"<ico>\2", r"<und>\1"]
        try:
            formatted_headers_list = [
                next(
                    re.sub(pattern, replacement, header).strip()
                    for pattern, replacement in zip(patterns, replacements)
                    if re.search(pattern, header)
                )
                for header in re.split(r'(?<=\))\s*,\s*|\s*;\s*|\s+', input_headers)
            ]
        except StopIteration:
            raise SyntaxError('Incorrect header syntax. Missing parentheses?', 'Headers and metadata processor', 'Check the syntax of your metadata.')

        properties = {}
        headers = {}

        for header in formatted_headers_list:
            if header.startswith('<chk>') and not type_lists.get('checkbox'):
                raise SyntaxError('No Checkbox Property Found', 'Headers and metadata processor', 'Add a checkbox property to your database or correct your metadata.')
            if header.startswith('<dat>') and not type_lists.get('date'):
                raise SyntaxError('No Date Property Found', 'Headers and metadata processor', 'Add a date property to your database or correct your metadata.')
            if header.startswith('<sel>') and not type_lists.get('select'):
                raise SyntaxError('No Select Property Found', 'Headers and metadata processor', 'Add a select property to your database or correct your metadata.')
            if header.startswith('<msl>') and not type_lists.get('multi_select'):
                raise SyntaxError('No Multi-Select Property Found', 'Headers and metadata processor', 'Add a multi-select property to your database or correct your metadata.')

            if not header.startswith('<msl>') and ',' in header:
                generic_marker = re.search(r'<\w+>', header)
                raise SyntaxError(f'Only one argument allowed for {generic_marker.group()} elements', 'Headers and metadata processor', 'Correct your metadata syntax.')

            stripped_header = re.sub(r'<\w\w\w>', '', header)
            if ':' in stripped_header:
                property_name, option_name = stripped_header.split(":", 1)
                property_name = spellmargin(property_name.strip(), all_property_names)
                if not property_name:
                    raise SyntaxError(f'Property Name not found for {header}', 'Headers and metadata processor', f'Wrong property in {header}')
                option_name = option_name.strip()
            else:
                property_name = None
                option_name = stripped_header.strip()

            if header.startswith('<und>'):
                if ':' in header:
                    marker = property_markers[property_types[property_name]]
                    header = marker
                else:
                    raise SyntaxError(f'Missing Property Name for value "{option_name}"', 'Headers and metadata processor', 'Specify the property name.')

            # Start marker and property parsing
            if header.startswith('<tit>'):
                if not self.title:
                    self.title = option_name

            elif header.startswith('<pit>'):
                if 'Parent Item' in properties_dict:
                    search_query = {
                        'filter': {
                            'property': type_lists['title'][0],
                            'title': {
                                'equals': option_name
                            }
                        }
                    }
                    response, status_code = self.notion_request(
                        f'https://api.notion.com/v1/databases/{self.database_id}/query', 'post', search_query)
                    if response and response.get('results'):
                        parent_id = response['results'][0]['id']
                        properties[type_lists['relation'][0]] = {
                            'relation': [
                                {
                                    'id': parent_id
                                }
                            ]
                        }
                    else:
                        raise APIError(f'Parent Item "{option_name}" not found.', 'Notion API', 'Ensure the parent item exists in your database.')
                else:
                    raise SyntaxError('No Relation Property "Parent Item" found.', 'Headers and metadata processor', 'Add a relation property named "Parent Item" to your database.')

            elif header.startswith('<ico>'):
                if not self.emoji:
                    self.emoji = option_name

            elif header.startswith('<chk>'):
                if property_name:
                    checkbox_answers = {'yes': True, 'no': False, 'true': True, 'false': False}
                    checkbox_value = checkbox_answers.get(option_name.lower())
                    if checkbox_value is not None:
                        properties[property_name] = {
                            'checkbox': checkbox_value
                        }
                    else:
                        raise SyntaxError('Checkbox value is invalid', 'Headers and metadata processor', 'Use "yes", "no", "true", or "false" for checkbox values.')
                else:
                    raise SyntaxError('No Property name specified for Checkbox Property', 'Headers and metadata processor', 'Specify the property name for the checkbox.')

            elif header.startswith('<dat>'):
                if property_name:
                    start, end = self.parse_dates(option_name)
                    properties[property_name] = {
                        'date': {
                            'start': start,
                            'end': end
                        }
                    }
                else:
                    raise SyntaxError('Date Property Name not specified', 'Headers and metadata processor', 'Specify the property name for the date.')

            elif header.startswith('<sel>'):
                properties = self.handle_select_property(properties, property_name, option_name, type_lists, property_options)

            elif header.startswith('<msl>'):
                properties = self.handle_multi_select_property(properties, property_name, option_name, type_lists, property_options)

        headers['parent'] = {
            'database_id': self.database_id
        }
        if self.title:
            properties[type_lists['title'][0]] = {'title': [
                {
                    'text': {
                        'content': self.title
                    }
                }
            ]}
        else:
            properties[type_lists['title'][0]] = {'title': [
                {
                    'text': {
                        'content': 'Untitled ' + self.today
                    }
                }
            ]}

        if self.emoji:
            if any(x.isalpha() for x in self.emoji):
                try:
                    with open('emoji.json', 'r', encoding='utf-8') as file:
                        emoji_list = json.load(file)
                    self.emoji = emoji_list.get(self.emoji, {}).get('emoji', None)
                except FileNotFoundError:
                    self.emoji = None
            if self.emoji:
                headers['icon'] = {
                    'emoji': self.emoji
                }

        headers['properties'] = properties

        return headers

    def parse_dates(self, option_name):
        prompt = f'''Input: {option_name}
A start date, start time, end date, and end time might be specified in the input.
Watch for prepositions that indicate the beginning (start) and the transition to the end.
Separate these two parts with a "$".
The format should thus be: "{{start bit}}${{end bit}}".
Either the start or end date might be missing, add it anyway as an empty value: "{{startbit}}$" (only start bit), "${{end bit}}" (only end bit).
Remove prepositions. Output must only be formatted string.'''

        response, _ = self.cohere_request(prompt)
        if response:
            start_part, _, end_part = response.partition('$')
            start = self.format_date(start_part.strip()) if start_part.strip() else self.today
            end = self.format_date(end_part.strip()) if end_part.strip() else None
            return start, end
        else:
            raise APIError('Failed to parse dates using Cohere API.', 'Cohere API', 'Check your input and Cohere API key.')

    def format_date(self, date_str):
        prompt = f'''Input string: "{date_str}"
Format input string into ISO 8601.
If input is sole two-digit number, treat it as day of the month.
IF NO TIME IS SPECIFIED, DO NOT ADD TIME. Only include the date. Ignore the time section completely if it's not provided.
IF TIME IS INCLUDED, FORMAT IT USING THIS TEMPLATE (THH:MM) AND ADD +00:00 TIMEZONE OFFSET.
For relative time terms, refer to "{self.today}".
Output must only be the formatted string.'''
        response, _ = self.cohere_request(prompt)
        if response:
            return response.strip()
        else:
            raise APIError('Failed to format date using Cohere API.', 'Cohere API', 'Check your input and Cohere API key.')

    def handle_select_property(self, properties, property_name, option_name, type_lists, property_options):
        if not property_name:
            match_property = None
            for property in type_lists.get('select', []):
                if option_name in property_options.get(property, {}):
                    match_property = property
                    option_id = property_options[property][option_name]
                    properties[match_property] = {
                        'select': {
                            'id': option_id
                        }
                    }
                    break
            if not match_property:
                property_name, _ = self.cohere_request(f'To which of these property names "{type_lists.get("select", [])}" does the option value "{option_name}" belong? Output only the chosen property value.')
                if property_name:
                    properties[property_name.strip()] = {
                        'select': {
                            'name': option_name
                        }
                    }
                else:
                    raise SyntaxError('Failed to determine select property name.', 'Cohere API', 'Ensure your select properties are correctly named.')
        else:
            if option_name in property_options.get(property_name, {}):
                option_id = property_options[property_name][option_name]
                properties[property_name] = {
                    'select': {
                        'id': option_id
                    }
                }
            else:
                properties[property_name] = {
                    'select': {
                        'name': option_name
                    }
                }
        return properties

    def handle_multi_select_property(self, properties, property_name, option_name, type_lists, property_options):
        tags_list = [tag.strip() for tag in option_name.split(',')]
        if not property_name:
            match_property = None
            for property in type_lists.get('multi_select', []):
                if any(tag in property_options.get(property, {}) for tag in tags_list):
                    match_property = property
                    option_dict = []
                    for tag in tags_list:
                        tag_id = property_options[match_property].get(tag)
                        if tag_id:
                            option_dict.append({'id': tag_id})
                        else:
                            option_dict.append({'name': tag})
                    properties[match_property] = {
                        'multi_select': option_dict
                    }
                    break
            if not match_property:
                property_name, _ = self.cohere_request(f'To which of these property names "{type_lists.get("multi_select", [])}" do the tags "{option_name}" belong? Output only the chosen property value.')
                if property_name:
                    option_dict = [{'name': tag} for tag in tags_list]
                    properties[property_name.strip()] = {
                        'multi_select': option_dict
                    }
                else:
                    raise SyntaxError('Failed to determine multi-select property name.', 'Cohere API', 'Ensure your multi-select properties are correctly named.')
        else:
            option_dict = []
            for tag in tags_list:
                tag_id = property_options.get(property_name, {}).get(tag)
                if tag_id:
                    option_dict.append({'id': tag_id})
                else:
                    option_dict.append({'name': tag})
            properties[property_name] = {
                'multi_select': option_dict
            }
        return properties

    def notion_api_children(self, content_to_process):
        children = []

        for element in content_to_process:
            if not element:
                continue
            element = element.strip()
            stripped_element = re.sub(r'<\w\w\w>', '', element)

            if element.startswith('<hd1>'):
                block = {
                    'object': 'block',
                    'type': 'heading_1',
                    'heading_1': {
                        'rich_text': [
                            {
                                'type': 'text',
                                'text': {
                                    'content': stripped_element
                                }
                            }
                        ]
                    }
                }
                children.append(block)

            elif element.startswith('<hd2>'):
                block = {
                    'object': 'block',
                    'type': 'heading_2',
                    'heading_2': {
                        'rich_text': [
                            {
                                'type': 'text',
                                'text': {
                                    'content': stripped_element
                                }
                            }
                        ]
                    }
                }
                children.append(block)

            elif element.startswith('<hd3>'):
                block = {
                    'object': 'block',
                    'type': 'heading_3',
                    'heading_3': {
                        'rich_text': [
                            {
                                'type': 'text',
                                'text': {
                                    'content': stripped_element
                                }
                            }
                        ]
                    }
                }
                children.append(block)

            elif element.startswith('<pgr>'):
                element = re.sub(r'eq\(([^)]+)\)', r'<ieq>\1$<pgr>', element)
                element = re.sub(r'url\(([^)]+)\)', r'<url>\1$<pgr>', element)
                element = re.sub(r'cd\(([^)]+)\)', r'<icd>\1$<pgr>', element)
                split_paragraph = element.split('$')

                inline_blocks = []
                for inline in split_paragraph:
                    stripped_inline = re.sub(r'<\w\w\w>\s*', '', inline)
                    if not stripped_inline:
                        continue

                    if inline.startswith('<pgr>'):
                        inline_block = {
                            'type': 'text',
                            'text': {
                                'content': stripped_inline
                            }
                        }
                        inline_blocks.append(inline_block)

                    elif inline.startswith('<ieq>'):
                        inline_block = {
                            'type': 'equation',
                            'equation': {
                                'expression': stripped_inline
                            }
                        }
                        inline_blocks.append(inline_block)

                    elif inline.startswith('<icd>'):
                        inline_block = {
                            'type': 'text',
                            'text': {
                                'content': stripped_inline
                            },
                            "annotations": {
                                "code": True
                            },
                        }
                        inline_blocks.append(inline_block)

                    elif inline.startswith('<url>'):
                        url = stripped_inline
                        if not self.is_website_valid(url):
                            continue
                        if 'http' not in url:
                            url = 'https://' + url
                        inline_block = {
                            'type': 'text',
                            'text': {
                                'content': stripped_inline,
                                'link': {
                                    'url': url
                                }
                            }
                        }
                        inline_blocks.append(inline_block)

                block = {
                    'object': 'block',
                    'type': 'paragraph',
                    'paragraph': {
                        'rich_text': inline_blocks
                    }
                }
                children.append(block)

            elif element.startswith('<cod>'):
                block = {
                    'object': 'block',
                    'type': 'code',
                    'code': {
                        'rich_text': [
                            {
                                'type': 'text',
                                'text': {
                                    'content': stripped_element
                                }
                            }
                        ],
                        'language': 'plain text'
                    }
                }
                children.append(block)

            elif element.startswith('<blp>'):
                block = {
                    'object': 'block',
                    'type': 'bulleted_list_item',
                    'bulleted_list_item': {
                        'rich_text': [
                            {
                                'type': 'text',
                                'text': {
                                    'content': stripped_element
                                }
                            }
                        ]
                    }
                }
                children.append(block)

            elif element.startswith('<nrp>'):
                block = {
                    'object': 'block',
                    'type': 'numbered_list_item',
                    'numbered_list_item': {
                        'rich_text': [
                            {
                                'type': 'text',
                                'text': {
                                    'content': stripped_element
                                }
                            }
                        ]
                    }
                }
                children.append(block)

            elif element.startswith('<beq>'):
                block = {
                    'object': 'block',
                    'type': 'equation',
                    'equation': {
                        'expression': stripped_element
                    }
                }
                children.append(block)

            else:
                # Handle unrecognized markers
                raise SyntaxError(f'Unrecognized element marker in "{element}"', 'Content Processor', 'Check your content formatting.')

        return children

    def process_input(self, metadata_to_process=None, content_to_process=None, title=None, emoji=None):

        if not metadata_to_process and not content_to_process:
            raise InputError('No input was given for properties or content', 'Main Script', 'Provide metadata or content to process.')

        if title:
            self.title = title
        if emoji:
            self.emoji = emoji

        data = self.notion_api_headers(metadata_to_process)
        input_children = content_to_process.split('$')

        # Break the list into batches of 100
        batches = [input_children[i:i + 100] for i in range(0, len(input_children), 100)]

        if batches:
            data['children'] = self.notion_api_children(batches[0])
            page_posted_response, status_code = self.notion_request('https://api.notion.com/v1/pages', 'post', data)
            if page_posted_response is None:
                raise APIError('Failed to create page.', 'Notion API', 'Check your data and API key.')
            page_posted_id = page_posted_response['id']
            print(f"Page created with ID: {page_posted_id}")

            # Append remaining batches
            for batch in batches[1:]:
                append_data = {'children': self.notion_api_children(batch)}
                append_block_response, status_code = self.notion_request(
                    f'https://api.notion.com/v1/blocks/{page_posted_id}/children', 'patch', append_data)
                if append_block_response:
                    print(f"Appended batch to page {page_posted_id}")
                else:
                    raise APIError('Failed to append batch.', 'Notion API', 'Check your data and API key.')

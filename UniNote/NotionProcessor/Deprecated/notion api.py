import sys
import subprocess
import requests
import re
import Levenshtein
import json
import datetime

title = 'Titolo'
emoji = None
notion_api_key = 'NOTION API'
cohere_api_key = 'COHERE API'
database_id = 'DATABASE ID'
metadata_to_process = 'tit(hello), select(Topics:Hello), msel(Tech:monitor,whatever,welcome)'
content_to_process = '<hd1>Introduction to Machine Learning$<pgr>Machine learning (ML) is a subset of artificial intelligence (AI) that focuses on the development of algorithms that can learn from and make predictions on data.$<pgr>ML has become a key technology in a wide range of applications, from recommendation systems to autonomous driving.$<blp>Supervised learning, unsupervised learning, and reinforcement learning are the three main categories of machine learning.$<blp>Supervised learning requires labeled data for training models.$<blp>Unsupervised learning identifies patterns in data without explicit labels.$<blp>Reinforcement learning trains models to make decisions based on feedback from their environment.$<nrp>One of the most well-known supervised learning algorithms is the linear regression model.$<nrp>Support vector machines (SVM) are used for classification and regression tasks.$<nrp>Decision trees are popular because they are easy to interpret and visualize.$<nrp>Random forests, an ensemble method, improve performance by averaging multiple decision trees.$<pgr>Neural networks, particularly deep learning models, have become central to modern machine learning.$<pgr>Deep learning models use multiple layers of neurons to model complex patterns in data.$<blp>The activation function used in a neuron introduces non-linearity, making the model more expressive.$<blp>Common activation functions include ReLU, sigmoid, and tanh.$<blp>Backpropagation is the method used to train neural networks by adjusting the weights.$<nrp>Convolutional neural networks (CNNs) are commonly used in image processing.$<nrp>Recurrent neural networks (RNNs) are used for sequential data like time series and text.$<nrp>Long short-term memory (LSTM) networks are a type of RNN that can handle long-term dependencies.$<nrp>Generative adversarial networks (GANs) consist of two models: a generator and a discriminator.$<pgr>Reinforcement learning (RL) differs from supervised learning because the system learns by interacting with its environment.$<pgr>RL systems are trained using rewards and punishments, encouraging the model to learn optimal behavior.$<blp>AlphaGo, developed by DeepMind, uses reinforcement learning to play the board game Go.$<blp>RL has applications in robotics, gaming, and autonomous systems.$<blp>The Markov decision process (MDP) is a mathematical framework for modeling RL problems.$<nrp>Q-learning is an RL algorithm that learns the quality of actions, helping an agent choose the best action.$<nrp>Deep Q-networks (DQNs) combine Q-learning with deep learning.$<nrp>Policy gradient methods are another approach used in reinforcement learning.$<nrp>Actor-critic methods combine policy gradient and value-based methods in RL.$<pgr>Unsupervised learning is often used for clustering data points based on their similarities.$<pgr>Clustering algorithms group data into clusters where each point is more similar to the points in its cluster than to points in other clusters.$<blp>One of the most common clustering algorithms is K-means clustering.$<blp>Hierarchical clustering builds a tree of clusters by iteratively merging or splitting clusters.$<blp>DBSCAN is a density-based clustering algorithm that groups points based on the density of data.$<nrp>Principal component analysis (PCA) is used to reduce the dimensionality of data.$<nrp>Singular value decomposition (SVD) is another technique used for matrix factorization and dimensionality reduction.$<nrp>Autoencoders are neural networks used for unsupervised learning, typically for data compression.$<nrp>Gaussian mixture models (GMMs) are probabilistic models used for representing normally distributed subpopulations.$<pgr>ML models require significant amounts of data for training and testing.$<pgr>The quality of the data greatly impacts the performance of the model, and data preprocessing is a critical step.$<blp>Data preprocessing steps include normalization, standardization, and handling missing data.$<blp>Feature engineering involves creating new input features to improve model performance.$<blp>Feature selection techniques are used to select the most relevant features from the data.$<nrp>Cross-validation is a technique used to assess the performance of a machine learning model.$<nrp>Hyperparameter tuning involves selecting the best settings for a model\'s parameters.$<nrp>Grid search and random search are common methods for hyperparameter tuning.$<nrp>Bayesian optimization is another approach used for hyperparameter tuning, often yielding better results.$<pgr>In recent years, machine learning has revolutionized fields such as healthcare, finance, and marketing.$<pgr>In healthcare, machine learning is being used for predictive diagnostics and personalized treatment.$<blp>AI-powered diagnostic tools can analyze medical images to identify diseases like cancer.$<blp>Machine learning models are used to predict patient outcomes based on historical data.$<blp>Recommender systems are one of the most widely used applications of machine learning in the consumer space.$<nrp>Amazon and Netflix use recommendation algorithms to suggest products and content.$<nrp>Google uses machine learning to improve search results and personalize user experiences.$<nrp>Social media platforms use ML to recommend posts, friends, and advertisements.$<nrp>Financial institutions use machine learning for credit scoring and fraud detection.$<pgr>Despite its benefits, machine learning presents challenges, such as ensuring fairness and reducing bias in models.$<pgr>Bias in machine learning models can arise from biased training data or model design.$<blp>Efforts are underway to develop explainable AI, which helps provide transparency into how models make decisions.$<blp>AI ethics and fairness are becoming crucial areas of research to ensure responsible AI development.$<blp>Regulatory frameworks are emerging to address ethical concerns related to AI and machine learning.$<nrp>In 2019, the European Union proposed AI ethics guidelines to ensure transparency and accountability.$<nrp>Organizations are adopting responsible AI principles to mitigate bias and ensure fairness.$<nrp>In the future, machine learning will continue to evolve, with more emphasis on ethics, fairness, and accountability.$<hd1>Overview of Data Science$<pgr>Data Science is a multidisciplinary field that uses scientific methods to extract insights from data.$<blp>It involves statistics, data analysis, and machine learning.$<blp>Data scientists use programming languages like Python and R.$<blp>They work with large datasets to find patterns and make predictions.$<nrp>Key tools include Jupyter notebooks and Pandas library.$<nrp>Data visualization is crucial for interpreting results.$<nrp>Common visualization tools are Matplotlib and Seaborn.$<nrp>Data preprocessing steps include cleaning and normalization.$<pgr>Data cleaning removes errors and inconsistencies.$<pgr>Normalization adjusts the data to a standard scale.$<blp>Feature selection improves model performance by using relevant attributes.$<blp>Feature engineering involves creating new features.$<nrp>Supervised learning requires labeled data for training.$<nrp>Unsupervised learning identifies hidden patterns.$<nrp>Reinforcement learning optimizes actions through rewards.$<nrp>Cross-validation assesses model performance.$<nrp>Hyperparameter tuning improves model accuracy.$<pgr>Machine learning models include regression, classification, and clustering.$<pgr>Regression predicts continuous outcomes.$<pgr>Classification assigns data to categories.$<blp>Clustering groups similar data points.$<blp>Common algorithms are K-means and hierarchical clustering.$<nrp>Principal Component Analysis (PCA) reduces dimensionality.$<nrp>Dimensionality reduction helps in visualizing high-dimensional data.$<nrp>Deep learning uses neural networks with many layers.$<nrp>Convolutional Neural Networks (CNNs) are used for image tasks.$<nrp>Recurrent Neural Networks (RNNs) handle sequential data.$<pgr>Data Science applications include healthcare, finance, and marketing.$<pgr>In healthcare, it helps in predictive diagnostics.$<pgr>In finance, it detects fraud and manages risk.$<blp>In marketing, it personalizes recommendations.$<blp>AI and ML are integral parts of modern data science.$<nrp>AI models include decision trees and random forests.$<nrp>Random forests improve decision trees by combining multiple trees.$<nrp>Support Vector Machines (SVM) are used for classification tasks.$<nrp>Gradient Boosting Machines (GBM) are another popular method.$<pgr>Data Science requires continuous learning and adaptation.$<pgr>The field evolves with new tools and techniques.$<blp>Ethics in data science involves privacy and bias.$<blp>Responsible data handling is crucial for trust.$<nrp>Data anonymization protects user identities.$<nrp>Bias mitigation ensures fairness in models.$<nrp>Explainable AI helps in understanding model decisions.$<pgr>Future trends include increased automation and AI integration.$<pgr>Data Science will continue to influence various industries.$<blp>Collaboration between data scientists and domain experts is key.$<blp>Effective communication of results is essential for decision-making.$<blp>Machine learning operations (MLOps) streamline deployment.$<nrp>MLOps practices ensure consistent model performance.$<nrp>Model monitoring tracks accuracy over time.$<nrp>Model retraining keeps the model updated.$<nrp>Cloud platforms facilitate scalable data science solutions.$<pgr>Big data technologies enable handling of large volumes of data.$<pgr>Hadoop and Spark are popular big data frameworks.$<blp>Data privacy regulations, like GDPR, impact data practices.$<blp>Compliance with regulations is mandatory for data scientists.$<nrp>Data Science skills are in high demand across various sectors.$<nrp>Continuous learning is essential to stay current in the field.$<pgr>Networking with professionals helps in career development.$<pgr>Data Science offers opportunities for innovation and impact.$'
error_dict = {}

def log_error(type,location,troubleshoot):
    global error_dict
    error_number = len(error_dict) + 1
    error_dict[error_number] = {'type': type, 'location': location, 'troubleshoot': troubleshoot}
    print('Program fail at line ' + sys._getframe().f_lineno)

    with open('error_log.json', 'w') as file:
        file.write(json.dump(error_dict, indent=4))

if not metadata_to_process and not content_to_process:
    log_error('Input Error', 'Main Script', 'No input was given for properties or content')
    sys.exit()

# Set functions for requests
def notion_request(url, method, body=None):
    try:
        headers = {'Authorization':f'Bearer {notion_api_key}', 'Notion-Version':'2022-06-28'}
        if method.lower() in ["post", "patch"]:
            headers['Content-Type'] = "application/json"
            request_syntax = getattr(requests, method.lower(), None)
            response = request_syntax(url=url, headers=headers, json=body)

            return response.json(), response.status_code
        elif method.lower() in ['get']:
            request_syntax = getattr(requests, method.lower(), None)
            response = request_syntax(url=url, headers=headers)
        
        if response.status_code == 200:
            return response.json(), response.status_code
        else:
            log_error(response.reason, 'Local Device or Notion API', 'Try checking your internet connection')
            return None
    except ConnectionError as e:
        log_error('Connection Error','Local Device or Notion API','Try checking your internet connection')
        return None
    
def cohere_request(prompt):
        try:
            url = "https://api.cohere.com/v1/chat"
            body = {'message': prompt}
            headers = {'Authorization':f'Bearer {cohere_api_key}', 'Content-Type':'application/json'}
            output = requests.post(url=url, headers=headers, json=body)
            response = output.json()['text']
            if status_code == 200:
                return response, output.status_code
            else:
                log_error(output.reason, 'Local Device or Cohere API', 'Try checking your internet connection')
                return None
        except ConnectionError as e:
            log_error('Connection Error','Local Device or Cohere API','Try checking your internet connection')
            return None

def is_website_valid(url):
    try:
        # Make a request to the website
        response = requests.get(url, timeout=5)
        
        # Check if the status code is 200 (OK)
        if response.status_code == 200:
            return True
        else:
            return False
    except requests.exceptions.RequestException:
        # If any request exception occurs, the website is not valid
        return False

def notion_api_headers(content_to_process):
    global title
    global emoji
    def spellmargin(input_word, word_list):
        word_length = len(input_word)
        if word_length < 4:
            threshold = 1
        elif 4 <= word_length <= 8:
            threshold = 3
        else:
            threshold = 4
        
        # Initialize variables to keep track of the best match
        best_match = None
        best_distance = float('inf')
        
        for word in word_list:
            distance = Levenshtein.distance(input_word, word)
            if distance <= threshold and distance < best_distance:
                best_match = word
                best_distance = distance
        
        return best_match

    today = datetime.datetime.now().strftime('%Y-%m-%d')

    # GET properties infos
    properties_dict, status_code = notion_request(f'https://api.notion.com/v1/databases/{database_id}', 'get')['properties']
    all_property_names = list(properties_dict.keys())
    # Counts how many times there is a specific "type"
    type_lists = {t: [key for key in all_property_names if properties_dict[key]['type'] == t] 
        for t in {properties_dict[key]['type'] for key in all_property_names}}
    property_types = {key: value['type'] for key, value in properties_dict.items()}
    property_markers = {'title':'<tit>','relation':'<pit>','date':'<dat>','checkbox':'<chk>','select':'<sel>','multi_select':'<msl>'}

    property_options = {
        key: {option['name']: option['id'] for option in property_info[property_info['type']]['options']}
        for key, property_info in properties_dict.items() 
        if property_info['type'] in ['select', 'multi_select']
    }

    if not content_to_process:
        headers['parent'] = {
        'database_id': database_id
    }
        properties = {}
        properties[type_lists['title'][0]] = {'title': [
                        {
                            'text': {
                                'content': 'Untitled' + today
                            }
                        }
                    ]
                }
        headers['properties'] = properties

        return headers


    # Start parsing headers
    input_headers = content_to_process.replace("\n","")
    matching = r"\s*\(\s*([^)]+)\s*\)\s*"
    patterns = [r"(title|tit|name)" + matching,r"(parentitem|parent Item|pit|pitem|parent)" + matching, r"(date|dat|data)" + matching, r"(checkbox|check|chk)" + matching, r"(multiselect|multi-select|msel|multisel|mselect)" + matching, r"(select|sel)" + matching, r'(ico|icon|emoji|emoticon)' + matching, matching]
    replacements = [r"<tit>\2", r"<pit>\2", r"<dat>\2", r"<chk>\2", r"<msl>\2", r"<sel>\2", r"<ico>\2", r"<und>\1"]
    # List comprehension to apply all patterns and replacements
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
        log_error('Syntax Error', 'Headers and metadata processer', 'Wrong headers syntax. Probably missing some \"()\"')
    
    properties = {}
    headers = {}
    for header in formatted_headers_list:

        # Check if type property actually exists in the database, if not ignore iteration
        if header.startswith('<chk>'):
            if type_lists['checkbox']: pass
            else:
                print('No Checkbox Property Found')
                continue
        if header.startswith('<dat>'):
            if type_lists['date']: pass
            else:
                print('No Date Property Found')
                continue
        if header.startswith('<sel>'):
            if type_lists['select']: pass
            else:
                print('No Select Property Found')
                continue
        if header.startswith('<msl>'):
            if type_lists['multi_select']: pass
            else:
                print('No Multi-Select Property Found')
                continue
        # Avoid properties with multiple arguments that do not allow multiple arguments
        if not header.startswith('<msl>'):
            if ',' in header:
                generic_marker = re.search(r'<\w+>', header)
                print(f'Only one argument allowed for {generic_marker.group()} elements')
                continue
        
        # Defining property name and option name based on if they're given or not.
        stripped_header = re.sub(r'<\w\w\w>', '', header)
        if ':' in header:
            property_name, option_name = stripped_header.split(":")
            property_name = spellmargin(property_name, all_property_names)
            if not property_name:
                print('Property Name not found for...')
                log_error('Properties Location','Headers and metadata processer',f'Wrong property was inserted for {header}')
        else:
            property_name = None
            option_name = stripped_header
        

        # Replacing Undefined metadata
        if header.startswith("<und>"):
            if ':' in header:
                marker = property_markers[property_types[property_name]]
                header = marker
            else:
                print(f'Missing Property Name for value \"{option_name}\"')


        # Starting marker and property parsing
        if header.startswith("<tit>"):
            if not title:
                title = option_name


        elif header.startswith('<pit>'):
            if properties_dict['Parent Item']:
                search_query = {
                    'filter': {
                        'property': type_lists['title'][0],
                        'title': {
                            'equals': option_name
                        }
                    }
                }


                parent_id, status_code = notion_request(f'https://api.notion.com/v1/databases/{database_id}/query', 'get')['results']['id']
                if parent_id:
                    properties[type_lists['relation'][0]] = {
                        'relation': [
                            {
                                'id': parent_id
                            }
                        ]
                    }
                

        elif header.startswith('<ico>'):
            if not emoji:
                emoji = option_name


        elif header.startswith('<chk>'):
            if property_name:
                checkbox_answers = {'yes': True,'no': False,'true': True,'false': False}
                if checkbox_answers[option_name.lower()]:
                    properties[property_name] = {
                        'checkbox': checkbox_answers[option_name.lower()]
                    }
                else:
                    print('Checkbox value is invalid')
            else:
                print('No Property name specified for Checkbox Property')


        elif header.startswith('<dat>'):
            if property_name:
                prompt = f'''Input: {option_name}
                A start date, start time, end date, and end time might be specified in the input.
                Watch for prepositions that indicate the beginning (start) and the transition to the end.
                Separate these two parts with a \"$\".
                The format should thus be: \"{{start bit}}${{end bit}}\".
                Either the start or end date might be missing, add it anyway as an empty value: \"{{startbit}}$\" (only start bit), \"${{end bit}}\" (only end bit).
                Remove prepositions. Output must only be formatted string.'''

                start = cohere_request(prompt).split('$')[0] if cohere_request(prompt).split('$')[0] else None
                end = cohere_request(prompt).split('$')[1] if cohere_request(prompt).split('$')[1] else None

                if start:
                    prompt = f'''Input string: \"{start}\"
                    Format input string into ISO 8601.
                    If input is sole two digit number, treat it as day of the month.
                    IF NO TIME IS SPECIFIED, DO NOT ADD TIME. Only include the date. Ignore the time section completely if it's not provided.
                    IF TIME IS INCLUDED, FORMAT IT USING THIS TEMPLATE (THH:MM) AND ADD +02:00 TIMEZONE OFFSET.
                    For relative time terms, refer to \"{today}\".\nOutput must only be the formatted string.'''
                else:
                    start = today

                    start = cohere_request(prompt)
                if end:
                    prompt = f'''Input string: \"{end}\"
                    Format input string into ISO 8601.
                    If input is sole two digit number, treat it as day of the month.
                    IF NO TIME IS SPECIFIED, DO NOT ADD TIME. Only include the date. Ignore the time section completely if it's not provided.
                    IF TIME IS INCLUDED, FORMAT IT USING THIS TEMPLATE (THH:MM) AND ADD +02:00 TIMEZONE OFFSET.
                    For relative time terms, refer to \"{today}\".\nOutput must only be the formatted string.'''

                    end = cohere_request(prompt)

                if 'T' in start and not 'T' in end or 'T' in end and not 'T' in start:
                    if start:
                        if not 'T' in start:
                            start += 'T00:00+02:00'
                    if end:
                        if not 'T' in end:
                            end += 'T00:00+02:00'

                properties[property_name] = {
                    'date': {
                        'start': start,
                        'end': end
                    }
                }
            
            else:
                print('Date Property Name not specified')

        elif header.startswith('<sel>'):
            if not property_name:
                    for property in type_lists['select']:
                        if property_options.get(property, {}).get(option_name,{}):
                            match_property = property
                            option_id = property_options[property][option_name]
                            properties[match_property] = {
                                'select': {
                                    'id': option_id
                                }
                            }
                    if not match_property:
                        property_name = cohere_request(f'To which of these property names \"{type_lists['select']}\" do you think the option value \"{option_name}\" belongs to? Output strictly only the chosen property value.')
                        properties[property_name] = {
                            'select': {
                                'name': option_name
                            }
                        }
            else:
                if property_options.get(property_name, {}).get(option_name,{}):
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

        #'multi_select': {'options':[{id,name},{id,name}]}

        elif header.startswith('<msl>'):
            tags_list = option_name.split(',')
            if not property_name:
                option_dict = []
                for property in type_lists['multi_select']:
                    if any(tag in property_options[property].keys() for tag in tags_list):
                        match_property = property
                        for tag in tags_list:
                            tag_id = property_options[match_property][tag]
                            tag_json = {
                                'id': tag_id
                            }
                            option_dict.append(tag_json)
                        properties[match_property] = {
                            'multi_select':  option_dict
                            }
                    
                    if not match_property:
                        property_name = cohere_request(f'To which of these property names \"{type_lists['multi_select']}\" do you think tags or tag \"{option_name}\" belong to? Output strictly only the chosen property value.')
                        for tag in tags_list:
                            tag_json = {
                                'name': tag
                            }
                            option_dict.append(tag_json)
                        properties[property_name] = {
                            'multi_select': option_dict
                            }

            else:
                option_dict = []
                for tag in tags_list:
                    if property_options.get(property_name, {}).get(tag,{}):
                        tag_id = property_options[property_name][tag]
                        tag_json = {
                            'id': tag_id
                        }
                        option_dict.append(tag_json)
                    else:
                        tag_json = {
                            'name': tag
                        }
                        option_dict.append(tag_json)

                properties[property_name] = {
                    'multi_select': option_dict
                    }

    headers['parent'] = {
        'database_id': database_id
    }
    if title:
        properties[type_lists['title'][0]] = {'title': [
                        {
                            'text': {
                                'content': title
                            }
                        }
                    ]
                }
    else:
        properties[type_lists['title'][0]] = {'title': [
                        {
                            'text': {
                                'content': 'Untitled' + today
                            }
                        }
                    ]
                }
    
    if emoji:
        if any(x in emoji for x in 'abcdefghijklmnopqrstuvwxyz'):
            with open('emoji.json','r', encoding='utf-8') as file:
                            emoji_list = json.load(file)
                        
            if emoji in emoji_list:
                emoji = emoji_list[emoji]['emoji']
            else: emoji = None
        
        headers['icon'] = {
                        'emoji': emoji
                    }
        
    headers['properties'] = properties

    return headers
    
def notion_api_children(content_to_process):
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

        if element.startswith('<hd2>'):
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

        if element.startswith('<hd3>'):
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

        if element.startswith('<pgr>'):
            element = re.sub(r'eq\(([^)]+)\)', r'<ieq>\\1\$<pgr>', element)
            element = re.sub(r'url\(([^)]+)\)', r'<url>\\1\$<pgr>', element)
            element = re.sub(r'cd\(([^)]+)\)', r'<icd>\\1\$<pgr>', element)
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

                if inline.startswith('<ieq>'):
                    inline_block = {
                        'type': 'equation',
                        'equation': {
                            'expression': stripped_inline
                        }
                    }
                    inline_blocks.append(inline_block)

                if inline.startswith('<icd>'):
                    inline_block = {
                        'type': 'text',
                        'text': {
                            'content': stripped_inline
                        },
                        "annotations": {
                            "bold": False,
                            "italic": False,
                            "strikethrough": False,
                            "underline": False,
                            "code": True,
                            "color": "default"
                        },
                    }
                    inline_blocks.append(inline_block)

                if inline.startswith('<url>'):
                    if is_website_valid(stripped_inline):
                        if 'www.' not in stripped_inline:
                            url = 'www.' + stripped_inline
                        else: url = stripped_inline
                        if 'https://' not in url:
                            url = 'https://' + url
                        
                    inline_block = {
                        'type': 'text',
                        'text': {
                            'content': stripped_inline,
                            'link': {
                                'url': url
                            }
                        },
                        "annotations": {
                            "bold": False,
                            "italic": False,
                            "strikethrough": False,
                            "underline": False,
                            "code": False,
                            "color": "default"
                        },
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

        if element.startswith('<cod>'):
            block = {
                'object': 'block',
                'type': 'code',
                'code': {
                    'rich_text': [
                        {
                            'type': 'text',
                            'conten': stripped_element
                        }
                    ],
                    'language': 'c'
                }
            }
            children.append(block)

        if element.startswith('<blp>'):
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

        if element.startswith('<nrp>'):
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

        if element.startswith('<beq>'):
            block = {
                'object': 'block',
                'type': 'equation',
                'equation': {
                    'expression': stripped_element
                }
            }

            children.append(block)

    return children

data = notion_api_headers(metadata_to_process)
input_children = content_to_process.split('$')

# Step 2: Break the list into batches of 100
batches = [input_children[i:i + 100] for i in range(0, len(input_children), 100)]

# Step 3: Feed the first batch to one function
if batches:
    data['children'] = notion_api_children(batches[0])
    page_posted_response, status_code = notion_request('https://api.notion.com/v1/pages','post', data)

    page_posted_id = page_posted_response['id']
    print(page_posted_id)
    
    # Feed the remaining batches to another function
    batches = batches[1:]
    for batch in batches:
        data = {}
        data['children'] = notion_api_children(batch)
        append_block_response, status_code = notion_request(f'https://api.notion.com/v1/blocks/{page_posted_id}/children','patch', data)
        print(append_block_response)


# output = subprocess.run([python 3, "scriptname", "input"],capture_output=True,text=True)
# output.stdout
from flask import Flask, request, jsonify, abort, Blueprint
import subprocess
import os
import sys
import json
import logging
from functools import wraps
from werkzeug.utils import secure_filename

app = Flask(__name__)

# ==========================
# Configuration Parameters
# ==========================

# API Keys (Replace with your actual API keys)
API_KEYS = {
    'public': 'public_api_key_here',     # Replace with your actual public API key
    'private': 'private_api_key_here'    # Replace with your actual private API key
}

# Unified Script Mapping with Access Levels
SCRIPT_MAPPING = {
    'script1': {'filename': 'script1.py', 'access': 'public'},
    'script3': {'filename': 'script3.py', 'access': 'private'},
    # Add more scripts as needed
}

# Temporary Directory for File Uploads
TEMP_DIR = os.path.join(os.getcwd(), 'temp_uploads')

# Ensure the temporary directory exists
os.makedirs(TEMP_DIR, exist_ok=True)

# Logging Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Maximum allowed file size (e.g., 50 MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB

# Allowed file extensions (modify as needed)
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'txt'}

# ==========================
# Helper Functions
# ==========================

def allowed_file(filename):
    """Check if the file has an allowed extension."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def check_api_key(required_access='public'):
    """
    Decorator to check API key for incoming requests.
    - 'public': Accessible by both public and private API keys.
    - 'private': Accessible only by the private API key.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            api_key = request.headers.get('x-api-key')
            if not api_key:
                logger.warning("Missing API key.")
                return jsonify({
                    'status': 'error',
                    'message': 'Missing API key.',
                    'data': None,
                    'errors': ['Missing API key.']
                }), 403

            if required_access == 'public':
                if api_key not in [API_KEYS['public'], API_KEYS['private']]:
                    logger.warning("Invalid public API key.")
                    return jsonify({
                        'status': 'error',
                        'message': 'Invalid API key.',
                        'data': None,
                        'errors': ['Invalid API key.']
                    }), 403
            elif required_access == 'private':
                if api_key != API_KEYS['private']:
                    logger.warning("Invalid private API key.")
                    return jsonify({
                        'status': 'error',
                        'message': 'Invalid API key for private access.',
                        'data': None,
                        'errors': ['Invalid API key for private access.']
                    }), 403
            else:
                logger.error(f"Unknown API key access level: {required_access}")
                return jsonify({
                    'status': 'error',
                    'message': 'Server configuration error.',
                    'data': None,
                    'errors': ['Server configuration error.']
                }), 500

            return f(*args, **kwargs)
        return decorated_function
    return decorator

def run_script(script_name, input_data):
    """Run a Python script as a subprocess with JSON input."""
    script_info = SCRIPT_MAPPING.get(script_name)
    if not script_info:
        logger.error(f"Script '{script_name}' not found in SCRIPT_MAPPING.")
        return {
            'status': 'error',
            'message': f"Script '{script_name}' not found.",
            'data': None,
            'errors': ['Invalid script name.']
        }, 1

    script_path = os.path.join(os.getcwd(), script_info['filename'])
    if not os.path.exists(script_path):
        logger.error(f"Script file '{script_path}' does not exist.")
        return {
            'status': 'error',
            'message': f"Script file '{script_info['filename']}' does not exist.",
            'data': None,
            'errors': ['Script file not found.']
        }, 1

    try:
        result = subprocess.run(
            ['python3', script_path],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=300  # Set a timeout as needed
        )

        if result.returncode != 0:
            logger.error(f"Script {script_name} exited with code {result.returncode}.")
            logger.error(f"Stderr: {result.stderr}")
            return {
                'status': 'error',
                'message': f"Script '{script_name}' failed with return code {result.returncode}.",
                'data': None,
                'errors': [result.stderr.strip()]
            }, result.returncode

        if result.stdout:
            try:
                response = json.loads(result.stdout)
                return response, result.returncode
            except json.JSONDecodeError:
                logger.error("Failed to parse JSON output from script.")
                return {
                    'status': 'error',
                    'message': 'Invalid JSON output from script.',
                    'data': None,
                    'errors': ['Invalid JSON output from script.']
                }, 1
        else:
            logger.error("No output received from script.")
            return {
                'status': 'error',
                'message': 'No output received from script.',
                'data': None,
                'errors': ['No output received from script.']
            }, 1

    except subprocess.TimeoutExpired:
        logger.error(f"Script {script_name} timed out.")
        return {
            'status': 'error',
            'message': f"Script '{script_name}' timed out.",
            'data': None,
            'errors': [f"Script '{script_name}' timed out."]
        }, 1
    except Exception as e:
        logger.error(f"Exception occurred while running script '{script_name}': {e}")
        return {
            'status': 'error',
            'message': f"Exception occurred while running script '{script_name}': {e}",
            'data': None,
            'errors': [str(e)]
        }, 1

def save_uploaded_files(files):
    """Save uploaded files to the temporary directory."""
    saved_file_paths = []
    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(TEMP_DIR, filename)
            file.save(file_path)
            saved_file_paths.append(file_path)
            logger.info(f"Saved file '{filename}' to '{file_path}'.")
        else:
            logger.warning(f"Disallowed file type or empty filename: '{file.filename}'")
    return saved_file_paths

def cleanup_files(file_paths):
    """Remove temporary files and directories."""
    for path in file_paths:
        try:
            os.remove(path)
            logger.info(f"Removed temporary file: '{path}'")
        except Exception as e:
            logger.error(f"Failed to remove temporary file '{path}': {e}")

# ==========================
# Blueprint Definitions
# ==========================

public_bp = Blueprint('public', __name__)
private_bp = Blueprint('private', __name__)

@public_bp.route('/<script_name>', methods=['POST'])
@check_api_key(required_access='public')
def handle_public_scripts(script_name):
    """
    Handle public script execution.
    URL Pattern: /public/<script_name>
    Example: /public/script1
    """
    script_info = SCRIPT_MAPPING.get(script_name)
    if not script_info or script_info['access'] != 'public':
        logger.warning(f"Public script '{script_name}' not found or access restricted.")
        return jsonify({
            'status': 'error',
            'message': f"Script '{script_name}' not found or not accessible via public routes.",
            'data': None,
            'errors': ['Invalid script name or access level.']
        }), 404

    # Collect input data
    input_data = {}

    # Handle JSON payload
    if request.is_json:
        input_data.update(request.get_json())

    # Handle form data
    form_data = request.form.to_dict()
    if form_data:
        input_data.update(form_data)

    # Handle files
    files = request.files.getlist('files') or request.files.getlist('file')
    if files:
        saved_files = save_uploaded_files(files)
        input_data['file_paths'] = saved_files
    else:
        input_data['file_paths'] = []

    # Execute the script
    response, return_code = run_script(script_name, input_data)

    # Clean up temporary files
    if input_data.get('file_paths'):
        cleanup_files(input_data['file_paths'])

    # Determine appropriate HTTP status code
    if response.get('status') == 'success':
        return jsonify(response), 200
    else:
        # Determine if it's a client or server error
        if return_code == 1:
            return jsonify(response), 400
        else:
            return jsonify(response), 500

@private_bp.route('/<script_name>', methods=['POST'])
@check_api_key(required_access='private')
def handle_private_scripts(script_name):
    """
    Handle private script execution.
    URL Pattern: /private/<script_name>
    Example: /private/script3
    Only accessible with the private API key.
    """
    script_info = SCRIPT_MAPPING.get(script_name)
    if not script_info or script_info['access'] != 'private':
        logger.warning(f"Private script '{script_name}' not found or access restricted.")
        return jsonify({
            'status': 'error',
            'message': f"Script '{script_name}' not found or not accessible via private routes.",
            'data': None,
            'errors': ['Invalid script name or access level.']
        }), 404

    # Collect input data
    input_data = {}

    # Handle JSON payload
    if request.is_json:
        input_data.update(request.get_json())

    # Handle form data
    form_data = request.form.to_dict()
    if form_data:
        input_data.update(form_data)

    # Handle files
    files = request.files.getlist('files') or request.files.getlist('file')
    if files:
        saved_files = save_uploaded_files(files)
        input_data['file_paths'] = saved_files
    else:
        input_data['file_paths'] = []

    # Execute the script
    response, return_code = run_script(script_name, input_data)

    # Clean up temporary files
    if input_data.get('file_paths'):
        cleanup_files(input_data['file_paths'])

    # Determine appropriate HTTP status code
    if response.get('status') == 'success':
        return jsonify(response), 200
    else:
        # Determine if it's a client or server error
        if return_code == 1:
            return jsonify(response), 400
        else:
            return jsonify(response), 500

# Register the blueprints
app.register_blueprint(public_bp, url_prefix='/public')
app.register_blueprint(private_bp, url_prefix='/private')

# ==========================
# Test Route
# ==========================

@app.route('/test', methods=['GET'])
def test():
    """A simple test route to verify the server is working."""
    logger.info("Test route accessed.")
    return jsonify({
        'status': 'success',
        'message': 'Server is up and running.',
        'data': None,
        'errors': []
    }), 200

# ==========================
# Error Handlers
# ==========================

@app.errorhandler(400)
def bad_request(error):
    return jsonify({
        'status': 'error',
        'message': 'Bad Request.',
        'data': None,
        'errors': [str(error)]
    }), 400

@app.errorhandler(403)
def forbidden(error):
    return jsonify({
        'status': 'error',
        'message': 'Forbidden.',
        'data': None,
        'errors': [str(error)]
    }), 403

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'status': 'error',
        'message': 'Not Found.',
        'data': None,
        'errors': [str(error)]
    }), 404

@app.errorhandler(413)
def payload_too_large(error):
    return jsonify({
        'status': 'error',
        'message': 'Payload Too Large.',
        'data': None,
        'errors': [str(error)]
    }), 413

@app.errorhandler(500)
def internal_server_error(error):
    return jsonify({
        'status': 'error',
        'message': 'Internal Server Error.',
        'data': None,
        'errors': [str(error)]
    }), 500

# ==========================
# Main Entry Point
# ==========================

if __name__ == '__main__':
    # Ensure the temporary directory exists
    os.makedirs(TEMP_DIR, exist_ok=True)

    # Run the Flask app
    app.run(host='0.0.0.0', port=9000)

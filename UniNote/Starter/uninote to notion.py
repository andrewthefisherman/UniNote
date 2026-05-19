import os
import subprocess

def run_script(script_name, input_data):
    script_path = os.path.join(os.getcwd(), script_name)
    result = subprocess.run(
        ['python3', script_path, input_data],
        capture_output=True,
        text=True
    )
    return result.stdout if result.returncode == 0 else result.stderr


import re

# File containing the start_id and end_id
SCRIPT_FILE = "get_urls.py"

def increment_ids_in_script():
    """Increment start_id and end_id in the script file."""
    with open(SCRIPT_FILE, "r") as file:
        lines = file.readlines()
    
    # Regular expressions to match start_id and end_id
    start_id_pattern = r"(start_id\s*=\s*)(\d+)"
    end_id_pattern = r"(end_id\s*=\s*)(\d+)"

    updated_lines = []
    for line in lines:
        # Match and increment start_id
        if re.search(start_id_pattern, line):
            match = re.search(start_id_pattern, line)
            current_start_id = int(match.group(2))
            updated_start_id = current_start_id + 1000
            line = re.sub(start_id_pattern, f"\\1{updated_start_id}", line)
            print(f"Updated start_id: {current_start_id} -> {updated_start_id}")
        
        # Match and increment end_id
        elif re.search(end_id_pattern, line):
            match = re.search(end_id_pattern, line)
            current_end_id = int(match.group(2))
            updated_end_id = current_end_id + 1000
            line = re.sub(end_id_pattern, f"\\1{updated_end_id}", line)
            print(f"Updated end_id: {current_end_id} -> {updated_end_id}")
        
        updated_lines.append(line)

    # Write the updated lines back to the script file
    with open(SCRIPT_FILE, "w") as file:
        file.writelines(updated_lines)

if __name__ == "__main__":
    increment_ids_in_script()
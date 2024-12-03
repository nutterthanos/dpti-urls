import re

# File containing the start_id and end_id
SCRIPT_FILE = "get_urls.py"

# Amount to increment the IDs
INCREMENT_AMOUNT = 1000

def increment_ids_in_script():
    """Increment start_id and end_id in the script file."""
    start_id_pattern = r"(main\(\s*)(\d+)(,\s*\d+\))"
    end_id_pattern = r"(main\(\s*\d+,\s*)(\d+)(\))"

    with open(SCRIPT_FILE, "r") as file:
        content = file.read()

    # Match and increment start_id
    start_match = re.search(start_id_pattern, content)
    if start_match:
        current_start_id = int(start_match.group(2))
        updated_start_id = current_start_id + INCREMENT_AMOUNT
        content = re.sub(
            start_id_pattern,
            rf"\1{updated_start_id}\3",
            content,
        )
        print(f"Updated start_id: {current_start_id} -> {updated_start_id}")

    # Match and increment end_id
    end_match = re.search(end_id_pattern, content)
    if end_match:
        current_end_id = int(end_match.group(2))
        updated_end_id = current_end_id + INCREMENT_AMOUNT
        content = re.sub(
            end_id_pattern,
            rf"\1{updated_end_id}\3",
            content,
        )
        print(f"Updated end_id: {current_end_id} -> {updated_end_id}")

    # Write the updated content back to the script file
    with open(SCRIPT_FILE, "w") as file:
        file.write(content)

if __name__ == "__main__":
    increment_ids_in_script()

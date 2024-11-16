import aiohttp
import asyncio
import os

# Constants for request limits and delays
MAX_CONCURRENT_REQUESTS_BASE = 100
MAX_RETRIES = 1000
RETRY_DELAY = 2
FALLBACK_RETRY_DELAY = 10
FALLBACK_REQUEST_DELAY = 2

existing_entries = {}
fallback_tasks = []


def clean_extension(extension):
    """Clean trailing characters like '; from file extensions."""
    return extension.replace(';', '').replace('"', '').strip()


def load_existing_data():
    """Load existing entries from files into memory, remove duplicates, and update in place."""
    global existing_entries
    for filename in os.listdir():
        if filename.startswith("urls_with_") and filename.endswith(".txt"):
            ext = filename.split("_with_")[-1].replace(".txt", "")
            unique_entries = set()
            updated_lines = []
            with open(filename, "r") as f:
                for line in f:
                    line = line.strip()
                    if line not in unique_entries:
                        unique_entries.add(line)
                        updated_lines.append(line)
                    else:
                        print(f"Duplicate removed: {line}")
            # Update file with deduplicated content
            with open(filename, "w") as f:
                for line in updated_lines:
                    f.write(f"{line}\n")
            existing_entries[ext] = unique_entries
            print(f"Loaded {len(unique_entries)} unique entries from '{filename}'")

    # Load redirects
    existing_entries["redirects"] = set()
    if os.path.exists("redirects.txt"):
        redirects_unique = set()
        updated_redirects = []
        with open("redirects.txt", "r") as f:
            for line in f:
                line = line.strip()
                if line not in redirects_unique:
                    redirects_unique.add(line)
                    updated_redirects.append(line)
                else:
                    print(f"Duplicate redirect removed: {line}")
        # Update redirects file
        with open("redirects.txt", "w") as f:
            for line in updated_redirects:
                f.write(f"{line}\n")
        existing_entries["redirects"] = redirects_unique
        print(f"Loaded {len(redirects_unique)} unique redirects from 'redirects.txt'")


def entry_exists(entry, category):
    """Check if an entry already exists in the in-memory existing_entries."""
    return entry in existing_entries.get(category, set())


async def fetch_non_fallback(session, base_url, fallback_url, id, semaphore_base, headers):
    """Fetch non-fallback requests and schedule fallback if needed."""
    async with semaphore_base:
        try:
            async with session.head(base_url.format(id=id), headers=headers, allow_redirects=False) as response:
                print(f"ID {id}: HTTP {response.status} (Base URL)")
                content_type = response.headers.get("Content-Type", "")
                content_disp = response.headers.get("Content-Disposition", "")

                # Process successful responses
                if response.status == 200:
                    if content_disp:
                        filename = content_disp.split("filename=")[-1].strip('\"')
                        extension = clean_extension(filename.split(".")[-1]) if "." in filename else "unknown"
                        entry = f"{base_url.format(id=id)} - {filename}"
                        file_name = f"urls_with_{extension}.txt"

                        # Check and append entry if it's new
                        if not entry_exists(entry, extension):
                            with open(file_name, "a") as f:
                                f.write(f"{entry}\n")
                            print(f"ID {id}: Added filename '{filename}' with extension '{extension}'")
                            existing_entries.setdefault(extension, set()).add(entry)
                        else:
                            print(f"ID {id}: Entry already exists, skipping.")
                    elif "text/html" in content_type:
                        html_url = base_url.format(id=id)
                        html_file = "urls_with_html.txt"
                        if not entry_exists(html_url, "html"):
                            with open(html_file, "a") as f:
                                f.write(f"{html_url}\n")
                            print(f"ID {id}: HTML content detected, added to HTML list")
                            existing_entries.setdefault("html", set()).add(html_url)
                        else:
                            print(f"ID {id}: HTML entry already exists, skipping.")
                elif response.status == 404:
                    print(f"ID {id}: Scheduling fallback request.")
                    fallback_tasks.append(id)

        except Exception as e:
            print(f"ID {id}: Unexpected error '{str(e)}' - skipping.")


async def fetch_fallback(session, fallback_url, id):
    """Process fallback requests with retry logic and per-request sleep."""
    retries = 0
    while retries < MAX_RETRIES:
        try:
            async with session.head(fallback_url.format(id=id), allow_redirects=False) as response:
                print(f"ID {id}: HTTP {response.status} (Fallback URL, Attempt {retries + 1})")
                content_type = response.headers.get("Content-Type", "")
                content_disp = response.headers.get("Content-Disposition", "")

                # Process successful fallback responses
                if response.status == 200:
                    if content_disp:
                        filename = content_disp.split("filename=")[-1].strip('\"')
                        extension = clean_extension(filename.split(".")[-1]) if "." in filename else "unknown"
                        entry = f"{fallback_url.format(id=id)} - {filename}"
                        file_name = f"urls_with_{extension}.txt"

                        # Check and append entry if it's new
                        if not entry_exists(entry, extension):
                            with open(file_name, "a") as f:
                                f.write(f"{entry}\n")
                            print(f"ID {id}: Added filename '{filename}' with extension '{extension}'")
                            existing_entries.setdefault(extension, set()).add(entry)
                        else:
                            print(f"ID {id}: Fallback entry already exists, skipping.")
                    elif "text/html" in content_type:
                        html_url = fallback_url.format(id=id)
                        html_file = "urls_with_html.txt"
                        if not entry_exists(html_url, "html"):
                            with open(html_file, "a") as f:
                                f.write(f"{html_url}\n")
                            print(f"ID {id}: HTML content detected, added to HTML list")
                            existing_entries.setdefault("html", set()).add(html_url)
                        else:
                            print(f"ID {id}: Fallback HTML entry already exists, skipping.")
                    return  # Exit loop on successful response

                elif response.status == 429:
                    print(f"ID {id}: Rate limited. Pausing for {FALLBACK_RETRY_DELAY} seconds...")
                    await asyncio.sleep(FALLBACK_RETRY_DELAY)
                    retries += 1
                    continue

                else:
                    print(f"ID {id}: Unexpected HTTP {response.status}.")
                    return

        except Exception as e:
            print(f"ID {id}: Error '{str(e)}' - Retrying ({retries + 1}/{MAX_RETRIES})")
            retries += 1
            await asyncio.sleep(FALLBACK_RETRY_DELAY)

    print(f"ID {id}: Failed after {MAX_RETRIES} retries.")


async def main(start_id, end_id):
    load_existing_data()  # Deduplicate and load existing data
    base_url = "https://dpti-web01.syd1.squiz.cloud/?a={id}"
    fallback_url = "https://www.adelaidemetro.com.au/?a={id}"
    headers = {"Host": "www.adelaidemetro.com.au"}

    semaphore_base = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS_BASE)

    connector = aiohttp.TCPConnector(ssl=False)  # Bypass SSL certificate verification
    async with aiohttp.ClientSession(connector=connector) as session:
        # Phase 1: Process base_url requests
        tasks = [
            fetch_non_fallback(session, base_url, fallback_url, i, semaphore_base, headers)
            for i in range(start_id, end_id + 1)
        ]
        await asyncio.gather(*tasks)

        # Phase 2: Process fallback_url requests sequentially
        print(f"Processing {len(fallback_tasks)} fallback requests...")
        for id in fallback_tasks:
            await fetch_fallback(session, fallback_url, id)
            print(f"Sleeping for {FALLBACK_REQUEST_DELAY} seconds after fallback request.")
            await asyncio.sleep(FALLBACK_REQUEST_DELAY)


# Run the script with your ID range
start_id = 0
end_id = 1000
asyncio.run(main(start_id, end_id))
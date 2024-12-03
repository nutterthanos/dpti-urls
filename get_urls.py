import aiohttp
import asyncio
import aiofiles
import os
from argparse import ArgumentParser

# Constants for request limits and delays
MAX_CONCURRENT_REQUESTS_BASE = 100
MAX_RETRIES = 1000
RETRY_DELAY = 2
FALLBACK_RETRY_DELAY = 10
FALLBACK_REQUEST_DELAY = 5

existing_entries = {}
fallback_tasks = []

# Base URLs for service updates
SERVICE_UPDATES_URL = "https://www.adelaidemetro.com.au/metro/api/service-updates"
BASE_URL = "https://dpti-web01.syd1.squiz.cloud/?a={id}"
FALLBACK_URL = "https://www.adelaidemetro.com.au/?a={id}"


def clean_extension(extension):
    """Clean trailing characters like '; from file extensions."""
    return extension.replace(';', '').replace('"', '').strip()


def load_existing_data():
    """Load existing entries from files into memory, remove duplicates, and update in place."""
    global existing_entries
    for filename in os.listdir():
        if filename.startswith("urls_with_") and filename.endswith(".txt"):
            print(f"Processing file: {filename}")
            ext = filename.split("_with_")[-1].replace(".txt", "")
            unique_entries = set()
            updated_lines = []
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line not in unique_entries:
                            unique_entries.add(line)
                            updated_lines.append(line)
                        else:
                            print(f"Duplicate removed: {line}")
            except Exception as e:
                print(f"Error reading file {filename}: {e}")
                continue
            # Update file with deduplicated content
            with open(filename, "w", encoding="utf-8") as f:
                for line in updated_lines:
                    f.write(f"{line}\n")
            existing_entries[ext] = unique_entries
            print(f"Loaded {len(unique_entries)} unique entries from '{filename}'")

    # Deduplicate redirects.txt
    redirects_file = "redirects.txt"
    if os.path.exists(redirects_file):
        print(f"Processing file: {redirects_file}")
        unique_redirects = set()
        updated_redirects = []
        try:
            with open(redirects_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line not in unique_redirects:
                        unique_redirects.add(line)
                        updated_redirects.append(line)
                    else:
                        print(f"Duplicate redirect removed: {line}")
        except Exception as e:
            print(f"Error reading {redirects_file}: {e}")
            return

        # Update redirects.txt with deduplicated content
        with open(redirects_file, "w", encoding="utf-8") as f:
            for line in updated_redirects:
                f.write(f"{line}\n")

        # Store redirects in memory for further checks
        existing_entries["redirects"] = unique_redirects
        print(f"Loaded {len(unique_redirects)} unique redirects from '{redirects_file}'")


async def fetch_service_updates():
    """Fetch asset IDs from the service updates endpoint."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(SERVICE_UPDATES_URL) as response:
                if response.status == 200:
                    print(f"Successfully fetched service updates from {SERVICE_UPDATES_URL}")
                    data = await response.json()
                    
                    # Iterate through the list to extract 'assetid'
                    asset_ids = [item["assetid"] for item in data if "assetid" in item]
                    return asset_ids
                else:
                    print(f"Failed to fetch service updates: HTTP {response.status}")
        except Exception as e:
            print(f"Error fetching service updates: {e}")
    return []


def entry_exists(entry, category):
    """Check if an entry already exists in the in-memory existing_entries."""
    return entry in existing_entries.get(category, set())

async def handle_response(id, url, response, is_fallback):
    """Handle the HTTP response and save results."""
    content_type = response.headers.get("Content-Type", "")
    content_disp = response.headers.get("Content-Disposition", "")
    location = response.headers.get("Location", "")

    if response.status == 200:
        if content_disp:
            filename = content_disp.split("filename=")[-1].strip('\"')
            extension = clean_extension(filename.split(".")[-1]) if "." in filename else "unknown"
            entry = f"{url.format(id=id)} - {filename}"
            file_name = f"urls_with_{extension}.txt"

            async with aiofiles.open(file_name, "a") as f:
                if not entry_exists(entry, extension):
                    await f.write(f"{entry}\n")
                    print(f"ID {id}: Added filename '{filename}' with extension '{extension}' ({'Fallback' if is_fallback else 'Base'})")
                    existing_entries.setdefault(extension, set()).add(entry)
                else:
                    print(f"ID {id}: Entry already exists, skipping ({'Fallback' if is_fallback else 'Base'}).")
        elif "text/html" in content_type:
            html_url = url.format(id=id)
            html_file = "urls_with_html.txt"
            async with aiofiles.open(html_file, "a") as f:
                if not entry_exists(html_url, "html"):
                    await f.write(f"{html_url}\n")
                    print(f"ID {id}: HTML content detected, added to HTML list ({'Fallback' if is_fallback else 'Base'}).")
                    existing_entries.setdefault("html", set()).add(html_url)
                else:
                    print(f"ID {id}: HTML entry already exists, skipping ({'Fallback' if is_fallback else 'Base'}).")
    elif response.status in {301, 302, 303, 307, 308}:
        if location:
            redirect_entry = f"{url.format(id=id)} -> {location}"
            async with aiofiles.open("redirects.txt", "a") as f:
                if not entry_exists(redirect_entry, "redirects"):
                    await f.write(f"{redirect_entry}\n")
                    print(f"ID {id}: Redirect logged: {redirect_entry} ({'Fallback' if is_fallback else 'Base'})")
                    existing_entries.setdefault("redirects", set()).add(redirect_entry)
                else:
                    print(f"ID {id}: Redirect entry already exists, skipping ({'Fallback' if is_fallback else 'Base'}).")
        else:
            print(f"ID {id}: Redirect detected but no Location header found ({'Fallback' if is_fallback else 'Base'}).")
    elif response.status == 429:
        print(f"ID {id}: Rate limited. Pausing for {FALLBACK_RETRY_DELAY} seconds...")
        await asyncio.sleep(FALLBACK_RETRY_DELAY)


async def fetch_non_fallback(session, base_url, id, semaphore):
    """Process primary BASE_URL requests and schedule fallback if needed."""
    retries = 0
    while retries < MAX_RETRIES:
        async with semaphore:
            try:
                async with session.head(base_url.format(id=id), allow_redirects=False) as response:
                    print(f"ID {id}: HTTP {response.status} (Base URL)")
                    await handle_response(id, base_url, response, is_fallback=False)
                    
                    if response.status == 200 or response.status in {301, 302, 303, 307, 308}:
                        # Successfully processed or redirected; no need to retry or fallback
                        return

                    if response.status == 404:
                        print(f"ID {id}: Scheduled for fallback due to 404.")
                        fallback_tasks.append(id)
                        return  # Exit after scheduling fallback

                    if response.status == 403:
                        print(f"ID {id}: Access forbidden (403). Skipping.")
                        return  # Exit without retrying or scheduling fallback

                    # Unexpected status: retry
                    print(f"ID {id}: Unexpected status {response.status}. Retrying...")
            except aiohttp.ClientConnectorError as e:
                print(f"ID {id}: Connection error '{e}'. Retrying ({retries + 1}/{MAX_RETRIES})...")
            except Exception as e:
                print(f"ID {id}: Error '{e}' - scheduling fallback.")
                fallback_tasks.append(id)
                return  # Exit after scheduling fallback

        retries += 1
        await asyncio.sleep(RETRY_DELAY)

    # If all retries fail, schedule for fallback
    print(f"ID {id}: Failed after {MAX_RETRIES} retries - scheduling fallback.")
    fallback_tasks.append(id)

async def process_service_updates():
    """Fetch and process asset IDs from the service updates endpoint."""
    asset_ids = await fetch_service_updates()
    if not asset_ids:
        print("No asset IDs found.")
        return

    print(f"Processing {len(asset_ids)} asset IDs...")
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS_BASE)
    failed_asset_ids = []

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        # Process primary BASE_URL requests
        tasks = [
            fetch_non_fallback(
                session, BASE_URL, asset_id, semaphore
            )
            for asset_id in asset_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect failed asset IDs for fallback processing
        for idx, result in enumerate(results):
            if isinstance(result, Exception) or result is None:
                failed_asset_ids.append(asset_ids[idx])

        # Process fallback requests sequentially
        print(f"Processing {len(failed_asset_ids)} fallback requests...")
        for asset_id in failed_asset_ids:
            await fetch_fallback_asset(session, FALLBACK_URL, asset_id)
            print(f"Sleeping for {FALLBACK_REQUEST_DELAY} seconds after fallback request.")
            await asyncio.sleep(FALLBACK_REQUEST_DELAY)

    # Summary
    print(f"Total asset IDs processed: {len(asset_ids)}")
    print(f"Total fallback requests: {len(failed_asset_ids)}")


async def fetch_fallback_asset(session, fallback_url, id):
    """Process fallback requests only for scheduled IDs."""
    retries = 0
    while retries < MAX_RETRIES:
        try:
            async with session.head(fallback_url.format(id=id), allow_redirects=False) as response:
                print(f"ID {id}: HTTP {response.status} (Fallback URL, Attempt {retries + 1})")
                await handle_response(id, fallback_url, response, is_fallback=True)
                return  # Exit after successful or handled response
        except aiohttp.ClientConnectorError as e:
            print(f"ID {id}: Connection error '{e}' - Retrying ({retries + 1}/{MAX_RETRIES}).")
        except Exception as e:
            print(f"ID {id}: Error '{e}' - Retrying ({retries + 1}/{MAX_RETRIES}).")
        retries += 1
        await asyncio.sleep(FALLBACK_RETRY_DELAY)

    print(f"ID {id}: Failed after {MAX_RETRIES} retries (Fallback).")


async def main(start_id, end_id):
    """Main function to process a range of IDs."""
    load_existing_data()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS_BASE)

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        # Phase 1: Process primary BASE_URL requests
        tasks = [
            fetch_non_fallback(session, BASE_URL, i, semaphore)
            for i in range(start_id, end_id + 1)
        ]
        await asyncio.gather(*tasks)

        # Phase 2: Process fallback requests sequentially for scheduled IDs
        print(f"Processing {len(fallback_tasks)} fallback requests...")
        for asset_id in fallback_tasks:
            await fetch_fallback_asset(session, FALLBACK_URL, asset_id)
            await asyncio.sleep(FALLBACK_REQUEST_DELAY)

    # Summary
    print(f"Processed IDs: {end_id - start_id + 1}, Fallbacks: {len(fallback_tasks)}")

def parse_arguments():
    """Parse command-line arguments."""
    parser = ArgumentParser(description="Process asset IDs from Adelaide Metro.")
    parser.add_argument(
        "command",
        choices=["run", "dump-service-updates"],
        help="Command to run: 'run' for regular operation, 'dump-service-updates' for processing service updates."
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()

    if args.command == "run":
        asyncio.run(main(0, 1000))
    elif args.command == "dump-service-updates":
        asyncio.run(process_service_updates())

import socket
import concurrent.futures
import threading
import gc
import ipaddress
from typing import Any, Set
from idna import encode as idna_encode
from queue import Queue
import logging
import argparse

logging.basicConfig(
    level=logging.NOTSET,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("resolver.log", mode="a"),
        logging.StreamHandler(),
    ],
)

file_write_lock = threading.Lock()
results_queue: Queue[Any] = Queue()


def resolve_domain(domain: str, max_retries: int = 2) -> list[str]:
    ip_set: Set[str] = set()
    # Convert to punycode if necessary
    try:
        domain = idna_encode(domain).decode("utf-8")
    except Exception:
        return []

    for _ in range(max_retries):
        try:
            ip_list = socket.gethostbyname_ex(domain)[2]
            ip_set.update(ip_list)
        except socket.gaierror:
            pass
    return list(ip_set)


def is_ip_in_existing_cidr(ip: str, cidrs: Set[str]):
    try:
        ip_obj = ipaddress.ip_address(ip)
        for cidr in cidrs:
            if ip_obj in ipaddress.ip_network(cidr, strict=False):
                return True
    except ValueError:
        pass
    return False


def process_domain(domain: str, existing_cidrs: Set[str]) -> Set[str]:
    try:
        cidrs: Set[str] = set()
        ip_addresses = resolve_domain(domain)  # Resolve domain to its IP addresses
        for ip in ip_addresses:
            if not is_ip_in_existing_cidr(ip, existing_cidrs):
                cidrs.add(f"{ip}/32")
        return cidrs
    except Exception:
        return set()


def read_domains_from_file(file_path: str, verbose: bool = False) -> list[str]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            domains = [line.strip() for line in f.readlines() if line.strip()]
        if verbose:
            logging.info(f"Read {len(domains)} total domains.")
        return domains
    except FileNotFoundError:
        return []


def write_cidrs_to_file(filename: str = "ips_temp.lst"):
    while True:
        # fetch CIDRs from the queue
        cidrs = results_queue.get()
        # sentinel value to stop the thread
        if cidrs is None:
            break
        with file_write_lock:
            with open(filename, "a", encoding="utf-8") as f:
                for cidr in cidrs:
                    f.write(f"{cidr}\n")
        results_queue.task_done()


def main():
    parser = argparse.ArgumentParser(description="Probe Parser for OONI Data")
    parser.add_argument("--input", "-i", required=True, help="Input file path")
    parser.add_argument("--output", "-o", required=True, help="Output file path")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose output"
    )

    args = parser.parse_args()

    output_file = args.output
    input_file = args.input
    verbose = args.verbose

    gc.enable()
    domains = read_domains_from_file(input_file, verbose)
    if not domains:
        return

    existing_cidrs: Set[str] = set()

    # file writer thread
    writer_thread = threading.Thread(target=write_cidrs_to_file, args=(output_file,))
    writer_thread.start()

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        future_to_domain = {
            executor.submit(process_domain, domain, existing_cidrs): domain
            for domain in domains
        }

        for future in concurrent.futures.as_completed(future_to_domain):
            # domain = future_to_domain[future]
            try:
                domain_cidrs = future.result()
                if domain_cidrs:
                    results_queue.put(domain_cidrs)
            except Exception:
                pass
            finally:
                gc.collect()

    # write thread stops by sentinel value
    results_queue.put(None)
    writer_thread.join()


if __name__ == "__main__":
    main()

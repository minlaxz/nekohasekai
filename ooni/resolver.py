import socket
import concurrent.futures
import threading
import gc
import ipaddress
from idna import encode as idna_encode
from queue import Queue

file_write_lock = threading.Lock()
results_queue = Queue()


def resolve_domain(domain, max_retries=2):
    ip_set = set()
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


def is_ip_in_existing_cidr(ip, cidrs):
    try:
        ip_obj = ipaddress.ip_address(ip)
        for cidr in cidrs:
            if ip_obj in ipaddress.ip_network(cidr, strict=False):
                return True
    except ValueError:
        pass
    return False


def process_domain(domain, existing_cidrs):
    try:
        cidrs = set()
        ip_addresses = resolve_domain(domain)  # Resolve domain to its IP addresses
        for ip in ip_addresses:
            if not is_ip_in_existing_cidr(ip, existing_cidrs):
                cidrs.add(f"{ip}/32")
        return cidrs
    except Exception:
        return set()


def read_domains_from_file(file_path="domains.lst"):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            domains = [line.strip() for line in f.readlines() if line.strip()]
        return domains
    except FileNotFoundError:
        return []


def write_cidrs_to_file(filename="ips_temp.lst"):
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
    gc.enable()
    domains = read_domains_from_file("domains.lst")
    if not domains:
        return

    existing_cidrs = set()

    # file writer thread
    writer_thread = threading.Thread(
        target=write_cidrs_to_file, args=("ips.lst",)
    )
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

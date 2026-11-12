"""Generate bounded synthetic traffic only for the local Nginx lab."""
import argparse
import concurrent.futures
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request

APPS = ("app-a", "app-b", "app-c")
SCAN_PATHS = ("/.env", "/.git/config", "/wp-admin", "/wp-login.php", "/phpmyadmin", "/etc/passwd")
MAX_RPS = 20.0
MAX_CONCURRENCY = 4
MAX_DURATION = 300.0


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("normal", "degradation", "scan", "peak"), default="normal")
    parser.add_argument("--duration", type=float, default=0, help="seconds; 0 runs the default normal service indefinitely")
    parser.add_argument("--rps", type=float, default=float(os.getenv("REQUESTS_PER_SECOND", "2")), help=f"target rate, maximum {MAX_RPS:g}")
    parser.add_argument("--concurrency", type=int, default=1, help=f"parallel requests, maximum {MAX_CONCURRENCY}")
    parser.add_argument("--seed", type=int, default=42, help="random seed for reproducible scenario paths and methods")
    parser.add_argument("--target", default=os.getenv("TARGET_URL", "http://nginx"), help="local Nginx URL only")
    args = parser.parse_args()

    target = urllib.parse.urlsplit(args.target)
    if target.scheme != "http" or target.hostname not in {"nginx", "localhost", "127.0.0.1", "::1"}:
        parser.error("--target must be http://nginx or a loopback URL; external hosts are rejected")
    if not 0 < args.rps <= MAX_RPS:
        parser.error(f"--rps must be greater than zero and no more than {MAX_RPS:g}")
    if not 1 <= args.concurrency <= MAX_CONCURRENCY:
        parser.error(f"--concurrency must be between 1 and {MAX_CONCURRENCY}")
    if not 0 <= args.duration <= MAX_DURATION:
        parser.error(f"--duration must be between 0 and {MAX_DURATION:g} seconds")
    if args.duration == 0 and args.scenario != "normal":
        parser.error("finite scenarios require --duration between 1 and 300 seconds")
    return args


def request_path(scenario, progress, rng):
    if scenario == "scan":
        return rng.choice(SCAN_PATHS)
    if scenario == "degradation":
        error_chance = 0.05 + 0.35 * progress
        slow_chance = 0.10 + 0.60 * progress
        if rng.random() < error_chance:
            return "/error"
        if rng.random() < slow_chance:
            return "/slower"
        return "/"
    if scenario == "peak" and rng.random() < 0.05:
        return "/slow"
    return "/"


def send_request(client, target, app, path, method):
    request = urllib.request.Request(f"{target}/{app}{path}", data=b"" if method == "POST" else None, method=method)
    try:
        with client.open(request, timeout=4) as response:
            response.read()
    except urllib.error.HTTPError:
        # 3xx/4xx/5xx are intentional observations; do not follow redirects.
        pass
    except Exception as error:
        print(f"request failed: {type(error).__name__}", flush=True)


def main():
    args = parse_args()
    target = args.target.rstrip("/")
    rng = random.Random(args.seed)
    client = urllib.request.build_opener(NoRedirect)
    started = time.monotonic()
    next_request = started
    sent = 0
    pending = set()

    print(
        f"scenario={args.scenario} duration={args.duration:g}s rps<={args.rps:g} "
        f"concurrency={args.concurrency} seed={args.seed} target={target}",
        flush=True,
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        while args.duration == 0 or time.monotonic() - started < args.duration:
            now = time.monotonic()
            progress = 0 if args.duration == 0 else min((now - started) / args.duration, 1)
            rate = args.rps
            if args.scenario == "peak":
                rate = args.rps * (0.2 + 0.8 * progress)
            if now < next_request:
                time.sleep(next_request - now)
            if len(pending) >= args.concurrency:
                done, pending = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    future.result()
            progress = 0 if args.duration == 0 else min((time.monotonic() - started) / args.duration, 1)
            app = rng.choice(APPS)
            path = request_path(args.scenario, progress, rng)
            method = "POST" if rng.random() < 0.10 else "GET"
            pending.add(pool.submit(send_request, client, target, app, path, method))
            sent += 1
            next_request += 1 / rate
        for future in concurrent.futures.as_completed(pending):
            future.result()
    print(f"completed scenario={args.scenario} requests={sent} elapsed={time.monotonic() - started:.1f}s", flush=True)


if __name__ == "__main__":
    main()

import argparse
import sys

from dotenv import load_dotenv

from agent.undercover.backend import Backend
from agent.undercover.claim_agent import work_claim
from agent.undercover.queue_agent import run_queue


def main(argv: list[str]) -> None:
    """Work the claim named on the command line, or else run the queue agent."""
    parser = argparse.ArgumentParser(prog="agent")
    parser.add_argument("claim_id", nargs="?", help="work just this claim")
    parser.add_argument("--limit", type=int, help="start at most this many claims")
    args = parser.parse_args(argv)
    if args.claim_id and args.limit:
        parser.error("a named claim and --limit don't go together")
    with Backend.connect() as backend:
        if args.claim_id:
            print(work_claim(backend, args.claim_id))
        else:
            run_queue(backend, args.limit)


if __name__ == "__main__":
    load_dotenv(override=True)
    main(sys.argv[1:])

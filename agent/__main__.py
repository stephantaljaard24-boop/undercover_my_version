import argparse
import sys

from agent.queue_run import run_queue
from agent.runner import work_claim


def main(argv: list[str]) -> None:
    """Work the claim named on the command line, or else run the queue agent."""
    parser = argparse.ArgumentParser(prog="agent")
    parser.add_argument("claim_id", nargs="?", help="work just this claim")
    parser.add_argument("--limit", type=int, help="start at most this many claims")
    args = parser.parse_args(argv)
    if args.claim_id and args.limit:
        parser.error("a named claim and --limit don't go together")
    if args.claim_id:
        print(work_claim(args.claim_id))
    else:
        run_queue(args.limit)


if __name__ == "__main__":
    main(sys.argv[1:])

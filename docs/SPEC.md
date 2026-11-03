# The claims pilot

From the head of claims operations at UnderCover Travel Insurance.

## How claims work today

UnderCover sells travel insurance on three plans: Economy, Premium and First. Our three claims handlers work through a queue of claims by hand. For each claim, a handler reads the customer's story and documents and checks them against the policy and our policy wording. Then they approve the claim with a payout, decline it or refer it. A claim is referred when it needs someone's judgment or more information, as the claims manual explains.

## The pilot

We want an AI agent, the UnderCover Agent, to work the queue the way a handler does. For each claim it should:

- read the claim, the customer's policy and claim history, and the sections of the policy wording and the claims manual it needs
- approve, decline or refer the claim
- work out the payout when it approves
- explain the decision in two or three sentences, along with the relevant section of the policy
Our goal is to handle claims straight through, as accurately as our handlers do. Someone starts the agent from the command line, and one run works the whole queue: the agent plans its work as a to-do list, chooses the order itself and finishes with a short summary for the handlers. A run can be capped at a number of claims, with the rest left waiting, and the agent can be run on one named claim. A claim shows as in progress while the agent works on it.

A long run meets timeouts, errors from the model provider and steps that fail. One bad claim never stops the run or leaves a claim stuck in progress. A claim that fails before it is decided goes back in the queue to be tried again, and a claim that fails twice is left for a handler. No claim is decided or paid twice.


## What the team needs to see

- The queue, with where each claim stands: waiting, in progress, waiting for sign-off, decided or left for a handler.
- The to-do list for the current run, with each item to do, in progress, done or left for a handler, and the run's summary once it finishes.
- Each claim in full, with the agent's decision and its reasons, and the sections of the wording and the manual the agent read.
- What the agent is doing on a claim while it works, step by step.
- The agent's instructions for running the queue and for working a claim, read only.

## Rules

- A payout over $1,000 needs a handler's sign-off. The agent can approve such a claim, but the payment waits until a handler signs off. The system must block the payment until then, even if the agent tries to pay.
- Decisions follow the policy wording and the claims manual. The wording comes first, and the manual covers what the wording leaves open.
- Our handlers' own decisions on these claims are in `data/evals/`. We use them to check the agent's work. The agent must never see them.
- Amounts are in US dollars.

## Our records

Everything is in `data/`, described in `data/README.md`: the claims queue, the policies, the customers, the plans, the handlers, the policy wording and the claims manual. The held-out claims in `data/evals/` are for checking the agent later and stay out of the queue.

## Not for now

- No sign-in. Everyone who uses the screens sees everything.
- No real payments.
- No messages to customers.
- Signing off from the screens. In the pilot, a claim over $1,000 that the agent approves stays waiting for sign-off, and its payment stays blocked. A handler signs it off outside the system for now.
